"""
Модуль для отправки уведомлений в Telegram (опционально)
"""
import logging
from typing import List, Dict, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


# Emoji для разных приоритетов
PRIORITY_EMOJI = {
    "CRITICAL": "🔴",
    "HIGH": "🟡",
    "MEDIUM": "🟢",
    "LOW": "⚪"
}

# Emoji для категорий
CATEGORY_EMOJI = {
    "core": "⚙️",
    "members": "👥",
    "ecommerce": "🛒",
    "zero_block": "🎨",
    "ui_components": "🧩",
    "utilities": "🔧"
}


def sanitize_url_for_logging(url: str) -> str:
    """Удалить токены из URL перед логированием"""
    import re
    # Заменить bot<TOKEN>/method на bot***HIDDEN***/method
    return re.sub(r'bot\d+:[A-Za-z0-9_-]+/', 'bot***HIDDEN***/', url)


def escape_html(text: str) -> str:
    """
    Экранировать HTML-символы для Telegram HTML parse_mode.
    Экранирует только &, <, > — этого достаточно для безопасной отправки
    любого текста (LLM-описания, URL, технические строки с _ * ` и т.д.).
    """
    if not text:
        return text
    return text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


class TelegramNotifier:
    """Класс для отправки уведомлений в Telegram"""

    def __init__(self, bot_token: str = None, chat_id: str = None,
                 thread_id: int = None, alerts_thread_id: int = None,
                 digest_thread_id: int = None, discovery_thread_id: int = None):
        """
        Инициализация Telegram бота

        Args:
            bot_token: Токен бота (из переменных окружения)
            chat_id: ID чата/канала для отправки
            thread_id: ID топика для основных сообщений (опционально)
            alerts_thread_id: ID топика для алертов (опционально)
            digest_thread_id: ID топика для дайджестов (опционально)
            discovery_thread_id: ID топика для Discovery отчетов (опционально)
        """
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.thread_id = thread_id
        self.alerts_thread_id = alerts_thread_id
        self.digest_thread_id = digest_thread_id
        self.discovery_thread_id = discovery_thread_id
        self.enabled = bool(bot_token and chat_id)

        # Проверка: если chat_id не начинается с "-", это личный чат (не группа)
        # В личных чатах thread_id игнорируется
        self.is_group_chat = str(chat_id).startswith('-') if chat_id else False

        # Атрибуты для хранения последнего ответа/ошибки
        self.last_response = None
        self.last_error = None

        if not self.enabled:
            logger.warning("Telegram уведомления отключены: не указан bot_token или chat_id")
    
    def send_announcement(self, announcement: Dict) -> bool:
        """
        Отправить анонс в Telegram

        Args:
            announcement: Словарь с анонсом

        Returns:
            True если успешно отправлено
        """
        if not self.enabled:
            logger.debug("Telegram отключен, пропускаем отправку")
            return False

        try:
            message = self._format_announcement(announcement)
            return self._send_message(message, thread_id=self.thread_id)
        except Exception as e:
            logger.error(f"Ошибка при отправке в Telegram: {e}", exc_info=True)
            return False
    
    def send_daily_digest(self, announcements: List[Dict], digest_analysis: Dict = None) -> bool:
        """
        Отправить ежедневный дайджест изменений

        Args:
            announcements: Список анонсов за день
            digest_analysis: Результат LLM-анализа дайджеста (опционально)

        Returns:
            True если успешно отправлено
        """
        if not self.enabled:
            return False

        if not announcements:
            logger.info("Нет анонсов для дайджеста")
            return False

        try:
            message = self._format_digest(announcements, digest_analysis=digest_analysis)
            return self._send_message(message, thread_id=self.digest_thread_id)
        except Exception as e:
            logger.error(f"Ошибка при отправке дайджеста: {e}", exc_info=True)
            return False
    
    def send_discovery_report(self, discovered_files: List[Dict]) -> bool:
        """
        Отправить отчет об обнаруженных новых файлах

        Args:
            discovered_files: Список обнаруженных файлов

        Returns:
            True если успешно отправлено
        """
        if not self.enabled:
            return False

        if not discovered_files:
            return False

        try:
            message = self._format_discovery_report(discovered_files)
            return self._send_message(message, thread_id=self.discovery_thread_id)
        except Exception as e:
            logger.error(f"Ошибка при отправке отчета Discovery: {e}", exc_info=True)
            return False
    
    def send_block_catalog_report(self, report: dict) -> bool:
        """
        Отправить отчёт о изменениях каталога блоков в Discovery топик.

        Args:
            report: Результат check_catalog() из BlockCatalogMonitor

        Returns:
            True если успешно отправлено
        """
        if not self.enabled:
            return False

        new_blocks = report.get('new_blocks', [])
        removed_blocks = report.get('removed_blocks', [])
        changed_blocks = report.get('changed_blocks', [])

        if not new_blocks and not removed_blocks and not changed_blocks:
            return False

        try:
            message = self._format_block_catalog_report(report)
            chunks = self._split_long_message(message)
            success = False
            for chunk in chunks:
                if self._send_message(chunk, parse_mode=None, thread_id=self.discovery_thread_id):
                    success = True
            return success
        except Exception as e:
            logger.error(f"Ошибка при отправке отчёта о блоках: {e}", exc_info=True)
            return False

    def _format_block_catalog_report(self, report: dict) -> str:
        """Форматировать отчёт об изменениях каталога блоков"""
        import json as _json

        new_blocks = report.get('new_blocks', [])
        removed_blocks = report.get('removed_blocks', [])
        changed_blocks = report.get('changed_blocks', [])

        parts = []
        parts.append("🧱 ИЗМЕНЕНИЯ В КАТАЛОГЕ БЛОКОВ TILDA")
        parts.append("=" * 40)

        # 1. Блоки вышли из беты (testers → '')
        released = []
        # 2. Блоки стали публичными напрямую (team → '')
        team_to_public = []
        # 3. Блоки стали бета (team → testers или '' → testers)
        became_beta = []
        # 4. Прочие смены видимости
        other_visibility = []

        for item in changed_blocks:
            for ch in item.get('changes', []):
                if ch.get('change_type') != 'visibility_change':
                    continue
                bd = item['block_data']
                old_v = ch.get('old_value', '')
                new_v = ch.get('new_value', '')

                def _llm_summary(ch):
                    raw = ch.get('llm_analysis')
                    if not raw:
                        return ''
                    try:
                        analysis = _json.loads(raw)
                        return analysis.get('summary', '')[:150]
                    except Exception:
                        return ''

                entry = f"  {bd['cod']} — {bd['title']}"
                summary = _llm_summary(ch)
                if summary:
                    entry += f"\n    {summary}"

                if old_v == 'testers' and new_v == '':
                    released.append(entry)
                elif old_v == 'team' and new_v == '':
                    team_to_public.append(entry)
                elif new_v == 'testers':
                    became_beta.append(f"  {bd['cod']} — {bd['title']} ({old_v!r} → 'testers')")
                else:
                    other_visibility.append(f"  {bd['cod']}: видимость {old_v!r} → {new_v!r}")

        if released:
            parts.append("")
            parts.append(f"🎉 Блоки вышли из беты ({len(released)}):")
            parts.extend(released)

        if team_to_public:
            parts.append("")
            parts.append(f"🆕 Блоки стали публичными ({len(team_to_public)}):")
            parts.extend(team_to_public)

        if became_beta:
            parts.append("")
            parts.append(f"🧪 Блоки перешли в бету ({len(became_beta)}):")
            parts.extend(became_beta[:10])

        if other_visibility:
            parts.append("")
            parts.append(f"👁 Прочие смены видимости ({len(other_visibility)}):")
            parts.extend(other_visibility[:10])

        def _block_entry(b):
            entry = f"  {b['cod']} — {b['title']}"
            if b.get('llm_analysis'):
                try:
                    analysis = _json.loads(b['llm_analysis'])
                    summary = analysis.get('summary', '')[:150]
                    if summary:
                        entry += f"\n    {summary}"
                except Exception:
                    pass
            return entry

        # 5. Новые бета-блоки
        beta_new = [b for b in new_blocks if b.get('whocansee') == 'testers']
        if beta_new:
            parts.append("")
            parts.append(f"🧪 Новые бета-блоки ({len(beta_new)}):")
            parts.extend(_block_entry(b) for b in beta_new[:10])

        # 5.5. Новые team-блоки (внутренние, whocansee == 'team')
        team_new = [b for b in new_blocks if b.get('whocansee') == 'team']
        if team_new:
            parts.append("")
            parts.append(f"👥 Новые внутренние блоки (team) ({len(team_new)}):")
            parts.extend(_block_entry(b) for b in team_new[:10])

        # 6. Новые публичные блоки (whocansee == '')
        public_new = [b for b in new_blocks if b.get('whocansee') == '']
        if public_new:
            parts.append("")
            parts.append(f"🆕 Новые публичные блоки ({len(public_new)}):")
            parts.extend(_block_entry(b) for b in public_new[:10])

        # 6.5. Прочие новые блоки (неизвестная видимость)
        known_vis = {'testers', 'team', ''}
        other_new = [b for b in new_blocks if b.get('whocansee') not in known_vis]
        if other_new:
            parts.append("")
            parts.append(f"🆕 Новые блоки ({len(other_new)}):")
            parts.extend(_block_entry(b) for b in other_new[:10])

        # 7. Удалённые блоки
        if removed_blocks:
            parts.append("")
            parts.append(f"🗑 Удалённые блоки ({len(removed_blocks)}):")
            for b in removed_blocks[:10]:
                parts.append(f"  {b.get('cod', 'N/A')} — {b.get('title', 'N/A')}")

        # 8. Прочие изменения полей (кратко)
        other_changes = []
        for item in changed_blocks:
            field_changes = [ch for ch in item.get('changes', []) if ch.get('change_type') == 'field_change']
            if field_changes:
                bd = item['block_data']
                fields = [ch.get('field_name', '?') for ch in field_changes]
                other_changes.append(f"  {bd['cod']}: изменены {', '.join(fields)}")

        if other_changes:
            parts.append("")
            parts.append(f"📝 Прочие изменения ({len(other_changes)}):")
            parts.extend(other_changes[:10])
            if len(other_changes) > 10:
                parts.append(f"  ... и ещё {len(other_changes) - 10}")

        parts.append("")
        total = len(new_blocks) + len(removed_blocks) + len(changed_blocks)
        parts.append(f"Итого: {total} изменений в каталоге")

        return "\n".join(parts)

    def send_version_alert(self, alert_data: Dict) -> bool:
        """
        Отправить алерт о новой версии файла

        Args:
            alert_data: Данные алерта (base_name, old_version, new_version, etc.)

        Returns:
            True если успешно отправлено
        """
        if not self.enabled:
            return False

        try:
            message = self._format_version_alert(alert_data)
            return self._send_message(message, thread_id=self.alerts_thread_id)
        except Exception as e:
            logger.error(f"Ошибка при отправке версионного алерта: {e}", exc_info=True)
            return False
    
    def send_migration_success(self, migration_data: Dict) -> bool:
        """
        Отправить уведомление об успешной миграции

        Args:
            migration_data: Данные миграции

        Returns:
            True если успешно отправлено
        """
        if not self.enabled:
            return False

        try:
            message = self._format_migration_success(migration_data)
            return self._send_message(message, thread_id=self.alerts_thread_id)
        except Exception as e:
            logger.error(f"Ошибка при отправке уведомления о миграции: {e}", exc_info=True)
            return False
    
    def send_migration_failure(self, migration_data: Dict) -> bool:
        """
        Отправить уведомление о неудачной миграции

        Args:
            migration_data: Данные миграции

        Returns:
            True если успешно отправлено
        """
        if not self.enabled:
            return False

        try:
            message = self._format_migration_failure(migration_data)
            return self._send_message(message, thread_id=self.alerts_thread_id)
        except Exception as e:
            logger.error(f"Ошибка при отправке уведомления о неудаче: {e}", exc_info=True)
            return False
    
    def send_404_critical(self, file_data: Dict) -> bool:
        """
        Отправить критический алерт о 404 ошибке

        Args:
            file_data: Данные о файле с 404

        Returns:
            True если успешно отправлено
        """
        if not self.enabled:
            return False

        try:
            message = self._format_404_critical(file_data)
            return self._send_message(message, thread_id=self.alerts_thread_id)
        except Exception as e:
            logger.error(f"Ошибка при отправке 404 алерта: {e}", exc_info=True)
            return False
    
    def _format_announcement(self, announcement: Dict) -> str:
        """
        Форматировать анонс для Telegram
        
        Args:
            announcement: Словарь с анонсом
            
        Returns:
            Отформатированное сообщение
        """
        severity = escape_html(announcement.get('severity', 'НЕЗНАЧИТЕЛЬНОЕ'))
        priority_emoji = PRIORITY_EMOJI.get(announcement.get('priority', 'MEDIUM'), '⚪')
        category = announcement.get('category', 'unknown')
        category_emoji = CATEGORY_EMOJI.get(category, '📦')

        title = escape_html(announcement.get('title', 'Без заголовка'))
        description = escape_html(announcement.get('description', 'Нет описания'))
        user_impact = escape_html(announcement.get('user_impact', 'Не указано'))
        recommendations = escape_html(announcement.get('recommendations', 'Действий не требуется'))
        url = escape_html(announcement.get('url', 'N/A'))

        message = f"""🔔 <b>Обновление Tilda</b> | {datetime.now().strftime('%d.%m.%Y %H:%M')}

{priority_emoji} <b>{severity}</b>

{category_emoji} <b>{escape_html(category.upper())}</b>
• {title}

📝 <b>Описание:</b>
{description}

👥 <b>Влияние:</b>
{user_impact}

💡 <b>Рекомендации:</b>
{recommendations}

━━━━━━━━━━━━━━━━
🔗 Файл: <code>{url}</code>
"""

        # Добавить тренд и фичу если есть
        trend = announcement.get('trend')
        feature = announcement.get('feature')
        if trend:
            message += f"\n📈 <b>Тренд:</b> {escape_html(trend)}"
        if feature:
            message += f"\n🎯 <b>Фича:</b> {escape_html(feature)}"

        return message
    
    def _format_digest(self, announcements: List[Dict], digest_analysis: Dict = None) -> str:
        """
        Форматировать ежедневный дайджест с LLM-сводкой

        Args:
            announcements: Список анонсов
            digest_analysis: Результат LLM-анализа (опционально)

        Returns:
            Отформатированное сообщение
        """
        message = f"📋 <b>Дайджест Tilda</b> | {datetime.now().strftime('%d %B %Y')}\n\n"

        # LLM-сводка дня (если доступна)
        if digest_analysis:
            summary = escape_html(digest_analysis.get('summary', ''))
            if summary:
                message += f"📈 <b>Сводка дня:</b>\n{summary}\n\n"

            attention = escape_html(digest_analysis.get('attention') or '')
            if attention:
                message += f"⚠️ <b>Обратить внимание:</b> {attention}\n\n"
        else:
            # Fallback: механическая сводка по категориям
            message += self._build_category_summary(announcements)

        # Группировка по приоритетам
        by_priority = {
            'CRITICAL': [],
            'HIGH': [],
            'MEDIUM': [],
            'LOW': []
        }

        for ann in announcements:
            priority = ann.get('priority', 'MEDIUM')
            if priority in by_priority:
                by_priority[priority].append(ann)
            else:
                by_priority['MEDIUM'].append(ann)

        # CRITICAL
        if by_priority['CRITICAL']:
            message += f"🔴 <b>КРИТИЧЕСКИЕ</b> ({len(by_priority['CRITICAL'])})\n"
            message += self._format_priority_group(by_priority['CRITICAL'], show_impact=True)

        # HIGH
        if by_priority['HIGH']:
            message += f"🟡 <b>ВАЖНЫЕ</b> ({len(by_priority['HIGH'])})\n"
            message += self._format_priority_group(by_priority['HIGH'], show_impact=False)

        # MEDIUM + LOW (кратко)
        minor = by_priority['MEDIUM'] + by_priority['LOW']
        if minor:
            message += f"🟢 <b>НЕЗНАЧИТЕЛЬНЫЕ</b> ({len(minor)})\n"
            # Группируем файлы через запятую
            filenames = []
            for ann in minor:
                category_emoji = CATEGORY_EMOJI.get(ann.get('category', 'unknown'), '📦')
                title = ann.get('title', 'Без заголовка')
                # Извлечь имя файла из заголовка
                filename = title.split(' - ')[0] if ' - ' in title else title.split('/')[-1]
                filenames.append(f"{category_emoji} {self._smart_truncate(filename, 40)}")
            message += "  " + ", ".join(filenames) + "\n"

        # Тренд (из LLM или из данных)
        if digest_analysis and digest_analysis.get('trend'):
            message += f"\n📈 <b>Тренд:</b> {escape_html(digest_analysis['trend'])}\n"

        message += "\n━━━━━━━━━━━━━━━━\n"
        message += f"📊 Всего: {len(announcements)} изменений за 24ч\n"

        # Сжатие если > 4000 символов (лимит Telegram)
        if len(message) > 4000:
            message = self._compress_digest(message)

        return message

    def _format_priority_group(self, items: List[Dict], show_impact: bool = False) -> str:
        """Форматировать группу анонсов одного приоритета"""
        result = ""
        # Группировка по категориям внутри приоритета
        by_cat = {}
        for ann in items:
            cat = ann.get('category', 'unknown')
            if cat not in by_cat:
                by_cat[cat] = []
            by_cat[cat].append(ann)

        for cat, cat_items in by_cat.items():
            category_emoji = CATEGORY_EMOJI.get(cat, '📦')
            result += f"  {category_emoji} {cat.upper()}\n"
            for ann in cat_items:
                title = ann.get('title', 'Без заголовка')
                filename = title.split(' - ')[0] if ' - ' in title else title.split('/')[-1]
                desc = escape_html(ann.get('description', ''))
                result += f"  • {escape_html(self._smart_truncate(filename, 40))}\n"
                if desc:
                    result += f"    {self._smart_truncate(desc, 120)}\n"
                if show_impact and ann.get('user_impact'):
                    impact = escape_html(ann['user_impact'])
                    result += f"    👥 {self._smart_truncate(impact, 100)}\n"
            result += "\n"
        return result

    def _smart_truncate(self, text: str, max_len: int) -> str:
        """Обрезка по границе слова"""
        if not text or len(text) <= max_len:
            return text or ''
        truncated = text[:max_len]
        # Найти последний пробел
        last_space = truncated.rfind(' ')
        if last_space > max_len * 0.6:
            truncated = truncated[:last_space]
        return truncated.rstrip('.,;: ') + '...'

    def _build_category_summary(self, announcements: List[Dict]) -> str:
        """Fallback: механическая сводка по категориям (без LLM)"""
        by_cat = {}
        for ann in announcements:
            cat = ann.get('category', 'unknown')
            if cat not in by_cat:
                by_cat[cat] = 0
            by_cat[cat] += 1

        if not by_cat:
            return ""

        parts = []
        for cat, count in sorted(by_cat.items(), key=lambda x: x[1], reverse=True):
            category_emoji = CATEGORY_EMOJI.get(cat, '📦')
            parts.append(f"{category_emoji} {cat} ({count})")

        return f"📈 <b>Обзор:</b> Изменения в {', '.join(parts)}\n\n"

    def _compress_digest(self, message: str) -> str:
        """Сжать дайджест если превышает лимит Telegram (4096 символов)"""
        if len(message) <= 4000:
            return message

        # Стратегия: убрать user_impact строки
        lines = message.split('\n')
        compressed = []
        for line in lines:
            if line.strip().startswith('👥'):
                continue
            compressed.append(line)

        result = '\n'.join(compressed)

        # Если всё ещё длинный — обрезаем описания
        if len(result) > 4000:
            result = result[:3950] + '\n\n... (сокращено)\n'

        return result
    
    def _format_discovery_report(self, discovered_files: List[Dict]) -> str:
        """
        Форматировать отчет об обнаруженных файлах
        
        Args:
            discovered_files: Список обнаруженных файлов
            
        Returns:
            Отформатированное сообщение
        """
        message = f"""🔍 <b>Discovery Mode Report</b> | {datetime.now().strftime('%d.%m.%Y')}

Обнаружено новых файлов: <b>{len(discovered_files)}</b>

"""

        # Группировка по категориям
        by_category = {}
        for file_info in discovered_files:
            cat = file_info.get('category', 'unknown')
            if cat not in by_category:
                by_category[cat] = []
            by_category[cat].append(file_info)

        # Вывод по категориям
        for category, files in sorted(by_category.items()):
            category_emoji = CATEGORY_EMOJI.get(category, '📦')
            message += f"{category_emoji} <b>{category.upper()}</b> ({len(files)} файлов)\n"

            for file_info in files[:5]:  # Максимум 5 файлов на категорию
                filename = escape_html(file_info['url'].split('/')[-1])
                message += f"  • <code>{filename}</code>\n"
            
            if len(files) > 5:
                message += f"  ... и еще {len(files) - 5} файлов\n"
            
            message += "\n"
        
        message += "━━━━━━━━━━━━━━━━\n"
        message += "⚠️ Требуется ручная проверка и добавление в мониторинг\n"
        
        return message
    
    def _format_version_alert(self, alert_data: Dict) -> str:
        """
        Форматировать алерт о новой версии
        
        Args:
            alert_data: Данные алерта
            
        Returns:
            Отформатированное сообщение
        """
        priority_emoji = PRIORITY_EMOJI.get(alert_data.get('priority', 'MEDIUM'), '⚪')
        category_emoji = CATEGORY_EMOJI.get(alert_data.get('category', 'unknown'), '📦')
        
        message = f"""🆕 <b>НОВАЯ ВЕРСИЯ ОБНАРУЖЕНА</b>

📦 Файл: <code>{escape_html(alert_data['base_name'])}</code>
{category_emoji} Категория: <b>{escape_html(alert_data.get('category', 'unknown').upper())}</b> ({priority_emoji} {alert_data.get('priority', 'MEDIUM')})

Текущая версия: {escape_html(str(alert_data.get('current_version', 'unknown')))}
Новая версия: <b>{escape_html(str(alert_data['new_version']))}</b> ✨

⚙️ Статус миграции: {escape_html(alert_data.get('migration_status', 'Автоматическая миграция запущена...'))}
⏱ Обнаружено: {datetime.now().strftime('%Y-%m-%d %H:%M')}

━━━━━━━━━━━━━━━━
🔗 Старый URL:
<code>{escape_html(alert_data.get('current_url', 'N/A'))}</code>

🔗 Новый URL:
<code>{escape_html(alert_data['new_url'])}</code>
"""
        return message
    
    def _format_migration_success(self, migration_data: Dict) -> str:
        """
        Форматировать успешную миграцию
        
        Args:
            migration_data: Данные миграции
            
        Returns:
            Отформатированное сообщение
        """
        category_emoji = CATEGORY_EMOJI.get(migration_data.get('category', 'unknown'), '📦')
        
        message = f"""✅ <b>МИГРАЦИЯ ЗАВЕРШЕНА</b>

📦 Файл: <code>{escape_html(migration_data['base_name'])}</code>
{category_emoji} Категория: <b>{escape_html(migration_data.get('category', 'unknown').upper())}</b>

{escape_html(str(migration_data.get('old_version', 'unknown')))} → <b>{escape_html(str(migration_data['new_version']))}</b>

⏱ Время миграции: {migration_data.get('migration_time', 0):.2f}с
✅ Статус: Активна и отслеживается

━━━━━━━━━━━━━━━━
📝 Файл автоматически обновлен и добавлен в мониторинг
"""
        return message
    
    def _format_migration_failure(self, migration_data: Dict) -> str:
        """
        Форматировать неудачную миграцию
        
        Args:
            migration_data: Данные миграции
            
        Returns:
            Отформатированное сообщение
        """
        category_emoji = CATEGORY_EMOJI.get(migration_data.get('category', 'unknown'), '📦')
        
        message = f"""❌ <b>МИГРАЦИЯ НЕ УДАЛАСЬ</b>

📦 Файл: <code>{escape_html(migration_data['base_name'])}</code>
{category_emoji} Категория: <b>{escape_html(migration_data.get('category', 'unknown').upper())}</b>

{escape_html(str(migration_data.get('old_version', 'unknown')))} → {escape_html(str(migration_data['new_version']))}

❌ Ошибка: {escape_html(migration_data.get('error', 'Unknown error'))}
🔙 Действие: Откат к предыдущей версии

━━━━━━━━━━━━━━━━
⚠️ Требуется ручная проверка!
"""
        return message
    
    def _format_404_critical(self, file_data: Dict) -> str:
        """
        Форматировать критическую 404 ошибку
        
        Args:
            file_data: Данные о файле
            
        Returns:
            Отформатированное сообщение
        """
        priority_emoji = PRIORITY_EMOJI.get(file_data.get('priority', 'MEDIUM'), '⚪')
        category_emoji = CATEGORY_EMOJI.get(file_data.get('category', 'unknown'), '📦')
        
        message = f"""⚠️ <b>КРИТИЧЕСКАЯ ОШИБКА 404</b>

📦 Файл: <code>{escape_html(file_data['base_name'])}</code>
{category_emoji} Категория: <b>{escape_html(file_data.get('category', 'unknown').upper())}</b> ({priority_emoji} {file_data.get('priority', 'MEDIUM')})

🔗 URL:
<code>{escape_html(file_data['url'])}</code>

⚠️ Последовательных 404: <b>{file_data.get('consecutive_count', 0)}</b>
🔍 Действие: Запущен Discovery Mode для поиска замены

⏱ Время: {datetime.now().strftime('%Y-%m-%d %H:%M')}

━━━━━━━━━━━━━━━━
🚨 Файл может быть удален или переименован Tilda!
"""
        return message
    
    def _split_long_message(self, message: str, max_len: int = 4000) -> list:
        """Разбить длинное сообщение на части по естественным границам (пустые строки)."""
        if len(message) <= max_len:
            return [message]

        lines = message.split('\n')
        chunks = []
        current_lines = []
        current_len = 0

        for line in lines:
            line_len = len(line) + 1  # +1 за символ переноса строки
            if current_len + line_len > max_len and current_lines:
                chunks.append('\n'.join(current_lines))
                current_lines = [line]
                current_len = line_len
            else:
                current_lines.append(line)
                current_len += line_len

        if current_lines:
            chunks.append('\n'.join(current_lines))

        return chunks

    def _send_message(self, message: str, parse_mode: str = "HTML", thread_id: int = None) -> bool:
        """
        Отправить сообщение через Telegram Bot API

        Args:
            message: Текст сообщения
            parse_mode: Режим парсинга (Markdown или HTML)
            thread_id: ID топика для отправки (только для групп с топиками)

        Returns:
            True если успешно отправлено
        """
        if not self.enabled:
            logger.debug("Telegram отключен")
            self.last_error = "Telegram не настроен (отсутствует bot_token или chat_id)"
            return False

        try:
            import requests

            url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"

            # Логировать с санитизацией токена
            logger.debug(f"Отправка POST запроса: {sanitize_url_for_logging(url)}")

            payload = {
                "chat_id": self.chat_id,
                "text": message,
                "disable_web_page_preview": True
            }
            if parse_mode:
                payload["parse_mode"] = parse_mode

            # Добавить message_thread_id только если:
            # 1. Это групповой чат (chat_id начинается с "-")
            # 2. thread_id указан
            if self.is_group_chat and thread_id is not None:
                payload["message_thread_id"] = thread_id
                logger.debug(f"Отправка в топик: thread_id={thread_id}")

            response = requests.post(url, json=payload, timeout=10)

            # Сохранить последний ответ
            result = response.json()
            self.last_response = result

            response.raise_for_status()

            if result.get('ok'):
                thread_info = f", thread_id={thread_id}" if self.is_group_chat and thread_id else ""
                message_id = result.get('result', {}).get('message_id', 'N/A')
                logger.info(f"✅ Сообщение отправлено в Telegram (chat_id: {self.chat_id}{thread_info}, msg_id: {message_id})")
                logger.debug(f"   Response: {result}")
                self.last_error = None
                return True
            else:
                error_desc = result.get('description', 'Unknown error')
                error_code = result.get('error_code', 'N/A')
                self.last_error = f"[{error_code}] {error_desc}"
                logger.error(f"❌ Telegram API ошибка: {self.last_error}")
                logger.error(f"   Payload: chat_id={self.chat_id}, thread_id={thread_id}")
                return False

        except requests.exceptions.RequestException as e:
            # Не логировать полный URL с токеном в ошибках
            self.last_error = f"HTTP Error: {type(e).__name__}"
            # Если есть сохранённый ответ от Telegram API — показать реальную ошибку
            if self.last_response and not self.last_response.get('ok'):
                tg_code = self.last_response.get('error_code', 'N/A')
                tg_desc = self.last_response.get('description', 'Unknown')
                self.last_error = f"[{tg_code}] {tg_desc}"
                logger.error(f"❌ Telegram API ошибка: {self.last_error}")
            else:
                logger.error(f"❌ Ошибка HTTP при отправке в Telegram: {self.last_error}")
            return False
        except Exception as e:
            self.last_error = f"Unexpected error: {type(e).__name__}"
            logger.error(f"❌ Непредвиденная ошибка: {self.last_error}", exc_info=False)
            return False
    
    def test_connection(self) -> bool:
        """
        Проверить соединение с Telegram
        
        Returns:
            True если соединение работает
        """
        if not self.enabled:
            logger.error("❌ Telegram не настроен (отсутствует bot_token или chat_id)")
            return False
        
        try:
            import requests
            
            # Проверка токена бота
            url = f"https://api.telegram.org/bot{self.bot_token}/getMe"
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            
            result = response.json()
            
            if result.get('ok'):
                bot_info = result.get('result', {})
                logger.info(f"✅ Бот подключен: @{bot_info.get('username', 'unknown')}")
                logger.info(f"   Имя: {bot_info.get('first_name', 'N/A')}")
                logger.info(f"   ID: {bot_info.get('id', 'N/A')}")
                
                # Проверка доступа к чату
                test_message = f"🔌 Тестовое подключение Tilda Update Checker\nВремя: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"

                if self._send_message(test_message, thread_id=self.thread_id):
                    logger.info(f"✅ Chat ID {self.chat_id} доступен для отправки сообщений")
                    return True
                else:
                    logger.error(f"❌ Не удалось отправить тестовое сообщение в chat_id: {self.chat_id}")
                    return False
            else:
                logger.error(f"❌ Telegram API вернул ошибку: {result.get('description', 'Unknown error')}")
                return False
                
        except requests.exceptions.RequestException as e:
            logger.error(f"❌ Ошибка HTTP при проверке подключения: {e}")
            return False
        except Exception as e:
            logger.error(f"❌ Ошибка проверки подключения к Telegram: {e}", exc_info=True)
            return False


# Глобальный экземпляр (инициализируется с переменными окружения)
def create_notifier() -> TelegramNotifier:
    """
    Создать экземпляр Telegram notifier из переменных окружения

    Returns:
        TelegramNotifier объект
    """
    import os

    bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
    chat_id = os.getenv('TELEGRAM_CHAT_ID')

    # Получить thread_id из переменных окружения (опционально)
    thread_id = os.getenv('TELEGRAM_THREAD_ID')
    alerts_thread_id = os.getenv('TELEGRAM_ALERTS_THREAD_ID')
    digest_thread_id = os.getenv('TELEGRAM_DIGEST_THREAD_ID')
    discovery_thread_id = os.getenv('TELEGRAM_DISCOVERY_THREAD_ID')

    # Конвертировать в int если указаны
    thread_id = int(thread_id) if thread_id else None
    alerts_thread_id = int(alerts_thread_id) if alerts_thread_id else None
    digest_thread_id = int(digest_thread_id) if digest_thread_id else None
    discovery_thread_id = int(discovery_thread_id) if discovery_thread_id else None

    return TelegramNotifier(
        bot_token=bot_token,
        chat_id=chat_id,
        thread_id=thread_id,
        alerts_thread_id=alerts_thread_id,
        digest_thread_id=digest_thread_id,
        discovery_thread_id=discovery_thread_id
    )


notifier = create_notifier()

