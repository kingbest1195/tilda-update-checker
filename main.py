"""
Tilda Update Checker - главный модуль приложения
"""
import argparse
import logging
import signal
import atexit
import sys
from pathlib import Path

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
        else:
            logger.warning("Анонсы не были созданы")
        
        logger.info("Проверка завершена")
        logger.info("=" * 80)
        
    except Exception as e:
        logger.error(f"❌ Критическая ошибка при проверке: {e}", exc_info=True)


def run_discovery_and_migrate():
    """Запуск Discovery Mode с автоматической миграцией обновлений"""
    try:
        logger.info("\n" + "="*80)
        logger.info("🔍 ЗАПУСК ЕЖЕНЕДЕЛЬНОГО DISCOVERY MODE")
        logger.info("="*80)
        
        # Запустить полный Discovery Mode
        result = discovery.run_full_discovery_with_version_check()
        
        version_updates = result.get('version_updates', [])
        
        if version_updates:
            logger.info(f"\n🆕 Обнаружено {len(version_updates)} обновлений версий")
            logger.info("Начало автоматической миграции...")
            
            # Выполнить пакетную миграцию
            stats = manager.perform_batch_migration(version_updates, force=False)
            
            logger.info(f"\n📊 Результаты миграции:")
            logger.info(f"   ✅ Успешно: {stats['successful']}")
            logger.info(f"   ❌ Неудачно: {stats['failed']}")
        else:
            logger.info("\n✅ Обновлений версий не обнаружено")
        
        logger.info("="*80 + "\n")
        
    except Exception as e:
        logger.error(f"❌ Ошибка в Discovery Mode: {e}", exc_info=True)


def check_404_errors():
    """Проверка файлов с критическими 404 ошибками"""
    try:
        logger.info("\n" + "="*80)
        logger.info("⚠️ ПРОВЕРКА 404 ОШИБОК")
        logger.info("="*80)
        
        files_with_404 = fetcher.check_404_errors()
        
        if files_with_404:
            logger.warning(f"🔴 Обнаружено {len(files_with_404)} файлов с критическими 404")
            logger.info("Запуск Discovery Mode для поиска замены...")
            
            # Запустить Discovery Mode для поиска новых версий
            run_discovery_and_migrate()
        else:
            logger.info("✅ Критических 404 ошибок не обнаружено")
        
        logger.info("="*80 + "\n")
        
    except Exception as e:
        logger.error(f"❌ Ошибка при проверке 404: {e}", exc_info=True)


def run_daemon():
    """Запуск в режиме демона с почасовыми проверками"""
    logger.info("🚀 Запуск Tilda Update Checker в режиме демона")
    logger.info(f"Интервал проверки: {config.TILDA_CHECK_INTERVAL} секунд")
    
    # Инициализировать БД
    if not db.init_db():
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
        
        logger.info(f"✅ Планировщик настроен:")
        logger.info(f"   - Проверка изменений: каждые {interval_hours or 1} час(ов)")
        logger.info(f"   - Discovery Mode: каждый понедельник в 9:00")
        logger.info(f"   - Проверка 404: ежедневно в 8:00")
        logger.info("Нажмите Ctrl+C для остановки")
        logger.info("")
        
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
    if not db.init_db():
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
    if not db.init_db():
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
    
    if not db.init_db():
        logger.error("Не удалось инициализировать базу данных")
        sys.exit(1)
    
    run_discovery_and_migrate()


def show_version_updates():
    """Показать обнаруженные обновления версий"""
    logger.info("🆕 Проверка обновлений версий...")
    
    if not db.init_db():
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
    
    if not db.init_db():
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
    
    if not db.init_db():
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
    
    if not db.init_db():
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
    
    if not db.init_db():
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
    
    if not db.init_db():
        logger.error("Не удалось инициализировать базу данных")
        sys.exit(1)
    
    try:
        alert_system.print_dashboard()
    except Exception as e:
        logger.error(f"Ошибка при выводе dashboard: {e}", exc_info=True)


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
    else:
        parser.print_help()
        print("\n⚠️ Укажите команду для выполнения\n")


if __name__ == "__main__":
    main()

