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


class TelegramNotifier:
    """Класс для отправки уведомлений в Telegram"""
    
    def __init__(self, bot_token: str = None, chat_id: str = None):
        """
        Инициализация Telegram бота
        
        Args:
            bot_token: Токен бота (из переменных окружения)
            chat_id: ID чата/канала для отправки
        """
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.enabled = bool(bot_token and chat_id)
        
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
            return self._send_message(message)
        except Exception as e:
            logger.error(f"Ошибка при отправке в Telegram: {e}", exc_info=True)
            return False
    
    def send_daily_digest(self, announcements: List[Dict]) -> bool:
        """
        Отправить ежедневный дайджест изменений
        
        Args:
            announcements: Список анонсов за день
            
        Returns:
            True если успешно отправлено
        """
        if not self.enabled:
            return False
        
        if not announcements:
            logger.info("Нет анонсов для дайджеста")
            return False
        
        try:
            message = self._format_digest(announcements)
            return self._send_message(message)
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
            return self._send_message(message)
        except Exception as e:
            logger.error(f"Ошибка при отправке отчета Discovery: {e}", exc_info=True)
            return False
    
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
            return self._send_message(message)
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
            return self._send_message(message)
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
            return self._send_message(message)
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
            return self._send_message(message)
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
        severity = announcement.get('severity', 'НЕЗНАЧИТЕЛЬНОЕ')
        priority_emoji = PRIORITY_EMOJI.get(announcement.get('priority', 'MEDIUM'), '⚪')
        category = announcement.get('category', 'unknown')
        category_emoji = CATEGORY_EMOJI.get(category, '📦')
        
        message = f"""🔔 **Обновление Tilda** | {datetime.now().strftime('%d.%m.%Y %H:%M')}

{priority_emoji} **{severity}**

{category_emoji} **{category.upper()}**
• {announcement.get('title', 'Без заголовка')}

📝 **Описание:**
{announcement.get('description', 'Нет описания')}

👥 **Влияние:**
{announcement.get('user_impact', 'Не указано')}

💡 **Рекомендации:**
{announcement.get('recommendations', 'Действий не требуется')}

━━━━━━━━━━━━━━━━
🔗 Файл: `{announcement.get('url', 'N/A')}`
"""
        
        return message
    
    def _format_digest(self, announcements: List[Dict]) -> str:
        """
        Форматировать ежедневный дайджест
        
        Args:
            announcements: Список анонсов
            
        Returns:
            Отформатированное сообщение
        """
        # Группировка по приоритетам
        by_priority = {
            'CRITICAL': [],
            'HIGH': [],
            'MEDIUM': [],
            'LOW': []
        }
        
        for ann in announcements:
            priority = ann.get('priority', 'MEDIUM')
            by_priority[priority].append(ann)
        
        message = f"""🔔 **Обновления Tilda** | {datetime.now().strftime('%d %B %Y')}

"""
        
        # CRITICAL
        if by_priority['CRITICAL']:
            message += f"🔴 **КРИТИЧЕСКИЕ ИЗМЕНЕНИЯ** ({len(by_priority['CRITICAL'])})\n\n"
            for ann in by_priority['CRITICAL']:
                category_emoji = CATEGORY_EMOJI.get(ann.get('category', 'unknown'), '📦')
                message += f"{category_emoji} {ann.get('category', 'unknown').upper()}\n"
                message += f"  • {ann.get('title', 'Без заголовка')}\n"
                message += f"    → {ann.get('description', 'Нет описания')[:100]}...\n\n"
        
        # HIGH
        if by_priority['HIGH']:
            message += f"🟡 **ВАЖНЫЕ ИЗМЕНЕНИЯ** ({len(by_priority['HIGH'])})\n\n"
            for ann in by_priority['HIGH']:
                category_emoji = CATEGORY_EMOJI.get(ann.get('category', 'unknown'), '📦')
                message += f"{category_emoji} {ann.get('category', 'unknown').upper()}\n"
                message += f"  • {ann.get('title', 'Без заголовка')}\n"
                message += f"    → {ann.get('description', 'Нет описания')[:100]}...\n\n"
        
        # MEDIUM
        if by_priority['MEDIUM']:
            message += f"🟢 **НЕЗНАЧИТЕЛЬНЫЕ ИЗМЕНЕНИЯ** ({len(by_priority['MEDIUM'])})\n\n"
            # Только заголовки для MEDIUM
            for ann in by_priority['MEDIUM']:
                category_emoji = CATEGORY_EMOJI.get(ann.get('category', 'unknown'), '📦')
                message += f"{category_emoji} {ann.get('title', 'Без заголовка')}\n"
        
        message += f"\n━━━━━━━━━━━━━━━━\n"
        message += f"📊 Всего изменений: {len(announcements)}\n"
        message += f"🕐 За последние 24 часа\n"
        
        return message
    
    def _format_discovery_report(self, discovered_files: List[Dict]) -> str:
        """
        Форматировать отчет об обнаруженных файлах
        
        Args:
            discovered_files: Список обнаруженных файлов
            
        Returns:
            Отформатированное сообщение
        """
        message = f"""🔍 **Discovery Mode Report** | {datetime.now().strftime('%d.%m.%Y')}

Обнаружено новых файлов: **{len(discovered_files)}**

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
            message += f"{category_emoji} **{category.upper()}** ({len(files)} файлов)\n"
            
            for file_info in files[:5]:  # Максимум 5 файлов на категорию
                filename = file_info['url'].split('/')[-1]
                message += f"  • `{filename}`\n"
            
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
        
        message = f"""🆕 **НОВАЯ ВЕРСИЯ ОБНАРУЖЕНА**

📦 Файл: `{alert_data['base_name']}`
{category_emoji} Категория: **{alert_data.get('category', 'unknown').upper()}** ({priority_emoji} {alert_data.get('priority', 'MEDIUM')})

Текущая версия: {alert_data.get('current_version', 'unknown')}
Новая версия: **{alert_data['new_version']}** ✨

⚙️ Статус миграции: {alert_data.get('migration_status', 'Автоматическая миграция запущена...')}
⏱ Обнаружено: {datetime.now().strftime('%Y-%m-%d %H:%M')}

━━━━━━━━━━━━━━━━
🔗 Старый URL:
`{alert_data.get('current_url', 'N/A')}`

🔗 Новый URL:
`{alert_data['new_url']}`
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
        
        message = f"""✅ **МИГРАЦИЯ ЗАВЕРШЕНА**

📦 Файл: `{migration_data['base_name']}`
{category_emoji} Категория: **{migration_data.get('category', 'unknown').upper()}**

{migration_data.get('old_version', 'unknown')} → **{migration_data['new_version']}**

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
        
        message = f"""❌ **МИГРАЦИЯ НЕ УДАЛАСЬ**

📦 Файл: `{migration_data['base_name']}`
{category_emoji} Категория: **{migration_data.get('category', 'unknown').upper()}**

{migration_data.get('old_version', 'unknown')} → {migration_data['new_version']}

❌ Ошибка: {migration_data.get('error', 'Unknown error')}
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
        
        message = f"""⚠️ **КРИТИЧЕСКАЯ ОШИБКА 404**

📦 Файл: `{file_data['base_name']}`
{category_emoji} Категория: **{file_data.get('category', 'unknown').upper()}** ({priority_emoji} {file_data.get('priority', 'MEDIUM')})

🔗 URL:
`{file_data['url']}`

⚠️ Последовательных 404: **{file_data.get('consecutive_count', 0)}**
🔍 Действие: Запущен Discovery Mode для поиска замены

⏱ Время: {datetime.now().strftime('%Y-%m-%d %H:%M')}

━━━━━━━━━━━━━━━━
🚨 Файл может быть удален или переименован Tilda!
"""
        return message
    
    def _send_message(self, message: str, parse_mode: str = "Markdown") -> bool:
        """
        Отправить сообщение через Telegram Bot API
        
        Args:
            message: Текст сообщения
            parse_mode: Режим парсинга (Markdown или HTML)
            
        Returns:
            True если успешно отправлено
        """
        if not self.enabled:
            logger.debug("Telegram отключен")
            return False
        
        try:
            import requests

            url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"

            # Логировать с санитизацией токена
            logger.debug(f"Отправка POST запроса: {sanitize_url_for_logging(url)}")

            payload = {
                "chat_id": self.chat_id,
                "text": message,
                "parse_mode": parse_mode,
                "disable_web_page_preview": True
            }

            response = requests.post(url, json=payload, timeout=10)
            response.raise_for_status()
            
            result = response.json()
            
            if result.get('ok'):
                logger.info(f"✅ Сообщение успешно отправлено в Telegram (chat_id: {self.chat_id})")
                return True
            else:
                logger.error(f"❌ Telegram API вернул ошибку: {result.get('description', 'Unknown error')}")
                return False
                
        except requests.exceptions.RequestException as e:
            # Не логировать полный URL с токеном в ошибках
            logger.error(f"❌ Ошибка HTTP при отправке в Telegram: {type(e).__name__}")
            return False
        except Exception as e:
            logger.error(f"❌ Непредвиденная ошибка при отправке в Telegram: {type(e).__name__}", exc_info=False)
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
                
                if self._send_message(test_message):
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
    
    return TelegramNotifier(bot_token=bot_token, chat_id=chat_id)


notifier = create_notifier()

