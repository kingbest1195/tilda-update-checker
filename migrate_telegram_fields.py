#!/usr/bin/env python3
"""
Миграция БД: добавление полей для Telegram статуса
"""
import logging
import sys
from pathlib import Path

# Добавить корневую директорию в PATH
sys.path.insert(0, str(Path(__file__).parent))

import config
from src.database import db

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def migrate_telegram_fields():
    """Добавить поля для Telegram статуса в существующую БД"""

    logger.info("=" * 80)
    logger.info("МИГРАЦИЯ БД: Добавление Telegram полей")
    logger.info("=" * 80)

    if not db.init_db():
        logger.error("❌ Не удалось инициализировать БД")
        return False

    from sqlalchemy import text

    with db.get_session() as session:
        try:
            # Проверить, существуют ли уже поля
            result = session.execute(text("PRAGMA table_info(announcements)"))
            columns = [row[1] for row in result]

            if 'telegram_sent' in columns:
                logger.info("✅ Поля Telegram уже существуют в БД")
                return True

            logger.info("📝 Добавление полей в таблицу announcements...")

            # Добавить новые колонки
            session.execute(text("""
                ALTER TABLE announcements
                ADD COLUMN telegram_sent INTEGER DEFAULT 0
            """))
            logger.info("   ✓ telegram_sent")

            session.execute(text("""
                ALTER TABLE announcements
                ADD COLUMN telegram_sent_at DATETIME
            """))
            logger.info("   ✓ telegram_sent_at")

            session.execute(text("""
                ALTER TABLE announcements
                ADD COLUMN telegram_error TEXT
            """))
            logger.info("   ✓ telegram_error")

            session.execute(text("""
                ALTER TABLE announcements
                ADD COLUMN telegram_retry_count INTEGER DEFAULT 0
            """))
            logger.info("   ✓ telegram_retry_count")

            session.execute(text("""
                ALTER TABLE announcements
                ADD COLUMN telegram_next_retry DATETIME
            """))
            logger.info("   ✓ telegram_next_retry")

            session.commit()

            logger.info("=" * 80)
            logger.info("✅ МИГРАЦИЯ УСПЕШНО ЗАВЕРШЕНА")
            logger.info("=" * 80)
            logger.info("")
            logger.info("📊 Теперь все анонсы имеют поля для отслеживания Telegram статуса")
            logger.info("📤 Существующие анонсы будут отправлены при следующем запуске retry механизма")
            logger.info("")

            return True

        except Exception as e:
            session.rollback()
            logger.error(f"❌ Ошибка миграции: {e}", exc_info=True)
            return False


if __name__ == "__main__":
    success = migrate_telegram_fields()
    sys.exit(0 if success else 1)
