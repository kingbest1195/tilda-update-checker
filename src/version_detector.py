"""
Модуль для обнаружения и сравнения версий файлов Tilda CDN
"""
import logging
import re
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse
from packaging import version as pkg_version

from src.database import db, TrackedFile, DiscoveredFile

logger = logging.getLogger(__name__)


class VersionDetector:
    """Класс для обнаружения новых версий файлов"""
    
    # Паттерны для извлечения версий из URL
    VERSION_PATTERNS = [
        # tilda-cart-1.1.min.js
        r'(?P<base>[\w-]+)-(?P<version>\d+\.\d+(?:\.\d+)?)(\.min)?\.(?P<ext>js|css)',
        # tilda-cart-v2.min.js
        r'(?P<base>[\w-]+)-v(?P<version>\d+(?:\.\d+)*)(\.min)?\.(?P<ext>js|css)',
        # tilda-cart.1.0.min.js (менее вероятно, но возможно)
        r'(?P<base>[\w-]+)\.(?P<version>\d+\.\d+(?:\.\d+)?)(\.min)?\.(?P<ext>js|css)',
        # Без версии: tilda-cart.min.js
        r'(?P<base>[\w-]+)(\.min)?\.(?P<ext>js|css)$',
    ]
    
    def __init__(self):
        """Инициализация детектора версий"""
        pass
    
    def parse_file_url(self, url: str) -> Dict[str, Optional[str]]:
        """
        Парсинг URL для извлечения базового имени и версии
        
        Args:
            url: URL файла
            
        Returns:
            Словарь с ключами: base_name, version, file_type, domain, full_url
        """
        parsed_url = urlparse(url)
        domain = parsed_url.netloc
        path = parsed_url.path
        filename = path.split('/')[-1]
        
        result = {
            'base_name': None,
            'version': None,
            'file_type': None,
            'domain': domain,
            'full_url': url,
            'filename': filename
        }
        
        # Попробовать все паттерны
        for pattern in self.VERSION_PATTERNS:
            match = re.search(pattern, filename)
            if match:
                groups = match.groupdict()
                result['base_name'] = groups.get('base')
                result['version'] = groups.get('version', None)
                result['file_type'] = groups.get('ext')
                
                logger.debug(f"Parsed {filename}: base='{result['base_name']}', version='{result['version']}'")
                return result
        
        # Если ничего не совпало, попытка извлечь хотя бы базовое имя
        if filename.endswith('.js'):
            result['base_name'] = filename.replace('.min.js', '').replace('.js', '')
            result['file_type'] = 'js'
        elif filename.endswith('.css'):
            result['base_name'] = filename.replace('.min.css', '').replace('.css', '')
            result['file_type'] = 'css'
        
        logger.debug(f"Fallback parse for {filename}: base='{result['base_name']}', no version")
        return result
    
    def compare_versions(self, version1: str, version2: str) -> int:
        """
        Семантическое сравнение версий
        
        Args:
            version1: Первая версия (например, "1.0")
            version2: Вторая версия (например, "1.1")
            
        Returns:
            -1 если version1 < version2
             0 если version1 == version2
             1 если version1 > version2
        """
        if version1 is None and version2 is None:
            return 0
        if version1 is None:
            return -1
        if version2 is None:
            return 1
        
        try:
            v1 = pkg_version.parse(version1)
            v2 = pkg_version.parse(version2)
            
            if v1 < v2:
                return -1
            elif v1 > v2:
                return 1
            else:
                return 0
                
        except Exception as e:
            logger.warning(f"Ошибка при сравнении версий '{version1}' и '{version2}': {e}")
            # Fallback на строковое сравнение
            if version1 < version2:
                return -1
            elif version1 > version2:
                return 1
            else:
                return 0
    
    def is_newer_version(self, current_version: str, new_version: str) -> bool:
        """
        Проверить, является ли new_version новее current_version
        
        Args:
            current_version: Текущая версия
            new_version: Новая версия
            
        Returns:
            True если новая версия действительно новее
        """
        return self.compare_versions(current_version, new_version) == -1
    
    def find_version_updates(self, tracked_files: List[TrackedFile],
                           discovered_files: List[DiscoveredFile]) -> List[Dict]:
        """
        Найти обновления версий, сравнивая отслеживаемые и обнаруженные файлы
        
        Args:
            tracked_files: Список отслеживаемых файлов
            discovered_files: Список обнаруженных файлов
            
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
        updates = []
        
        # Создать индекс отслеживаемых файлов по base_name
        tracked_index = {}
        for tf in tracked_files:
            if not tf.base_name:
                # Если base_name не установлено, парсим URL
                parsed = self.parse_file_url(tf.url)
                tf.base_name = parsed['base_name']
            
            if tf.base_name and tf.is_active:
                tracked_index[tf.base_name] = tf
        
        # Проверить обнаруженные файлы на наличие новых версий
        for df in discovered_files:
            parsed = self.parse_file_url(df.url)
            base_name = parsed['base_name']
            new_version = parsed['version']
            
            if not base_name:
                continue
            
            # Проверить, есть ли этот файл в отслеживаемых
            if base_name in tracked_index:
                tracked_file = tracked_index[base_name]
                current_version = tracked_file.version
                
                # Если у обнаруженного файла есть версия и она новее
                if new_version and self.is_newer_version(current_version, new_version):
                    updates.append({
                        'base_name': base_name,
                        'current_version': current_version or 'unknown',
                        'current_url': tracked_file.url,
                        'new_version': new_version,
                        'new_url': df.url,
                        'priority': tracked_file.priority,
                        'category': tracked_file.category,
                        'file_type': parsed['file_type'],
                        'domain': parsed['domain']
                    })
                    
                    logger.info(
                        f"🆕 Найдено обновление: {base_name} "
                        f"{current_version or 'unknown'} -> {new_version}"
                    )
        
        return updates
    
    def get_all_versions_for_base(self, base_name: str) -> List[Dict]:
        """
        Получить все версии конкретного файла (активные и архивные)
        
        Args:
            base_name: Базовое имя файла
            
        Returns:
            Список словарей с информацией о версиях
        """
        versions = []
        
        # Получить активную версию из TrackedFile
        tracked_file = db.get_file_by_base_name(base_name)
        if tracked_file:
            versions.append({
                'base_name': base_name,
                'version': tracked_file.version or 'unknown',
                'url': tracked_file.url,
                'is_active': True,
                'category': tracked_file.category,
                'priority': tracked_file.priority,
                'last_checked': tracked_file.last_checked
            })
        
        # Получить архивные версии из FileVersion
        archived_versions = db.get_versions_by_base_name(base_name)
        for av in archived_versions:
            versions.append({
                'base_name': base_name,
                'version': av.version,
                'url': av.full_url,
                'is_active': False,
                'category': av.category,
                'priority': av.priority,
                'archived_at': av.archived_at
            })
        
        # Сортировать по версии (новые сверху)
        versions.sort(
            key=lambda x: pkg_version.parse(x['version']) if x['version'] != 'unknown' else pkg_version.parse('0.0'),
            reverse=True
        )
        
        return versions
    
    def detect_schema_change(self, old_url: str, new_url: str) -> Optional[str]:
        """
        Обнаружить изменение схемы именования файла
        
        Args:
            old_url: Старый URL
            new_url: Новый URL
            
        Returns:
            Описание изменения или None
        """
        old_parsed = self.parse_file_url(old_url)
        new_parsed = self.parse_file_url(new_url)
        
        # Проверить, изменилось ли базовое имя
        if old_parsed['base_name'] != new_parsed['base_name']:
            # Вычислить схожесть (простая метрика)
            similarity = self._calculate_similarity(
                old_parsed['base_name'],
                new_parsed['base_name']
            )
            
            if similarity > 0.7:  # Высокая схожесть
                return (
                    f"Возможна смена схемы именования: "
                    f"{old_parsed['base_name']} -> {new_parsed['base_name']} "
                    f"(схожесть: {similarity:.0%})"
                )
        
        return None
    
    def _calculate_similarity(self, str1: str, str2: str) -> float:
        """
        Вычислить простую метрику схожести строк (Levenshtein-подобная)
        
        Args:
            str1: Первая строка
            str2: Вторая строка
            
        Returns:
            Коэффициент схожести от 0 до 1
        """
        if not str1 or not str2:
            return 0.0
        
        # Простая метрика: количество общих подстрок
        longer = str1 if len(str1) >= len(str2) else str2
        shorter = str2 if len(str1) >= len(str2) else str1
        
        # Подсчитать общие символы в правильном порядке
        matches = 0
        j = 0
        for i, char in enumerate(shorter):
            if j < len(longer) and char == longer[j]:
                matches += 1
                j += 1
        
        return matches / len(longer)
    
    def analyze_discovered_files(self) -> Dict[str, List]:
        """
        Анализ всех обнаруженных файлов и поиск потенциальных обновлений
        
        Returns:
            Словарь с категориями результатов:
            - version_updates: файлы с новыми версиями
            - new_files: совершенно новые файлы
            - schema_changes: файлы с изменениями схемы именования
        """
        tracked_files = db.get_active_tracked_files()
        discovered_files = db.get_undiscovered_files()
        
        version_updates = self.find_version_updates(tracked_files, discovered_files)
        
        # Определить новые файлы (не имеющие соответствий в tracked)
        tracked_base_names = {tf.base_name for tf in tracked_files if tf.base_name}
        
        new_files = []
        for df in discovered_files:
            parsed = self.parse_file_url(df.url)
            base_name = parsed['base_name']
            
            if base_name and base_name not in tracked_base_names:
                new_files.append({
                    'base_name': base_name,
                    'version': parsed['version'] or 'unknown',
                    'url': df.url,
                    'suggested_category': df.suggested_category,
                    'source_page': df.source_page
                })
        
        # Анализ изменений схемы (требует дополнительной логики)
        schema_changes = []
        # TODO: реализовать при необходимости
        
        return {
            'version_updates': version_updates,
            'new_files': new_files,
            'schema_changes': schema_changes
        }
    
    def print_version_updates_report(self, updates: List[Dict]):
        """Вывести отчет об обнаруженных обновлениях версий"""
        if not updates:
            logger.info("📭 Обновлений версий не обнаружено")
            return
        
        logger.info(f"\n{'='*80}")
        logger.info(f"📋 ОТЧЕТ ОБ ОБНОВЛЕНИЯХ ВЕРСИЙ")
        logger.info(f"{'='*80}")
        logger.info(f"Обнаружено обновлений: {len(updates)}\n")
        
        # Группировка по категориям
        by_category = {}
        for update in updates:
            cat = update['category']
            if cat not in by_category:
                by_category[cat] = []
            by_category[cat].append(update)
        
        # Вывести по категориям с приоритетами
        priority_order = {'CRITICAL': 0, 'HIGH': 1, 'MEDIUM': 2, 'LOW': 3}
        sorted_categories = sorted(
            by_category.items(),
            key=lambda x: priority_order.get(updates[0]['priority'], 99)
        )
        
        for category, cat_updates in sorted_categories:
            priority = cat_updates[0]['priority']
            logger.info(f"📁 Категория: {category} (Приоритет: {priority}) - {len(cat_updates)} обновлений")
            
            for update in cat_updates:
                logger.info(f"   🆕 {update['base_name']}")
                logger.info(f"      Текущая: {update['current_version']}")
                logger.info(f"      Новая: {update['new_version']} ✨")
                logger.info(f"      URL: {update['new_url']}")
            logger.info("")
        
        logger.info(f"{'='*80}\n")


# Глобальный экземпляр детектора
detector = VersionDetector()



