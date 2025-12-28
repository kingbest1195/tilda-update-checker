"""
Модуль для централизованной системы алертов о версионных изменениях
"""
import logging
from datetime import datetime
from typing import Dict, List, Optional

from src.database import db, VersionAlert

logger = logging.getLogger(__name__)


class AlertSystem:
    """Централизованная система алертов"""
    
    # Эмодзи для разных типов алертов
    EMOJI_MAP = {
        'CRITICAL': '🔴',
        'HIGH': '🟡',
        'MEDIUM': '🟢',
        'LOW': '⚪',
        'version_update': '🆕',
        'migration_success': '✅',
        'migration_failed': '❌',
        'rollback': '🔙',
        '404_error': '⚠️'
    }
    
    def __init__(self):
        """Инициализация системы алертов"""
        pass
    
    def log_version_update(self, update_info: Dict):
        """
        Логировать обнаружение новой версии
        
        Args:
            update_info: Информация об обновлении
        """
        base_name = update_info['base_name']
        current_version = update_info.get('current_version', 'unknown')
        new_version = update_info['new_version']
        priority = update_info.get('priority', 'MEDIUM')
        category = update_info.get('category', 'unknown')
        
        emoji_priority = self.EMOJI_MAP.get(priority, '⚪')
        emoji_update = self.EMOJI_MAP['version_update']
        
        log_message = f"""
{emoji_update} VERSION UPDATE DETECTED:
   File: {base_name}
   Current: v{current_version} ({update_info.get('current_url', 'N/A')})
   New: v{new_version} ({update_info['new_url']})
   Category: {category} ({emoji_priority} {priority} priority)
   Status: Migration pending...
"""
        logger.info(log_message)
    
    def log_migration_start(self, base_name: str, old_version: str, new_version: str):
        """Логировать начало миграции"""
        logger.info(f"\n{'='*80}")
        logger.info(f"🔄 MIGRATION STARTED: {base_name}")
        logger.info(f"   From: v{old_version}")
        logger.info(f"   To: v{new_version}")
        logger.info(f"{'='*80}")
    
    def log_migration_success(self, base_name: str, old_version: str, new_version: str,
                             migration_time: float):
        """Логировать успешную миграцию"""
        emoji = self.EMOJI_MAP['migration_success']
        
        log_message = f"""
{emoji} MIGRATION COMPLETED SUCCESSFULLY:
   File: {base_name}
   From: v{old_version}
   To: v{new_version}
   Time: {migration_time:.2f}s
   Status: Active and monitored
"""
        logger.info(log_message)
    
    def log_migration_failure(self, base_name: str, old_version: str, new_version: str,
                             error: str):
        """Логировать неудачную миграцию"""
        emoji = self.EMOJI_MAP['migration_failed']
        
        log_message = f"""
{emoji} MIGRATION FAILED:
   File: {base_name}
   From: v{old_version}
   To: v{new_version}
   Error: {error}
   Status: Rollback initiated
"""
        logger.error(log_message)
    
    def log_rollback(self, base_name: str, from_version: str, to_version: str):
        """Логировать откат версии"""
        emoji = self.EMOJI_MAP['rollback']
        
        log_message = f"""
{emoji} ROLLBACK PERFORMED:
   File: {base_name}
   From: v{from_version}
   To: v{to_version}
   Reason: Manual rollback or migration failure
"""
        logger.warning(log_message)
    
    def log_404_error(self, url: str, consecutive_count: int):
        """Логировать 404 ошибку"""
        emoji = self.EMOJI_MAP['404_error']
        
        if consecutive_count >= 3:
            log_level = logger.critical
            severity = "CRITICAL"
        else:
            log_level = logger.warning
            severity = "WARNING"
        
        log_message = f"""
{emoji} 404 ERROR DETECTED ({severity}):
   URL: {url}
   Consecutive 404s: {consecutive_count}
   Action: {"Discovery Mode triggered" if consecutive_count >= 3 else "Monitoring"}
"""
        log_level(log_message)
    
    def format_alert_summary(self, alerts: List[VersionAlert]) -> str:
        """
        Форматировать сводку алертов
        
        Args:
            alerts: Список алертов
            
        Returns:
            Отформатированная строка
        """
        if not alerts:
            return "📭 No alerts"
        
        lines = [
            "\n" + "="*80,
            "📋 VERSION ALERTS SUMMARY",
            "="*80,
            f"Total alerts: {len(alerts)}\n"
        ]
        
        # Группировка по статусу
        by_status = {}
        for alert in alerts:
            status = alert.migration_status
            if status not in by_status:
                by_status[status] = []
            by_status[status].append(alert)
        
        # Вывод по статусам
        status_emoji = {
            'pending': '⏳',
            'completed': '✅',
            'failed': '❌',
            'rolled_back': '🔙'
        }
        
        for status, status_alerts in sorted(by_status.items()):
            emoji = status_emoji.get(status, '❓')
            lines.append(f"{emoji} {status.upper()}: {len(status_alerts)} alerts")
            
            for alert in status_alerts[:5]:  # Показать первые 5
                priority_emoji = self.EMOJI_MAP.get(alert.priority, '⚪')
                lines.append(
                    f"   {priority_emoji} {alert.base_name}: "
                    f"{alert.old_version or 'unknown'} → {alert.new_version}"
                )
            
            if len(status_alerts) > 5:
                lines.append(f"   ... and {len(status_alerts) - 5} more")
            lines.append("")
        
        lines.append("="*80 + "\n")
        return "\n".join(lines)
    
    def format_migration_stats(self, stats: Dict) -> str:
        """
        Форматировать статистику миграций
        
        Args:
            stats: Словарь со статистикой
            
        Returns:
            Отформатированная строка
        """
        lines = [
            "\n" + "="*80,
            "📊 MIGRATION STATISTICS",
            "="*80
        ]
        
        if 'metrics_30d' in stats:
            metrics = stats['metrics_30d']
            lines.extend([
                f"Period: Last {metrics.get('period_days', 30)} days\n",
                f"🆕 Versions discovered: {metrics.get('total_discovered', 0)}",
                f"✅ Successful migrations: {metrics.get('total_successful', 0)}",
                f"❌ Failed migrations: {metrics.get('total_failed', 0)}",
                f"🔙 Rollbacks performed: {metrics.get('total_rollbacks', 0)}",
                f"⏱ Avg migration time: {metrics.get('avg_migration_time', 0):.2f}s"
            ])
        
        if 'pending_migrations' in stats:
            lines.extend([
                "",
                f"⏳ Pending migrations: {stats['pending_migrations']}",
                f"📈 Recent migrations: {stats.get('recent_migrations', 0)}",
                f"⚠️ Recent failures: {stats.get('failed_migrations', 0)}"
            ])
        
        lines.append("="*80 + "\n")
        return "\n".join(lines)
    
    def format_version_history(self, versions: List[Dict]) -> str:
        """
        Форматировать историю версий файла
        
        Args:
            versions: Список версий
            
        Returns:
            Отформатированная строка
        """
        if not versions:
            return "📭 No version history available"
        
        base_name = versions[0]['base_name']
        
        lines = [
            "\n" + "="*80,
            f"📜 VERSION HISTORY: {base_name}",
            "="*80,
            f"Total versions: {len(versions)}\n"
        ]
        
        for i, version in enumerate(versions, 1):
            is_active = version.get('is_active', False)
            status_marker = "🟢 ACTIVE" if is_active else "📦 ARCHIVED"
            
            lines.append(f"{i}. v{version['version']} {status_marker}")
            lines.append(f"   URL: {version['url']}")
            lines.append(f"   Category: {version.get('category', 'unknown')}")
            lines.append(f"   Priority: {version.get('priority', 'MEDIUM')}")
            
            if is_active:
                last_checked = version.get('last_checked')
                if last_checked:
                    lines.append(f"   Last checked: {last_checked}")
            else:
                archived_at = version.get('archived_at')
                if archived_at:
                    lines.append(f"   Archived: {archived_at}")
            
            lines.append("")
        
        lines.append("="*80 + "\n")
        return "\n".join(lines)
    
    def create_telegram_message(self, alert_type: str, data: Dict) -> str:
        """
        Создать сообщение для Telegram
        
        Args:
            alert_type: Тип алерта ('version_update', 'migration_success', etc.)
            data: Данные для сообщения
            
        Returns:
            Отформатированное сообщение для Telegram
        """
        if alert_type == 'version_update':
            return self._format_version_update_telegram(data)
        elif alert_type == 'migration_success':
            return self._format_migration_success_telegram(data)
        elif alert_type == 'migration_failed':
            return self._format_migration_failed_telegram(data)
        elif alert_type == 'rollback':
            return self._format_rollback_telegram(data)
        elif alert_type == '404_critical':
            return self._format_404_critical_telegram(data)
        else:
            return f"Unknown alert type: {alert_type}"
    
    def _format_version_update_telegram(self, data: Dict) -> str:
        """Форматировать алерт о новой версии для Telegram"""
        emoji_update = self.EMOJI_MAP['version_update']
        emoji_priority = self.EMOJI_MAP.get(data.get('priority', 'MEDIUM'), '⚪')
        
        message = f"""{emoji_update} *НОВАЯ ВЕРСИЯ ОБНАРУЖЕНА*

📦 Файл: `{data['base_name']}`
📊 Категория: {data.get('category', 'unknown')} ({emoji_priority} {data.get('priority', 'MEDIUM')})

Текущая версия: {data.get('current_version', 'unknown')}
Новая версия: *{data['new_version']}* ✨

⚙️ Статус миграции: {data.get('migration_status', 'Автоматическая миграция запущена...')}
⏱ Обнаружено: {datetime.now().strftime('%Y-%m-%d %H:%M')}

🔗 Старый URL: `{data.get('current_url', 'N/A')}`
🔗 Новый URL: `{data['new_url']}`
"""
        return message
    
    def _format_migration_success_telegram(self, data: Dict) -> str:
        """Форматировать успешную миграцию для Telegram"""
        emoji = self.EMOJI_MAP['migration_success']
        
        message = f"""{emoji} *МИГРАЦИЯ ЗАВЕРШЕНА*

📦 Файл: `{data['base_name']}`
📊 Категория: {data.get('category', 'unknown')}

{data.get('old_version', 'unknown')} → *{data['new_version']}*

⏱ Время миграции: {data.get('migration_time', 0):.2f}с
✅ Статус: Активна и отслеживается
"""
        return message
    
    def _format_migration_failed_telegram(self, data: Dict) -> str:
        """Форматировать неудачную миграцию для Telegram"""
        emoji = self.EMOJI_MAP['migration_failed']
        
        message = f"""{emoji} *МИГРАЦИЯ НЕ УДАЛАСЬ*

📦 Файл: `{data['base_name']}`
📊 Категория: {data.get('category', 'unknown')}

{data.get('old_version', 'unknown')} → {data['new_version']}

❌ Ошибка: {data.get('error', 'Unknown error')}
🔙 Действие: Откат к предыдущей версии
"""
        return message
    
    def _format_rollback_telegram(self, data: Dict) -> str:
        """Форматировать откат для Telegram"""
        emoji = self.EMOJI_MAP['rollback']
        
        message = f"""{emoji} *ОТКАТ ВЕРСИИ*

📦 Файл: `{data['base_name']}`

{data.get('from_version', 'unknown')} → *{data['to_version']}*

📝 Причина: {data.get('reason', 'Manual rollback')}
✅ Статус: Восстановлена предыдущая версия
"""
        return message
    
    def _format_404_critical_telegram(self, data: Dict) -> str:
        """Форматировать критическую 404 ошибку для Telegram"""
        emoji = self.EMOJI_MAP['404_error']
        
        message = f"""{emoji} *КРИТИЧЕСКАЯ ОШИБКА 404*

📦 Файл: `{data['base_name']}`
🔗 URL: `{data['url']}`

⚠️ Последовательных 404: {data.get('consecutive_count', 0)}
🔍 Действие: Запущен Discovery Mode для поиска замены

⏱ Время: {datetime.now().strftime('%Y-%m-%d %H:%M')}
"""
        return message
    
    def print_dashboard(self):
        """Вывести дашборд с общей информацией о системе"""
        try:
            # Получить статистику
            pending_alerts = db.get_pending_alerts()
            recent_alerts = db.get_recent_version_alerts(limit=10)
            metrics = db.get_metrics_summary(days=30)
            files_with_404 = db.get_files_with_404_errors(min_count=1)
            
            lines = [
                "\n" + "="*80,
                "🎛 VERSION MONITORING DASHBOARD",
                "="*80,
                "",
                "📊 CURRENT STATUS:",
                f"   ⏳ Pending migrations: {len(pending_alerts)}",
                f"   ⚠️ Files with 404 errors: {len(files_with_404)}",
                "",
                "📈 LAST 30 DAYS:",
                f"   🆕 Versions discovered: {metrics.get('total_discovered', 0)}",
                f"   ✅ Successful migrations: {metrics.get('total_successful', 0)}",
                f"   ❌ Failed migrations: {metrics.get('total_failed', 0)}",
                f"   🔙 Rollbacks: {metrics.get('total_rollbacks', 0)}",
                f"   ⏱ Avg migration time: {metrics.get('avg_migration_time', 0):.2f}s",
                ""
            ]
            
            if recent_alerts:
                lines.append("🕒 RECENT ALERTS:")
                for alert in recent_alerts[:5]:
                    status_emoji = {
                        'pending': '⏳',
                        'completed': '✅',
                        'failed': '❌',
                        'rolled_back': '🔙'
                    }.get(alert.migration_status, '❓')
                    
                    lines.append(
                        f"   {status_emoji} {alert.base_name}: "
                        f"{alert.old_version or '?'} → {alert.new_version} "
                        f"({alert.discovered_at.strftime('%Y-%m-%d %H:%M')})"
                    )
                lines.append("")
            
            if files_with_404:
                lines.append("⚠️ FILES WITH 404 ERRORS:")
                for file in files_with_404[:5]:
                    lines.append(
                        f"   🔴 {file.base_name or file.url}: "
                        f"{file.consecutive_404_count} consecutive 404s"
                    )
                lines.append("")
            
            lines.append("="*80 + "\n")
            
            dashboard = "\n".join(lines)
            logger.info(dashboard)
            
        except Exception as e:
            logger.error(f"Ошибка при выводе дашборда: {e}", exc_info=True)


# Глобальный экземпляр системы алертов
alert_system = AlertSystem()

