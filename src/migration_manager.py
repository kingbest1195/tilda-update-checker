"""
Модуль для автоматической миграции между версиями файлов Tilda CDN
"""
import logging
import hashlib
import time
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import requests

import config
from src.database import db, TrackedFile, FileVersion, VersionAlert
from src.version_detector import detector

logger = logging.getLogger(__name__)


# Задержки миграций в зависимости от приоритета (в секундах)
MIGRATION_DELAYS = {
    "CRITICAL": 0,       # Немедленно
    "HIGH": 3600,        # Через 1 час
    "MEDIUM": 86400,     # Через 24 часа
    "LOW": 604800        # Через неделю
}


class MigrationManager:
    """Класс для управления миграциями версий файлов"""
    
    def __init__(self):
        """Инициализация менеджера миграций"""
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': config.USER_AGENT
        })
    
    def validate_new_version(self, url: str, timeout: int = 30) -> Tuple[bool, Optional[str], Optional[Dict]]:
        """
        Валидация нового файла перед миграцией
        
        Args:
            url: URL нового файла
            timeout: Таймаут запроса
            
        Returns:
            Tuple (успех, ошибка, метаданные)
            - успех: True если валидация прошла успешно
            - ошибка: сообщение об ошибке или None
            - метаданные: словарь с content, hash, size или None
        """
        start_time = time.time()
        
        try:
            logger.info(f"Валидация нового файла: {url}")
            
            # 1. Проверка доступности
            response = self.session.get(url, timeout=timeout)
            
            if response.status_code == 404:
                return False, "Файл не найден (404)", None
            
            response.raise_for_status()
            
            # 2. Проверка содержимого
            content = response.text
            
            if not content or len(content) < 10:
                return False, "Файл пустой или слишком маленький", None
            
            # 3. Вычисление метаданных
            content_hash = hashlib.sha256(content.encode('utf-8')).hexdigest()
            size = len(content.encode('utf-8'))
            
            validation_time = time.time() - start_time
            
            metadata = {
                'content': content,
                'hash': content_hash,
                'size': size,
                'validation_time': validation_time
            }
            
            logger.info(f"✅ Валидация успешна: {url} ({size} байт, {validation_time:.2f}с)")
            return True, None, metadata
            
        except requests.exceptions.Timeout:
            return False, f"Timeout при загрузке ({timeout}s)", None
        except requests.exceptions.RequestException as e:
            return False, f"Ошибка HTTP: {str(e)}", None
        except Exception as e:
            logger.error(f"Неожиданная ошибка при валидации {url}: {e}", exc_info=True)
            return False, f"Неожиданная ошибка: {str(e)}", None
    
    def archive_old_version(self, tracked_file: TrackedFile) -> Optional[FileVersion]:
        """
        Архивирование старой версии файла
        
        Args:
            tracked_file: Отслеживаемый файл для архивирования
            
        Returns:
            FileVersion объект или None при ошибке
        """
        try:
            logger.info(f"Архивирование старой версии: {tracked_file.url}")
            
            # Парсинг URL для извлечения метаданных если они не установлены
            if not tracked_file.base_name:
                parsed = detector.parse_file_url(tracked_file.url)
                tracked_file.base_name = parsed['base_name']
                tracked_file.version = parsed['version']
            
            # Создание записи в FileVersion
            file_version = db.save_file_version(
                base_name=tracked_file.base_name,
                version=tracked_file.version or 'unknown',
                full_url=tracked_file.url,
                file_type=tracked_file.file_type,
                category=tracked_file.category,
                priority=tracked_file.priority,
                domain=tracked_file.domain,
                last_hash=tracked_file.last_hash,
                last_content=tracked_file.last_content,
                last_size=tracked_file.last_size,
                tracked_file_id=tracked_file.id
            )
            
            # Деактивация старой версии в TrackedFile
            session = db.get_session()
            try:
                tf = session.query(TrackedFile).filter(TrackedFile.id == tracked_file.id).first()
                if tf:
                    tf.is_active = 0
                    session.commit()
                    logger.info(f"✅ Старая версия архивирована: {tracked_file.base_name} v{tracked_file.version}")
            finally:
                session.close()
            
            return file_version
            
        except Exception as e:
            logger.error(f"Ошибка при архивировании {tracked_file.url}: {e}", exc_info=True)
            return None
    
    def activate_new_version(self, url: str, metadata: Dict, version_info: Dict) -> Optional[TrackedFile]:
        """
        Активация новой версии файла
        
        Args:
            url: URL нового файла
            metadata: Метаданные из валидации (content, hash, size)
            version_info: Информация о версии (base_name, version, category, priority, etc.)
            
        Returns:
            TrackedFile объект или None при ошибке
        """
        try:
            logger.info(f"Активация новой версии: {url}")
            
            # Парсинг URL
            parsed = detector.parse_file_url(url)
            
            # Сохранение нового TrackedFile
            tracked_file = db.save_file_state(
                url=url,
                file_type=parsed['file_type'],
                content=metadata['content'],
                content_hash=metadata['hash'],
                size=metadata['size'],
                category=version_info.get('category', 'unknown'),
                priority=version_info.get('priority', 'MEDIUM'),
                domain=parsed['domain']
            )
            
            # Обновление base_name и version
            session = db.get_session()
            try:
                tf = session.query(TrackedFile).filter(TrackedFile.id == tracked_file.id).first()
                if tf:
                    tf.base_name = version_info['base_name']
                    tf.version = version_info['new_version']
                    tf.is_active = 1
                    session.commit()
            finally:
                session.close()
            
            logger.info(
                f"✅ Новая версия активирована: {version_info['base_name']} "
                f"v{version_info['new_version']}"
            )
            return tracked_file
            
        except Exception as e:
            logger.error(f"Ошибка при активации {url}: {e}", exc_info=True)
            return None
    
    def perform_migration(self, update_info: Dict, force: bool = False) -> bool:
        """
        Выполнить полную миграцию с одной версии на другую
        
        Args:
            update_info: Информация об обновлении (из version_detector)
            force: Принудительная миграция без учета задержек
            
        Returns:
            True если миграция успешна
        """
        base_name = update_info['base_name']
        new_version = update_info['new_version']
        new_url = update_info['new_url']
        priority = update_info['priority']
        
        logger.info(f"\n{'='*80}")
        logger.info(f"🔄 НАЧАЛО МИГРАЦИИ: {base_name} -> v{new_version}")
        logger.info(f"{'='*80}")
        
        migration_start = time.time()
        
        # Создать алерт
        alert = db.create_version_alert(
            base_name=base_name,
            old_version=update_info.get('current_version'),
            new_version=new_version,
            old_url=update_info.get('current_url'),
            new_url=new_url,
            category=update_info.get('category'),
            priority=priority
        )
        
        try:
            # Проверка задержки (если не force)
            if not force:
                delay = MIGRATION_DELAYS.get(priority, 0)
                if delay > 0:
                    logger.info(f"⏱ Миграция отложена на {delay}с согласно приоритету {priority}")
                    # TODO: В production это должно быть запланировано через scheduler
                    # Пока выполняем немедленно для MVP
                    pass
            
            # 1. Валидация нового файла
            logger.info("Шаг 1/3: Валидация нового файла...")
            is_valid, error, metadata = self.validate_new_version(new_url)
            
            if not is_valid:
                logger.error(f"❌ Валидация не прошла: {error}")
                db.update_version_alert_status(alert.id, 'failed', error)
                return False
            
            # 2. Архивирование старой версии
            logger.info("Шаг 2/3: Архивирование старой версии...")
            old_tracked_file = db.get_file_by_base_name(base_name)
            
            if old_tracked_file:
                archived = self.archive_old_version(old_tracked_file)
                if not archived:
                    logger.error("❌ Ошибка при архивировании старой версии")
                    db.update_version_alert_status(alert.id, 'failed', 'Archive error')
                    return False
            else:
                logger.warning(f"⚠️ Старая версия {base_name} не найдена в БД (возможно, первая миграция)")
            
            # 3. Активация новой версии
            logger.info("Шаг 3/3: Активация новой версии...")
            new_tracked_file = self.activate_new_version(new_url, metadata, update_info)
            
            if not new_tracked_file:
                logger.error("❌ Ошибка при активации новой версии")
                db.update_version_alert_status(alert.id, 'failed', 'Activation error')
                # Попытка rollback (если была архивация)
                if old_tracked_file:
                    self._attempt_rollback(old_tracked_file)
                return False
            
            # Успешное завершение
            migration_time = time.time() - migration_start
            db.update_version_alert_status(alert.id, 'completed')
            
            logger.info(f"{'='*80}")
            logger.info(f"✅ МИГРАЦИЯ ЗАВЕРШЕНА УСПЕШНО")
            logger.info(f"   Файл: {base_name}")
            logger.info(f"   Старая версия: {update_info.get('current_version')}")
            logger.info(f"   Новая версия: {new_version}")
            logger.info(f"   Время: {migration_time:.2f}с")
            logger.info(f"{'='*80}\n")
            
            # Сохранить метрики
            self._save_migration_metrics(
                discovered=1,
                successful=1,
                avg_migration_time=migration_time,
                avg_validation_time=metadata['validation_time']
            )
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Критическая ошибка при миграции: {e}", exc_info=True)
            db.update_version_alert_status(alert.id, 'failed', str(e))
            
            # Сохранить метрики о неудаче
            self._save_migration_metrics(discovered=1, failed=1)
            
            return False
    
    def perform_batch_migration(self, updates: List[Dict], force: bool = False) -> Dict[str, int]:
        """
        Выполнить пакетную миграцию нескольких файлов
        
        Args:
            updates: Список обновлений для миграции
            force: Принудительная миграция
            
        Returns:
            Статистика: {'successful': N, 'failed': M, 'skipped': K}
        """
        stats = {'successful': 0, 'failed': 0, 'skipped': 0}
        
        logger.info(f"\n{'='*80}")
        logger.info(f"🔄 ПАКЕТНАЯ МИГРАЦИЯ: {len(updates)} файлов")
        logger.info(f"{'='*80}\n")
        
        # Сортировка по приоритету
        priority_order = {'CRITICAL': 0, 'HIGH': 1, 'MEDIUM': 2, 'LOW': 3}
        sorted_updates = sorted(
            updates,
            key=lambda x: priority_order.get(x.get('priority', 'MEDIUM'), 99)
        )
        
        for i, update in enumerate(sorted_updates, 1):
            logger.info(f"\n[{i}/{len(updates)}] Миграция: {update['base_name']}")
            
            success = self.perform_migration(update, force=force)
            
            if success:
                stats['successful'] += 1
            else:
                stats['failed'] += 1
            
            # Небольшая задержка между миграциями
            if i < len(sorted_updates):
                time.sleep(2)
        
        logger.info(f"\n{'='*80}")
        logger.info(f"📊 ИТОГИ ПАКЕТНОЙ МИГРАЦИИ")
        logger.info(f"{'='*80}")
        logger.info(f"✅ Успешно: {stats['successful']}")
        logger.info(f"❌ Неудачно: {stats['failed']}")
        logger.info(f"⏭ Пропущено: {stats['skipped']}")
        logger.info(f"{'='*80}\n")
        
        return stats
    
    def rollback_to_version(self, base_name: str, version: str) -> bool:
        """
        Откатить файл к предыдущей версии
        
        Args:
            base_name: Базовое имя файла
            version: Версия для восстановления
            
        Returns:
            True если откат успешен
        """
        logger.info(f"\n{'='*80}")
        logger.info(f"🔙 ОТКАТ: {base_name} -> v{version}")
        logger.info(f"{'='*80}")
        
        try:
            # Найти нужную версию в архиве
            archived_version = db.get_version_by_exact(base_name, version)
            
            if not archived_version:
                logger.error(f"❌ Версия {base_name} v{version} не найдена в архиве")
                return False
            
            # Получить текущую активную версию
            current_tracked = db.get_file_by_base_name(base_name)
            
            if current_tracked:
                # Архивировать текущую версию
                logger.info("Архивирование текущей версии...")
                self.archive_old_version(current_tracked)
            
            # Валидация архивного файла (может быть уже недоступен)
            logger.info("Проверка доступности архивной версии...")
            is_valid, error, metadata = self.validate_new_version(archived_version.full_url)
            
            if not is_valid:
                # Если файл недоступен, используем сохраненное содержимое
                logger.warning(f"⚠️ Файл недоступен, используем архивное содержимое")
                if not archived_version.last_content:
                    logger.error("❌ Архивное содержимое отсутствует")
                    return False
                
                metadata = {
                    'content': archived_version.last_content,
                    'hash': archived_version.last_hash,
                    'size': archived_version.last_size,
                    'validation_time': 0
                }
            
            # Активация архивной версии
            logger.info("Активация архивной версии...")
            version_info = {
                'base_name': base_name,
                'new_version': version,
                'category': archived_version.category,
                'priority': archived_version.priority
            }
            
            restored = self.activate_new_version(
                archived_version.full_url,
                metadata,
                version_info
            )
            
            if not restored:
                logger.error("❌ Ошибка при активации архивной версии")
                return False
            
            # Создать алерт об откате
            if current_tracked:
                alert = db.create_version_alert(
                    base_name=base_name,
                    old_version=current_tracked.version,
                    new_version=version,
                    old_url=current_tracked.url,
                    new_url=archived_version.full_url,
                    category=archived_version.category,
                    priority=archived_version.priority
                )
                db.update_version_alert_status(alert.id, 'rolled_back')
            
            logger.info(f"{'='*80}")
            logger.info(f"✅ ОТКАТ ВЫПОЛНЕН УСПЕШНО")
            logger.info(f"   Файл: {base_name}")
            logger.info(f"   Восстановлена версия: {version}")
            logger.info(f"{'='*80}\n")
            
            # Сохранить метрики
            self._save_migration_metrics(rollbacks=1)
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Ошибка при откате: {e}", exc_info=True)
            return False
    
    def _attempt_rollback(self, old_tracked_file: TrackedFile):
        """Попытка автоматического отката при ошибке миграции"""
        try:
            logger.warning("⚠️ Попытка автоматического отката...")
            session = db.get_session()
            try:
                tf = session.query(TrackedFile).filter(TrackedFile.id == old_tracked_file.id).first()
                if tf:
                    tf.is_active = 1
                    session.commit()
                    logger.info("✅ Откат выполнен: старая версия восстановлена")
            finally:
                session.close()
        except Exception as e:
            logger.error(f"❌ Ошибка при автоматическом откате: {e}")
    
    def _save_migration_metrics(self, discovered: int = 0, successful: int = 0,
                               failed: int = 0, rollbacks: int = 0,
                               avg_migration_time: float = None,
                               avg_validation_time: float = None):
        """Сохранить метрики миграции"""
        try:
            db.save_migration_metrics(
                discovered=discovered,
                successful=successful,
                failed=failed,
                rollbacks=rollbacks,
                avg_migration_time=avg_migration_time,
                avg_validation_time=avg_validation_time
            )
        except Exception as e:
            logger.error(f"Ошибка при сохранении метрик: {e}")
    
    def get_migration_status(self) -> Dict:
        """
        Получить текущий статус всех миграций
        
        Returns:
            Словарь со статистикой миграций
        """
        try:
            pending_alerts = db.get_pending_alerts()
            recent_alerts = db.get_recent_version_alerts(limit=20)
            metrics = db.get_metrics_summary(days=30)
            
            return {
                'pending_migrations': len(pending_alerts),
                'recent_migrations': len([a for a in recent_alerts if a.migration_status == 'completed']),
                'failed_migrations': len([a for a in recent_alerts if a.migration_status == 'failed']),
                'metrics_30d': metrics
            }
        except Exception as e:
            logger.error(f"Ошибка при получении статуса миграций: {e}")
            return {}


# Глобальный экземпляр менеджера миграций
manager = MigrationManager()



