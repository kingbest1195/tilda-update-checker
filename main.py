"""
Tilda Update Checker - главный модуль приложения
"""
import argparse
import logging
import signal
import atexit
import sys
from pathlib import Path
from datetime import datetime

from apscheduler.schedulers.blocking import BlockingScheduler

import config
from src.database import db
from src.cdn_fetcher import fetcher
from src.diff_detector import detector
from src.llm_analyzer import analyzer
from src.announcement import generator
from src.discovery import discovery
from src.version_detector import detector as version_detector
from src.migration_manager import manager
from src.alert_system import alert_system
from src.telegram_notifier import notifier
from src.block_catalog import block_monitor


def setup_logging():
    """Настроить систему логирования"""
    # Создать директорию для логов если не существует
    log_dir = Path(config.BASE_DIR / "logs")
    log_dir.mkdir(exist_ok=True)

    # Настроить формат логов
    log_format = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"

    # Основной logger
    logger = logging.getLogger()
    logger.setLevel(config.LOG_LEVEL)

    # Обработчик для файла
    file_handler = logging.FileHandler(
        config.BASE_DIR / config.LOG_FILE,
        encoding='utf-8'
    )
    file_handler.setLevel(config.LOG_LEVEL)
    file_handler.setFormatter(logging.Formatter(log_format, date_format))

    # Обработчик для консоли
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(config.LOG_LEVEL)
    console_handler.setFormatter(logging.Formatter(log_format, date_format))

    # Добавить обработчики
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    return logger


def init_database_with_health_check():
    """
    Инициализировать БД с проверкой здоровья и автоматической миграцией.

    Эта функция является единой точкой инициализации БД для всего приложения.
    Она выполняет:
    1. Базовую инициализацию БД (создание таблиц)
    2. Автоматическую миграцию схемы (через _check_and_migrate_schema)
    3. Health check для валидации корректности БД

    Returns:
        bool: True если БД готова к работе (healthy или degraded)
              False если БД полностью нерабочая (unhealthy)
    """
    # Базовая инициализация с автоматической миграцией
    if not db.init_db():
        logger.error("❌ Не удалось инициализировать базу данных")
        return False

    # Комплексная проверка здоровья БД
    health = db.health_check()

    if health['status'] == 'healthy':
        logger.info("✅ БД здорова и готова к работе")
        return True
    elif health['status'] == 'degraded':
        logger.warning(f"⚠️ БД в деградированном состоянии: {health['details']}")
        logger.warning("⚠️ Приложение продолжит работу, но функциональность может быть ограничена")
        return True
    else:
        logger.error(f"❌ БД нездорова и не может использоваться: {health['details']}")
        return False


logger = setup_logging()


def shutdown_handler(scheduler, signum=None, frame=None):
    """Обработчик graceful shutdown"""
    logger.info("🛑 Получен сигнал завершения. Graceful shutdown...")
    try:
        if scheduler and scheduler.running:
            scheduler.shutdown(wait=True)
            logger.info("✅ Scheduler остановлен корректно")
    except Exception as e:
        logger.error(f"Ошибка при остановке scheduler: {e}")
    finally:
        logger.info("👋 Приложение остановлено")
        sys.exit(0)


def check_and_analyze():
    """Основная функция проверки и анализа изменений"""
    try:
        logger.info("=" * 80)
        logger.info("Начало проверки изменений в Tilda CDN")
        logger.info("=" * 80)
        
        # 1. Загрузить список отслеживаемых файлов
        logger.info("Шаг 1: Загрузка файлов с CDN...")
        downloaded_files = fetcher.download_all_files()
        
        if not downloaded_files:
            logger.error("Не удалось загрузить файлы с CDN")
            return
        
        success_count = sum(1 for f in downloaded_files if f['success'])
        logger.info(f"Успешно загружено: {success_count}/{len(downloaded_files)} файлов")
        
        # 2. Проверить изменения (быстрая проверка по хешам)
        logger.info("Шаг 2: Проверка на изменения...")
        changes = detector.check_for_changes(downloaded_files)
        
        if not changes:
            logger.info("✅ Изменений не обнаружено")
            logger.info("=" * 80)
            return
        
        logger.info(f"🔍 Обнаружено изменений: {len(changes)}")

        # 2.5 Обогатить change_info историей и cross-file данными
        for change in changes:
            change['history'] = db.get_change_history(change['file_id'], limit=5)
            change['concurrent_changes'] = db.get_recent_changes_by_category(
                change['category'], hours=4
            )

        # 3. Проанализировать через LLM (только значимые изменения)
        logger.info("Шаг 3: Анализ изменений через LLM...")
        analysis_results = []

        for change in changes:
            if change.get('is_significant'):
                logger.info(f"Анализ: {change['url']}")
                analysis = analyzer.analyze_change(change)
                
                if analysis:
                    analysis_results.append(analysis)
                    logger.info(
                        f"  → {analysis.get('severity', 'N/A')}: "
                        f"{analysis.get('change_type', 'N/A')}"
                    )
            else:
                logger.info(f"Пропущено незначительное изменение: {change['url']}")
        
        if not analysis_results:
            logger.warning("Нет результатов анализа для создания анонса")
            logger.info("=" * 80)
            return

        # 3.5 Batch-анализ трендов (если 2+ файла одной категории)
        batch_analysis = analyzer.analyze_batch(analysis_results)
        if batch_analysis:
            logger.info(f"📊 Batch-анализ трендов: {len(batch_analysis)} категорий")
            for result in analysis_results:
                cat = result.get('change_info', {}).get('category')
                if cat and cat in batch_analysis:
                    result['trend'] = batch_analysis[cat].get('trend')
                    result['feature'] = batch_analysis[cat].get('feature')

        # 4. Сгенерировать и сохранить анонсы
        logger.info("Шаг 4: Генерация анонсов...")
        announcement_ids = generator.save_announcements(analysis_results)

        if announcement_ids:
            logger.info(f"✅ Создано анонсов: {len(announcement_ids)}")

            # Вывести сводный анонс в лог
            full_announcement = generator.generate_announcement(analysis_results)
            if full_announcement:
                logger.info("\n" + "=" * 80)
                logger.info("СВОДНЫЙ АНОНС:")
                logger.info("=" * 80)
                logger.info(full_announcement)
                logger.info("=" * 80)

            # 5. Отправить анонсы в Telegram с отслеживанием статуса
            logger.info("Шаг 5: Отправка в Telegram...")
            telegram_sent = 0
            telegram_failed = 0

            # Создать маппинг: change_id -> announcement_id
            with db.get_session() as session:
                from src.database import Announcement
                id_mapping = {}
                for ann_id in announcement_ids:
                    announcement = session.query(Announcement).filter_by(id=ann_id).first()
                    if announcement:
                        id_mapping[announcement.change_id] = ann_id

            # Отправить каждый анонс используя данные из analysis_results
            for result in analysis_results:
                change_info = result.get('change_info', {})
                change_id = change_info.get('change_id')

                if not change_id or change_id not in id_mapping:
                    logger.warning(f"Не найден announcement_id для change_id={change_id}")
                    continue

                ann_id = id_mapping[change_id]

                # Подготовить данные для отправки (используя analysis_results)
                announcement_data = {
                    'id': ann_id,
                    'url': result.get('url'),
                    'change_type': result.get('change_type'),
                    'severity': result.get('severity'),
                    'title': result.get('url', 'Unknown').split('/')[-1],
                    'description': result.get('description', ''),
                    'user_impact': result.get('user_impact', ''),
                    'recommendations': result.get('recommendations', ''),
                    'priority': change_info.get('priority', 'MEDIUM'),
                    'category': change_info.get('category', 'unknown'),
                    'trend': result.get('trend'),
                    'feature': result.get('feature'),
                }

                # Попытка отправки
                success = notifier.send_announcement(announcement_data)

                # Записать статус отправки
                error_message = notifier.last_error if not success else None
                response_data = notifier.last_response

                db.mark_telegram_sent(
                    announcement_id=ann_id,
                    success=success,
                    error=error_message,
                    response_data=response_data
                )

                if success:
                    telegram_sent += 1
                    logger.info(f"  ✅ Telegram отправлен для анонса ID={ann_id}")
                else:
                    telegram_failed += 1
                    logger.warning(f"  ❌ Telegram не отправлен для анонса ID={ann_id}: {error_message}")

            # Статистика отправки
            logger.info(f"📊 Telegram статистика: отправлено {telegram_sent}/{len(announcement_ids)}")
            if telegram_failed > 0:
                logger.warning(f"⚠️ Не удалось отправить {telegram_failed} сообщений (будет повтор позже)")
        else:
            logger.warning("Анонсы не были созданы")
        
        logger.info("Проверка завершена")
        logger.info("=" * 80)
        
    except Exception as e:
        logger.error(f"❌ Критическая ошибка при проверке: {e}", exc_info=True)


def retry_pending_telegrams():
    """Повторная отправка неудачных Telegram сообщений"""
    try:
        logger.info("=" * 80)
        logger.info("📤 ПОВТОРНАЯ ОТПРАВКА TELEGRAM СООБЩЕНИЙ")
        logger.info("=" * 80)

        # Проверить инициализацию БД
        if not db.SessionLocal:
            logger.warning("⚠️ БД не инициализирована, пропуск повторной отправки")
            return

        # Получить ожидающие анонсы с обработкой ошибок схемы
        try:
            pending = db.get_pending_announcements(limit=50)
        except Exception as db_error:
            # Проверить, является ли это ошибкой схемы БД
            error_msg = str(db_error)
            if "no such column" in error_msg or "OperationalError" in str(type(db_error).__name__):
                logger.error(
                    "❌ Ошибка схемы БД: отсутствуют колонки для Telegram статуса.\n"
                    "   Решение: перезапустите приложение для автоматической миграции БД.\n"
                    f"   Детали: {error_msg}"
                )
                return
            else:
                # Для других ошибок БД пробрасываем дальше
                raise

        if not pending:
            logger.info("✅ Нет сообщений для повторной отправки")
            logger.info("=" * 80)
            return

        logger.info(f"📋 Найдено {len(pending)} сообщений для повторной отправки")

        telegram_sent = 0
        telegram_failed = 0

        for announcement in pending:
            try:
                # Отправить content как простой текст без Markdown-разметки:
                # announcement.content хранит LLM-текст, который может содержать
                # CSS-селекторы (*), символы подчёркивания и другие символы,
                # ломающие Telegram Markdown-парсер (ошибка 400 "can't parse entities").
                message = f"🔔 {announcement.title}\n\n{announcement.content}"

                # Попытка отправки без parse_mode (plain text)
                success = notifier._send_message(
                    message,
                    parse_mode=None,
                    thread_id=notifier.thread_id
                )

                # Записать статус
                error_message = notifier.last_error if not success else None
                response_data = notifier.last_response

                db.mark_telegram_sent(
                    announcement_id=announcement.id,
                    success=success,
                    error=error_message,
                    response_data=response_data
                )

                if success:
                    telegram_sent += 1
                    logger.info(f"  ✅ Успешно отправлен анонс ID={announcement.id}")
                else:
                    telegram_failed += 1
                    retry_count = announcement.telegram_retry_count + 1
                    logger.warning(
                        f"  ❌ Не удалось отправить анонс ID={announcement.id} "
                        f"(попытка {retry_count}): {error_message}"
                    )

            except Exception as send_error:
                telegram_failed += 1
                logger.error(
                    f"  ❌ Исключение при отправке анонса ID={announcement.id}: {send_error}",
                    exc_info=False
                )

        # Итоговая статистика
        logger.info(f"📊 Результаты повтора: успешно {telegram_sent}, неудачно {telegram_failed}")
        logger.info("=" * 80)

    except Exception as e:
        logger.error(f"❌ Критическая ошибка в retry_pending_telegrams: {e}", exc_info=True)


def run_discovery_and_migrate():
    """Запуск Discovery Mode с автоматической миграцией обновлений"""
    try:
        logger.info("\n" + "="*80)
        logger.info("🔍 ЗАПУСК ЕЖЕНЕДЕЛЬНОГО DISCOVERY MODE")
        logger.info("="*80)

        # Запустить полный Discovery Mode
        result = discovery.run_full_discovery_with_version_check()

        version_updates = result.get('version_updates', [])
        discovered_files = result.get('discovered_files', [])
        new_files = result.get('new_files', [])

        # Отправить Discovery отчет в Telegram
        if notifier and notifier.enabled:
            discovery_report = []

            # Добавить новые файлы
            for file in new_files:
                discovery_report.append({
                    'url': file.get('url'),
                    'category': file.get('category', 'unknown'),
                    'priority': file.get('priority', 'MEDIUM'),
                    'status': 'Новый файл'
                })

            # Добавить обновления версий
            for update in version_updates:
                discovery_report.append({
                    'url': update.get('new_url'),
                    'category': update.get('category', 'unknown'),
                    'priority': update.get('priority', 'MEDIUM'),
                    'status': f"Обновление: {update.get('old_version', 'N/A')} → {update.get('new_version')}"
                })

            if discovery_report:
                logger.info(f"📨 Отправка Discovery отчета: {len(discovery_report)} файлов")
                success = notifier.send_discovery_report(discovery_report)
                if success:
                    logger.info("✅ Discovery отчет отправлен в Telegram")
                else:
                    logger.error(f"❌ Ошибка отправки Discovery отчета: {notifier.last_error}")

        if version_updates:
            logger.info(f"\n🆕 Обнаружено {len(version_updates)} обновлений версий")
            logger.info("Начало автоматической миграции...")

            # Выполнить пакетную миграцию
            stats = manager.perform_batch_migration(version_updates, force=False)

            successful_migrations = stats.get('successful_migrations', [])
            failed_migrations = stats.get('failed_migrations', [])

            logger.info(f"\n📊 Результаты миграции:")
            logger.info(f"   ✅ Успешно: {stats['successful']}")
            logger.info(f"   ❌ Неудачно: {stats['failed']}")

            # Отправить дайджест миграций в Digest топик
            if (successful_migrations or failed_migrations) and notifier and notifier.enabled:
                digest_data = []

                for migration in successful_migrations:
                    digest_data.append({
                        'title': f"Миграция {migration.get('base_name', 'Unknown')}",
                        'severity': 'ВАЖНОЕ',
                        'category': migration.get('category', 'unknown'),
                        'priority': migration.get('priority', 'MEDIUM'),
                        'description': f"Успешная миграция с версии {migration.get('old_version', 'N/A')} на {migration.get('new_version', 'N/A')}",
                        'url': migration.get('new_url', 'N/A')
                    })

                for migration in failed_migrations:
                    digest_data.append({
                        'title': f"Ошибка миграции {migration.get('base_name', 'Unknown')}",
                        'severity': 'КРИТИЧЕСКОЕ',
                        'category': migration.get('category', 'unknown'),
                        'priority': 'HIGH',
                        'description': f"Не удалось мигрировать: {migration.get('error', 'Unknown error')[:100]}",
                        'url': migration.get('new_url', 'N/A')
                    })

                if digest_data:
                    logger.info("📨 Отправка дайджеста миграций")
                    success = notifier.send_daily_digest(digest_data)
                    if success:
                        logger.info("✅ Дайджест миграций отправлен в Telegram")
                    else:
                        logger.error(f"❌ Ошибка отправки дайджеста миграций: {notifier.last_error}")
        else:
            logger.info("\n✅ Обновлений версий не обнаружено")

        logger.info("="*80 + "\n")

    except Exception as e:
        logger.error(f"❌ Ошибка в Discovery Mode: {e}", exc_info=True)


def _extract_description_fallback(content: str) -> str:
    """
    Извлечь описание из старого формата ann.content (fallback для записей без новых полей).
    Ищет строку после "   " (описание в format_change_entry).
    """
    if not content:
        return 'Нет описания'

    lines = content.split('\n')
    for line in lines:
        stripped = line.strip()
        # Пропускаем служебные строки
        if stripped and not stripped.startswith(('1.', '2.', '3.')) and \
           not any(stripped.startswith(p) for p in ('🔴', '🟡', '🟢', '⚪', 'Тип:', 'Значимость:', 'Влияние:', 'Рекомендации:', 'Тренд:', 'Фича:', 'Ссылка:')):
            if len(stripped) > 15:  # Достаточно длинная строка — это описание
                return stripped[:300]

    return content[:200] if content else 'Нет описания'


def send_daily_digest_task():
    """Отправить ежедневный дайджест всех анонсов за последние 24 часа"""
    try:
        logger.info("\n" + "="*80)
        logger.info("📊 ОТПРАВКА ЕЖЕДНЕВНОГО ДАЙДЖЕСТА")
        logger.info("="*80)

        if not db.init_db():
            logger.error("❌ Ошибка инициализации БД")
            return

        # Получить все анонсы за последние 24 часа
        with db.get_session() as session:
            from datetime import timedelta
            from src.database import Announcement, Change, TrackedFile
            from sqlalchemy.orm import joinedload

            yesterday = datetime.now() - timedelta(hours=24)
            announcements_raw = session.query(Announcement)\
                .options(
                    joinedload(Announcement.change).joinedload(Change.file)
                )\
                .filter(
                    Announcement.generated_at >= yesterday
                ).order_by(Announcement.generated_at.desc()).all()

            if not announcements_raw:
                logger.info("ℹ️ Нет анонсов за последние 24 часа")
                logger.info("="*80 + "\n")
                return

            # Собрать структурированные данные (без двойной обрезки)
            digest_data = []
            for ann in announcements_raw:
                tracked_file = ann.change.file if ann.change else None
                digest_data.append({
                    'id': ann.id,
                    'title': ann.title or 'Обновление файла',
                    'severity': ann.severity or 'НЕЗНАЧИТЕЛЬНОЕ',
                    'category': tracked_file.category if tracked_file else 'unknown',
                    'priority': tracked_file.priority if tracked_file else 'MEDIUM',
                    'description': ann.description_short or _extract_description_fallback(ann.content),
                    'user_impact': ann.user_impact or '',
                    'trend': ann.trend,
                    'feature': ann.feature,
                    'change_type': ann.change_type or '',
                    'url': tracked_file.url if tracked_file else 'N/A',
                    'created_at': ann.generated_at,
                })

            logger.info(f"📨 Подготовка дайджеста: {len(digest_data)} анонсов")

            # LLM-анализ дайджеста (общая картина дня)
            digest_analysis = None
            if analyzer.client:
                logger.info("🤖 Запуск LLM-анализа дайджеста...")
                digest_analysis = analyzer.analyze_digest(digest_data)
                if digest_analysis:
                    logger.info(f"✅ LLM дайджест-анализ завершён: {digest_analysis.get('summary', '')[:80]}...")
                else:
                    logger.warning("⚠️ LLM-анализ дайджеста не дал результатов, используется механический формат")

            # Отправить в Telegram
            if notifier and notifier.enabled:
                success = notifier.send_daily_digest(digest_data, digest_analysis=digest_analysis)
                if success:
                    logger.info("✅ Дайджест успешно отправлен в Telegram")
                else:
                    logger.error(f"❌ Ошибка отправки дайджеста: {notifier.last_error}")
            else:
                logger.info("ℹ️ Telegram уведомления отключены")

        logger.info("="*80 + "\n")

    except Exception as e:
        logger.error(f"❌ Ошибка при отправке дайджеста: {e}", exc_info=True)


def check_404_errors():
    """Проверка файлов с критическими 404 ошибками"""
    try:
        logger.info("\n" + "="*80)
        logger.info("⚠️ ПРОВЕРКА 404 ОШИБОК")
        logger.info("="*80)

        files_with_404 = fetcher.check_404_errors()

        if files_with_404:
            logger.warning(f"🔴 Обнаружено {len(files_with_404)} файлов с критическими 404")

            # Сохранить информацию о 404 файлах для отчета
            files_404_info = []
            for file_entry in files_with_404:
                files_404_info.append({
                    'url': file_entry.get('url'),
                    'category': file_entry.get('category', 'unknown'),
                    'priority': file_entry.get('priority', 'MEDIUM'),
                    'status': f"404 Error (последовательных: {file_entry.get('consecutive_404_count', 0)})"
                })

            logger.info("Запуск Discovery Mode для поиска замены...")

            # Запустить Discovery Mode для поиска новых версий
            run_discovery_and_migrate()

            # Отправить отчет о найденных заменах в Discovery топик
            if notifier and notifier.enabled and files_404_info:
                logger.info("📨 Отправка отчета о замене 404 файлов")
                success = notifier.send_discovery_report(files_404_info)
                if success:
                    logger.info("✅ Discovery отчет (404 замены) отправлен в Telegram")
                else:
                    logger.error(f"❌ Ошибка отправки Discovery отчета: {notifier.last_error}")
        else:
            logger.info("✅ Критических 404 ошибок не обнаружено")

        logger.info("="*80 + "\n")

    except Exception as e:
        logger.error(f"❌ Ошибка при проверке 404: {e}", exc_info=True)


def check_block_catalog():
    """Проверка каталога блоков Tilda"""
    try:
        logger.info("\n" + "="*80)
        logger.info("🧱 ПРОВЕРКА КАТАЛОГА БЛОКОВ TILDA")
        logger.info("="*80)

        result = block_monitor.check_catalog()
        block_monitor.print_changes_report(result)

        # Отправить отчёт в Telegram (только если не первый запуск и есть изменения)
        if not result.get('is_first_run') and (
            result.get('new_blocks') or result.get('removed_blocks') or result.get('changed_blocks')
        ):
            if notifier and notifier.enabled:
                logger.info("📨 Отправка отчёта о блоках в Telegram...")
                success = notifier.send_block_catalog_report(result)
                if success:
                    logger.info("✅ Отчёт о блоках отправлен в Telegram")
                    for change_id in result.get('change_ids', []):
                        db.mark_block_notification_sent(change_id, success=True)
                else:
                    logger.error(f"❌ Ошибка отправки отчёта о блоках: {notifier.last_error}")
                    for change_id in result.get('change_ids', []):
                        db.mark_block_notification_sent(change_id, success=False, error=notifier.last_error)

        logger.info("="*80 + "\n")

    except Exception as e:
        logger.error(f"❌ Ошибка при проверке каталога блоков: {e}", exc_info=True)


def handle_check_blocks():
    """CLI: разовая проверка каталога блоков"""
    if not init_database_with_health_check():
        logger.error("Не удалось инициализировать базу данных")
        sys.exit(1)
    check_block_catalog()


def handle_show_blocks():
    """CLI: показать текущий каталог блоков из БД"""
    if not init_database_with_health_check():
        logger.error("Не удалось инициализировать базу данных")
        sys.exit(1)
    block_monitor.print_catalog()


def handle_show_block_changes(limit: int = 50):
    """CLI: показать историю изменений каталога блоков"""
    if not init_database_with_health_check():
        logger.error("Не удалось инициализировать базу данных")
        sys.exit(1)
    block_monitor.print_changes_report(limit=limit)


def run_daemon():
    """Запуск в режиме демона с почасовыми проверками"""
    logger.info("🚀 Запуск Tilda Update Checker в режиме демона")
    logger.info(f"Интервал проверки: {config.TILDA_CHECK_INTERVAL} секунд")
    
    # Инициализировать БД
    if not init_database_with_health_check():
        logger.error("Не удалось инициализировать базу данных")
        sys.exit(1)
    
    try:
        scheduler = BlockingScheduler()

        # Зарегистрировать обработчики сигналов для graceful shutdown
        signal.signal(signal.SIGTERM, lambda s, f: shutdown_handler(scheduler, s, f))
        signal.signal(signal.SIGINT, lambda s, f: shutdown_handler(scheduler, s, f))
        atexit.register(lambda: shutdown_handler(scheduler))

        # Задача 1: Основная проверка изменений (каждый час)
        interval_hours = config.TILDA_CHECK_INTERVAL // 3600
        scheduler.add_job(
            check_and_analyze,
            'interval',
            hours=interval_hours if interval_hours > 0 else 1,
            id="tilda_checker"
        )
        
        # Задача 2: Еженедельный Discovery Mode (каждый понедельник в 9:00)
        scheduler.add_job(
            run_discovery_and_migrate,
            'cron',
            day_of_week='mon',
            hour=9,
            minute=0,
            id='weekly_discovery'
        )
        
        # Задача 3: Ежедневная проверка 404 ошибок (каждый день в 8:00)
        scheduler.add_job(
            check_404_errors,
            'cron',
            hour=8,
            minute=0,
            id='daily_404_check'
        )

        # Задача 4: Повторная отправка неудачных Telegram сообщений (каждые 15 минут)
        scheduler.add_job(
            retry_pending_telegrams,
            'interval',
            minutes=15,
            id='telegram_retry'
        )

        # Задача 5: Ежедневный дайджест изменений (каждый день в 22:00)
        scheduler.add_job(
            send_daily_digest_task,
            'cron',
            hour=22,
            minute=0,
            id='daily_digest',
            misfire_grace_time=3600
        )

        # Задача 6: Ежедневная проверка каталога блоков (каждый день в 10:00)
        if config.BLOCK_CATALOG_CHECK_ENABLED:
            scheduler.add_job(
                check_block_catalog,
                'cron',
                hour=10,
                minute=0,
                id='block_catalog_check',
                misfire_grace_time=3600
            )

        logger.info(f"✅ Планировщик настроен:")
        logger.info(f"   - Проверка изменений: каждые {interval_hours or 1} час(ов)")
        logger.info(f"   - Discovery Mode: каждый понедельник в 9:00")
        logger.info(f"   - Проверка 404: ежедневно в 8:00")
        logger.info(f"   - Повтор Telegram: каждые 15 минут")
        logger.info(f"   - Ежедневный дайджест: ежедневно в 22:00")
        if config.BLOCK_CATALOG_CHECK_ENABLED:
            logger.info(f"   - Каталог блоков: ежедневно в 10:00")
        logger.info("Нажмите Ctrl+C для остановки")
        logger.info("")

        # Проверить Telegram соединение и отправить deployment notification
        if notifier.enabled:
            logger.info("🔌 Проверка соединения с Telegram...")

            # Отправить deployment notification
            deployment_message = (
                "🚀 *Tilda Update Checker запущен*\n\n"
                f"📅 Время: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                f"⏱ Интервал проверки: каждые {interval_hours or 1} час(ов)\n"
                f"🤖 Режим: daemon mode\n\n"
                "Система мониторинга Tilda CDN активна."
            )

            # Отправить в alerts топик
            success = notifier._send_message(
                deployment_message,
                parse_mode="Markdown",
                thread_id=notifier.alerts_thread_id
            )

            if success:
                logger.info("✅ Deployment notification отправлен в Telegram")
                # Telegram работает — сбрасываем permanently failed анонсы,
                # чтобы они были повторно отправлены при старте после фиксов
                reset_count = db.reset_all_permanently_failed()
                if reset_count > 0:
                    logger.info(
                        f"🔄 Сброшено {reset_count} permanently failed анонсов. "
                        "Запуск немедленной повторной отправки..."
                    )
                    retry_pending_telegrams()
            else:
                logger.warning(f"⚠️ Не удалось отправить deployment notification: {notifier.last_error}")
        else:
            logger.warning("⚠️ Telegram уведомления отключены")

        # Выполнить первую проверку сразу
        logger.info("Выполнение первоначальной проверки...")
        check_and_analyze()
        
        # Запустить планировщик
        scheduler.start()
            
    except KeyboardInterrupt:
        logger.info("\n👋 Получен сигнал остановки. Завершение работы...")
    except Exception as e:
        logger.error(f"Критическая ошибка планировщика: {e}", exc_info=True)
        sys.exit(1)


def run_once():
    """Однократная проверка (для тестирования)"""
    logger.info("🔍 Запуск однократной проверки")
    
    # Инициализировать БД
    if not init_database_with_health_check():
        logger.error("Не удалось инициализировать базу данных")
        sys.exit(1)
    
    # Выполнить проверку
    check_and_analyze()


def show_announcements(limit: int = 10):
    """
    Показать последние анонсы
    
    Args:
        limit: Количество анонсов для отображения
    """
    logger.info(f"📋 Получение последних {limit} анонсов...")
    
    # Инициализировать БД
    if not init_database_with_health_check():
        logger.error("Не удалось инициализировать базу данных")
        sys.exit(1)
    
    try:
        announcements = db.get_recent_announcements(limit=limit)
        
        if not announcements:
            print("\n📭 Анонсов пока нет. Запустите проверку с флагом --once или --daemon\n")
            return
        
        # Форматировать и вывести
        formatted = generator.format_announcements_list(announcements)
        print("\n" + formatted + "\n")
        
    except Exception as e:
        logger.error(f"Ошибка при получении анонсов: {e}", exc_info=True)


def run_discovery_mode():
    """Запуск Discovery Mode вручную"""
    logger.info("🔍 Запуск Discovery Mode вручную")
    
    if not init_database_with_health_check():
        logger.error("Не удалось инициализировать базу данных")
        sys.exit(1)
    
    run_discovery_and_migrate()


def show_version_updates():
    """Показать обнаруженные обновления версий"""
    logger.info("🆕 Проверка обновлений версий...")
    
    if not init_database_with_health_check():
        logger.error("Не удалось инициализировать базу данных")
        sys.exit(1)
    
    try:
        # Получить обнаруженные файлы
        discovered_files = db.get_undiscovered_files()
        
        if not discovered_files:
            print("\n📭 Нет обнаруженных файлов. Запустите --discover сначала\n")
            return
        
        # Проверить на наличие обновлений версий
        updates = discovery.detect_version_upgrades()
        
        if updates:
            version_detector.print_version_updates_report(updates)
        else:
            print("\n✅ Обновлений версий не обнаружено\n")
        
    except Exception as e:
        logger.error(f"Ошибка при проверке обновлений: {e}", exc_info=True)


def migrate_file(base_name: str, to_version: str):
    """
    Выполнить миграцию конкретного файла
    
    Args:
        base_name: Базовое имя файла
        to_version: Целевая версия
    """
    logger.info(f"🔄 Миграция {base_name} на версию {to_version}")
    
    if not init_database_with_health_check():
        logger.error("Не удалось инициализировать базу данных")
        sys.exit(1)
    
    try:
        # Найти обновление для этого файла
        discovered_files = db.get_undiscovered_files()
        tracked_files = db.get_active_tracked_files()
        
        updates = version_detector.find_version_updates(tracked_files, discovered_files)
        
        # Найти конкретное обновление
        target_update = None
        for update in updates:
            if update['base_name'] == base_name and update['new_version'] == to_version:
                target_update = update
                break
        
        if not target_update:
            logger.error(f"❌ Обновление {base_name} -> v{to_version} не найдено")
            logger.info("Попробуйте сначала запустить --discover")
            return
        
        # Выполнить миграцию
        success = manager.perform_migration(target_update, force=True)
        
        if success:
            print(f"\n✅ Миграция {base_name} успешно завершена\n")
        else:
            print(f"\n❌ Миграция {base_name} не удалась. Проверьте логи.\n")
        
    except Exception as e:
        logger.error(f"Ошибка при миграции: {e}", exc_info=True)


def rollback_file(base_name: str, to_version: str):
    """
    Откатить файл к предыдущей версии
    
    Args:
        base_name: Базовое имя файла
        to_version: Версия для восстановления
    """
    logger.info(f"🔙 Откат {base_name} к версии {to_version}")
    
    if not init_database_with_health_check():
        logger.error("Не удалось инициализировать базу данных")
        sys.exit(1)
    
    try:
        success = manager.rollback_to_version(base_name, to_version)
        
        if success:
            print(f"\n✅ Откат {base_name} успешно выполнен\n")
        else:
            print(f"\n❌ Откат не удался. Проверьте логи.\n")
        
    except Exception as e:
        logger.error(f"Ошибка при откате: {e}", exc_info=True)


def show_version_history(base_name: str):
    """
    Показать историю версий файла
    
    Args:
        base_name: Базовое имя файла
    """
    logger.info(f"📜 История версий для {base_name}")
    
    if not init_database_with_health_check():
        logger.error("Не удалось инициализировать базу данных")
        sys.exit(1)
    
    try:
        versions = version_detector.get_all_versions_for_base(base_name)
        
        if not versions:
            print(f"\n📭 История версий для {base_name} не найдена\n")
            return
        
        formatted = alert_system.format_version_history(versions)
        print(formatted)
        
    except Exception as e:
        logger.error(f"Ошибка при получении истории: {e}", exc_info=True)


def show_migration_status():
    """Показать статус всех миграций"""
    logger.info("📊 Получение статуса миграций...")
    
    if not init_database_with_health_check():
        logger.error("Не удалось инициализировать базу данных")
        sys.exit(1)
    
    try:
        stats = manager.get_migration_status()
        formatted = alert_system.format_migration_stats(stats)
        print(formatted)
        
    except Exception as e:
        logger.error(f"Ошибка при получении статуса: {e}", exc_info=True)


def show_dashboard():
    """Показать dashboard с общей информацией"""
    logger.info("🎛 Dashboard")

    if not init_database_with_health_check():
        logger.error("Не удалось инициализировать базу данных")
        sys.exit(1)

    try:
        alert_system.print_dashboard()
    except Exception as e:
        logger.error(f"Ошибка при выводе dashboard: {e}", exc_info=True)


def show_telegram_status():
    """Показать статистику Telegram отправок"""
    logger.info("📊 Статистика Telegram")

    if not init_database_with_health_check():
        logger.error("Не удалось инициализировать базу данных")
        sys.exit(1)

    try:
        stats = db.get_telegram_stats()

        print("\n" + "=" * 80)
        print("📊 СТАТИСТИКА TELEGRAM ОТПРАВОК")
        print("=" * 80)
        print(f"📬 Всего анонсов: {stats['total']}")
        print(f"✅ Отправлено: {stats['sent']}")
        print(f"⏳ В очереди: {stats['pending']}")
        print(f"❌ Неудачно (retry): {stats['failed']}")
        print(f"🚫 Permanently failed: {stats['permanently_failed']}")
        print(f"📈 Процент успеха: {stats['success_rate']:.1f}%")
        if stats['permanently_failed'] > 0:
            print(f"\n💡 Совет: используйте --reset-telegram <ID> для сброса permanently failed анонсов")
        print("=" * 80)

        # Показать ожидающие анонсы
        pending = db.get_pending_announcements(limit=10)
        if pending:
            print("\n⏳ ОЖИДАЮЩИЕ ОТПРАВКИ (последние 10):")
            print("-" * 80)
            for ann in pending:
                retry_info = f"попытка {ann.telegram_retry_count + 1}" if ann.telegram_retry_count > 0 else "первая попытка"
                error_info = f"\n   Ошибка: {ann.telegram_error[:50]}..." if ann.telegram_error else ""
                file_url = ann.change.file.url if ann.change and ann.change.file else "N/A"
                print(f"  • ID={ann.id} | {file_url}")
                print(f"    {retry_info}{error_info}")
            print("-" * 80)

        print()

    except Exception as e:
        logger.error(f"Ошибка при получении статистики: {e}", exc_info=True)


def handle_retry_telegram():
    """Вручную запустить повтор Telegram отправок"""
    logger.info("📤 Ручной запуск повтора Telegram отправок")

    if not init_database_with_health_check():
        logger.error("Не удалось инициализировать базу данных")
        sys.exit(1)

    retry_pending_telegrams()


def handle_reset_telegram(announcement_id: int):
    """Сбросить Telegram статус конкретного анонса"""
    logger.info(f"🔄 Сброс Telegram статуса для анонса ID={announcement_id}")

    if not init_database_with_health_check():
        logger.error("Не удалось инициализировать базу данных")
        sys.exit(1)

    success = db.reset_telegram_status(announcement_id)

    if success:
        print(f"\n✅ Telegram статус анонса ID={announcement_id} сброшен")
        print("   Анонс будет повторно отправлен при следующем retry цикле.\n")
    else:
        print(f"\n❌ Не удалось сбросить статус анонса ID={announcement_id}")
        print("   Проверьте, что анонс с таким ID существует.\n")


def test_telegram_topics():
    """Тестирование всех Telegram топиков"""
    logger.info("🧪 Тестирование Telegram топиков")

    if not notifier or not notifier.enabled:
        logger.error("❌ Telegram уведомления отключены")
        print("\n❌ Telegram не настроен. Проверьте переменные окружения:\n")
        print("   - TELEGRAM_BOT_TOKEN")
        print("   - TELEGRAM_CHAT_ID")
        print("   - TELEGRAM_THREAD_ID (опционально)")
        print("   - TELEGRAM_ALERTS_THREAD_ID (опционально)")
        print("   - TELEGRAM_DIGEST_THREAD_ID (опционально)")
        print("   - TELEGRAM_DISCOVERY_THREAD_ID (опционально)\n")
        return

    print("\n" + "="*80)
    print("🧪 ТЕСТИРОВАНИЕ TELEGRAM ТОПИКОВ")
    print("="*80)

    # Тест 1: General топик
    print("\nТест 1/4: General топик (thread_id={})".format(notifier.thread_id or 'None'))
    success_1 = notifier._send_message(
        "🧪 *Тест General топика*\n\nЭто тестовое сообщение в основной топик для анонсов.",
        thread_id=notifier.thread_id
    )
    print("   {}".format("✅ Отправлено" if success_1 else f"❌ Ошибка: {notifier.last_error}"))

    # Тест 2: Alerts топик
    print("\nТест 2/4: Alerts топик (thread_id={})".format(notifier.alerts_thread_id or 'None'))
    success_2 = notifier._send_message(
        "🧪 *Тест Alerts топика*\n\nЭто тестовое сообщение в топик для алертов о версиях и миграциях.",
        thread_id=notifier.alerts_thread_id
    )
    print("   {}".format("✅ Отправлено" if success_2 else f"❌ Ошибка: {notifier.last_error}"))

    # Тест 3: Digest топик
    print("\nТест 3/4: Digest топик (thread_id={})".format(notifier.digest_thread_id or 'None'))
    test_digest = [{
        'title': 'Тестовый анонс',
        'severity': 'ВАЖНОЕ',
        'category': 'core',
        'priority': 'HIGH',
        'description': 'Это тестовое сообщение для проверки Digest топика',
        'url': 'https://static.tildacdn.com/js/test.js',
        'created_at': datetime.now()
    }]
    success_3 = notifier.send_daily_digest(test_digest)
    print("   {}".format("✅ Отправлено" if success_3 else f"❌ Ошибка: {notifier.last_error}"))

    # Тест 4: Discovery топик
    print("\nТест 4/4: Discovery топик (thread_id={})".format(notifier.discovery_thread_id or 'None'))
    test_discovery = [{
        'url': 'https://static.tildacdn.com/js/test-discovery-1.0.min.js',
        'category': 'core',
        'priority': 'HIGH',
        'status': 'Тестовый файл для проверки Discovery топика'
    }]
    success_4 = notifier.send_discovery_report(test_discovery)
    print("   {}".format("✅ Отправлено" if success_4 else f"❌ Ошибка: {notifier.last_error}"))

    print("\n" + "="*80)
    print("📊 РЕЗУЛЬТАТЫ ТЕСТИРОВАНИЯ")
    print("="*80)
    successful = sum([success_1, success_2, success_3, success_4])
    print(f"✅ Успешно: {successful}/4")
    print(f"❌ Неудачно: {4 - successful}/4")
    print("="*80 + "\n")

    if successful == 4:
        print("🎉 Все топики работают корректно!\n")
    else:
        print("⚠️ Некоторые топики недоступны. Проверьте логи выше.\n")


def handle_auto_add():
    """Автоматически добавить обнаруженные файлы в мониторинг"""
    logger.info("🤖 Автодобавление обнаруженных файлов")

    if not init_database_with_health_check():
        logger.error("Не удалось инициализировать базу данных")
        sys.exit(1)

    stats = discovery.auto_add_discovered_files()

    print(f"\n✅ Добавлено: {stats['added']}")
    print(f"⏭️  Пропущено: {stats['skipped']}")
    print(f"❌ Ошибок: {stats['failed']}")

    if stats['details']:
        print("\nДетали:")
        for d in stats['details']:
            status_icon = '✅' if d['status'] == 'added' else '❌'
            print(f"  {status_icon} [{d['category']}] {d['url']}")
    print()


def main():
    """Главная функция"""
    parser = argparse.ArgumentParser(
        description="Tilda Update Checker - отслеживание изменений в Tilda CDN",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Примеры использования:
  # Основные команды
  %(prog)s --once                           # Однократная проверка
  %(prog)s --daemon                         # Запуск в фоновом режиме
  %(prog)s --show-announcements             # Показать последние анонсы

  # Версионный мониторинг
  %(prog)s --discover                       # Запуск Discovery Mode
  %(prog)s --show-version-updates           # Показать обнаруженные обновления
  %(prog)s --migrate tilda-cart --to-version 1.2  # Миграция файла
  %(prog)s --rollback tilda-cart --to-version 1.1 # Откат версии
  %(prog)s --version-history tilda-cart     # История версий
  %(prog)s --migration-status               # Статус миграций
  %(prog)s --dashboard                      # Показать dashboard

  # Каталог блоков
  %(prog)s --check-blocks                   # Проверка каталога блоков
  %(prog)s --show-blocks                    # Показать каталог блоков из БД
  %(prog)s --show-block-changes             # Последние изменения каталога

  # Автодобавление
  %(prog)s --auto-add                       # Добавить обнаруженные файлы в мониторинг

  # Telegram команды
  %(prog)s --telegram-status                # Статистика Telegram отправок
  %(prog)s --retry-telegram                 # Повторить неудачные отправки
  %(prog)s --reset-telegram 18              # Сбросить статус анонса для повторной отправки
  %(prog)s --test-telegram-topics           # Тестировать все Telegram топики
        """
    )
    
    # Основные команды
    parser.add_argument(
        "--daemon",
        action="store_true",
        help="Запуск в фоновом режиме с периодическими проверками"
    )
    
    parser.add_argument(
        "--once",
        action="store_true",
        help="Однократная проверка (для тестирования)"
    )
    
    parser.add_argument(
        "--show-announcements",
        action="store_true",
        help="Показать последние анонсы из БД"
    )
    
    # Версионный мониторинг
    parser.add_argument(
        "--discover",
        action="store_true",
        help="Запустить Discovery Mode вручную"
    )
    
    parser.add_argument(
        "--show-version-updates",
        action="store_true",
        help="Показать все обнаруженные обновления версий"
    )
    
    parser.add_argument(
        "--migrate",
        type=str,
        metavar="FILE",
        help="Выполнить миграцию конкретного файла (базовое имя)"
    )
    
    parser.add_argument(
        "--rollback",
        type=str,
        metavar="FILE",
        help="Откатить файл к предыдущей версии (базовое имя)"
    )
    
    parser.add_argument(
        "--to-version",
        type=str,
        metavar="VERSION",
        help="Целевая версия для миграции или отката"
    )
    
    parser.add_argument(
        "--version-history",
        type=str,
        metavar="FILE",
        help="Показать историю версий файла (базовое имя)"
    )
    
    parser.add_argument(
        "--migration-status",
        action="store_true",
        help="Показать статус всех миграций"
    )
    
    parser.add_argument(
        "--dashboard",
        action="store_true",
        help="Показать dashboard с общей информацией"
    )

    # Telegram команды
    parser.add_argument(
        "--telegram-status",
        action="store_true",
        help="Показать статистику Telegram отправок"
    )

    parser.add_argument(
        "--retry-telegram",
        action="store_true",
        help="Вручную повторить отправку неудачных Telegram сообщений"
    )

    parser.add_argument(
        "--test-telegram-topics",
        action="store_true",
        help="Тестировать все Telegram топики (General, Alerts, Digest, Discovery)"
    )

    parser.add_argument(
        "--reset-telegram",
        type=int,
        metavar="ID",
        help="Сбросить Telegram статус анонса для повторной отправки"
    )

    # Автодобавление
    parser.add_argument(
        "--auto-add",
        action="store_true",
        help="Автоматически добавить все обнаруженные файлы в мониторинг"
    )

    # Каталог блоков
    parser.add_argument(
        "--check-blocks",
        action="store_true",
        help="Проверить каталог блоков Tilda на изменения"
    )

    parser.add_argument(
        "--show-blocks",
        action="store_true",
        help="Показать текущий каталог блоков из БД"
    )

    parser.add_argument(
        "--show-block-changes",
        action="store_true",
        help="Показать последние изменения каталога блоков"
    )

    # Дополнительные параметры
    parser.add_argument(
        "-n", "--number",
        type=int,
        default=10,
        help="Количество записей для отображения (по умолчанию: 10)"
    )
    
    args = parser.parse_args()
    
    # Проверить конфигурацию
    if not config.OPENAI_API_KEY and (args.daemon or args.once):
        logger.warning("⚠️ OPENAI_API_KEY не установлен!")
        logger.warning("LLM анализ будет недоступен. Создайте файл .env с ключом API.")
        logger.warning("Скопируйте env.example в .env и добавьте ваш ключ.")
        print()
    
    # Выполнить действие
    if args.daemon:
        run_daemon()
    elif args.once:
        run_once()
    elif args.show_announcements:
        show_announcements(limit=args.number)
    elif args.discover:
        run_discovery_mode()
    elif args.show_version_updates:
        show_version_updates()
    elif args.migrate:
        if not args.to_version:
            parser.error("--migrate требует --to-version")
        migrate_file(args.migrate, args.to_version)
    elif args.rollback:
        if not args.to_version:
            parser.error("--rollback требует --to-version")
        rollback_file(args.rollback, args.to_version)
    elif args.version_history:
        show_version_history(args.version_history)
    elif args.migration_status:
        show_migration_status()
    elif args.dashboard:
        show_dashboard()
    elif args.telegram_status:
        show_telegram_status()
    elif args.retry_telegram:
        handle_retry_telegram()
    elif args.test_telegram_topics:
        test_telegram_topics()
    elif args.reset_telegram:
        handle_reset_telegram(args.reset_telegram)
    elif args.auto_add:
        handle_auto_add()
    elif args.check_blocks:
        handle_check_blocks()
    elif args.show_blocks:
        handle_show_blocks()
    elif args.show_block_changes:
        handle_show_block_changes(limit=args.number)
    else:
        parser.print_help()
        print("\n⚠️ Укажите команду для выполнения\n")


if __name__ == "__main__":
    main()

