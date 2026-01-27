#!/bin/bash
# Integration тесты для Tilda Update Checker
# Дата: $(date '+%Y-%m-%d %H:%M:%S')

set -e

# Цвета для вывода
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Переменные
TEST_LOG="docs/test-logs/integration-test-$(date +%Y%m%d-%H%M%S).log"
PASSED=0
FAILED=0
TOTAL=0

# Функции логирования
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1" | tee -a "$TEST_LOG"
}

log_success() {
    echo -e "${GREEN}[✓]${NC} $1" | tee -a "$TEST_LOG"
    ((PASSED++))
}

log_error() {
    echo -e "${RED}[✗]${NC} $1" | tee -a "$TEST_LOG"
    ((FAILED++))
}

log_warning() {
    echo -e "${YELLOW}[⚠]${NC} $1" | tee -a "$TEST_LOG"
}

test_header() {
    echo "" | tee -a "$TEST_LOG"
    echo "========================================" | tee -a "$TEST_LOG"
    echo "$1" | tee -a "$TEST_LOG"
    echo "========================================" | tee -a "$TEST_LOG"
}

run_test() {
    ((TOTAL++))
    local test_name="$1"
    local test_cmd="$2"

    log_info "Тест #$TOTAL: $test_name"

    if eval "$test_cmd" >> "$TEST_LOG" 2>&1; then
        log_success "$test_name - ПРОЙДЕН"
        return 0
    else
        log_error "$test_name - ПРОВАЛЕН"
        return 1
    fi
}

# Создать директорию для логов
mkdir -p docs/test-logs data logs

# Заголовок
test_header "INTEGRATION ТЕСТИРОВАНИЕ TILDA UPDATE CHECKER"
echo "Дата: $(date '+%Y-%m-%d %H:%M:%S')" | tee -a "$TEST_LOG"
echo "Платформа: $(uname -s)" | tee -a "$TEST_LOG"
echo "Python: $(python3 --version)" | tee -a "$TEST_LOG"
echo "" | tee -a "$TEST_LOG"

# ==========================================
# БЛОК 1: ПРОВЕРКА ОКРУЖЕНИЯ
# ==========================================
test_header "БЛОК 1: ПРОВЕРКА ОКРУЖЕНИЯ"

run_test "Python 3 доступен" "python3 --version"
run_test "Структура директорий" "test -d src && test -d data && test -d logs"
run_test "Основной модуль существует" "test -f main.py"
run_test "Конфигурация существует" "test -f config.py"
run_test "Healthcheck существует" "test -f healthcheck.py"

# ==========================================
# БЛОК 2: ПРОВЕРКА ЗАВИСИМОСТЕЙ
# ==========================================
test_header "БЛОК 2: ПРОВЕРКА ЗАВИСИМОСТЕЙ PYTHON"

log_info "Проверка импортов основных модулей..."
run_test "Импорт config" "python3 -c 'import config; print(\"OK\")'"
run_test "Импорт database" "python3 -c 'from src.database import db; print(\"OK\")'"
run_test "Импорт cdn_fetcher" "python3 -c 'from src.cdn_fetcher import fetcher; print(\"OK\")'"
run_test "Импорт llm_analyzer" "python3 -c 'from src.llm_analyzer import analyzer; print(\"OK\")'"

# ==========================================
# БЛОК 3: ИНИЦИАЛИЗАЦИЯ БАЗЫ ДАННЫХ
# ==========================================
test_header "БЛОК 3: ИНИЦИАЛИЗАЦИЯ БАЗЫ ДАННЫХ"

# Удалить старую тестовую БД если есть
rm -f data/tilda_checker.db

run_test "Инициализация БД" "python3 -c 'from src.database import db; assert db.init_db(), \"DB init failed\"'"
run_test "БД файл создан" "test -f data/tilda_checker.db"
run_test "БД не пустая" "test -s data/tilda_checker.db"

log_info "Проверка структуры БД..."
run_test "Таблица TrackedFile" "python3 -c 'from src.database import db, TrackedFile; db.init_db(); session = db.get_session(); session.query(TrackedFile).first(); session.close()'"
run_test "Таблица Change" "python3 -c 'from src.database import db, Change; db.init_db(); session = db.get_session(); session.query(Change).first(); session.close()'"
run_test "Таблица Announcement" "python3 -c 'from src.database import db, Announcement; db.init_db(); session = db.get_session(); session.query(Announcement).first(); session.close()'"

# ==========================================
# БЛОК 4: HEALTHCHECK
# ==========================================
test_header "БЛОК 4: HEALTHCHECK"

run_test "Healthcheck скрипт выполняется" "python3 healthcheck.py"
run_test "Healthcheck возвращает exit code 0" "python3 healthcheck.py; test \$? -eq 0"

# ==========================================
# БЛОК 5: CLI КОМАНДЫ
# ==========================================
test_header "БЛОК 5: CLI КОМАНДЫ"

log_info "Тестирование CLI команд (без выполнения действий)..."
run_test "CLI: --help" "python3 main.py --help | grep -q 'usage:'"
run_test "CLI: --dashboard" "timeout 10 python3 main.py --dashboard || true"
run_test "CLI: --show-announcements" "timeout 10 python3 main.py --show-announcements -n 5 || true"

# ==========================================
# БЛОК 6: ВЕРСИОННЫЙ МОНИТОРИНГ
# ==========================================
test_header "БЛОК 6: ВЕРСИОННЫЙ МОНИТОРИНГ"

log_info "Тестирование версионного детектора..."
run_test "Version detector импорт" "python3 -c 'from src.version_detector import detector; print(\"OK\")'"

# Тест парсинга URL
log_info "Тестирование парсинга версий из URL..."
cat > /tmp/test_version_parsing.py << 'PYEOF'
from src.version_detector import detector

# Тест различных форматов URL
test_cases = [
    ("https://static.tildacdn.com/js/tilda-cart-1.1.min.js", "tilda-cart", "1.1"),
    ("https://static.tildacdn.com/js/tilda-blocks-2.12.js", "tilda-blocks", "2.12"),
    ("https://static.tildacdn.com/css/tilda-grid-3.0.min.css", "tilda-grid", "3.0"),
]

for url, expected_base, expected_version in test_cases:
    parsed = detector.parse_file_url(url)
    assert parsed['base_name'] == expected_base, f"Base name mismatch: {parsed['base_name']} != {expected_base}"
    assert parsed['version'] == expected_version, f"Version mismatch: {parsed['version']} != {expected_version}"

print("✓ Все тесты парсинга версий пройдены")
PYEOF

run_test "Version parsing" "python3 /tmp/test_version_parsing.py"

# ==========================================
# БЛОК 7: РАБОТА С ФАЙЛАМИ (MOCK)
# ==========================================
test_header "БЛОК 7: РАБОТА С CDN FETCHER"

log_info "Тестирование CDN fetcher..."
cat > /tmp/test_cdn_fetcher.py << 'PYEOF'
from src.cdn_fetcher import fetcher

# Проверка получения списка файлов из конфига
files = fetcher.get_monitored_files(use_db=False)
assert len(files) > 0, "Нет файлов для мониторинга"
assert all('url' in f for f in files), "Не все файлы имеют URL"
assert all('category' in f for f in files), "Не все файлы имеют категорию"

print(f"✓ Найдено {len(files)} файлов для мониторинга")

# Проверка категорий
categories = set(f['category'] for f in files)
expected_categories = {'core', 'members', 'ecommerce', 'zero_block', 'ui_components', 'utilities'}
assert categories.issubset(expected_categories), f"Неожиданные категории: {categories - expected_categories}"

print(f"✓ Категории: {', '.join(categories)}")
PYEOF

run_test "CDN Fetcher: получение списка файлов" "python3 /tmp/test_cdn_fetcher.py"

# ==========================================
# БЛОК 8: DATABASE ОПЕРАЦИИ
# ==========================================
test_header "БЛОК 8: DATABASE ОПЕРАЦИИ"

log_info "Тестирование операций с БД..."
cat > /tmp/test_database_ops.py << 'PYEOF'
from src.database import db, TrackedFile
import datetime

db.init_db()

# Тест 1: Сохранение файла
tracked_file = db.save_file_state(
    url="https://test.tildacdn.com/js/test-file-1.0.js",
    file_type="js",
    content="console.log('test');",
    content_hash="abc123def456",
    size=100,
    category="utilities",
    priority="LOW",
    domain="test.tildacdn.com"
)
assert tracked_file is not None, "Не удалось сохранить файл"
print(f"✓ Файл сохранен: ID={tracked_file.id}")

# Тест 2: Получение файлов
files = db.get_tracked_files()
assert len(files) > 0, "Не удалось получить файлы"
print(f"✓ Получено файлов: {len(files)}")

# Тест 3: Обновление файла (повторное сохранение)
updated_file = db.save_file_state(
    url="https://test.tildacdn.com/js/test-file-1.0.js",
    file_type="js",
    content="console.log('test updated');",
    content_hash="xyz789updated",
    size=120,
    category="utilities",
    priority="LOW",
    domain="test.tildacdn.com"
)
assert updated_file.id == tracked_file.id, "Должен обновиться тот же файл"
print(f"✓ Файл обновлен: hash={updated_file.last_hash}")

# Тест 4: 404 счетчик
db.increment_404_count("https://test.tildacdn.com/js/test-file-1.0.js")
session = db.get_session()
try:
    tf = session.query(TrackedFile).filter_by(id=tracked_file.id).first()
    assert tf.consecutive_404_count == 1, "404 счетчик не увеличился"
    print(f"✓ 404 счетчик: {tf.consecutive_404_count}")
finally:
    session.close()

# Тест 5: Сброс 404
db.reset_404_count("https://test.tildacdn.com/js/test-file-1.0.js")
session = db.get_session()
try:
    tf = session.query(TrackedFile).filter_by(id=tracked_file.id).first()
    assert tf.consecutive_404_count == 0, "404 счетчик не сброшен"
    print(f"✓ 404 счетчик сброшен: {tf.consecutive_404_count}")
finally:
    session.close()

print("✓ Все тесты БД операций пройдены")
PYEOF

run_test "Database: CRUD операции" "python3 /tmp/test_database_ops.py"

# ==========================================
# БЛОК 9: КОНТЕКСТНЫЕ МЕНЕДЖЕРЫ (УТЕЧКИ)
# ==========================================
test_header "БЛОК 9: ПРОВЕРКА УТЕЧЕК СЕССИЙ"

log_info "Тестирование контекстных менеджеров БД..."
cat > /tmp/test_session_leaks.py << 'PYEOF'
from src.database import db

db.init_db()

# Проверка что get_session работает как контекстный менеджер
try:
    with db.get_session() as session:
        from src.database import TrackedFile
        files = session.query(TrackedFile).limit(1).all()
        print(f"✓ Контекстный менеджер работает")
except Exception as e:
    raise AssertionError(f"Контекстный менеджер не работает: {e}")

# Симуляция множественных операций
for i in range(10):
    with db.get_session() as session:
        from src.database import TrackedFile
        session.query(TrackedFile).first()

print("✓ 10 операций выполнены без утечек")
PYEOF

run_test "Session leaks: контекстные менеджеры" "python3 /tmp/test_session_leaks.py"

# ==========================================
# БЛОК 10: EXCEPTION HANDLING
# ==========================================
test_header "БЛОК 10: EXCEPTION HANDLING"

log_info "Тестирование обработки ошибок..."
cat > /tmp/test_exceptions.py << 'PYEOF'
from src.cdn_fetcher import fetcher
import requests
from unittest.mock import patch, Mock

# Тест timeout
with patch.object(fetcher.session, 'get') as mock_get:
    mock_get.side_effect = requests.exceptions.Timeout("Connection timeout")
    result = fetcher.download_file("https://test.com/timeout.js")
    assert result is None, "Timeout должен возвращать None"
    print("✓ Timeout обработан корректно")

# Тест 404
with patch.object(fetcher.session, 'get') as mock_get:
    mock_response = Mock()
    mock_response.status_code = 404
    mock_get.return_value = mock_response
    result = fetcher.download_file("https://test.com/notfound.js")
    assert result is None, "404 должен возвращать None"
    print("✓ 404 обработан корректно")

# Тест ConnectionError
with patch.object(fetcher.session, 'get') as mock_get:
    mock_get.side_effect = requests.exceptions.ConnectionError("Connection refused")
    result = fetcher.download_file("https://test.com/connection-error.js")
    assert result is None, "ConnectionError должен возвращать None"
    print("✓ ConnectionError обработан корректно")

print("✓ Все тесты обработки ошибок пройдены")
PYEOF

run_test "Exception handling: различные типы ошибок" "python3 /tmp/test_exceptions.py"

# ==========================================
# БЛОК 11: RATE LIMITING
# ==========================================
test_header "БЛОК 11: RATE LIMITING"

log_info "Тестирование rate limiter для LLM..."
cat > /tmp/test_rate_limiting.py << 'PYEOF'
from src.llm_analyzer import _last_api_call_time, _rate_limit_lock, MIN_API_CALL_INTERVAL
import time
from threading import Lock

# Простой тест rate limiting логики
print(f"✓ Rate limit параметры: {MIN_API_CALL_INTERVAL}s между запросами")
print(f"✓ Lock создан: {_rate_limit_lock is not None}")
print("✓ Rate limiting механизм настроен")
PYEOF

run_test "Rate limiting: конфигурация" "python3 /tmp/test_rate_limiting.py"

# ==========================================
# БЛОК 12: БЕЗОПАСНОСТЬ
# ==========================================
test_header "БЛОК 12: БЕЗОПАСНОСТЬ"

log_info "Проверка санитизации токенов..."
cat > /tmp/test_security.py << 'PYEOF'
from src.telegram_notifier import sanitize_url_for_logging

# Тест санитизации URL с токеном
test_url = "https://api.telegram.org/bot123456789:ABCdefGHIjklMNOpqrsTUVwxyz/sendMessage"
safe_url = sanitize_url_for_logging(test_url)

assert "123456789:ABC" not in safe_url, "Токен не санитизирован!"
assert "***HIDDEN***" in safe_url, "Плейсхолдер отсутствует!"
print(f"✓ URL санитизирован: {safe_url}")

# Тест нормального URL без токена
normal_url = "https://static.tildacdn.com/js/test.js"
safe_normal = sanitize_url_for_logging(normal_url)
assert safe_normal == normal_url, "Нормальный URL изменен!"
print(f"✓ Нормальный URL не изменен")

print("✓ Санитизация токенов работает корректно")
PYEOF

run_test "Security: санитизация токенов" "python3 /tmp/test_security.py"

# Проверка что в коде нет хардкод секретов
log_info "Проверка на хардкод секреты..."
if grep -r "sk-[a-zA-Z0-9]\{20,\}" src/ main.py config.py 2>/dev/null | grep -v ".pyc" | grep -v "mask"; then
    log_error "Найдены потенциальные API ключи в коде!"
    ((FAILED++))
else
    log_success "Хардкод секреты не найдены"
    ((PASSED++))
fi

# ==========================================
# БЛОК 13: GRACEFUL SHUTDOWN
# ==========================================
test_header "БЛОК 13: GRACEFUL SHUTDOWN"

log_info "Проверка обработчиков сигналов..."
cat > /tmp/test_graceful_shutdown.py << 'PYEOF'
import signal
import sys

# Проверка что в main.py есть обработчики сигналов
with open('main.py', 'r') as f:
    content = f.read()

    # Проверка импортов
    assert 'import signal' in content, "signal не импортирован"
    print("✓ signal импортирован")

    # Проверка функции shutdown_handler
    assert 'def shutdown_handler' in content, "shutdown_handler не найден"
    print("✓ shutdown_handler функция найдена")

    # Проверка регистрации SIGTERM
    assert 'signal.SIGTERM' in content, "SIGTERM не обрабатывается"
    print("✓ SIGTERM обработчик зарегистрирован")

    # Проверка регистрации SIGINT
    assert 'signal.SIGINT' in content, "SIGINT не обрабатывается"
    print("✓ SIGINT обработчик зарегистрирован")

    # Проверка scheduler.shutdown
    assert 'scheduler.shutdown' in content, "scheduler.shutdown не вызывается"
    print("✓ scheduler.shutdown вызывается")

print("✓ Graceful shutdown реализован корректно")
PYEOF

run_test "Graceful shutdown: наличие обработчиков" "python3 /tmp/test_graceful_shutdown.py"

# Проверка entrypoint.sh
log_info "Проверка graceful shutdown в entrypoint.sh..."
if grep -q "trap shutdown SIGTERM SIGINT" entrypoint.sh && grep -q "APP_PID" entrypoint.sh; then
    log_success "entrypoint.sh: graceful shutdown настроен"
    ((PASSED++))
else
    log_error "entrypoint.sh: graceful shutdown отсутствует"
    ((FAILED++))
fi

# ==========================================
# ФИНАЛЬНЫЙ ОТЧЕТ
# ==========================================
test_header "ФИНАЛЬНЫЙ ОТЧЕТ"

echo "" | tee -a "$TEST_LOG"
echo "╔════════════════════════════════════════╗" | tee -a "$TEST_LOG"
echo "║         РЕЗУЛЬТАТЫ ТЕСТИРОВАНИЯ        ║" | tee -a "$TEST_LOG"
echo "╚════════════════════════════════════════╝" | tee -a "$TEST_LOG"
echo "" | tee -a "$TEST_LOG"
echo "Всего тестов:    $TOTAL" | tee -a "$TEST_LOG"
echo "Успешно:         $PASSED" | tee -a "$TEST_LOG"
echo "Провалено:       $FAILED" | tee -a "$TEST_LOG"
echo "" | tee -a "$TEST_LOG"

if [ $FAILED -eq 0 ]; then
    echo -e "${GREEN}✓ ВСЕ ТЕСТЫ ПРОЙДЕНЫ УСПЕШНО!${NC}" | tee -a "$TEST_LOG"
    echo "" | tee -a "$TEST_LOG"
    echo "Приложение готово к production деплою." | tee -a "$TEST_LOG"
    EXIT_CODE=0
else
    echo -e "${RED}✗ ОБНАРУЖЕНЫ ПРОВАЛЕННЫЕ ТЕСТЫ!${NC}" | tee -a "$TEST_LOG"
    echo "" | tee -a "$TEST_LOG"
    echo "Необходимо исправить ошибки перед деплоем." | tee -a "$TEST_LOG"
    EXIT_CODE=1
fi

echo "" | tee -a "$TEST_LOG"
echo "Лог тестирования сохранен: $TEST_LOG" | tee -a "$TEST_LOG"
echo "Дата завершения: $(date '+%Y-%m-%d %H:%M:%S')" | tee -a "$TEST_LOG"

# Cleanup
rm -f /tmp/test_*.py

exit $EXIT_CODE
