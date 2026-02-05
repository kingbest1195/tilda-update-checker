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
from src.diff_detector import detector

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
            # Подготовить контекст с реальными фрагментами кода
            code_context = detector.prepare_llm_context(
                change_info,
                max_tokens=config.MAX_DIFF_TOKENS
            )

            # Передать code_context в промпт
            user_prompt = self._create_analysis_prompt(change_info, code_context)

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
    
    def _create_analysis_prompt(self, change_info: Dict, code_context: str = None) -> str:
        """
        Создать промпт для анализа с учетом категории файла

        Args:
            change_info: Информация об изменении
            code_context: Подготовленный контекст с фрагментами кода (опционально)

        Returns:
            Текст промпта
        """
        stats = change_info['stats']
        category = change_info.get('category', 'unknown')
        priority = change_info.get('priority', 'MEDIUM')

        # Получить контекст категории
        category_context = CATEGORY_CONTEXTS.get(category, "")

        # Если code_context не передан - использовать только статистику
        if not code_context:
            code_context = f"""Метаданные изменения:
- Изменение размера файла: {change_info['size_diff']} байт
- Процент изменения: {change_info['change_percent']}%

Статистика:
- Добавлено строк: {stats['added_lines']}
- Удалено строк: {stats['removed_lines']}
- Всего изменений: {stats['total_changes']}
"""
        
        # Создать расширенный промпт с контекстом категории и примерами
        prompt = f"""Проанализируй изменения в файле конструктора Tilda.

КОНТЕКСТ КАТЕГОРИИ:
{category_context}

Файл: {change_info['url']}
Категория: {category}
Приоритет: {priority}
Тип файла: {change_info['file_type']}

{code_context}

ПРИМЕРЫ ХОРОШИХ АНАЛИЗОВ:

Пример 1 (новая функция):
{{
  "change_type": "Новая функция",
  "severity": "ВАЖНОЕ",
  "description": "Добавлена функция t_cart__validatePromoCode() для валидации промокодов. Функция проверяет формат кода, срок действия и применимость к товарам в корзине.",
  "user_impact": "Пользователи смогут использовать промокоды при оформлении заказов. Требуется настройка промокодов в админке.",
  "recommendations": "Проверьте работу оформления заказа с промокодами. Убедитесь, что скидки применяются корректно."
}}

Пример 2 (исправление бага):
{{
  "change_type": "Исправление бага",
  "severity": "КРИТИЧЕСКОЕ",
  "description": "Исправлен баг в функции t_members__checkSession(): раньше expiration time не учитывал timezone, из-за чего сессии истекали преждевременно.",
  "user_impact": "Пользователи больше не будут внезапно разлогиниваться из личного кабинета. Исправлен критичный баг с авторизацией.",
  "recommendations": "Проверьте работу авторизации на сайтах с Members Area. Убедитесь, что сессии не истекают раньше времени."
}}

Пример 3 (изменение API):
{{
  "change_type": "Breaking Change",
  "severity": "КРИТИЧЕСКОЕ",
  "description": "Изменён API функции t_cart__init(): удалён параметр 'autoOpen', добавлен новый параметр 'config' объект с настройками. Старый способ вызова больше не работает.",
  "user_impact": "Кастомный код, использующий t_cart__init(true), сломается. Требуется обновление кастомного JS кода.",
  "recommendations": "СРОЧНО: Проверьте все сайты с кастомным JS кодом для корзины. Обновите вызовы t_cart__init() на новый формат."
}}

Пример 4 (минифицированный код без понимания):
{{
  "change_type": "Обновление кода",
  "severity": "ВАЖНОЕ",
  "description": "Код минифицирован, детальный анализ затруднён. Обнаружены изменения в области обработки событий (видны вызовы addEventListener). Размер увеличился на 512 байт, что указывает на добавление новой логики.",
  "user_impact": "Возможны улучшения в обработке пользовательских событий в Zero Block. Рекомендуется тестирование.",
  "recommendations": "Проверьте работу интерактивных элементов в Zero блоках (кнопки, формы, ховер-эффекты)."
}}

Задачи:
1. Определи, что конкретно изменилось:
   - Новая функция → НАЗОВИ имя функции (ищи "function XXX(", "XXX: function", "const XXX =")
   - Исправление бага → ОПИШИ суть с примером (ищи изменения в условиях if/else)
   - Оптимизация → ЧТО именно оптимизировано (например: "убран лишний цикл", "кеширование результата")
   - Изменение API → КАКИЕ методы/параметры изменились (сравни параметры функций в старом и новом коде)
   - Breaking Change → КАКОЙ код сломается (укажи старый способ вызова и новый)

2. Найди ключевые индикаторы изменений:
   - Добавлены функции: ищи "+ function XXX", "+ const XXX =", "+ XXX: function"
   - Удалены функции: ищи "- function XXX"
   - Изменены параметры: сравни "(param1, param2)" в старом и новом коде
   - Изменены условия: ищи изменения в "if", "switch", "&&", "||"
   - Новые зависимости: ищи новые "import", "require"

3. Оцени значимость с учетом категории '{category}' (приоритет: {priority}):
   - КРИТИЧЕСКОЕ:
     * Breaking changes (удалены функции, изменён API)
     * Баги безопасности или потери данных
     * Изменения в core функционале (формы, авторизация, оплата)

   - ВАЖНОЕ:
     * Новые функции или параметры
     * Значимые исправления багов
     * Изменения, требующие тестирования

   - НЕЗНАЧИТЕЛЬНОЕ:
     * Рефакторинг без изменения API
     * Форматирование, комментарии
     * Оптимизация без видимых изменений

4. Опиши влияние на пользователей Tilda простым языком:
   - ЧТО изменится в поведении сайта? (конкретные действия: "кнопка теперь X", "форма будет Y")
   - КОГО это затронет? (все сайты / только с определёнными блоками / только с кастомным кодом)
   - НУЖНЫ ли действия? (обновить код / проверить работу / ничего не делать)

5. Дай рекомендации:
   - КАКИЕ места на сайте проверить? (конкретные блоки, формы, страницы)
   - КАКИЕ риски? (может сломаться X, если используется Y)
   - Или "Действий не требуется" (если изменения не критичны)

ВАЖНО:
- Используй РЕАЛЬНЫЕ примеры из секции "Ключевые изменения в коде"
- Ищи имена функций, параметры, условия в diff
- Если видишь "function XXX(" или "XXX: function" - НАЗОВИ эту функцию
- Если видишь новый параметр - УКАЖИ его
- Если код минифицирован и неясен - используй формат как в Примере 4
- НЕ используй абстрактные формулировки без деталей

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
    
    def _generate_user_impact(self, metadata: Dict, category: str) -> str:
        """
        Генерировать описание влияния на основе метаданных

        Args:
            metadata: Метаданные из diff
            category: Категория файла

        Returns:
            Описание влияния на пользователей
        """
        if metadata.get('removed_functions'):
            return f"Удалены функции. Возможны проблемы с совместимостью в категории '{category}'"

        if metadata.get('added_functions'):
            return f"Добавлена новая функциональность в категории '{category}'. Требуется тестирование."

        if metadata.get('modified_functions'):
            return f"Изменена существующая функциональность в категории '{category}'. Рекомендуется проверка."

        return f'Возможны изменения в функциональности категории "{category}" конструктора Tilda'

    def _create_default_analysis(self, change_info: Dict) -> Dict:
        """
        Создать анализ по умолчанию (fallback без LLM) с использованием метаданных

        Args:
            change_info: Информация об изменении

        Returns:
            Словарь с базовым анализом
        """
        from src.diff_detector import detector

        size_diff = change_info['size_diff']
        change_percent = change_info['change_percent']
        category = change_info.get('category', 'unknown')
        priority = change_info.get('priority', 'MEDIUM')

        # Извлечь метаданные из diff
        diff_lines = change_info.get('diff_lines', [])
        metadata = detector._extract_diff_metadata(diff_lines)

        # Улучшенное описание на основе метаданных
        description_parts = []

        if metadata['added_functions']:
            funcs = ', '.join(metadata['added_functions'][:3])
            description_parts.append(f"Добавлены функции: {funcs}")

        if metadata['removed_functions']:
            funcs = ', '.join(metadata['removed_functions'][:3])
            description_parts.append(f"Удалены функции: {funcs}")

        if metadata['modified_functions']:
            funcs = ', '.join(metadata['modified_functions'][:3])
            description_parts.append(f"Изменены функции: {funcs}")

        if metadata['new_imports']:
            description_parts.append(f"Добавлены зависимости ({len(metadata['new_imports'])} шт.)")

        if metadata['condition_changes']:
            description_parts.append(f"Изменена логика выполнения ({len(metadata['condition_changes'])} условий)")

        # Если метаданные не найдены - общее описание
        if not description_parts:
            direction = "увеличился" if size_diff > 0 else "уменьшился"
            description_parts.append(
                f"Файл {direction} на {abs(size_diff)} байт ({change_percent}%). "
                f"Детальный анализ недоступен (LLM API не настроен)."
            )

        description = " ".join(description_parts)

        # Определить severity на основе метаданных
        if metadata['removed_functions']:
            severity = 'КРИТИЧЕСКОЕ'  # Удаление функций - breaking change
        elif metadata['added_functions'] or metadata['modified_functions']:
            severity = 'ВАЖНОЕ'
        else:
            # Fallback к эвристике по приоритету
            if priority == 'CRITICAL':
                severity = 'ВАЖНОЕ' if change_percent > 5 else 'НЕЗНАЧИТЕЛЬНОЕ'
            elif priority == 'HIGH':
                severity = 'ВАЖНОЕ' if change_percent > 10 else 'НЕЗНАЧИТЕЛЬНОЕ'
            elif priority == 'MEDIUM':
                severity = 'ВАЖНОЕ' if change_percent > 50 else 'НЕЗНАЧИТЕЛЬНОЕ'
            else:  # LOW
                severity = 'НЕЗНАЧИТЕЛЬНОЕ'

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
            'description': description,
            'user_impact': self._generate_user_impact(metadata, category),
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



