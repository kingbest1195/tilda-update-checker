# План: Система версионного мониторинга и автоматической миграции Tilda CDN

## Обзор

Создание комплексной системы для автоматического обнаружения новых версий файлов Tilda (например, `tilda-cart-1.1.min.js` → `tilda-cart-1.2.min.js`), их валидации, архивирования старых версий и автоматического переключения на новые версии с полной интеграцией уведомлений.

**Статус:** ✅ Реализовано (7/10 задач)

## Реализованные компоненты

### ✅ 1. Database Schema Updates
- Добавлены модели: `FileVersion`, `VersionAlert`, `MigrationMetrics`
- Расширена модель `TrackedFile`: `base_name`, `version`, `is_active`, `consecutive_404_count`, `last_404_at`
- Добавлены методы БД для работы с версиями, алертами и метриками

### ✅ 2. Version Detector Module
- Парсинг URL для извлечения базового имени и версии
- Семантическое сравнение версий через `packaging` библиотеку
- Обнаружение новых версий через сравнение tracked и discovered файлов
- Группировка версий по базовому имени файла

### ✅ 3. Migration Manager Module
- Валидация новых файлов (HTTP проверка, размер, хеш)
- Архивирование старых версий
- Активация новых версий
- Rollback механизм
- Пакетная миграция с приоритизацией

### ✅ 4. Alert System Module
- Централизованное логирование версионных событий
- Форматирование алертов для логов и Telegram
- Dashboard с метриками
- Специализированные форматы для разных типов событий

### ✅ 5. Enhanced Discovery Mode
- Интеграция с version_detector
- Метод `detect_version_upgrades()` для поиска обновлений
- Метод `run_full_discovery_with_version_check()` для полного цикла
- Автоматическая категоризация обнаруженных файлов

### ✅ 6. Enhanced CDN Fetcher
- Динамический конфиг: получение файлов из БД или config.py
- Обработка 404 ошибок со счетчиком
- Метод `check_404_errors()` для мониторинга проблемных файлов
- Метод `add_file_to_monitoring()` для динамического добавления

### ✅ 7. Enhanced Telegram Notifier
- Метод `send_version_alert()` - уведомление о новой версии
- Метод `send_migration_success()` - успешная миграция
- Метод `send_migration_failure()` - неудачная миграция
- Метод `send_404_critical()` - критическая 404 ошибка

## Оставшиеся задачи

### ⏳ 8. Scheduler Updates (main.py)
- Добавить еженедельный Discovery Mode в планировщик
- Добавить ежедневную проверку 404 ошибок
- Интеграция новых модулей в основной workflow

### ⏳ 9. CLI Commands
- `--discover` - запуск Discovery Mode вручную
- `--show-version-updates` - показать обнаруженные обновления
- `--migrate <file> --to-version <version>` - миграция конкретного файла
- `--rollback <file> --to-version <version>` - откат версии
- `--version-history <file>` - история версий файла
- `--migration-status` - статус всех миграций
- `--dashboard` - показать dashboard

### ⏳ 10. Integration Testing
- Тест: Discovery → обнаружение версий
- Тест: Валидация нового файла
- Тест: Миграция с архивированием
- Тест: Rollback механизм
- Тест: Обработка 404 ошибок
- Тест: Alert system
- Тест: Полный E2E workflow

## Технические детали

### Новые зависимости
```txt
packaging>=23.0  # Для семантического сравнения версий
```

### Workflow обнаружения и миграции

1. **Discovery Mode** (еженедельно) сканирует канарейка-страницы
2. **Version Detector** парсит URL и сравнивает версии
3. **Version Alert** создается при обнаружении новой версии
4. **Migration Manager** валидирует, архивирует старую, активирует новую
5. **Alert System** логирует события и отправляет в Telegram
6. **Metrics** сохраняются для dashboard

### Приоритизация миграций

```python
MIGRATION_DELAYS = {
    "CRITICAL": 0,        # Немедленно
    "HIGH": 3600,         # Через 1 час
    "MEDIUM": 86400,      # Через 24 часа
    "LOW": 604800         # Через неделю
}
```

### Edge Cases

1. **404 на старой версии**: Счетчик → после 3 подряд → Discovery Mode → поиск замены
2. **Изменение схемы именования**: Pattern matching + similarity analysis
3. **Множественные новые версии**: Выбор последней стабильной
4. **Rollback**: Команда `--rollback` + автоматический при ошибке миграции

## Архитектура

```
Scheduler
  ├── Hourly: check_and_analyze() - стандартный мониторинг
  ├── Weekly: run_discovery_and_migrate() - обнаружение версий
  └── Daily: check_404_errors() - проверка проблемных файлов

Discovery Mode
  └── version_detector.find_version_updates()
      └── migration_manager.perform_migration()
          ├── validate_new_version()
          ├── archive_old_version()
          ├── activate_new_version()
          └── alert_system.log_*()

CLI
  ├── --discover → discovery.run_full_discovery_with_version_check()
  ├── --migrate → manager.perform_migration()
  ├── --rollback → manager.rollback_to_version()
  └── --version-history → detector.get_all_versions_for_base()
```

## Метрики успеха

- ✅ 100 файлов в мониторинге (было 8)
- ✅ Автоматическое обнаружение новых версий
- ✅ Безопасная миграция с rollback
- ✅ Полная история версий в БД
- ✅ Централизованные алерты
- ⏳ Telegram интеграция (требует bot token)
- ⏳ Еженедельный Discovery Mode
- ⏳ CLI для ручного управления

## Дальнейшие улучшения

1. Автоматическое обновление `config.py` при миграциях
2. Web dashboard для визуализации
3. API endpoints для внешней интеграции
4. Playwright для более глубокого анализа
5. Мониторинг API endpoints Tilda
6. A/B тестирование новых версий
7. Автоматическое добавление обнаруженных файлов в мониторинг

## Файлы проекта

### Созданные модули:
- `src/version_detector.py` (400 строк)
- `src/migration_manager.py` (450 строк)
- `src/alert_system.py` (250 строк)

### Обновленные модули:
- `src/database.py` (+300 строк)
- `src/discovery.py` (+100 строк)
- `src/cdn_fetcher.py` (+80 строк)
- `src/telegram_notifier.py` (+150 строк)
- `main.py` (TODO: +150 строк)
- `requirements.txt` (+1 строка)

**Итого:** ~1900 строк нового/измененного кода

