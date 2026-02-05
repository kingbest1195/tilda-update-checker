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
                new_size,
                file_type
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
    
    def _beautify_code(self, content: str, file_type: str) -> str:
        """
        Форматировать минифицированный код для лучшего diff

        Args:
            content: Исходный код
            file_type: Тип файла (js/css)

        Returns:
            Отформатированный код
        """
        if file_type == 'js':
            try:
                import jsbeautifier
                opts = jsbeautifier.default_options()
                opts.indent_size = 2
                opts.max_preserve_newlines = 2
                return jsbeautifier.beautify(content, opts)
            except Exception as e:
                logger.warning(f"Не удалось beautify JS: {e}")
                return content
        return content  # CSS пока оставляем как есть

    def _analyze_change(self, old_content: str, new_content: str,
                       old_size: int, new_size: int, file_type: str = 'js') -> Dict:
        """
        Проанализировать изменение

        Args:
            old_content: Старое содержимое
            new_content: Новое содержимое
            old_size: Старый размер
            new_size: Новый размер
            file_type: Тип файла для beautify

        Returns:
            Словарь с информацией об изменении
        """
        # Вычислить процент изменения
        size_diff = abs(new_size - old_size)
        change_percent = int((size_diff / old_size * 100)) if old_size > 0 else 100

        # Определить, значимое ли изменение
        is_significant = size_diff >= config.MIN_CHANGE_SIZE

        # Beautify для минифицированного кода (если меньше 10 строк - признак минификации)
        old_content_formatted = old_content
        new_content_formatted = new_content

        if len(old_content.splitlines()) < 10:
            logger.info("Обнаружен минифицированный код, применяю beautify...")
            old_content_formatted = self._beautify_code(old_content, file_type)
            new_content_formatted = self._beautify_code(new_content, file_type)

        # Вычислить diff на форматированном коде
        old_lines = old_content_formatted.splitlines(keepends=True)
        new_lines = new_content_formatted.splitlines(keepends=True)

        diff = list(difflib.unified_diff(
            old_lines,
            new_lines,
            lineterm='',
            n=3  # Контекст = 3 для лучшего понимания изменений
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
            'diff_lines': diff[:300],  # Увеличено с 100 до 300
            'old_content': old_content,  # Оригинальный для сохранения
            'new_content': new_content,  # Оригинальный для сохранения
            'beautified_diff': '\n'.join(diff[:300]) if len(old_content.splitlines()) < 10 else None
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
    
    def _extract_diff_metadata(self, diff_lines: List[str]) -> Dict:
        """
        Извлечь метаданные из diff (функции, параметры, условия)

        Returns:
            Словарь с метаданными:
            - added_functions: Список добавленных функций
            - removed_functions: Список удалённых функций
            - modified_functions: Список изменённых функций
            - param_changes: Изменения параметров функций
            - condition_changes: Изменения условий
        """
        import re

        metadata = {
            'added_functions': [],
            'removed_functions': [],
            'modified_functions': [],
            'param_changes': [],
            'condition_changes': [],
            'new_imports': [],
            'removed_imports': []
        }

        # Регулярки для поиска функций
        func_patterns = [
            r'function\s+(\w+)\s*\(',           # function name(
            r'(\w+):\s*function\s*\(',          # name: function(
            r'const\s+(\w+)\s*=\s*function',    # const name = function
            r'const\s+(\w+)\s*=\s*\([^)]*\)\s*=>', # const name = () =>
        ]

        for line in diff_lines:
            if line.startswith('+') and not line.startswith('+++'):
                clean_line = line[1:].strip()

                # Поиск добавленных функций
                for pattern in func_patterns:
                    match = re.search(pattern, clean_line)
                    if match:
                        func_name = match.group(1)
                        metadata['added_functions'].append(func_name)
                        break

                # Поиск новых import/require
                if 'import' in clean_line or 'require(' in clean_line:
                    metadata['new_imports'].append(clean_line[:100])

                # Поиск изменений условий
                if any(kw in clean_line for kw in ['if (', 'else if', 'switch', '&&', '||']):
                    metadata['condition_changes'].append(('added', clean_line[:150]))

            elif line.startswith('-') and not line.startswith('---'):
                clean_line = line[1:].strip()

                # Поиск удалённых функций
                for pattern in func_patterns:
                    match = re.search(pattern, clean_line)
                    if match:
                        func_name = match.group(1)
                        metadata['removed_functions'].append(func_name)
                        break

                # Поиск удалённых import/require
                if 'import' in clean_line or 'require(' in clean_line:
                    metadata['removed_imports'].append(clean_line[:100])

                # Поиск изменений условий
                if any(kw in clean_line for kw in ['if (', 'else if', 'switch', '&&', '||']):
                    metadata['condition_changes'].append(('removed', clean_line[:150]))

        # Найти изменённые функции (функция есть и в added, и в removed)
        common_funcs = set(metadata['added_functions']) & set(metadata['removed_functions'])
        metadata['modified_functions'] = list(common_funcs)

        # Убрать изменённые из added и removed
        metadata['added_functions'] = [f for f in metadata['added_functions'] if f not in common_funcs]
        metadata['removed_functions'] = [f for f in metadata['removed_functions'] if f not in common_funcs]

        return metadata

    def prepare_llm_context(self, change_info: Dict, max_tokens: int = None) -> str:
        """
        Подготовить контекст для отправки в LLM с реальными фрагментами кода

        Args:
            change_info: Информация об изменении
            max_tokens: Максимальное количество токенов (примерно)

        Returns:
            Подготовленный текст для LLM
        """
        if max_tokens is None:
            max_tokens = config.MAX_DIFF_TOKENS

        stats = change_info['stats']

        # Базовый контекст
        context_parts = [
            f"Файл: {change_info['url']}",
            f"Тип: {change_info['file_type']}",
            f"Категория: {change_info.get('category', 'unknown')}",
            "",
            "Метаданные изменения:",
            f"- Разница: {change_info['size_diff']} байт ({change_info['change_percent']}%)",
            f"- Добавлено строк: {stats['added_lines']}",
            f"- Удалено строк: {stats['removed_lines']}",
            ""
        ]

        # Извлечь метаданные из diff
        diff_lines = change_info.get('diff_lines', [])
        metadata = self._extract_diff_metadata(diff_lines)

        # Добавить метаданные в контекст
        if any(metadata.values()):
            context_parts.append("Обнаруженные структурные изменения:")

            if metadata['added_functions']:
                context_parts.append(f"  Добавлены функции: {', '.join(metadata['added_functions'][:10])}")

            if metadata['removed_functions']:
                context_parts.append(f"  Удалены функции: {', '.join(metadata['removed_functions'][:10])}")

            if metadata['modified_functions']:
                context_parts.append(f"  Изменены функции: {', '.join(metadata['modified_functions'][:10])}")

            if metadata['new_imports']:
                context_parts.append(f"  Новые зависимости: {len(metadata['new_imports'])} шт.")

            if metadata['condition_changes']:
                context_parts.append(f"  Изменения логики (if/else/switch): {len(metadata['condition_changes'])} шт.")

            context_parts.append("")

        # Добавить фрагменты diff если доступны
        if diff_lines:
            context_parts.append("Ключевые изменения в коде:")
            context_parts.append("```")

            # Извлечь только строки с изменениями (+ и -)
            code_changes = []
            for line in diff_lines[:300]:  # Увеличено с 100 до 300 строк
                if line.startswith('+') and not line.startswith('+++'):
                    # Для минифицированного кода - разбить длинные строки
                    if len(line) > 200:
                        # Разбить по точке с запятой, взять первые 15 фрагментов
                        fragments = line[1:].split(';')[:15]
                        for frag in fragments:
                            if frag.strip():
                                code_changes.append(f"+{frag.strip()};")
                    else:
                        code_changes.append(line)
                elif line.startswith('-') and not line.startswith('---'):
                    if len(line) > 200:
                        fragments = line[1:].split(';')[:15]
                        for frag in fragments:
                            if frag.strip():
                                code_changes.append(f"-{frag.strip()};")
                    else:
                        code_changes.append(line)

            context_parts.extend(code_changes[:150])  # Увеличено с 50 до 150 фрагментов
            context_parts.append("```")

        # Проверить лимит токенов
        full_context = "\n".join(context_parts)
        estimated_tokens = len(full_context) // 4

        if estimated_tokens > max_tokens - 500:
            allowed_chars = (max_tokens - 500) * 4
            return full_context[:allowed_chars] + "\n... (контекст обрезан)"

        return full_context


# Глобальный экземпляр детектора
detector = DiffDetector()



