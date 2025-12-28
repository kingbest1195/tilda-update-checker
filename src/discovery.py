"""
Модуль для автоматического обнаружения новых файлов Tilda (Discovery Mode)
"""
import logging
import re
from typing import List, Dict, Set, Optional
from urllib.parse import urlparse, urljoin

import requests
from bs4 import BeautifulSoup

import config
from src.database import db
from src.version_detector import detector
from src.alert_system import alert_system

logger = logging.getLogger(__name__)


# Паттерны для категоризации обнаруженных файлов
PATTERN_CATEGORIES = {
    r"tilda-members|members\.tildaapi\.com|members2\.tildacdn\.com": "members",
    r"tilda-(cart|catalog|wishlist|products|variant)": "ecommerce",
    r"tilda-zero": "zero_block",
    r"tilda-(quiz|cards|stories|slider|popup|slds|zoom|video)": "ui_components",
    r"tilda-(scripts|grid|forms|animation|cover|menu|lazyload|events)": "core",
    r"tilda-(phone|conditional|payment|ratescale|step-manager|widget|lk|skiplink|stat|error|performance|table|paint|redactor|highlight)": "utilities",
}

# Приоритеты для категорий
CATEGORY_PRIORITIES = {
    "core": "CRITICAL",
    "members": "CRITICAL",
    "ecommerce": "HIGH",
    "zero_block": "HIGH",
    "ui_components": "MEDIUM",
    "utilities": "LOW",
    "unknown": "MEDIUM"
}

# Домены Tilda для фильтрации
TILDA_DOMAINS = [
    "static.tildacdn.com",
    "members.tildaapi.com",
    "members2.tildacdn.com",
    "neo.tildacdn.com",
]

# Страницы-канарейки для сканирования
CANARY_PAGES = [
    "https://tilda.nomadnocode.com/all-external",
    "https://tilda.nomadnocode.com/members/login",
    "https://tilda.nomadnocode.com/members/recover-password",
]


class FileDiscovery:
    """Класс для автоматического обнаружения новых файлов"""
    
    def __init__(self):
        """Инициализация discovery"""
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': config.USER_AGENT
        })
    
    def discover_files(self) -> List[Dict]:
        """
        Обнаружить новые файлы на канарейка-страницах
        
        Returns:
            Список обнаруженных новых файлов
        """
        all_discovered = []
        already_tracked = self._get_tracked_urls()
        
        logger.info(f"Начало Discovery Mode. Уже отслеживается файлов: {len(already_tracked)}")
        
        for page_url in CANARY_PAGES:
            try:
                logger.info(f"Сканирование страницы: {page_url}")
                discovered = self._scan_page(page_url, already_tracked)
                
                if discovered:
                    logger.info(f"  → Найдено новых файлов: {len(discovered)}")
                    all_discovered.extend(discovered)
                else:
                    logger.info(f"  → Новых файлов не обнаружено")
                    
            except Exception as e:
                logger.error(f"Ошибка при сканировании {page_url}: {e}", exc_info=True)
        
        # Удалить дубликаты
        unique_discovered = self._remove_duplicates(all_discovered)
        
        logger.info(f"Discovery Mode завершен. Найдено уникальных новых файлов: {len(unique_discovered)}")
        
        # Сохранить в БД
        for file_info in unique_discovered:
            self._save_discovered_file(file_info)
        
        return unique_discovered
    
    def _get_tracked_urls(self) -> Set[str]:
        """
        Получить множество уже отслеживаемых URL
        
        Returns:
            Множество URL
        """
        tracked = set()
        
        # Из config
        for category_data in config.TILDA_MONITORED_FILES.values():
            tracked.update(category_data.get('files', []))
        
        # Из БД
        tracked_files = db.get_tracked_files()
        for tf in tracked_files:
            tracked.add(tf.url)
        
        return tracked
    
    def _scan_page(self, page_url: str, already_tracked: Set[str]) -> List[Dict]:
        """
        Сканировать страницу на наличие ссылок на Tilda файлы
        
        Args:
            page_url: URL страницы для сканирования
            already_tracked: Множество уже отслеживаемых URL
            
        Returns:
            Список обнаруженных файлов
        """
        try:
            response = self.session.get(page_url, timeout=30)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Найти все script и link теги
            discovered_urls = set()
            
            # Script теги
            for script in soup.find_all('script', src=True):
                url = urljoin(page_url, script['src'])
                if self._is_tilda_url(url):
                    discovered_urls.add(url)
            
            # Link теги (CSS)
            for link in soup.find_all('link', href=True):
                if link.get('rel') == ['stylesheet'] or link['href'].endswith('.css'):
                    url = urljoin(page_url, link['href'])
                    if self._is_tilda_url(url):
                        discovered_urls.add(url)
            
            # Фильтровать уже отслеживаемые
            new_urls = discovered_urls - already_tracked
            
            # Категоризировать
            discovered_files = []
            for url in new_urls:
                file_info = self._categorize_file(url, page_url)
                discovered_files.append(file_info)
            
            return discovered_files
            
        except Exception as e:
            logger.error(f"Ошибка при обработке страницы {page_url}: {e}")
            return []
    
    def _is_tilda_url(self, url: str) -> bool:
        """
        Проверить, относится ли URL к Tilda
        
        Args:
            url: URL для проверки
            
        Returns:
            True если это Tilda URL
        """
        parsed = urlparse(url)
        domain = parsed.netloc
        
        return any(tilda_domain in domain for tilda_domain in TILDA_DOMAINS)
    
    def _categorize_file(self, url: str, source_page: str) -> Dict:
        """
        Категоризировать обнаруженный файл
        
        Args:
            url: URL файла
            source_page: Страница, на которой был обнаружен
            
        Returns:
            Словарь с информацией о файле
        """
        # Определить категорию по паттернам
        category = "unknown"
        pattern_matched = None
        
        for pattern, cat in PATTERN_CATEGORIES.items():
            if re.search(pattern, url, re.IGNORECASE):
                category = cat
                pattern_matched = pattern
                break
        
        # Определить приоритет
        priority = CATEGORY_PRIORITIES.get(category, "MEDIUM")
        
        # Определить тип файла
        if url.endswith('.js'):
            file_type = 'js'
        elif url.endswith('.css'):
            file_type = 'css'
        else:
            file_type = 'unknown'
        
        # Извлечь домен
        parsed = urlparse(url)
        domain = parsed.netloc
        
        return {
            'url': url,
            'category': category,
            'priority': priority,
            'file_type': file_type,
            'domain': domain,
            'source_page': source_page,
            'pattern_matched': pattern_matched
        }
    
    def _remove_duplicates(self, discovered: List[Dict]) -> List[Dict]:
        """
        Удалить дубликаты из списка обнаруженных файлов
        
        Args:
            discovered: Список обнаруженных файлов
            
        Returns:
            Список без дубликатов
        """
        seen_urls = set()
        unique = []
        
        for file_info in discovered:
            url = file_info['url']
            if url not in seen_urls:
                seen_urls.add(url)
                unique.append(file_info)
        
        return unique
    
    def _save_discovered_file(self, file_info: Dict):
        """
        Сохранить обнаруженный файл в БД
        
        Args:
            file_info: Информация о файле
        """
        try:
            db.save_discovered_file(
                url=file_info['url'],
                source_page=file_info['source_page'],
                pattern_matched=file_info.get('pattern_matched'),
                suggested_category=file_info['category']
            )
        except Exception as e:
            logger.error(f"Ошибка при сохранении обнаруженного файла {file_info['url']}: {e}")
    
    def get_new_discoveries(self) -> List[Dict]:
        """
        Получить список файлов, которые еще не добавлены в отслеживание
        
        Returns:
            Список обнаруженных файлов
        """
        discovered_files = db.get_undiscovered_files()
        
        result = []
        for df in discovered_files:
            result.append({
                'id': df.id,
                'url': df.url,
                'category': df.suggested_category,
                'discovered_at': df.discovered_at,
                'source_page': df.source_page
            })
        
        return result
    
    def print_discovery_report(self):
        """Вывести отчет об обнаруженных файлах"""
        undiscovered = self.get_new_discoveries()
        
        if not undiscovered:
            logger.info("📭 Новых обнаруженных файлов нет")
            return
        
        logger.info(f"\n{'='*80}")
        logger.info(f"📋 ОТЧЕТ DISCOVERY MODE")
        logger.info(f"{'='*80}")
        logger.info(f"Обнаружено новых файлов: {len(undiscovered)}\n")
        
        # Группировка по категориям
        by_category = {}
        for file_info in undiscovered:
            cat = file_info['category']
            if cat not in by_category:
                by_category[cat] = []
            by_category[cat].append(file_info)
        
        # Вывести по категориям
        for category, files in sorted(by_category.items()):
            logger.info(f"📁 Категория: {category} ({len(files)} файлов)")
            for file_info in files:
                logger.info(f"   → {file_info['url']}")
                logger.info(f"      Обнаружен на: {file_info['source_page']}")
            logger.info("")
        
        logger.info(f"{'='*80}\n")
    
    def detect_version_upgrades(self) -> List[Dict]:
        """
        Обнаружить потенциальные обновления версий
        
        Returns:
            Список словарей с информацией об обновлениях:
            - base_name
            - current_version
            - current_url
            - new_version
            - new_url
            - priority
            - category
        """
        logger.info("🔍 Поиск обновлений версий...")
        
        # Получить отслеживаемые файлы
        tracked_files = db.get_active_tracked_files()
        
        # Получить обнаруженные файлы
        discovered_files = db.get_undiscovered_files()
        
        if not discovered_files:
            logger.info("📭 Нет обнаруженных файлов для анализа")
            return []
        
        # Использовать version_detector для поиска обновлений
        updates = detector.find_version_updates(tracked_files, discovered_files)
        
        if updates:
            logger.info(f"🆕 Найдено обновлений версий: {len(updates)}")
            
            # Логировать каждое обновление через alert_system
            for update in updates:
                alert_system.log_version_update(update)
        else:
            logger.info("✅ Обновлений версий не обнаружено")
        
        return updates
    
    def run_full_discovery_with_version_check(self) -> Dict:
        """
        Запустить полный цикл Discovery Mode с проверкой версий
        
        Returns:
            Словарь с результатами:
            - discovered_files: список новых файлов
            - version_updates: список обновлений версий
            - new_files: полностью новые файлы (не обновления)
        """
        logger.info("\n" + "="*80)
        logger.info("🚀 ЗАПУСК ПОЛНОГО DISCOVERY MODE")
        logger.info("="*80 + "\n")
        
        # 1. Обнаружение файлов на канарейка-страницах
        logger.info("Шаг 1/3: Сканирование канарейка-страниц...")
        discovered_files = self.discover_files()
        
        # 2. Анализ обнаруженных файлов через version_detector
        logger.info("\nШаг 2/3: Анализ обнаруженных файлов...")
        analysis_result = detector.analyze_discovered_files()
        
        version_updates = analysis_result['version_updates']
        new_files = analysis_result['new_files']
        
        # 3. Вывод отчетов
        logger.info("\nШаг 3/3: Формирование отчетов...")
        
        if version_updates:
            detector.print_version_updates_report(version_updates)
        
        if new_files:
            logger.info(f"\n{'='*80}")
            logger.info(f"📦 НОВЫЕ ФАЙЛЫ (не обновления)")
            logger.info(f"{'='*80}")
            logger.info(f"Найдено новых файлов: {len(new_files)}\n")
            
            for nf in new_files[:10]:  # Показать первые 10
                logger.info(f"   🆕 {nf['base_name']} v{nf['version']}")
                logger.info(f"      URL: {nf['url']}")
                logger.info(f"      Категория: {nf.get('suggested_category', 'unknown')}")
            
            if len(new_files) > 10:
                logger.info(f"\n   ... и еще {len(new_files) - 10} файлов")
            
            logger.info(f"\n{'='*80}\n")
        
        logger.info("="*80)
        logger.info("✅ DISCOVERY MODE ЗАВЕРШЕН")
        logger.info(f"   Обнаружено файлов: {len(discovered_files)}")
        logger.info(f"   Обновлений версий: {len(version_updates)}")
        logger.info(f"   Новых файлов: {len(new_files)}")
        logger.info("="*80 + "\n")
        
        return {
            'discovered_files': discovered_files,
            'version_updates': version_updates,
            'new_files': new_files
        }


# Глобальный экземпляр discovery
discovery = FileDiscovery()

