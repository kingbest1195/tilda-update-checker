"""
Модуль для генерации анонсов на основе LLM анализа
"""
import logging
from datetime import datetime
from typing import List, Dict, Optional

from src.database import db

logger = logging.getLogger(__name__)


class AnnouncementGenerator:
    """Класс для генерации анонсов"""
    
    def __init__(self):
        """Инициализация генератора"""
        pass
    
    def generate_announcement(self, analysis_results: List[Dict]) -> Optional[str]:
        """
        Сгенерировать анонс на основе результатов анализа
        
        Args:
            analysis_results: Список результатов LLM анализа
            
        Returns:
            Текст анонса или None если нет изменений
        """
        if not analysis_results:
            logger.info("Нет данных для создания анонса")
            return None
        
        # Заголовок
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M")
        title = f"📢 Обновление Tilda CDN - {current_time}"
        
        # Статистика
        total_files = len(analysis_results)
        
        # Группировать по severity
        critical = [r for r in analysis_results if r.get('severity') == 'КРИТИЧЕСКОЕ']
        important = [r for r in analysis_results if r.get('severity') == 'ВАЖНОЕ']
        minor = [r for r in analysis_results if r.get('severity') == 'НЕЗНАЧИТЕЛЬНОЕ']
        
        # Формировать анонс
        lines = [
            title,
            "",
            f"🔧 Изменено файлов: {total_files}",
        ]
        
        # Добавить статистику по важности
        if critical:
            lines.append(f"⚠️ Критических изменений: {len(critical)}")
        if important:
            lines.append(f"📌 Важных изменений: {len(important)}")
        if minor:
            lines.append(f"ℹ️ Незначительных изменений: {len(minor)}")
        
        lines.append("")
        lines.append("📝 Основные изменения:")
        lines.append("")
        
        # Добавить детали по каждому изменению
        for idx, result in enumerate(analysis_results, 1):
            change_entry = self.format_change_entry(idx, result)
            lines.append(change_entry)
            lines.append("")
        
        # Футер
        lines.append("---")
        lines.append("Сгенерировано автоматически | Tilda Update Checker v1.0")
        
        announcement_text = "\n".join(lines)
        
        logger.info(f"Анонс сгенерирован ({len(announcement_text)} символов)")
        return announcement_text
    
    def format_change_entry(self, index: int, result: Dict) -> str:
        """
        Форматировать запись об изменении
        
        Args:
            index: Номер изменения
            result: Результат анализа
            
        Returns:
            Форматированный текст
        """
        url = result.get('url', 'Неизвестно')
        filename = url.split('/')[-1] if url else 'Неизвестный файл'
        
        change_type = result.get('change_type', 'Обновление')
        severity = result.get('severity', 'НЕЗНАЧИТЕЛЬНОЕ')
        description = result.get('description', 'Нет описания')
        user_impact = result.get('user_impact', 'Влияние неизвестно')
        recommendations = result.get('recommendations', 'Рекомендации отсутствуют')
        
        # Иконка severity
        severity_icon = {
            'КРИТИЧЕСКОЕ': '🔴',
            'ВАЖНОЕ': '🟡',
            'НЕЗНАЧИТЕЛЬНОЕ': '🟢'
        }.get(severity, '⚪')
        
        trend = result.get('trend')
        feature = result.get('feature')

        # Форматировать текст с отступами
        lines = [
            f"{index}. {filename}",
            f"   {severity_icon} Тип: {change_type}",
            f"   Значимость: {severity}",
            f"",
            f"   {description}",
            f"",
            f"   Влияние: {user_impact}",
            f"",
            f"   Рекомендации: {recommendations}",
        ]

        if trend:
            lines.append(f"")
            lines.append(f"   Тренд: {trend}")
        if feature:
            lines.append(f"   Фича: {feature}")

        lines.append(f"")
        lines.append(f"   Ссылка: {url}")

        return "\n".join(lines)
    
    def save_announcements(self, analysis_results: List[Dict]) -> List[int]:
        """
        Сгенерировать и сохранить анонсы в БД
        
        Args:
            analysis_results: Список результатов анализа
            
        Returns:
            Список ID созданных анонсов
        """
        announcement_ids = []
        
        # Генерировать общий анонс
        full_announcement = self.generate_announcement(analysis_results)
        
        if not full_announcement:
            return announcement_ids
        
        # Сохранить анонс для каждого изменения
        for result in analysis_results:
            try:
                change_info = result.get('change_info', {})
                change_id = change_info.get('change_id')
                
                if not change_id:
                    logger.warning("Отсутствует change_id в результате анализа")
                    continue
                
                # Создать заголовок для отдельного анонса
                url = result.get('url', 'Неизвестно')
                filename = url.split('/')[-1] if url else 'Неизвестный файл'
                current_time = datetime.now().strftime("%Y-%m-%d %H:%M")
                title = f"Обновление {filename} - {current_time}"
                
                # Форматировать содержимое
                content = self.format_change_entry(1, result)
                
                # Сохранить в БД
                announcement = db.save_announcement(
                    change_id=change_id,
                    title=title,
                    content=content,
                    change_type=result.get('change_type'),
                    severity=result.get('severity'),
                    description_short=result.get('description', ''),
                    user_impact=result.get('user_impact', ''),
                    trend=result.get('trend'),
                    feature=result.get('feature'),
                )
                
                announcement_ids.append(announcement.id)
                logger.info(f"Анонс сохранен: ID={announcement.id}, change_id={change_id}")
                
            except Exception as e:
                logger.error(f"Ошибка при сохранении анонса: {e}", exc_info=True)
                continue
        
        logger.info(f"Сохранено анонсов: {len(announcement_ids)}")
        return announcement_ids
    
    def get_announcement_summary(self, announcement_id: int) -> Optional[str]:
        """
        Получить краткую сводку анонса
        
        Args:
            announcement_id: ID анонса
            
        Returns:
            Краткий текст или None
        """
        try:
            announcements = db.get_recent_announcements(limit=100)
            
            for ann in announcements:
                if ann.id == announcement_id:
                    return f"{ann.title}\n{ann.severity or 'N/A'}\n{ann.content[:200]}..."
            
            return None
            
        except Exception as e:
            logger.error(f"Ошибка при получении анонса: {e}", exc_info=True)
            return None
    
    def format_announcements_list(self, announcements: List) -> str:
        """
        Форматировать список анонсов для вывода
        
        Args:
            announcements: Список объектов Announcement
            
        Returns:
            Форматированный текст
        """
        if not announcements:
            return "📭 Анонсов пока нет"
        
        lines = [
            f"📋 Последние анонсы ({len(announcements)}):",
            "=" * 80,
            ""
        ]
        
        for idx, ann in enumerate(announcements, 1):
            timestamp = ann.generated_at.strftime("%Y-%m-%d %H:%M:%S")
            severity_icon = {
                'КРИТИЧЕСКОЕ': '🔴',
                'ВАЖНОЕ': '🟡',
                'НЕЗНАЧИТЕЛЬНОЕ': '🟢'
            }.get(ann.severity, '⚪')
            
            lines.extend([
                f"{idx}. {severity_icon} {ann.title}",
                f"   Дата: {timestamp}",
                f"   Тип: {ann.change_type or 'N/A'}",
                f"",
                ann.content,
                "",
                "-" * 80,
                ""
            ])
        
        return "\n".join(lines)


# Глобальный экземпляр генератора
generator = AnnouncementGenerator()





