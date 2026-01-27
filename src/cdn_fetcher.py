"""
Модуль для загрузки файлов с Tilda CDN
"""
import logging
import hashlib
import time
from typing import List, Dict, Optional, Tuple
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry

import config
from src.database import db

logger = logging.getLogger(__name__)


class CDNFetcher:
    """Класс для загрузки файлов с Tilda CDN"""
    
    def __init__(self):
        """Инициализация fetcher с настройками retry"""
        self.session = self._create_session()
    
    def _create_session(self) -> requests.Session:
        """
        Создать сессию с retry логикой
        
        Returns:
            Настроенная сессия requests
        """
        session = requests.Session()
        
        # Настройка retry стратегии
        retry_strategy = Retry(
            total=config.REQUEST_RETRY_COUNT,
            backoff_factor=config.REQUEST_RETRY_DELAY,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET"]
        )
        
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        
        # Установить User-Agent
        session.headers.update({
            'User-Agent': config.USER_AGENT
        })
        
        return session
    
    def get_monitored_files(self, use_db: bool = True) -> List[Dict[str, str]]:
        """
        Получить список файлов для мониторинга с метаданными
        
        Args:
            use_db: Использовать динамический конфиг из БД (True) или статический из config.py (False)
        
        Returns:
            Список словарей с URL, типом файла, категорией и приоритетом
        """
        files = []
        
        if use_db:
            # ДИНАМИЧЕСКИЙ КОНФИГ: получить активные файлы из БД
            logger.debug("Использование динамического конфига из БД...")
            tracked_files = db.get_active_tracked_files()
            
            for tf in tracked_files:
                files.append({
                    'url': tf.url,
                    'type': tf.file_type,
                    'category': tf.category,
                    'priority': tf.priority,
                    'domain': tf.domain
                })
            
            # Если в БД пусто, fallback на config.py
            if not files:
                logger.warning("⚠️ БД пуста, используется fallback на config.py")
                use_db = False
        
        if not use_db:
            # СТАТИЧЕСКИЙ КОНФИГ: из config.py
            logger.debug("Использование статического конфига из config.py...")
            for category, category_config in config.TILDA_MONITORED_FILES.items():
                priority = category_config.get('priority', 'MEDIUM')
                
                for url in category_config.get('files', []):
                    file_type = self._get_file_type(url)
                    domain = self._extract_domain(url)
                    
                    files.append({
                        'url': url,
                        'type': file_type,
                        'category': category,
                        'priority': priority,
                        'domain': domain
                    })
        
        logger.info(f"Найдено файлов для мониторинга: {len(files)}")
        logger.debug(f"Категории: {set(f['category'] for f in files)}")
        logger.debug(f"Домены: {set(f['domain'] for f in files)}")
        
        return files
    
    def _extract_domain(self, url: str) -> str:
        """
        Извлечь домен из URL
        
        Args:
            url: URL файла
            
        Returns:
            Домен (например, 'static.tildacdn.com')
        """
        parsed = urlparse(url)
        return parsed.netloc
    
    def _get_file_type(self, url: str) -> str:
        """
        Определить тип файла по URL
        
        Args:
            url: URL файла
            
        Returns:
            Тип файла ('js' или 'css')
        """
        if url.endswith('.js'):
            return 'js'
        elif url.endswith('.css'):
            return 'css'
        else:
            # По умолчанию
            return 'unknown'
    
    def download_file(self, url: str) -> Optional[Tuple[str, int]]:
        """
        Скачать файл с CDN
        
        Args:
            url: URL файла
            
        Returns:
            Кортеж (содержимое, размер) или None при ошибке
        """
        try:
            logger.debug(f"Скачивание: {url}")
            
            response = self.session.get(
                url,
                timeout=(5.0, config.REQUEST_TIMEOUT)  # (connect, read)
            )
            
            # Обработка 404 ошибок
            if response.status_code == 404:
                logger.error(f"❌ 404 Not Found: {url}")
                db.increment_404_count(url)
                return None
            
            response.raise_for_status()
            
            content = response.text
            size = len(content.encode('utf-8'))
            
            # Сбросить счетчик 404 при успешной загрузке
            db.reset_404_count(url)
            
            logger.debug(f"Успешно скачано: {url} ({size} байт)")
            return content, size

        except requests.exceptions.Timeout:
            logger.error(f"⏱ Timeout при загрузке {url}")
            return None
        except requests.exceptions.HTTPError as e:
            logger.error(f"🌐 HTTP ошибка {e.response.status_code}: {url}")
            return None
        except requests.exceptions.ConnectionError:
            logger.error(f"🔌 Ошибка соединения при загрузке {url}")
            return None
        except requests.exceptions.RequestException as e:
            logger.error(f"🌐 Ошибка сети: {url} - {e}")
            return None
        except Exception as e:
            logger.error(f"💥 Неожиданная ошибка при скачивании {url}: {e}", exc_info=True)
            return None
    
    def calculate_hash(self, content: str) -> str:
        """
        Вычислить SHA-256 хеш содержимого
        
        Args:
            content: Содержимое файла
            
        Returns:
            SHA-256 хеш в виде hex строки
        """
        return hashlib.sha256(content.encode('utf-8')).hexdigest()
    
    def download_all_files(self) -> List[Dict]:
        """
        Скачать все отслеживаемые файлы с метаданными
        
        Returns:
            Список словарей с информацией о файлах
        """
        files = self.get_monitored_files()
        results = []
        
        for file_info in files:
            url = file_info['url']
            file_type = file_info['type']
            category = file_info['category']
            priority = file_info['priority']
            domain = file_info['domain']
            
            # Скачать файл
            download_result = self.download_file(url)
            
            if download_result:
                content, size = download_result
                content_hash = self.calculate_hash(content)
                
                results.append({
                    'url': url,
                    'type': file_type,
                    'category': category,
                    'priority': priority,
                    'domain': domain,
                    'content': content,
                    'hash': content_hash,
                    'size': size,
                    'success': True
                })
                
                logger.info(f"✓ [{category}] {url} - {size} байт, hash: {content_hash[:16]}...")
            else:
                results.append({
                    'url': url,
                    'type': file_type,
                    'category': category,
                    'priority': priority,
                    'domain': domain,
                    'content': None,
                    'hash': None,
                    'size': None,
                    'success': False
                })
                
                logger.warning(f"✗ [{category}] {url} - ошибка загрузки")
            
            # Небольшая задержка между запросами
            time.sleep(0.5)
        
        success_count = sum(1 for r in results if r['success'])
        logger.info(f"Загружено файлов: {success_count}/{len(results)}")
        
        # Статистика по категориям
        categories_stats = {}
        for r in results:
            if r['success']:
                cat = r['category']
                categories_stats[cat] = categories_stats.get(cat, 0) + 1
        
        logger.info(f"По категориям: {categories_stats}")
        
        return results
    
    def add_file_to_monitoring(self, url: str, category: str = 'unknown',
                              priority: str = 'MEDIUM') -> bool:
        """
        Добавить новый файл для мониторинга
        
        Args:
            url: URL файла
            category: Категория файла
            priority: Приоритет файла
            
        Returns:
            True если успешно добавлен
        """
        try:
            from src.version_detector import detector
            
            # Парсинг URL для извлечения метаданных
            parsed = detector.parse_file_url(url)
            
            # Загрузить файл для получения начального состояния
            download_result = self.download_file(url)
            
            if not download_result:
                logger.error(f"Не удалось загрузить файл для добавления: {url}")
                return False
            
            content, size = download_result
            content_hash = self.calculate_hash(content)
            
            # Сохранить в БД
            tracked_file = db.save_file_state(
                url=url,
                file_type=parsed['file_type'],
                content=content,
                content_hash=content_hash,
                size=size,
                category=category,
                priority=priority,
                domain=parsed['domain']
            )
            
            # Обновить base_name и version
            session = db.get_session()
            try:
                tf = session.query(db.TrackedFile).filter(
                    db.TrackedFile.id == tracked_file.id
                ).first()
                if tf:
                    tf.base_name = parsed['base_name']
                    tf.version = parsed['version']
                    tf.is_active = 1
                    session.commit()
            except Exception as db_error:
                session.rollback()
                logger.error(f"Ошибка при обновлении метаданных файла: {db_error}", exc_info=True)
                raise
            finally:
                session.close()

            logger.info(f"✅ Файл добавлен в мониторинг: {url}")
            return True

        except Exception as e:
            logger.error(f"Ошибка при добавлении файла в мониторинг: {e}", exc_info=True)
            return False
    
    def check_404_errors(self) -> List[Dict]:
        """
        Проверить файлы с критическим количеством 404 ошибок
        
        Returns:
            Список файлов с 404 ошибками
        """
        files_with_404 = db.get_files_with_404_errors(min_count=3)
        
        if not files_with_404:
            logger.info("✅ Файлов с критическими 404 ошибками не обнаружено")
            return []
        
        logger.warning(f"⚠️ Обнаружено {len(files_with_404)} файлов с критическими 404 ошибками:")
        
        results = []
        for file in files_with_404:
            logger.warning(
                f"   🔴 {file.base_name or file.url}: "
                f"{file.consecutive_404_count} последовательных 404"
            )
            
            results.append({
                'url': file.url,
                'base_name': file.base_name,
                'consecutive_404_count': file.consecutive_404_count,
                'last_404_at': file.last_404_at,
                'category': file.category,
                'priority': file.priority
            })
        
        return results


# Глобальный экземпляр fetcher
fetcher = CDNFetcher()



