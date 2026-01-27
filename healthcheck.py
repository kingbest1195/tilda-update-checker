#!/usr/bin/env python3
"""
Healthcheck script для Docker контейнера
Проверяет работоспособность приложения и доступность базы данных
"""
import sys
from pathlib import Path


def check_health():
    """Проверка здоровья приложения"""
    db_file = Path('data/tilda_checker.db')

    # Проверка 1: Файл БД существует
    if not db_file.exists():
        print("ERROR: Database file not found", file=sys.stderr)
        return False

    # Проверка 2: Файл не пустой
    if db_file.stat().st_size == 0:
        print("ERROR: Database file is empty", file=sys.stderr)
        return False

    # Проверка 3: Можно открыть SQLite соединение
    try:
        import sqlite3
        conn = sqlite3.connect(str(db_file), timeout=5)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' LIMIT 1")
        cursor.fetchone()
        conn.close()
        return True
    except Exception as e:
        print(f"ERROR: Database connection failed: {e}", file=sys.stderr)
        return False


if __name__ == "__main__":
    sys.exit(0 if check_health() else 1)
