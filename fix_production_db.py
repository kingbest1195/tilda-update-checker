#!/usr/bin/env python3
"""
Скрипт для быстрого исправления production БД
Добавляет отсутствующие Telegram колонки в таблицу announcements
"""
import logging
import sys
from pathlib import Path

# Добавить корневую директорию в PATH
sys.path.insert(0, str(Path(__file__).parent))

import config
from src.database import db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)


def fix_database():
    """Исправить БД - добавить недостающие колонки"""
    logger.info("=" * 80)
    logger.info("🔧 БЫСТРОЕ ИСПРАВЛЕНИЕ PRODUCTION БД")
    logger.info("=" * 80)

    # Инициализация БД (включает автоматическую миграцию)
    if not db.init_db():
        logger.error("❌ Ошибка инициализации БД")
        return False

    # Проверка здоровья
    health = db.health_check()

    logger.info("\n📊 Результаты проверки:")
    logger.info(f"  Статус: {health['status']}")
    logger.info(f"  Подключение: {'✅' if health['checks']['connection'] else '❌'}")
    logger.info(f"  Таблицы: {'✅' if health['checks']['tables'] else '❌'}")
    logger.info(f"  Схема: {'✅' if health['checks']['schema'] else '❌'}")

    if health['details']:
        logger.info(f"  Детали: {health['details']}")

    if health['status'] == 'healthy':
        logger.info("\n✅ БД полностью исправлена и готова к работе!")
        return True
    elif health['status'] == 'degraded':
        logger.warning("\n⚠️ БД в деградированном состоянии")
        logger.warning("Может потребоваться ручное вмешательство")
        return True
    else:
        logger.error("\n❌ БД все еще нездорова")
        return False


if __name__ == "__main__":
    success = fix_database()
    sys.exit(0 if success else 1)
