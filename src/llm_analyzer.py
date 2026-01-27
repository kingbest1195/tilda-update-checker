"""
Модуль для анализа изменений через OpenAI API
"""
import logging
import json
import time
from threading import Lock
from typing import Dict, Optional

from openai import OpenAI
from openai import OpenAIError

import config

logger = logging.getLogger(__name__)

# Rate limiting для OpenAI API
_last_api_call_time = 0
_rate_limit_lock = Lock()
MIN_API_CALL_INTERVAL = 1.0  # секунда между запросами


# Контексты для разных категорий файлов
CATEGORY_CONTEXTS = {
    "core": """
    Этот файл относится к ЯДРУ TILDA (Core).
    Изменения здесь влияют на:
    - Базовую инициализацию страниц
    - Сетку и структуру layout
    - Глобальные события и обработчики
    - Формы и их валидацию
    Такие изменения КРИТИЧНЫ для всех сайтов на Tilda.
    """,
    
    "members": """
    Этот файл относится к модулю ЛИЧНЫХ КАБИНЕТОВ (Members Area).
    Изменения здесь влияют на:
    - Авторизацию и аутентификацию пользователей
    - Профили пользователей и личные данные
    - Историю заказов в магазине (ЛКИМ)
    - Систему подписок и членства
    - Интеграцию с системой оплаты
    Такие изменения КРИТИЧНЫ для сайтов с закрытыми зонами и членством.
    """,
    
    "ecommerce": """
    Этот файл относится к E-COMMERCE функционалу.
    Изменения здесь влияют на:
    - Работу корзины и оформление заказов
    - Каталог товаров, фильтры и поиск
    - Систему скидок и промокодов
    - Wishlist (список желаний)
    - Варианты товаров (размеры, цвета)
    - Интеграцию с платежными системами
    Такие изменения ВАЖНЫ для интернет-магазинов на Tilda.
    """,
    
    "zero_block": """
    Этот файл относится к ZERO BLOCK - профессиональному редактору.
    Изменения здесь влияют на:
    - Рендеринг абсолютно позиционированных элементов
    - Адаптивность и масштабирование Zero блоков
    - Формы внутри Zero блоков
    - Галереи и интерактивные элементы
    - Анимацию step-by-step (появление элементов)
    Такие изменения ВАЖНЫ для сайтов с кастомным дизайном в Zero.
    """,
    
    "ui_components": """
    Этот файл относится к UI КОМПОНЕНТАМ.
    Изменения здесь влияют на:
    - Меню, попапы, слайдеры
    - Квизы и интерактивные формы
    - Stories, видеоплейлисты
    - Before/After блоки
    - Карточки и таблицы
    Такие изменения обычно СРЕДНЕЙ ВАЖНОСТИ, затрагивают конкретные блоки.
    """,
    
    "utilities": """
    Этот файл относится к ВСПОМОГАТЕЛЬНЫМ УТИЛИТАМ.
    Изменения здесь влияют на:
    - Маски ввода телефонов
    - Статистику и аналитику
    - Производительность и оптимизацию
    - Обработку ошибок
    - Условную логику форм
    Такие изменения обычно НИЗКОЙ ВАЖНОСТИ, не критичны для основного функционала.
    """
}


class LLMAnalyzer:
    """Класс для анализа изменений через LLM"""
    
    def __init__(self):
        """Инициализация анализатора"""
        if not config.OPENAI_API_KEY:
            logger.warning("OPENAI_API_KEY не установлен! LLM анализ будет недоступен.")
            self.client = None
        else:
            self.client = OpenAI(
                api_key=config.OPENAI_API_KEY,
                timeout=60.0,
                max_retries=2
            )

    def _wait_for_rate_limit(self):
        """Применить rate limiting для OpenAI API"""
        global _last_api_call_time
        with _rate_limit_lock:
            current_time = time.time()
            time_since_last_call = current_time - _last_api_call_time
            if time_since_last_call < MIN_API_CALL_INTERVAL:
                sleep_time = MIN_API_CALL_INTERVAL - time_since_last_call
                logger.debug(f"⏱ Rate limiting: ожидание {sleep_time:.2f}s")
                time.sleep(sleep_time)
            _last_api_call_time = time.time()

    def analyze_change(self, change_info: Dict) -> Optional[Dict]:
        """
        Проанализировать изменение через LLM
        
        Args:
            change_info: Информация об изменении
            
        Returns:
            Словарь с результатами анализа или None при ошибке
        """
        if not self.client:
            logger.error("OpenAI клиент не инициализирован. Проверьте OPENAI_API_KEY.")
            return None
        
        if not change_info.get('is_significant'):
            logger.info("Изменение незначительное, пропускаем LLM анализ")
            return self._create_default_analysis(change_info)
        
        try:
            # Подготовить промпт
            user_prompt = self._create_analysis_prompt(change_info)
            
            logger.info(f"Отправка запроса в OpenAI для анализа: {change_info['url']}")

            # Применить rate limiting
            self._wait_for_rate_limit()

            # Отправить запрос к OpenAI
            response = self.client.chat.completions.create(
                model=config.OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": config.SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt}
                ],
                response_format={"type": "json_object"},
                temperature=config.OPENAI_TEMPERATURE,
                max_tokens=config.OPENAI_MAX_TOKENS
            )
            
            # Извлечь ответ
            content = response.choices[0].message.content
            
            # Парсить JSON ответ
            analysis = self._parse_llm_response(content)
            
            if analysis:
                # Добавить метаданные
                analysis['url'] = change_info['url']
                analysis['file_type'] = change_info['file_type']
                analysis['change_info'] = change_info
                
                # Логировать использование токенов
                usage = response.usage
                logger.info(
                    f"OpenAI анализ завершен. "
                    f"Токены: {usage.prompt_tokens} input + {usage.completion_tokens} output = {usage.total_tokens} всего"
                )
                
                return analysis
            else:
                logger.error("Не удалось распарсить ответ LLM")
                return self._create_default_analysis(change_info)
            
        except OpenAIError as e:
            logger.error(f"Ошибка OpenAI API: {e}")
            return self._create_default_analysis(change_info)
        except Exception as e:
            logger.error(f"Неожиданная ошибка при анализе через LLM: {e}", exc_info=True)
            return self._create_default_analysis(change_info)
    
    def _create_analysis_prompt(self, change_info: Dict) -> str:
        """
        Создать промпт для анализа с учетом категории файла
        
        Args:
            change_info: Информация об изменении
            
        Returns:
            Текст промпта
        """
        stats = change_info['stats']
        category = change_info.get('category', 'unknown')
        priority = change_info.get('priority', 'MEDIUM')
        
        # Получить контекст категории
        category_context = CATEGORY_CONTEXTS.get(category, "")
        
        # Форматировать статистику
        change_stats = f"""- Добавлено строк: {stats['added_lines']}
- Удалено строк: {stats['removed_lines']}
- Всего изменений: {stats['total_changes']}
"""
        
        # Создать расширенный промпт с контекстом категории
        prompt = f"""Проанализируй изменения в файле конструктора Tilda.

КОНТЕКСТ КАТЕГОРИИ:
{category_context}

Файл: {change_info['url']}
Категория: {category}
Приоритет: {priority}
Тип файла: {change_info['file_type']}
Размер изменения: {abs(change_info['size_diff'])} байт

Метаданные изменения:
- Изменение размера файла: {change_info['size_diff']} байт
- Процент изменения: {change_info['change_percent']}%

Статистика:
{change_stats}

Задачи:
1. Определи, что конкретно изменилось (новая функция, исправление бага, оптимизация, изменение API)
2. Оцени значимость с учетом категории файла: КРИТИЧЕСКОЕ / ВАЖНОЕ / НЕЗНАЧИТЕЛЬНОЕ
3. Опиши влияние на пользователей Tilda простым языком
4. Дай рекомендации разработчикам (если нужны действия)

ВАЖНО: Учитывай приоритет категории '{priority}' при определении severity.

Ответ СТРОГО в JSON формате:
{{
  "change_type": "тип изменения",
  "severity": "КРИТИЧЕСКОЕ/ВАЖНОЕ/НЕЗНАЧИТЕЛЬНОЕ",
  "description": "краткое описание изменений",
  "user_impact": "влияние на пользователей",
  "recommendations": "рекомендации или 'Действий не требуется'"
}}
"""
        
        return prompt
    
    def _parse_llm_response(self, content: str) -> Optional[Dict]:
        """
        Распарсить JSON ответ от LLM
        
        Args:
            content: Текст ответа
            
        Returns:
            Словарь с результатами или None при ошибке
        """
        try:
            data = json.loads(content)
            
            # Валидация обязательных полей
            required_fields = ['change_type', 'severity', 'description', 'user_impact', 'recommendations']
            
            for field in required_fields:
                if field not in data:
                    logger.warning(f"Отсутствует обязательное поле в ответе LLM: {field}")
                    return None
            
            # Нормализовать severity
            severity = data['severity'].upper()
            if severity not in ['КРИТИЧЕСКОЕ', 'ВАЖНОЕ', 'НЕЗНАЧИТЕЛЬНОЕ']:
                logger.warning(f"Некорректное значение severity: {severity}, использую 'ВАЖНОЕ'")
                data['severity'] = 'ВАЖНОЕ'
            
            return data
            
        except json.JSONDecodeError as e:
            logger.error(f"Ошибка парсинга JSON: {e}")
            logger.debug(f"Ответ LLM: {content}")
            return None
        except Exception as e:
            logger.error(f"Ошибка при обработке ответа LLM: {e}", exc_info=True)
            return None
    
    def _create_default_analysis(self, change_info: Dict) -> Dict:
        """
        Создать анализ по умолчанию (fallback без LLM) с учетом категории
        
        Args:
            change_info: Информация об изменении
            
        Returns:
            Словарь с базовым анализом
        """
        size_diff = change_info['size_diff']
        change_percent = change_info['change_percent']
        category = change_info.get('category', 'unknown')
        priority = change_info.get('priority', 'MEDIUM')
        
        # Эвристика для определения severity на основе приоритета и процента изменения
        if priority == 'CRITICAL':
            if change_percent > 20:
                severity = 'КРИТИЧЕСКОЕ'
            elif change_percent > 5:
                severity = 'ВАЖНОЕ'
            else:
                severity = 'ВАЖНОЕ'
        elif priority == 'HIGH':
            if change_percent > 30:
                severity = 'КРИТИЧЕСКОЕ'
            elif change_percent > 10:
                severity = 'ВАЖНОЕ'
            else:
                severity = 'НЕЗНАЧИТЕЛЬНОЕ'
        elif priority == 'MEDIUM':
            if change_percent > 50:
                severity = 'ВАЖНОЕ'
            else:
                severity = 'НЕЗНАЧИТЕЛЬНОЕ'
        else:  # LOW
            severity = 'НЕЗНАЧИТЕЛЬНОЕ'
        
        direction = "увеличился" if size_diff > 0 else "уменьшился"
        
        # Специфичные рекомендации для разных категорий
        recommendations_map = {
            'core': 'Рекомендуется проверить работу всех сайтов, особенно формы и базовый функционал',
            'members': 'Проверьте работу авторизации и личных кабинетов на всех сайтах',
            'ecommerce': 'Протестируйте корзину, оформление заказов и систему скидок',
            'zero_block': 'Проверьте отображение Zero блоков на разных разрешениях экрана',
            'ui_components': 'Проверьте работу затронутых UI компонентов',
            'utilities': 'Действий не требуется, изменения затрагивают вспомогательный функционал'
        }
        
        recommendations = recommendations_map.get(category, 'Рекомендуется проверить работу сайтов после обновления')
        
        return {
            'url': change_info['url'],
            'file_type': change_info['file_type'],
            'category': category,
            'priority': priority,
            'change_type': 'Обновление кода',
            'severity': severity,
            'description': f"Файл {direction} на {abs(size_diff)} байт ({change_percent}%). Категория: {category}.",
            'user_impact': f'Возможны изменения в функциональности категории "{category}" конструктора Tilda',
            'recommendations': recommendations,
            'change_info': change_info
        }
    
    def estimate_tokens(self, text: str) -> int:
        """
        Оценить количество токенов в тексте
        
        Args:
            text: Текст для оценки
            
        Returns:
            Приблизительное количество токенов
        """
        # Простая эвристика: ~4 символа = 1 токен для английского
        # Для русского может быть другое соотношение
        return len(text) // 4


# Глобальный экземпляр анализатора
analyzer = LLMAnalyzer()



