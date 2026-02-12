"""
Модуль для анализа изменений через OpenAI API
"""
import logging
import json
import time
from threading import Lock
from typing import Dict, List, Optional

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
                max_completion_tokens=config.OPENAI_MAX_TOKENS
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
        
        # Секция истории изменений
        history_section = ""
        history = change_info.get('history', [])
        if history:
            history_lines = ["ИСТОРИЯ ИЗМЕНЕНИЙ ЭТОГО ФАЙЛА:"]
            for h in history[:5]:
                date_str = h.get('detected_at') or 'N/A'
                if hasattr(date_str, 'strftime'):
                    date_str = date_str.strftime('%Y-%m-%d')
                pct = h.get('change_percent') or 0
                sev = h.get('severity') or ''
                desc = (h.get('description') or '')[:80]
                history_lines.append(f"- {date_str}: изменение {pct}%, {sev}. {desc}")
            history_section = "\n".join(history_lines) + "\n"

        # Секция одновременных изменений
        concurrent_section = ""
        concurrent = change_info.get('concurrent_changes', [])
        if concurrent:
            concurrent_lines = ["ОДНОВРЕМЕННО ИЗМЕНЁННЫЕ ФАЙЛЫ:"]
            for c in concurrent[:5]:
                fname = c.get('filename') or c.get('url') or 'N/A'
                pct = c.get('change_percent') or 0
                concurrent_lines.append(f"- {fname}: изменение {pct}%")
            concurrent_lines.append("→ Если файлы связаны — это координированное обновление, опиши общий тренд.")
            concurrent_section = "\n".join(concurrent_lines) + "\n"

        # Создать расширенный промпт с контекстом категории и примерами
        prompt = f"""Проанализируй изменения в файле конструктора Tilda.

КОНТЕКСТ КАТЕГОРИИ:
{category_context}

Файл: {change_info['url']}
Категория: {category}
Приоритет: {priority}
Тип файла: {change_info['file_type']}

{code_context}

{history_section}
{concurrent_section}
Задачи:
1. Определи БИЗНЕС-СМЫСЛ изменений:
   - Какую фичу Tilda разрабатывает?
   - Какой тренд это отражает?
   - Как это повлияет на владельцев сайтов?

2. Найди технические детали:
   - Добавлены/удалены/изменены функции (ищи "function XXX(", "XXX: function", "const XXX =")
   - Изменены параметры, условия (if/else/switch)
   - Новые зависимости (import, require)

3. Оцени значимость с учетом категории '{category}' (приоритет: {priority}):
   - КРИТИЧЕСКОЕ: Breaking changes, баги безопасности, изменения core функционала
   - ВАЖНОЕ: Новые функции, значимые исправления, требующие тестирования
   - НЕЗНАЧИТЕЛЬНОЕ: Рефакторинг, форматирование, оптимизация без видимых изменений

4. Если есть история изменений — определи тренд (активная разработка, серия фиксов и т.д.)

5. Если несколько файлов одной категории изменились одновременно — опиши координированное обновление.

ВАЖНО:
- Фокус на БИЗНЕС-СМЫСЛЕ, а не на технических деталях
- Называй функции, но в контексте бизнес-значения
- Если код минифицирован и неясен — честно предложи гипотезу
- НЕ используй абстрактные формулировки без деталей

Ответ СТРОГО в JSON формате:
{{
  "change_type": "Новая фича / Улучшение / Исправление / Рефакторинг / Breaking Change",
  "severity": "КРИТИЧЕСКОЕ/ВАЖНОЕ/НЕЗНАЧИТЕЛЬНОЕ",
  "description": "2-3 предложения: бизнес-смысл + технические детали",
  "user_impact": "что конкретно изменится для владельца сайта на Tilda",
  "recommendations": "конкретные действия или 'Действий не требуется'",
  "trend": "гипотеза о тренде развития (или null если нет контекста)",
  "feature": "предположение о разрабатываемой фиче (или null если неясно)"
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

            # Опциональные поля trend и feature (дефолт None)
            data.setdefault('trend', None)
            data.setdefault('feature', None)

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
        Создать анализ по умолчанию (fallback без LLM) с использованием метаданных,
        исторического контекста и cross-file корреляции.

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
        file_type = change_info.get('file_type', 'js')

        # Извлечь метаданные из diff
        diff_lines = change_info.get('diff_lines', [])
        metadata = detector._extract_diff_metadata(diff_lines, file_type=file_type)

        # Улучшенное описание на основе метаданных
        description_parts = []

        if metadata['added_functions']:
            funcs = ', '.join(metadata['added_functions'][:3])
            description_parts.append(f"Добавлены функции: {funcs}.")

        if metadata['removed_functions']:
            funcs = ', '.join(metadata['removed_functions'][:3])
            description_parts.append(f"Удалены функции: {funcs}.")

        if metadata['modified_functions']:
            funcs = ', '.join(metadata['modified_functions'][:3])
            description_parts.append(f"Изменены функции: {funcs}.")

        if metadata['new_imports']:
            description_parts.append(f"Добавлены зависимости ({len(metadata['new_imports'])} шт.).")

        if metadata['condition_changes']:
            description_parts.append(f"Изменена логика выполнения ({len(metadata['condition_changes'])} условий).")

        # CSS-специфичные метаданные
        if metadata.get('css_selectors_added'):
            sels = ', '.join(metadata['css_selectors_added'][:5])
            description_parts.append(f"Добавлены CSS-селекторы: {sels}.")

        if metadata.get('css_selectors_removed'):
            sels = ', '.join(metadata['css_selectors_removed'][:5])
            description_parts.append(f"Удалены CSS-селекторы: {sels}.")

        # Если метаданные не найдены — бизнес-гипотеза по категории
        if not description_parts:
            category_hypotheses = {
                'core': 'Обновление ядра Tilda. Возможны изменения в базовом фреймворке, инициализации страниц или обработке форм.',
                'members': 'Обновление системы личных кабинетов. Возможны изменения в авторизации, профилях или подписках.',
                'ecommerce': 'Обновление модуля магазина. Возможны изменения в корзине, каталоге, оплате или системе скидок.',
                'zero_block': 'Обновление редактора Zero Block. Возможны изменения в рендеринге, адаптивности или анимациях.',
                'ui_components': 'Обновление UI-компонентов. Возможны изменения в виджетах, меню, попапах или слайдерах.',
                'utilities': 'Обновление утилит. Возможны изменения в масках ввода, аналитике или обработке ошибок.',
            }
            direction = "увеличился" if size_diff > 0 else "уменьшился"
            hypothesis = category_hypotheses.get(category, 'Обновление файла Tilda.')
            description_parts.append(
                f"Файл {direction} на {abs(size_diff)} байт ({change_percent}%). {hypothesis}"
            )

        # Исторический контекст
        history = change_info.get('history', [])
        trend = None
        feature = None
        if history:
            update_count = len(history)
            description_parts.append(f"Это {update_count + 1}-е обновление файла. Файл активно развивается.")
            if update_count >= 3:
                trend = f"Активная разработка: {update_count + 1} обновлений. Направление: {category}"

        # Cross-file контекст
        concurrent = change_info.get('concurrent_changes', [])
        # Исключить текущий файл из списка одновременных
        current_url = change_info.get('url', '')
        other_concurrent = [c for c in concurrent if c.get('url') != current_url]
        if other_concurrent:
            filenames = [c.get('filename', 'N/A') for c in other_concurrent[:3]]
            description_parts.append(f"Координированное обновление: одновременно изменились {', '.join(filenames)}.")
            feature = f"Комплексное обновление подсистемы {category}"

        description = " ".join(description_parts)

        # Определить severity на основе метаданных
        if metadata['removed_functions'] or metadata.get('css_selectors_removed'):
            severity = 'КРИТИЧЕСКОЕ'
        elif metadata['added_functions'] or metadata['modified_functions'] or metadata.get('css_selectors_added'):
            severity = 'ВАЖНОЕ'
        else:
            if priority == 'CRITICAL':
                severity = 'ВАЖНОЕ' if change_percent > 5 else 'НЕЗНАЧИТЕЛЬНОЕ'
            elif priority == 'HIGH':
                severity = 'ВАЖНОЕ' if change_percent > 10 else 'НЕЗНАЧИТЕЛЬНОЕ'
            elif priority == 'MEDIUM':
                severity = 'ВАЖНОЕ' if change_percent > 50 else 'НЕЗНАЧИТЕЛЬНОЕ'
            else:
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
            'trend': trend,
            'feature': feature,
            'change_info': change_info
        }
    
    def analyze_batch(self, analysis_results: list) -> Optional[Dict]:
        """
        Batch-анализ трендов: если 2+ файла одной категории изменились,
        определить общий тренд и фичу.

        Args:
            analysis_results: Список результатов индивидуальных анализов

        Returns:
            Словарь {category: {trend, feature, context}} или None
        """
        if not self.client or len(analysis_results) < 2:
            return None

        # Группировать по категориям
        by_category = {}
        for result in analysis_results:
            cat = result.get('change_info', {}).get('category', 'unknown')
            if cat not in by_category:
                by_category[cat] = []
            by_category[cat].append(result)

        # Отфильтровать категории с 2+ изменениями
        multi_change_categories = {cat: items for cat, items in by_category.items() if len(items) >= 2}

        if not multi_change_categories:
            return None

        batch_results = {}

        for category, items in multi_change_categories.items():
            # Собрать описания для промпта
            descriptions = []
            for item in items:
                url = item.get('url', 'N/A')
                filename = url.split('/')[-1] if url else 'N/A'
                desc = item.get('description', 'Нет описания')
                descriptions.append(f"- {filename}: {desc}")

            descriptions_text = "\n".join(descriptions)

            prompt = f"""Эти {len(items)} файла категории "{category}" изменились одновременно:

{descriptions_text}

Ответь в JSON:
{{
  "trend": "общий тренд развития этой подсистемы Tilda",
  "feature": "какую фичу Tilda вероятно разрабатывает",
  "context": "краткое пояснение связи между изменениями"
}}"""

            try:
                self._wait_for_rate_limit()

                response = self.client.chat.completions.create(
                    model=config.OPENAI_MODEL,
                    messages=[
                        {"role": "system", "content": config.SYSTEM_PROMPT},
                        {"role": "user", "content": prompt}
                    ],
                    response_format={"type": "json_object"},
                    temperature=config.OPENAI_TEMPERATURE,
                    max_completion_tokens=500
                )

                content = response.choices[0].message.content
                data = json.loads(content)
                batch_results[category] = {
                    'trend': data.get('trend'),
                    'feature': data.get('feature'),
                    'context': data.get('context'),
                }

                logger.info(f"Batch-анализ для {category}: trend='{data.get('trend', 'N/A')}'")

            except Exception as e:
                logger.warning(f"Ошибка batch-анализа для {category}: {e}")
                continue

        return batch_results if batch_results else None

    def analyze_digest(self, digest_items: List[Dict]) -> Optional[Dict]:
        """
        LLM-анализ дневной сводки: общая картина, тренды, рекомендации.
        Получает список всех дневных изменений и создаёт осмысленную сводку.
        """
        if not self.client or not digest_items:
            return None

        # Собрать контекст всех изменений дня
        changes_text = []
        for item in digest_items:
            category = item.get('category', 'unknown')
            severity = item.get('severity', '')
            desc = item.get('description', '')
            impact = item.get('user_impact', '')
            filename = (item.get('title') or '').split(' - ')[0]

            entry = f"- [{category}/{severity}] {filename}: {desc}"
            if impact:
                entry += f" | Влияние: {impact}"
            changes_text.append(entry)

        prompt = f"""За последние 24 часа в Tilda CDN обнаружено {len(digest_items)} изменений:

{chr(10).join(changes_text)}

Создай СВОДКУ ДНЯ для менеджеров."""

        try:
            self._wait_for_rate_limit()
            response = self.client.chat.completions.create(
                model=config.OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": config.DIGEST_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt}
                ],
                response_format={"type": "json_object"},
                temperature=config.OPENAI_TEMPERATURE,
                max_completion_tokens=config.OPENAI_DIGEST_MAX_TOKENS
            )
            content = response.choices[0].message.content
            data = json.loads(content)

            logger.info("LLM дайджест-анализ завершён")

            return {
                'summary': data.get('summary', ''),
                'highlights': data.get('highlights', []),
                'trend': data.get('trend'),
                'attention': data.get('attention'),
            }
        except Exception as e:
            logger.warning(f"Ошибка LLM-анализа дайджеста: {e}")
            return None

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



