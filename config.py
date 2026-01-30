"""
Конфигурация приложения
"""
import os
from pathlib import Path
from dotenv import load_dotenv

# Загрузить переменные окружения
load_dotenv()

# Базовая директория проекта
BASE_DIR = Path(__file__).parent

# OpenAI Configuration
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5")  # GPT-5 - самая мощная модель 2026
OPENAI_TEMPERATURE = float(os.getenv("OPENAI_TEMPERATURE", "0.3"))
OPENAI_MAX_TOKENS = int(os.getenv("OPENAI_MAX_TOKENS", "3000"))  # Увеличено с 500 до 3000

# Database Configuration
DATABASE_PATH = os.getenv("DATABASE_PATH", "data/tilda_checker.db")
DATABASE_URL = f"sqlite:///{BASE_DIR / DATABASE_PATH}"

# Monitoring Configuration
TILDA_CHECK_INTERVAL = int(os.getenv("TILDA_CHECK_INTERVAL", "3600"))  # секунды

# Logging Configuration
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_FILE = os.getenv("LOG_FILE", "logs/tilda_checker.log")

# Список файлов Tilda для мониторинга с категоризацией
TILDA_MONITORED_FILES = {
    "core": {
        "priority": "CRITICAL",
        "files": [
            "https://neo.tildacdn.com/js/tilda-fallback-1.0.min.js",
            "https://static.tildacdn.com/js/tilda-scripts-3.0.min.js",
            "https://static.tildacdn.com/js/tilda-scripts-2.8.min.js",  # Legacy
            "https://static.tildacdn.com/css/tilda-grid-3.0.min.css",
            "https://static.tildacdn.com/js/tilda-cover-1.0.min.js",
            "https://static.tildacdn.com/css/tilda-cover-1.0.min.css",
            "https://static.tildacdn.com/js/tilda-animation-1.0.min.js",
            "https://static.tildacdn.com/js/tilda-animation-2.0.min.js",
            "https://static.tildacdn.com/css/tilda-animation-1.0.min.css",
            "https://static.tildacdn.com/css/tilda-animation-2.0.min.css",
            "https://static.tildacdn.com/js/tilda-forms-1.0.min.js",
            "https://static.tildacdn.com/css/tilda-forms-1.0.min.css",
            "https://static.tildacdn.com/js/tilda-lazyload-1.0.min.js",
            "https://static.tildacdn.com/js/tilda-events-1.0.min.js",
            "https://static.tildacdn.com/js/jquery-1.10.2.min.js",
            "https://static.tildacdn.com/js/hammer.min.js",
        ]
    },
    "members": {
        "priority": "CRITICAL",
        "files": [
            "https://members.tildaapi.com/frontend/js/tilda-members-scripts.min.js",
            "https://members.tildaapi.com/frontend/js/tilda-members-userbar.min.js",
            "https://members.tildaapi.com/frontend/js/tilda-members-userbar-dict.min.js",
            "https://members.tildaapi.com/frontend/js/tilda-members-profile.min.js",
            "https://members.tildaapi.com/frontend/js/tilda-members-store-profile.min.js",
            "https://members.tildaapi.com/frontend/js/tilda-members-sign.min.js",
            "https://members.tildaapi.com/frontend/js/tilda-members-sign-dict.min.js",
            "https://members.tildaapi.com/frontend/css/tilda-members-styles.min.css",
            "https://members.tildaapi.com/frontend/css/tilda-members-popup.min.css",
            "https://members.tildaapi.com/frontend/css/tilda-members-resetpage.min.css",
            "https://members.tildaapi.com/frontend/css/tilda-members-userbar.min.css",
            "https://members.tildaapi.com/frontend/css/tilda-members-sign.min.css",
            "https://members2.tildacdn.com/frontend/js/tilda-members-init.min.js",
            "https://members2.tildacdn.com/frontend/js/tilda-members-sign.min.js",
            "https://members2.tildacdn.com/frontend/js/tilda-members-sign-dict.min.js",
            "https://members2.tildacdn.com/frontend/css/tilda-members-base.min.css",
        ]
    },
    "ecommerce": {
        "priority": "HIGH",
        "files": [
            "https://static.tildacdn.com/js/tilda-catalog-1.1.min.js",
            "https://static.tildacdn.com/css/tilda-catalog-1.1.min.css",
            "https://static.tildacdn.com/js/tilda-cart-1.1.min.js",
            "https://static.tildacdn.com/css/tilda-cart-1.0.min.css",
            "https://static.tildacdn.com/js/tilda-cart-discounts-1.0.min.js",
            "https://static.tildacdn.com/css/tilda-cart-discounts-1.0.min.css",
            "https://static.tildacdn.com/js/tilda-products-1.0.min.js",
            "https://static.tildacdn.com/js/tilda-wishlist-1.0.min.js",
            "https://static.tildacdn.com/css/tilda-wishlist-1.0.min.css",
            "https://static.tildacdn.com/js/tilda-variant-select-1.0.min.js",
            "https://static.tildacdn.com/css/tilda-catalog-filters-1.0.min.css",
            "https://static.tildacdn.com/js/tilda-range-1.0.min.js",
            "https://static.tildacdn.com/css/tilda-range-1.0.min.css",
        ]
    },
    "zero_block": {
        "priority": "HIGH",
        "files": [
            "https://static.tildacdn.com/js/tilda-zero-1.1.min.js",
            "https://static.tildacdn.com/js/tilda-zero-1.0.min.js",  # Legacy
            "https://static.tildacdn.com/js/tilda-zero-scale-1.0.min.js",
            "https://static.tildacdn.com/js/tilda-zero-forms-1.0.min.js",
            "https://static.tildacdn.com/js/tilda-zero-gallery-1.0.min.js",
            "https://static.tildacdn.com/js/tilda-zero-tooltip-1.0.min.js",
            "https://static.tildacdn.com/js/tilda-animation-sbs-1.0.min.js",
            "https://static.tildacdn.com/css/tilda-zero-form-errorbox.min.css",
        ]
    },
    "ui_components": {
        "priority": "MEDIUM",
        "files": [
            "https://static.tildacdn.com/js/tilda-quiz-form-1.0.min.js",
            "https://static.tildacdn.com/css/tilda-quiz-form-1.1.min.css",
            "https://static.tildacdn.com/js/tilda-cards-1.0.min.js",
            "https://static.tildacdn.com/css/tilda-cards-1.0.min.css",
            "https://static.tildacdn.com/js/tilda-t410-beforeafter-1.0.min.js",
            "https://static.tildacdn.com/css/tilda-t410-beforeafter-1.0.min.css",
            "https://static.tildacdn.com/js/tilda-img-select-1.0.min.js",
            "https://static.tildacdn.com/css/tilda-img-select-1.0.min.css",
            "https://static.tildacdn.com/js/tilda-t994-stories-1.0.min.js",
            "https://static.tildacdn.com/js/tilda-t937-videoplaylist-1.0.min.js",
            "https://static.tildacdn.com/js/tilda-t431-table-1.0.min.js",
            "https://static.tildacdn.com/js/tilda-menu-1.1.min.js",
            "https://static.tildacdn.com/js/tilda-menu-1.0.min.js",  # Legacy
            "https://static.tildacdn.com/js/tilda-menu-burger-1.0.min.js",
            "https://static.tildacdn.com/css/tilda-menu-burger-1.0.min.css",
            "https://static.tildacdn.com/js/tilda-menusub-1.0.min.js",
            "https://static.tildacdn.com/css/tilda-menusub-1.0.min.css",
            "https://static.tildacdn.com/js/tilda-slider-1.0.min.js",
            "https://static.tildacdn.com/js/tilda-slds-1.4.min.js",
            "https://static.tildacdn.com/css/tilda-slds-1.4.min.css",
            "https://static.tildacdn.com/js/tilda-popup-1.0.min.js",
            "https://static.tildacdn.com/css/tilda-popup-1.1.min.css",
            "https://static.tildacdn.com/js/tilda-zoom-2.0.min.js",
            "https://static.tildacdn.com/css/tilda-zoom-2.0.min.css",
            "https://static.tildacdn.com/js/tilda-video-1.0.min.js",
            "https://static.tildacdn.com/js/tilda-video-processor-1.0.min.js",
        ]
    },
    "utilities": {
        "priority": "LOW",
        "files": [
            "https://static.tildacdn.com/js/tilda-phone-mask-1.1.min.js",
            "https://static.tildacdn.com/js/tilda-conditional-form-1.0.min.js",
            "https://static.tildacdn.com/js/tilda-forms-payments-1.0.min.js",
            "https://static.tildacdn.com/js/tilda-ratescale-1.0.min.js",
            "https://static.tildacdn.com/js/tilda-step-manager-1.0.min.js",
            "https://static.tildacdn.com/js/tilda-widget-positions-1.0.min.js",
            "https://static.tildacdn.com/js/tilda-lk-dashboard-1.0.min.js",
            "https://static.tildacdn.com/js/tilda-skiplink-1.0.min.js",
            "https://static.tildacdn.com/js/tilda-stat-1.0.min.js",
            "https://static.tildacdn.com/js/tilda-errors-1.0.min.js",
            "https://static.tildacdn.com/js/tilda-performance-1.0.min.js",
            "https://static.tildacdn.com/js/tilda-table-editor.min.js",
            "https://static.tildacdn.com/css/tilda-table-editor.min.css",
            "https://static.tildacdn.com/js/tilda-paint-icons.min.js",
            "https://static.tildacdn.com/css/tilda-redactor-1.0.min.css",
            "https://static.tildacdn.com/js/highlight.min.js",
            "https://static.tildacdn.com/css/highlight.min.css",
            "https://static.tildacdn.com/js/ya-share.js",
            "https://static.tildacdn.com/js/masonry-imagesloaded.min.js",
            "https://static.tildacdn.com/css/tilda-menu-widgeticons-1.0.min.css",
            "https://static.tildacdn.com/js/tilda-menu-widgeticons-1.0.min.js",
        ]
    }
}

# Backwards compatibility - старое имя для совместимости
TILDA_CORE_FILES = []
for category_data in TILDA_MONITORED_FILES.values():
    TILDA_CORE_FILES.extend(category_data["files"])

# HTTP Configuration
REQUEST_TIMEOUT = 30  # секунды
REQUEST_RETRY_COUNT = 3
REQUEST_RETRY_DELAY = 5  # секунды
USER_AGENT = "Mozilla/5.0 (compatible; TildaUpdateChecker/1.0)"

# LLM Analysis Configuration
MAX_DIFF_TOKENS = 5000  # Увеличено с 2000 до 5000 для подробного контекста
MIN_CHANGE_SIZE = 10  # Минимальный размер изменения в байтах для анализа

# Промпты для LLM
SYSTEM_PROMPT = """Ты эксперт-аналитик по frontend-разработке и конструкторам сайтов с глубокими знаниями JavaScript, CSS и экосистемы Tilda.

ТВОИ НАВЫКИ:
- Анализ JavaScript и CSS кода (включая минифицированный)
- Понимание архитектуры Tilda (корзина, личный кабинет, Zero Block, формы)
- Выявление breaking changes и backward compatibility
- Оценка влияния изменений на production сайты

ТВОЯ ЗАДАЧА:
- Анализировать изменения в коде Tilda CDN файлов
- Создавать КОНКРЕТНЫЕ анонсы с реальными примерами из кода
- НЕ использовать обобщения типа "улучшена производительность" без деталей
- Если видишь изменение функции - НАЗОВИ её по имени
- Если видишь новый параметр - УКАЖИ его
- Если не понятно из минифицированного кода - ЧЕСТНО признай это

ФОРМАТ ОТВЕТА:
Строго JSON. Все поля обязательны.

ПРИМЕРЫ ХОРОШИХ ОПИСАНИЙ:
✅ "Добавлена функция t_cart__applyPromoCode() для обработки промокодов"
✅ "Исправлен баг в t_members__validateSession() - теперь корректно проверяется expiration"
✅ "Изменен API метода initCart() - добавлен параметр discountRules"
✅ "В функции t_zero__renderBlock() изменена логика инициализации lazy-loading изображений"

ПРИМЕРЫ ПЛОХИХ ОПИСАНИЙ:
❌ "Улучшена производительность корзины"
❌ "Оптимизация кода"
❌ "Мелкие исправления"

Отвечай строго в формате JSON."""

USER_PROMPT_TEMPLATE = """Проанализируй изменения в файле конструктора Tilda.

Файл: {file_url}
Размер изменения: {change_size} байт

Метаданные изменения:
- Изменение размера файла: {size_diff} байт
- Процент изменения: {change_percent}%

Статистика:
{change_stats}

Задачи:
1. Определи, что конкретно изменилось (новая функция, исправление, оптимизация, изменение API)
2. Оцени значимость: КРИТИЧЕСКОЕ / ВАЖНОЕ / НЕЗНАЧИТЕЛЬНОЕ
3. Опиши влияние на пользователей Tilda простым языком
4. Дай рекомендации разработчикам (если нужны действия)

Ответ СТРОГО в JSON формате:
{{
  "change_type": "тип изменения",
  "severity": "КРИТИЧЕСКОЕ/ВАЖНОЕ/НЕЗНАЧИТЕЛЬНОЕ",
  "description": "краткое описание изменений",
  "user_impact": "влияние на пользователей",
  "recommendations": "рекомендации или 'Действий не требуется'"
}}
"""



