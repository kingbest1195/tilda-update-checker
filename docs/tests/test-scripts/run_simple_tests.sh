#!/bin/bash
# Упрощенное тестирование Tilda Update Checker
# Продолжает работу даже при ошибках

LOGFILE="docs/test-logs/simple-test-$(date +%Y%m%d-%H%M%S).log"
PASSED=0
FAILED=0

log_test() {
    local name="$1"
    local cmd="$2"

    echo "========================================"  | tee -a "$LOGFILE"
    echo "ТЕСТ: $name" | tee -a "$LOGFILE"
    echo "========================================"  | tee -a "$LOGFILE"

    if eval "$cmd" >> "$LOGFILE" 2>&1; then
        echo "✅ ПРОЙДЕН: $name" | tee -a "$LOGFILE"
        ((PASSED++))
    else
        echo "❌ ПРОВАЛЕН: $name" | tee -a "$LOGFILE"
        ((FAILED++))
    fi
    echo "" | tee -a "$LOGFILE"
}

# Заголовок
echo "========================================" | tee "$LOGFILE"
echo "УПРОЩЕННОЕ INTEGRATION ТЕСТИРОВАНИЕ" | tee -a "$LOGFILE"
echo "Дата: $(date '+%Y-%m-%d %H:%M:%S')" | tee -a "$LOGFILE"
echo "========================================" | tee -a "$LOGFILE"
echo "" | tee -a "$LOGFILE"

# БЛОК 1: Импорты
log_test "Импорт config" "python3 -c 'import config'"
log_test "Импорт database" "python3 -c 'from src.database import db'"
log_test "Импорт cdn_fetcher" "python3 -c 'from src.cdn_fetcher import fetcher'"
log_test "Импорт llm_analyzer" "python3 -c 'from src.llm_analyzer import analyzer'"
log_test "Импорт telegram_notifier" "python3 -c 'from src.telegram_notifier import sanitize_url_for_logging'"

# БЛОК 2: Инициализация БД
log_test "Инициализация БД" "python3 -c 'from src.database import db; assert db.init_db()'"
log_test "БД файл существует" "test -f data/tilda_checker.db"
log_test "БД не пустая" "test -s data/tilda_checker.db"

# БЛОК 3: Healthcheck
log_test "Healthcheck выполняется" "python3 healthcheck.py"

# БЛОК 4: Version detector
log_test "Version detector" "python3 -c '
from src.version_detector import detector
parsed = detector.parse_file_url(\"https://static.tildacdn.com/js/tilda-cart-1.1.min.js\")
assert parsed[\"base_name\"] == \"tilda-cart\"
assert parsed[\"version\"] == \"1.1\"
print(\"Version parsing OK\")
'"

# БЛОК 5: Database операции
log_test "Database save_file_state" "python3 -c '
from src.database import db
db.init_db()
tf = db.save_file_state(
    url=\"https://test.com/test.js\",
    file_type=\"js\",
    content=\"test\",
    content_hash=\"abc123\",
    size=100
)
assert tf is not None
print(f\"File saved: ID={tf.id}\")
'"

log_test "Database get_tracked_files" "python3 -c '
from src.database import db
db.init_db()
files = db.get_tracked_files()
print(f\"Files: {len(files)}\")
'"

log_test "Database 404 counter" "python3 -c '
from src.database import db, TrackedFile
db.init_db()
db.increment_404_count(\"https://test.com/test.js\")
session = db.get_session()
try:
    tf = session.query(TrackedFile).filter_by(url=\"https://test.com/test.js\").first()
    print(f\"404 count: {tf.consecutive_404_count}\")
    assert tf.consecutive_404_count > 0
finally:
    session.close()
'"

# БЛОК 6: CDN Fetcher
log_test "CDN Fetcher get_monitored_files" "python3 -c '
from src.cdn_fetcher import fetcher
files = fetcher.get_monitored_files(use_db=False)
assert len(files) > 0
print(f\"Monitored files: {len(files)}\")
'"

# БЛОК 7: Безопасность
log_test "Token sanitization" "python3 -c '
from src.telegram_notifier import sanitize_url_for_logging
url = \"https://api.telegram.org/bot123:ABC/sendMessage\"
safe = sanitize_url_for_logging(url)
assert \"123:ABC\" not in safe
assert \"***HIDDEN***\" in safe
print(f\"Sanitized: {safe}\")
'"

# БЛОК 8: Exception handling
log_test "Exception handling (mock)" "python3 -c '
from src.cdn_fetcher import fetcher
import requests
from unittest.mock import patch, Mock

with patch.object(fetcher.session, \"get\") as mock_get:
    mock_get.side_effect = requests.exceptions.Timeout()
    result = fetcher.download_file(\"https://test.com/timeout.js\")
    assert result is None
    print(\"Timeout handled correctly\")
'"

# БЛОК 9: Graceful shutdown
log_test "Graceful shutdown in main.py" "grep -q 'def shutdown_handler' main.py && grep -q 'signal.SIGTERM' main.py"
log_test "Graceful shutdown in entrypoint.sh" "grep -q 'trap shutdown SIGTERM' entrypoint.sh"

# БЛОК 10: CLI команды
log_test "CLI --help" "python3 main.py --help | grep -q 'usage:'"
log_test "CLI --dashboard" "timeout 5 python3 main.py --dashboard 2>&1 | head -20"

# Финальный отчет
echo "" | tee -a "$LOGFILE"
echo "========================================" | tee -a "$LOGFILE"
echo "РЕЗУЛЬТАТЫ ТЕСТИРОВАНИЯ" | tee -a "$LOGFILE"
echo "========================================" | tee -a "$LOGFILE"
echo "Успешно: $PASSED" | tee -a "$LOGFILE"
echo "Провалено: $FAILED" | tee -a "$LOGFILE"
echo "Всего: $((PASSED + FAILED))" | tee -a "$LOGFILE"
echo "" | tee -a "$LOGFILE"

if [ $FAILED -eq 0 ]; then
    echo "✅ ВСЕ ТЕСТЫ ПРОЙДЕНЫ!" | tee -a "$LOGFILE"
else
    echo "⚠️ Есть проваленные тесты: $FAILED" | tee -a "$LOGFILE"
fi

echo "" | tee -a "$LOGFILE"
echo "Лог сохранен: $LOGFILE" | tee -a "$LOGFILE"
