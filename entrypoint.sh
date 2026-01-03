#!/bin/bash
set -e

# ============================================
# Tilda Update Checker - Entrypoint Script
# ============================================

echo "============================================"
echo "Tilda Update Checker - Инициализация"
echo "============================================"

# Функция логирования
log_info() {
    echo "[INFO] $1"
}

log_error() {
    echo "[ERROR] $1" >&2
}

log_warning() {
    echo "[WARNING] $1"
}

# ============================================
# 1. Проверка и создание необходимых директорий
# ============================================
log_info "Проверка директорий..."

mkdir -p /app/data /app/logs

# Проверка прав доступа
if [ ! -w /app/data ]; then
    log_error "Нет прав на запись в /app/data"
    exit 1
fi

if [ ! -w /app/logs ]; then
    log_error "Нет прав на запись в /app/logs"
    exit 1
fi

log_info "✓ Директории готовы"

# ============================================
# 2. Валидация конфигурации
# ============================================
log_info "Валидация конфигурации..."

# Проверка Python версии
python_version=$(python --version 2>&1 | awk '{print $2}')
log_info "Python версия: $python_version"

# Проверка наличия config.py
if [ ! -f /app/config.py ]; then
    log_error "Файл config.py не найден!"
    exit 1
fi

# Проверка наличия main.py
if [ ! -f /app/main.py ]; then
    log_error "Файл main.py не найден!"
    exit 1
fi

log_info "✓ Конфигурация валидна"

# ============================================
# 3. Проверка переменных окружения
# ============================================
log_info "Проверка переменных окружения..."

# Опциональные API ключи - только предупреждения
if [ -z "$OPENAI_API_KEY" ]; then
    log_warning "OPENAI_API_KEY не установлен - LLM анализ будет недоступен"
fi

if [ -z "$TELEGRAM_BOT_TOKEN" ] || [ -z "$TELEGRAM_CHAT_ID" ]; then
    log_warning "Telegram credentials не установлены - уведомления будут недоступны"
fi

log_info "✓ Проверка переменных окружения завершена"

# ============================================
# 4. Инициализация базы данных
# ============================================
log_info "Инициализация базы данных..."

DB_FILE="/app/data/tilda_checker.db"

if [ -f "$DB_FILE" ]; then
    log_info "База данных существует: $DB_FILE"
    
    # Проверка целостности БД
    if python -c "from src.database import db; db.init_db()" 2>/dev/null; then
        log_info "✓ База данных валидна"
    else
        log_warning "База данных требует миграции"
        # Попытка миграции
        python -c "from src.database import db; db.init_db()" || {
            log_error "Не удалось мигрировать базу данных"
            exit 1
        }
        log_info "✓ Миграция завершена"
    fi
else
    log_info "Создание новой базы данных..."
    python -c "from src.database import db; db.init_db()" || {
        log_error "Не удалось создать базу данных"
        exit 1
    }
    log_info "✓ База данных создана: $DB_FILE"
fi

# ============================================
# 5. Вывод информации о конфигурации
# ============================================
echo ""
echo "============================================"
echo "Конфигурация:"
echo "============================================"
echo "Database:    ${DATABASE_PATH:-data/tilda_checker.db}"
echo "Log file:    ${LOG_FILE:-logs/tilda_checker.log}"
echo "Log level:   ${LOG_LEVEL:-INFO}"
echo "Check interval: ${TILDA_CHECK_INTERVAL:-3600} sec"
echo "OpenAI API:  ${OPENAI_API_KEY:+Настроен}${OPENAI_API_KEY:-Не настроен}"
echo "Telegram:    ${TELEGRAM_BOT_TOKEN:+Настроен}${TELEGRAM_BOT_TOKEN:-Не настроен}"
echo "Timezone:    ${TZ:-UTC}"
echo "============================================"
echo ""

# ============================================
# 6. Healthcheck helper
# ============================================
# Создать простой файл для healthcheck
touch /app/.healthy

# ============================================
# 7. Запуск приложения
# ============================================
log_info "Запуск приложения с аргументами: $@"
echo "============================================"
echo ""

# Передать все аргументы в main.py
exec python /app/main.py "$@"



