"""
Модуль для работы с базой данных SQLite
"""
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from sqlalchemy import (
    create_engine,
    Column,
    Integer,
    String,
    Text,
    DateTime,
    ForeignKey,
    Float,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship, Session

import config

logger = logging.getLogger(__name__)

# Базовый класс для моделей
Base = declarative_base()


class TrackedFile(Base):
    """Модель отслеживаемого файла"""
    
    __tablename__ = "files"
    
    id = Column(Integer, primary_key=True)
    url = Column(String(500), unique=True, nullable=False, index=True)
    file_type = Column(String(10), nullable=False)  # 'js' или 'css'
    last_hash = Column(String(64))  # SHA-256 хеш
    last_content = Column(Text)  # Последнее содержимое файла
    last_size = Column(Integer)  # Размер файла в байтах
    last_checked = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Поля для категоризации
    category = Column(String(50), default='unknown', index=True)  # core, members, ecommerce, etc.
    priority = Column(String(20), default='MEDIUM')  # CRITICAL, HIGH, MEDIUM, LOW
    domain = Column(String(100), index=True)  # Извлеченный домен из URL
    
    # НОВЫЕ ПОЛЯ для версионирования
    base_name = Column(String(200), index=True)  # Базовое имя без версии (например, "tilda-cart")
    version = Column(String(50))  # Текущая версия (например, "1.1")
    is_active = Column(Integer, default=1)  # 1 = активен, 0 = архивирован
    
    # НОВЫЕ ПОЛЯ для обработки 404
    consecutive_404_count = Column(Integer, default=0)  # Счетчик последовательных 404 ошибок
    last_404_at = Column(DateTime)  # Время последней 404 ошибки
    
    # Связи
    changes = relationship("Change", back_populates="file", cascade="all, delete-orphan")
    versions = relationship("FileVersion", foreign_keys="FileVersion.tracked_file_id", back_populates="tracked_file")
    
    def __repr__(self):
        return f"<TrackedFile(id={self.id}, url='{self.url}', base_name='{self.base_name}', version='{self.version}', is_active={self.is_active})>"


class Change(Base):
    """Модель обнаруженного изменения"""
    
    __tablename__ = "changes"
    
    id = Column(Integer, primary_key=True)
    file_id = Column(Integer, ForeignKey("files.id"), nullable=False)
    old_hash = Column(String(64))
    new_hash = Column(String(64))
    old_size = Column(Integer)
    new_size = Column(Integer)
    diff_summary = Column(Text)  # Краткое описание изменений
    change_percent = Column(Integer)  # Процент изменения
    is_significant = Column(Integer, default=1)  # 1 = значимое, 0 = незначительное
    detected_at = Column(DateTime, default=datetime.utcnow)
    
    # Связи
    file = relationship("TrackedFile", back_populates="changes")
    announcements = relationship("Announcement", back_populates="change", cascade="all, delete-orphan")
    
    def __repr__(self):
        return f"<Change(id={self.id}, file_id={self.file_id}, detected={self.detected_at})>"


class Announcement(Base):
    """Модель анонса"""
    
    __tablename__ = "announcements"
    
    id = Column(Integer, primary_key=True)
    change_id = Column(Integer, ForeignKey("changes.id"), nullable=False)
    title = Column(String(500), nullable=False)
    content = Column(Text, nullable=False)
    change_type = Column(String(100))  # Тип изменения из LLM
    severity = Column(String(50))  # КРИТИЧЕСКОЕ/ВАЖНОЕ/НЕЗНАЧИТЕЛЬНОЕ
    generated_at = Column(DateTime, default=datetime.utcnow)
    
    # Связь
    change = relationship("Change", back_populates="announcements")
    
    def __repr__(self):
        return f"<Announcement(id={self.id}, title='{self.title[:50]}...')>"


class DiscoveredFile(Base):
    """Модель обнаруженного нового файла (Discovery Mode)"""
    
    __tablename__ = "discovered_files"
    
    id = Column(Integer, primary_key=True)
    url = Column(String(500), unique=True, nullable=False, index=True)
    discovered_at = Column(DateTime, default=datetime.utcnow)
    added_to_tracking = Column(Integer, default=0)  # 0 = нет, 1 = да
    pattern_matched = Column(String(100))  # Какой паттерн совпал
    source_page = Column(String(500))  # С какой страницы обнаружен
    suggested_category = Column(String(50))  # Предложенная категория
    
    def __repr__(self):
        return f"<DiscoveredFile(id={self.id}, url='{self.url}', category='{self.suggested_category}')>"


class FileVersion(Base):
    """Модель архивных версий файлов"""
    
    __tablename__ = "file_versions"
    
    id = Column(Integer, primary_key=True)
    base_name = Column(String(200), nullable=False, index=True)  # "tilda-cart"
    version = Column(String(50), nullable=False, index=True)  # "1.1"
    full_url = Column(String(500), nullable=False)
    file_type = Column(String(10), nullable=False)  # 'js' или 'css'
    
    # Метаданные версии
    category = Column(String(50))
    priority = Column(String(20))
    domain = Column(String(100))
    
    # Состояние на момент архивирования
    last_hash = Column(String(64))
    last_content = Column(Text)
    last_size = Column(Integer)
    
    # Статус
    is_active = Column(Integer, default=0)  # 0 = архивная, 1 = активная
    archived_at = Column(DateTime, default=datetime.utcnow)
    replaced_by_version_id = Column(Integer, ForeignKey("file_versions.id"), nullable=True)
    
    # Связь с активным tracked файлом (если is_active=1)
    tracked_file_id = Column(Integer, ForeignKey("files.id"), nullable=True)
    tracked_file = relationship("TrackedFile", foreign_keys=[tracked_file_id], back_populates="versions")
    
    def __repr__(self):
        return f"<FileVersion(id={self.id}, base_name='{self.base_name}', version='{self.version}', is_active={self.is_active})>"


class VersionAlert(Base):
    """Модель алертов о новых версиях файлов"""
    
    __tablename__ = "version_alerts"
    
    id = Column(Integer, primary_key=True)
    base_name = Column(String(200), nullable=False, index=True)
    old_version = Column(String(50))
    new_version = Column(String(50), nullable=False)
    old_url = Column(String(500))
    new_url = Column(String(500), nullable=False)
    
    # Статус миграции
    migration_status = Column(String(20), default='pending')  # "pending", "completed", "failed", "rolled_back"
    migration_attempted_at = Column(DateTime)
    migration_completed_at = Column(DateTime)
    error_message = Column(Text)
    
    # Уведомления
    telegram_sent = Column(Integer, default=0)  # 0 = нет, 1 = да
    discovered_at = Column(DateTime, default=datetime.utcnow)
    
    # Метаданные
    category = Column(String(50))
    priority = Column(String(20))
    
    def __repr__(self):
        return f"<VersionAlert(id={self.id}, base_name='{self.base_name}', {self.old_version} -> {self.new_version}, status='{self.migration_status}')>"


class MigrationMetrics(Base):
    """Модель метрик миграций"""
    
    __tablename__ = "migration_metrics"
    
    id = Column(Integer, primary_key=True)
    date = Column(DateTime, default=datetime.utcnow, index=True)
    
    # Счетчики
    total_versions_discovered = Column(Integer, default=0)
    successful_migrations = Column(Integer, default=0)
    failed_migrations = Column(Integer, default=0)
    rollbacks_performed = Column(Integer, default=0)
    
    # Тайминги
    avg_migration_time_seconds = Column(Float)
    avg_validation_time_seconds = Column(Float)
    
    def __repr__(self):
        return f"<MigrationMetrics(date={self.date}, discovered={self.total_versions_discovered}, success={self.successful_migrations})>"


class Database:
    """Класс для работы с базой данных"""
    
    def __init__(self, database_url: str = None):
        """
        Инициализация подключения к БД
        
        Args:
            database_url: URL базы данных (по умолчанию из config)
        """
        self.database_url = database_url or config.DATABASE_URL
        self.engine = None
        self.SessionLocal = None
        
    def init_db(self):
        """Инициализация базы данных"""
        try:
            # Создать директорию для БД если не существует
            db_path = Path(config.BASE_DIR / config.DATABASE_PATH)
            db_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Создать движок
            self.engine = create_engine(
                self.database_url,
                echo=False,
                connect_args={"check_same_thread": False}  # Для SQLite
            )
            
            # Создать таблицы
            Base.metadata.create_all(self.engine)
            
            # Создать фабрику сессий
            self.SessionLocal = sessionmaker(
                autocommit=False,
                autoflush=False,
                bind=self.engine
            )
            
            logger.info(f"База данных инициализирована: {db_path}")
            return True
            
        except Exception as e:
            logger.error(f"Ошибка при инициализации БД: {e}", exc_info=True)
            return False
    
    def get_session(self) -> Session:
        """Получить сессию базы данных"""
        if not self.SessionLocal:
            raise RuntimeError("База данных не инициализирована. Вызовите init_db() сначала.")
        return self.SessionLocal()
    
    def get_tracked_files(self) -> List[TrackedFile]:
        """Получить список всех отслеживаемых файлов"""
        session = self.get_session()
        try:
            return session.query(TrackedFile).all()
        finally:
            session.close()
    
    def get_file_by_url(self, url: str) -> Optional[TrackedFile]:
        """Получить файл по URL"""
        session = self.get_session()
        try:
            return session.query(TrackedFile).filter(TrackedFile.url == url).first()
        finally:
            session.close()
    
    def save_file_state(self, url: str, file_type: str, content: str, 
                       content_hash: str, size: int, category: str = 'unknown',
                       priority: str = 'MEDIUM', domain: str = None) -> TrackedFile:
        """
        Сохранить или обновить состояние файла
        
        Args:
            url: URL файла
            file_type: Тип файла ('js' или 'css')
            content: Содержимое файла
            content_hash: SHA-256 хеш содержимого
            size: Размер файла в байтах
            category: Категория файла (core, members, ecommerce, etc.)
            priority: Приоритет (CRITICAL, HIGH, MEDIUM, LOW)
            domain: Домен файла (auto-extracted if None)
            
        Returns:
            TrackedFile объект
        """
        session = self.get_session()
        try:
            # Извлечь домен из URL если не передан
            if domain is None:
                from urllib.parse import urlparse
                parsed = urlparse(url)
                domain = parsed.netloc
            
            # Попытаться найти существующий файл
            tracked_file = session.query(TrackedFile).filter(
                TrackedFile.url == url
            ).first()
            
            if tracked_file:
                # Обновить существующий
                tracked_file.last_hash = content_hash
                tracked_file.last_content = content
                tracked_file.last_size = size
                tracked_file.last_checked = datetime.utcnow()
                tracked_file.category = category
                tracked_file.priority = priority
                tracked_file.domain = domain
            else:
                # Создать новый
                tracked_file = TrackedFile(
                    url=url,
                    file_type=file_type,
                    last_hash=content_hash,
                    last_content=content,
                    last_size=size,
                    last_checked=datetime.utcnow(),
                    category=category,
                    priority=priority,
                    domain=domain
                )
                session.add(tracked_file)
            
            session.commit()
            session.refresh(tracked_file)
            logger.debug(f"Сохранено состояние файла: {url} (category={category}, priority={priority})")
            return tracked_file
            
        except Exception as e:
            session.rollback()
            logger.error(f"Ошибка при сохранении файла: {e}", exc_info=True)
            raise
        finally:
            session.close()
    
    def save_change(self, file_id: int, old_hash: str, new_hash: str,
                   old_size: int, new_size: int, diff_summary: str,
                   change_percent: int, is_significant: bool = True) -> Change:
        """
        Сохранить обнаруженное изменение
        
        Args:
            file_id: ID отслеживаемого файла
            old_hash: Старый хеш
            new_hash: Новый хеш
            old_size: Старый размер
            new_size: Новый размер
            diff_summary: Краткое описание изменений
            change_percent: Процент изменения
            is_significant: Значимое ли изменение
            
        Returns:
            Change объект
        """
        session = self.get_session()
        try:
            change = Change(
                file_id=file_id,
                old_hash=old_hash,
                new_hash=new_hash,
                old_size=old_size,
                new_size=new_size,
                diff_summary=diff_summary,
                change_percent=change_percent,
                is_significant=1 if is_significant else 0
            )
            session.add(change)
            session.commit()
            session.refresh(change)
            logger.info(f"Сохранено изменение для файла ID={file_id}")
            return change
            
        except Exception as e:
            session.rollback()
            logger.error(f"Ошибка при сохранении изменения: {e}", exc_info=True)
            raise
        finally:
            session.close()
    
    def save_announcement(self, change_id: int, title: str, content: str,
                         change_type: str = None, severity: str = None) -> Announcement:
        """
        Сохранить анонс
        
        Args:
            change_id: ID изменения
            title: Заголовок анонса
            content: Содержимое анонса
            change_type: Тип изменения
            severity: Уровень важности
            
        Returns:
            Announcement объект
        """
        session = self.get_session()
        try:
            announcement = Announcement(
                change_id=change_id,
                title=title,
                content=content,
                change_type=change_type,
                severity=severity
            )
            session.add(announcement)
            session.commit()
            session.refresh(announcement)
            logger.info(f"Сохранен анонс для изменения ID={change_id}")
            return announcement
            
        except Exception as e:
            session.rollback()
            logger.error(f"Ошибка при сохранении анонса: {e}", exc_info=True)
            raise
        finally:
            session.close()
    
    def get_recent_announcements(self, limit: int = 10) -> List[Announcement]:
        """
        Получить последние анонсы
        
        Args:
            limit: Количество анонсов
            
        Returns:
            Список анонсов
        """
        session = self.get_session()
        try:
            return session.query(Announcement).order_by(
                Announcement.generated_at.desc()
            ).limit(limit).all()
        finally:
            session.close()
    
    def get_changes_without_announcements(self) -> List[Change]:
        """Получить изменения без анонсов"""
        session = self.get_session()
        try:
            return session.query(Change).filter(
                ~Change.announcements.any()
            ).all()
        finally:
            session.close()
    
    def save_discovered_file(self, url: str, source_page: str, 
                           pattern_matched: str = None, 
                           suggested_category: str = None) -> DiscoveredFile:
        """
        Сохранить обнаруженный новый файл
        
        Args:
            url: URL обнаруженного файла
            source_page: Страница, на которой файл был обнаружен
            pattern_matched: Паттерн, который совпал
            suggested_category: Предложенная категория
            
        Returns:
            DiscoveredFile объект
        """
        session = self.get_session()
        try:
            # Проверить, не существует ли уже
            existing = session.query(DiscoveredFile).filter(
                DiscoveredFile.url == url
            ).first()
            
            if existing:
                return existing
            
            discovered = DiscoveredFile(
                url=url,
                source_page=source_page,
                pattern_matched=pattern_matched,
                suggested_category=suggested_category
            )
            session.add(discovered)
            session.commit()
            session.refresh(discovered)
            logger.info(f"Обнаружен новый файл: {url} (category={suggested_category})")
            return discovered
            
        except Exception as e:
            session.rollback()
            logger.error(f"Ошибка при сохранении обнаруженного файла: {e}", exc_info=True)
            raise
        finally:
            session.close()
    
    def get_undiscovered_files(self) -> List[DiscoveredFile]:
        """Получить файлы, которые еще не добавлены в отслеживание"""
        session = self.get_session()
        try:
            return session.query(DiscoveredFile).filter(
                DiscoveredFile.added_to_tracking == 0
            ).all()
        finally:
            session.close()
    
    def mark_discovered_as_tracked(self, discovered_id: int):
        """Отметить обнаруженный файл как добавленный в отслеживание"""
        session = self.get_session()
        try:
            discovered = session.query(DiscoveredFile).filter(
                DiscoveredFile.id == discovered_id
            ).first()
            
            if discovered:
                discovered.added_to_tracking = 1
                session.commit()
                logger.info(f"Файл {discovered.url} отмечен как отслеживаемый")
                
        except Exception as e:
            session.rollback()
            logger.error(f"Ошибка при обновлении discovered file: {e}", exc_info=True)
            raise
        finally:
            session.close()
    
    # ==================== НОВЫЕ МЕТОДЫ ДЛЯ ВЕРСИОНИРОВАНИЯ ====================
    
    def get_active_tracked_files(self) -> List[TrackedFile]:
        """Получить только активные отслеживаемые файлы"""
        session = self.get_session()
        try:
            return session.query(TrackedFile).filter(
                TrackedFile.is_active == 1
            ).all()
        finally:
            session.close()
    
    def get_file_by_base_name(self, base_name: str) -> Optional[TrackedFile]:
        """Получить активный файл по базовому имени"""
        session = self.get_session()
        try:
            return session.query(TrackedFile).filter(
                TrackedFile.base_name == base_name,
                TrackedFile.is_active == 1
            ).first()
        finally:
            session.close()
    
    def increment_404_count(self, url: str):
        """Увеличить счетчик 404 ошибок для файла"""
        session = self.get_session()
        try:
            tracked_file = session.query(TrackedFile).filter(
                TrackedFile.url == url
            ).first()
            
            if tracked_file:
                tracked_file.consecutive_404_count += 1
                tracked_file.last_404_at = datetime.utcnow()
                session.commit()
                logger.warning(f"404 count для {url}: {tracked_file.consecutive_404_count}")
                
        except Exception as e:
            session.rollback()
            logger.error(f"Ошибка при обновлении 404 счетчика: {e}", exc_info=True)
        finally:
            session.close()
    
    def reset_404_count(self, url: str):
        """Сбросить счетчик 404 ошибок для файла"""
        session = self.get_session()
        try:
            tracked_file = session.query(TrackedFile).filter(
                TrackedFile.url == url
            ).first()
            
            if tracked_file:
                tracked_file.consecutive_404_count = 0
                tracked_file.last_404_at = None
                session.commit()
                
        except Exception as e:
            session.rollback()
            logger.error(f"Ошибка при сбросе 404 счетчика: {e}", exc_info=True)
        finally:
            session.close()
    
    def get_files_with_404_errors(self, min_count: int = 3) -> List[TrackedFile]:
        """Получить файлы с критическим количеством 404 ошибок"""
        session = self.get_session()
        try:
            return session.query(TrackedFile).filter(
                TrackedFile.consecutive_404_count >= min_count
            ).all()
        finally:
            session.close()
    
    # FileVersion методы
    
    def save_file_version(self, base_name: str, version: str, full_url: str,
                         file_type: str, category: str, priority: str, domain: str,
                         last_hash: str = None, last_content: str = None,
                         last_size: int = None, tracked_file_id: int = None) -> FileVersion:
        """Сохранить архивную версию файла"""
        session = self.get_session()
        try:
            file_version = FileVersion(
                base_name=base_name,
                version=version,
                full_url=full_url,
                file_type=file_type,
                category=category,
                priority=priority,
                domain=domain,
                last_hash=last_hash,
                last_content=last_content,
                last_size=last_size,
                tracked_file_id=tracked_file_id,
                is_active=0
            )
            session.add(file_version)
            session.commit()
            session.refresh(file_version)
            logger.info(f"Архивирована версия: {base_name} v{version}")
            return file_version
            
        except Exception as e:
            session.rollback()
            logger.error(f"Ошибка при сохранении версии: {e}", exc_info=True)
            raise
        finally:
            session.close()
    
    def get_versions_by_base_name(self, base_name: str) -> List[FileVersion]:
        """Получить все версии файла по базовому имени"""
        session = self.get_session()
        try:
            return session.query(FileVersion).filter(
                FileVersion.base_name == base_name
            ).order_by(FileVersion.archived_at.desc()).all()
        finally:
            session.close()
    
    def get_version_by_exact(self, base_name: str, version: str) -> Optional[FileVersion]:
        """Получить конкретную версию файла"""
        session = self.get_session()
        try:
            return session.query(FileVersion).filter(
                FileVersion.base_name == base_name,
                FileVersion.version == version
            ).first()
        finally:
            session.close()
    
    # VersionAlert методы
    
    def create_version_alert(self, base_name: str, old_version: str, new_version: str,
                           old_url: str, new_url: str, category: str,
                           priority: str) -> VersionAlert:
        """Создать алерт о новой версии"""
        session = self.get_session()
        try:
            alert = VersionAlert(
                base_name=base_name,
                old_version=old_version,
                new_version=new_version,
                old_url=old_url,
                new_url=new_url,
                category=category,
                priority=priority,
                migration_status='pending'
            )
            session.add(alert)
            session.commit()
            session.refresh(alert)
            logger.info(f"Создан алерт: {base_name} {old_version} -> {new_version}")
            return alert
            
        except Exception as e:
            session.rollback()
            logger.error(f"Ошибка при создании алерта: {e}", exc_info=True)
            raise
        finally:
            session.close()
    
    def update_version_alert_status(self, alert_id: int, status: str,
                                   error_message: str = None):
        """Обновить статус миграции в алерте"""
        session = self.get_session()
        try:
            alert = session.query(VersionAlert).filter(
                VersionAlert.id == alert_id
            ).first()
            
            if alert:
                alert.migration_status = status
                if status == 'completed':
                    alert.migration_completed_at = datetime.utcnow()
                if status in ['completed', 'failed']:
                    alert.migration_attempted_at = datetime.utcnow()
                if error_message:
                    alert.error_message = error_message
                session.commit()
                logger.info(f"Статус алерта {alert_id} обновлен: {status}")
                
        except Exception as e:
            session.rollback()
            logger.error(f"Ошибка при обновлении алерта: {e}", exc_info=True)
            raise
        finally:
            session.close()
    
    def get_pending_alerts(self) -> List[VersionAlert]:
        """Получить алерты в ожидании миграции"""
        session = self.get_session()
        try:
            return session.query(VersionAlert).filter(
                VersionAlert.migration_status == 'pending'
            ).all()
        finally:
            session.close()
    
    def get_recent_version_alerts(self, limit: int = 10) -> List[VersionAlert]:
        """Получить последние алерты о версиях"""
        session = self.get_session()
        try:
            return session.query(VersionAlert).order_by(
                VersionAlert.discovered_at.desc()
            ).limit(limit).all()
        finally:
            session.close()
    
    def mark_alert_telegram_sent(self, alert_id: int):
        """Отметить, что Telegram уведомление отправлено"""
        session = self.get_session()
        try:
            alert = session.query(VersionAlert).filter(
                VersionAlert.id == alert_id
            ).first()
            
            if alert:
                alert.telegram_sent = 1
                session.commit()
                
        except Exception as e:
            session.rollback()
            logger.error(f"Ошибка при обновлении алерта: {e}", exc_info=True)
        finally:
            session.close()
    
    # MigrationMetrics методы
    
    def save_migration_metrics(self, discovered: int = 0, successful: int = 0,
                              failed: int = 0, rollbacks: int = 0,
                              avg_migration_time: float = None,
                              avg_validation_time: float = None) -> MigrationMetrics:
        """Сохранить метрики миграции"""
        session = self.get_session()
        try:
            metrics = MigrationMetrics(
                total_versions_discovered=discovered,
                successful_migrations=successful,
                failed_migrations=failed,
                rollbacks_performed=rollbacks,
                avg_migration_time_seconds=avg_migration_time,
                avg_validation_time_seconds=avg_validation_time
            )
            session.add(metrics)
            session.commit()
            session.refresh(metrics)
            return metrics
            
        except Exception as e:
            session.rollback()
            logger.error(f"Ошибка при сохранении метрик: {e}", exc_info=True)
            raise
        finally:
            session.close()
    
    def get_metrics_summary(self, days: int = 30) -> dict:
        """Получить сводку метрик за последние N дней"""
        session = self.get_session()
        try:
            from datetime import timedelta
            cutoff_date = datetime.utcnow() - timedelta(days=days)
            
            metrics = session.query(MigrationMetrics).filter(
                MigrationMetrics.date >= cutoff_date
            ).all()
            
            if not metrics:
                return {
                    'total_discovered': 0,
                    'total_successful': 0,
                    'total_failed': 0,
                    'total_rollbacks': 0,
                    'avg_migration_time': 0,
                    'period_days': days
                }
            
            return {
                'total_discovered': sum(m.total_versions_discovered for m in metrics),
                'total_successful': sum(m.successful_migrations for m in metrics),
                'total_failed': sum(m.failed_migrations for m in metrics),
                'total_rollbacks': sum(m.rollbacks_performed for m in metrics),
                'avg_migration_time': sum(m.avg_migration_time_seconds or 0 for m in metrics) / len(metrics),
                'period_days': days
            }
            
        finally:
            session.close()


# Глобальный экземпляр базы данных
db = Database()



