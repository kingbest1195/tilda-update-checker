"""
Модуль для обнаружения изменений в файлах
"""
import logging
import difflib
from typing import List, Dict, Optional, Tuple

import config
from src.database import db, TrackedFile, Change

logger = logging.getLogger(__name__)


class DiffDetector:
    """Класс для обнаружения изменений в файлах"""
    
    def __init__(self):
        """Инициализация детектора"""
        pass
    
    def check_for_changes(self, downloaded_files: List[Dict]) -> List[Dict]:
        """
        Проверить файлы на изменения
        
        Args:
            downloaded_files: Список скачанных файлов с информацией
            
        Returns:
            Список обнаруженных изменений
        """
        changes = []
        
        for file_data in downloaded_files:
            if not file_data['success']:
                continue
            
            url = file_data['url']
            new_content = file_data['content']
            new_hash = file_data['hash']
            new_size = file_data['size']
            file_type = file_data['type']
            category = file_data.get('category', 'unknown')
            priority = file_data.get('priority', 'MEDIUM')
            domain = file_data.get('domain', '')
            
            # Получить существующую запись из БД
            tracked_file = db.get_file_by_url(url)
            
            if not tracked_file:
                # Первая проверка - создать baseline
                logger.info(f"Новый файл для мониторинга: {url} [{category}]")
                db.save_file_state(url, file_type, new_content, new_hash, new_size,
                                  category=category, priority=priority, domain=domain)
                continue
            
            # Сравнить хеши
            if tracked_file.last_hash == new_hash:
                # Изменений нет
                logger.debug(f"Без изменений: {url}")
                # Обновить время проверки
                db.save_file_state(url, file_type, new_content, new_hash, new_size,
                                  category=category, priority=priority, domain=domain)
                continue
            
            # Обнаружены изменения!
            logger.info(f"🔍 Обнаружены изменения: {url} [{category}/{priority}]")
            
            # Анализ изменений
            change_info = self._analyze_change(
                tracked_file.last_content,
                new_content,
                tracked_file.last_size,
                new_size
            )
            
            # Сохранить изменение в БД
            change = db.save_change(
                file_id=tracked_file.id,
                old_hash=tracked_file.last_hash,
                new_hash=new_hash,
                old_size=tracked_file.last_size,
                new_size=new_size,
                diff_summary=change_info['summary'],
                change_percent=change_info['change_percent'],
                is_significant=change_info['is_significant']
            )
            
            # Обновить состояние файла
            db.save_file_state(url, file_type, new_content, new_hash, new_size,
                              category=category, priority=priority, domain=domain)
            
            # Добавить в список изменений
            changes.append({
                'change_id': change.id,
                'file_id': tracked_file.id,
                'url': url,
                'file_type': file_type,
                'category': category,
                'priority': priority,
                'domain': domain,
                'old_hash': tracked_file.last_hash,
                'new_hash': new_hash,
                'old_size': tracked_file.last_size,
                'new_size': new_size,
                'size_diff': new_size - tracked_file.last_size,
                'change_percent': change_info['change_percent'],
                'is_significant': change_info['is_significant'],
                'summary': change_info['summary'],
                'stats': change_info['stats']
            })
        
        logger.info(f"Всего обнаружено изменений: {len(changes)}")
        return changes
    
    def _analyze_change(self, old_content: str, new_content: str,
                       old_size: int, new_size: int) -> Dict:
        """
        Проанализировать изменение
        
        Args:
            old_content: Старое содержимое
            new_content: Новое содержимое
            old_size: Старый размер
            new_size: Новый размер
            
        Returns:
            Словарь с информацией об изменении
        """
        # Вычислить процент изменения
        size_diff = abs(new_size - old_size)
        change_percent = int((size_diff / old_size * 100)) if old_size > 0 else 100
        
        # Определить, значимое ли изменение
        is_significant = size_diff >= config.MIN_CHANGE_SIZE
        
        # Вычислить diff
        old_lines = old_content.splitlines(keepends=True)
        new_lines = new_content.splitlines(keepends=True)
        
        diff = list(difflib.unified_diff(
            old_lines,
            new_lines,
            lineterm='',
            n=0  # Контекст = 0 для минимального вывода
        ))
        
        # Статистика изменений
        added_lines = sum(1 for line in diff if line.startswith('+') and not line.startswith('+++'))
        removed_lines = sum(1 for line in diff if line.startswith('-') and not line.startswith('---'))
        
        # Создать краткую сводку
        summary = self._create_summary(size_diff, added_lines, removed_lines, change_percent)
        
        # Статистика для LLM
        stats = {
            'size_diff': size_diff,
            'change_percent': change_percent,
            'added_lines': added_lines,
            'removed_lines': removed_lines,
            'total_changes': added_lines + removed_lines
        }
        
        return {
            'summary': summary,
            'change_percent': change_percent,
            'is_significant': is_significant,
            'stats': stats,
            'diff_lines': diff[:100]  # Ограничить количество строк
        }
    
    def _create_summary(self, size_diff: int, added: int, removed: int,
                       change_percent: int) -> str:
        """
        Создать краткую сводку изменения
        
        Args:
            size_diff: Разница в размере
            added: Добавлено строк
            removed: Удалено строк
            change_percent: Процент изменения
            
        Returns:
            Текстовая сводка
        """
        direction = "увеличен" if size_diff > 0 else "уменьшен"
        return (
            f"Размер файла {direction} на {abs(size_diff)} байт ({change_percent}%). "
            f"Добавлено строк: {added}, удалено: {removed}."
        )
    
    def calculate_diff(self, old_content: str, new_content: str) -> str:
        """
        Вычислить полный diff между версиями
        
        Args:
            old_content: Старое содержимое
            new_content: Новое содержимое
            
        Returns:
            Строка с diff
        """
        old_lines = old_content.splitlines(keepends=True)
        new_lines = new_content.splitlines(keepends=True)
        
        diff = difflib.unified_diff(
            old_lines,
            new_lines,
            lineterm=''
        )
        
        return ''.join(diff)
    
    def extract_significant_changes(self, diff_lines: List[str], max_lines: int = 50) -> str:
        """
        Извлечь наиболее значимые изменения из diff
        
        Args:
            diff_lines: Строки diff
            max_lines: Максимальное количество строк
            
        Returns:
            Строка с ключевыми изменениями
        """
        # Фильтровать только добавления и удаления
        changes = [
            line for line in diff_lines
            if line.startswith('+') or line.startswith('-')
            if not line.startswith('+++') and not line.startswith('---')
        ]
        
        # Ограничить количество строк
        if len(changes) > max_lines:
            changes = changes[:max_lines]
            changes.append(f"\n... и еще {len(changes) - max_lines} изменений")
        
        return '\n'.join(changes)
    
    def prepare_llm_context(self, change_info: Dict, max_tokens: int = None) -> str:
        """
        Подготовить контекст для отправки в LLM
        
        Args:
            change_info: Информация об изменении
            max_tokens: Максимальное количество токенов (примерно)
            
        Returns:
            Подготовленный текст для LLM
        """
        if max_tokens is None:
            max_tokens = config.MAX_DIFF_TOKENS
        
        stats = change_info['stats']
        
        context = f"""Файл: {change_info['url']}
Тип: {change_info['file_type']}

Метаданные изменения:
- Старый размер: {change_info['old_size']} байт
- Новый размер: {change_info['new_size']} байт
- Разница: {change_info['size_diff']} байт ({change_info['change_percent']}%)
- Добавлено строк: {stats['added_lines']}
- Удалено строк: {stats['removed_lines']}
- Всего изменений: {stats['total_changes']}

Краткое описание: {change_info['summary']}
"""
        
        # Примерно 4 символа = 1 токен
        # Оставить место для остального промпта (~500 токенов)
        remaining_chars = (max_tokens - 500) * 4
        
        if len(context) < remaining_chars:
            return context
        else:
            return context[:remaining_chars] + "\n... (контекст обрезан)"


# Глобальный экземпляр детектора
detector = DiffDetector()



