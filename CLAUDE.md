# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Language Preference

**ВАЖНО: Всегда отвечай на русском языке при работе с этим репозиторием.**

## Project Overview

Tilda Update Checker is an automated monitoring system for Tilda CDN files with advanced version control and automatic migration capabilities. It tracks 100+ JavaScript and CSS files across Tilda's CDN, detects changes via SHA-256 hashing, performs LLM-based analysis of changes, and automatically manages version migrations.

**Key Features:**
- Monitors 100 Tilda CDN files across 6 categories (core, members, ecommerce, zero_block, ui_components, utilities)
- Automatic version detection and semantic version comparison (semver)
- Automatic migration to new versions with rollback support
- Smart 404 handling with automatic replacement discovery
- Optional OpenAI API integration for LLM analysis of code changes
- Optional Telegram notifications for alerts
- SQLite database for tracking files, versions, changes, and announcements

## Development Setup

### Local Development

```bash
# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Setup environment
cp env.example .env
# Edit .env and add API keys if needed (optional)

# Initialize database
python -c "from src.database import db; db.init_db()"

# Run once for testing
python main.py --once
```

### Docker Development

```bash
# Local testing with Docker
docker-compose up -d

# View logs
docker-compose logs -f

# Stop
docker-compose down
```

## Common Commands

### Basic Operations

```bash
# Single check run (for testing)
python main.py --once

# Run in daemon mode (continuous monitoring)
python main.py --daemon

# Show recent announcements
python main.py --show-announcements
python main.py --show-announcements -n 20  # Show 20 announcements
```

### Version Monitoring

```bash
# Run Discovery Mode to find new versions
python main.py --discover

# Show discovered version updates
python main.py --show-version-updates

# Migrate specific file to new version
python main.py --migrate tilda-cart --to-version 1.2

# Rollback file to previous version
python main.py --rollback tilda-cart --to-version 1.1

# Show version history for a file
python main.py --version-history tilda-cart

# Show migration status
python main.py --migration-status

# Show dashboard with metrics
python main.py --dashboard
```

### Docker Commands

```bash
# Build and run
docker-compose up -d

# View logs
docker-compose logs -f tilda-checker

# Restart container
docker-compose restart

# Stop and remove
docker-compose down

# Rebuild after code changes
docker-compose up -d --build
```

## Architecture

### High-Level Data Flow

1. **Monitoring Pipeline:**
   ```
   cdn_fetcher → diff_detector → llm_analyzer → announcement_generator → database
   ```

2. **Version Monitoring Pipeline:**
   ```
   discovery → version_detector → migration_manager → alert_system → telegram_notifier
   ```

3. **404 Handling:**
   ```
   404 Error (3x) → Discovery Mode → Find Replacement → Auto-Migration → Alert
   ```

### Core Modules

- **`main.py`**: Entry point, CLI argument parsing, scheduler setup
- **`config.py`**: Configuration management, file categories, priorities, LLM prompts
- **`src/database.py`**: SQLAlchemy ORM models and database operations
- **`src/cdn_fetcher.py`**: Downloads files from Tilda CDN, handles HTTP requests
- **`src/diff_detector.py`**: Detects changes using SHA-256 hashing
- **`src/llm_analyzer.py`**: OpenAI API integration for analyzing code changes
- **`src/announcement.py`**: Generates user-friendly announcements from analysis
- **`src/discovery.py`**: Discovery Mode - finds new files and versions on CDN
- **`src/version_detector.py`**: Parses versions from URLs, semantic version comparison
- **`src/migration_manager.py`**: Manages version migrations and rollbacks
- **`src/alert_system.py`**: Alert generation and dashboard metrics
- **`src/telegram_notifier.py`**: Sends notifications to Telegram

### Database Schema

**Core Tables:**
- `files` (TrackedFile): Currently monitored files with versioning info
- `file_versions` (FileVersion): Archive of all file versions
- `changes` (Change): Detected changes between versions
- `announcements` (Announcement): Generated announcements from LLM analysis
- `discovered_files` (DiscoveredFile): New files found during Discovery Mode
- `version_alerts` (VersionAlert): Alerts about version updates
- `migration_metrics` (MigrationMetrics): Migration performance metrics

**Key Fields:**
- `TrackedFile.base_name`: Base name without version (e.g., "tilda-cart")
- `TrackedFile.version`: Current version (e.g., "1.1")
- `TrackedFile.is_active`: 1 = active, 0 = archived
- `TrackedFile.consecutive_404_count`: Counts consecutive 404 errors
- `TrackedFile.category`: File category (core, members, ecommerce, etc.)
- `TrackedFile.priority`: Migration priority (CRITICAL, HIGH, MEDIUM, LOW)

### Version Detection Logic

The system uses regex patterns to extract versions from filenames:
- Pattern 1: `tilda-cart-1.1.min.js` → base: "tilda-cart", version: "1.1"
- Pattern 2: `tilda-cart-v2.min.js` → base: "tilda-cart", version: "2"
- Pattern 3: `tilda-cart.1.0.min.js` → base: "tilda-cart", version: "1.0"
- Pattern 4: `tilda-cart.min.js` → base: "tilda-cart", version: None

Semantic version comparison uses Python's `packaging.version` library for proper ordering (e.g., 1.0 < 1.1 < 1.10 < 2.0).

### Scheduler Tasks (Daemon Mode)

When running in `--daemon` mode, APScheduler manages three recurring tasks:

1. **Hourly Check** (`check_and_analyze`): Monitors tracked files for changes
   - Interval: Every 1 hour (configurable via `TILDA_CHECK_INTERVAL`)

2. **Weekly Discovery** (`run_discovery_and_migrate`): Finds new versions and migrates
   - Schedule: Every Monday at 9:00 AM
   - Auto-migrates based on priority

3. **Daily 404 Check** (`check_404_errors`): Checks for broken files
   - Schedule: Daily at 8:00 AM
   - Triggers Discovery Mode if 3+ consecutive 404s detected

## Configuration

### Environment Variables

All configuration is managed through `.env` file (see `env.example` for template):

**Optional (System Works Without These):**
- `OPENAI_API_KEY`: OpenAI API key for LLM analysis
- `OPENAI_MODEL`: Model to use (default: gpt-4o-mini)
- `TELEGRAM_BOT_TOKEN`: Telegram bot token for notifications
- `TELEGRAM_CHAT_ID`: Telegram chat ID for messages

**Database:**
- `DATABASE_PATH`: Path to SQLite database (default: data/tilda_checker.db)

**Monitoring:**
- `TILDA_CHECK_INTERVAL`: Check interval in seconds (default: 3600 = 1 hour)
- `AUTO_MIGRATION_ENABLED`: Enable auto-migration (default: true)
- `CONSECUTIVE_404_THRESHOLD`: 404 errors before critical alert (default: 3)

**Logging:**
- `LOG_LEVEL`: Logging level (default: INFO)
- `LOG_FILE`: Log file path (default: logs/tilda_checker.log)

### Monitored Files Configuration

Files are configured in `config.py` under `TILDA_MONITORED_FILES` dictionary with structure:

```python
{
    "category_name": {
        "priority": "CRITICAL|HIGH|MEDIUM|LOW",
        "files": ["url1", "url2", ...]
    }
}
```

**Categories:**
- `core`: Essential Tilda framework files (CRITICAL priority)
- `members`: Membership system files (CRITICAL priority)
- `ecommerce`: E-commerce cart/catalog files (HIGH priority)
- `zero_block`: Zero Block editor files (HIGH priority)
- `ui_components`: UI widgets and components (MEDIUM priority)
- `utilities`: Helper utilities and tools (LOW priority)

## Testing

The project includes comprehensive testing reports in `docs/`:
- `TESTING_REPORT.md`: Original system testing
- `TESTING_REPORT_VERSION_MONITORING.md`: Version monitoring feature testing
- `REFACTORING_TEST_REPORT.md`: Refactoring validation

All core components have been manually tested including database schema, version detection, migration workflows, rollback mechanism, and CLI commands.

## Deployment

### Docker Deployment

The application is containerized using multi-stage Docker builds:
- Stage 1 (builder): Installs Python dependencies
- Stage 2 (runtime): Slim final image with non-privileged user

**Important Docker Considerations:**
- Runs as non-root user `tilda` (UID 1000)
- Requires volumes for `/app/data` (database) and `/app/logs` (logs)
- Healthcheck verifies database file exists
- Default command: `--daemon` mode

### Production Deployment (Dokploy)

The project is designed for deployment via Dokploy (Docker-based PaaS):
- Auto-deploy on `git push`
- Persistent volumes for data and logs
- Environment variables managed through Dokploy Web UI
- See `DEPLOYMENT.md` for detailed instructions

## Code Patterns

### Adding New CLI Commands

To add a new command:

1. Add argument in `main.py` `main()` function:
```python
parser.add_argument("--your-command", action="store_true", help="Description")
```

2. Create handler function:
```python
def handle_your_command():
    logger.info("Starting your command")
    if not db.init_db():
        logger.error("Database initialization failed")
        sys.exit(1)
    # Your logic here
```

3. Add to argument routing in `main()`:
```python
elif args.your_command:
    handle_your_command()
```

### Working with Database

Always use context managers for database sessions:

```python
from src.database import db

# Query example
with db.get_session() as session:
    files = session.query(TrackedFile).filter_by(is_active=1).all()

# Insert example
with db.get_session() as session:
    new_file = TrackedFile(url="...", ...)
    session.add(new_file)
    session.commit()
```

### Version Parsing

Use `version_detector.parse_file_url()` for consistent version extraction:

```python
from src.version_detector import detector

parsed = detector.parse_file_url("https://static.tildacdn.com/js/tilda-cart-1.1.min.js")
# Returns: {'base_name': 'tilda-cart', 'version': '1.1', 'file_type': 'js', ...}
```

### Migration Workflow

Migrations should follow this pattern:

```python
from src.migration_manager import manager

# 1. Validate new version
is_valid = manager.validate_new_version(new_url)

# 2. Archive current version
manager.archive_current_version(tracked_file)

# 3. Activate new version
manager.activate_new_version(tracked_file, new_url, new_content)

# 4. Record metrics
manager.record_migration_metric(...)
```

### Graceful Shutdown Pattern

При работе с scheduler или long-running процессами необходимо реализовать graceful shutdown для корректного завершения при получении сигналов SIGTERM/SIGINT:

```python
import signal
import sys
from apscheduler.schedulers.blocking import BlockingScheduler

def shutdown_handler(scheduler, signum=None, frame=None):
    """Обработчик graceful shutdown для scheduler"""
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

def run_daemon():
    """Запуск приложения в daemon режиме"""
    scheduler = BlockingScheduler()

    # Зарегистрировать обработчики сигналов ПЕРЕД запуском scheduler
    signal.signal(signal.SIGTERM, lambda s, f: shutdown_handler(scheduler, s, f))
    signal.signal(signal.SIGINT, lambda s, f: shutdown_handler(scheduler, s, f))

    # Настройка задач scheduler
    scheduler.add_job(check_and_analyze, 'interval', hours=1)

    try:
        logger.info("Запуск scheduler...")
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        shutdown_handler(scheduler)
```

**Важно для Docker/Dokploy:**
- Обработка SIGTERM критична для корректного завершения при `docker stop` или обновлении на Dokploy
- `wait=True` в `scheduler.shutdown()` гарантирует завершение текущих задач (до 10 секунд)
- Без graceful shutdown возможна потеря данных при незавершенных транзакциях БД

**Тестирование graceful shutdown:**
```bash
# Запустить приложение
python main.py --daemon &
APP_PID=$!

# Дать время на инициализацию
sleep 5

# Отправить SIGTERM
kill -SIGTERM $APP_PID

# Проверить логи - должно быть "Приложение остановлено"
grep "Приложение остановлено" logs/tilda_checker.log
```

## Important Notes

### LLM Analysis

- LLM analysis is **optional** - the system works without OpenAI API key
- When enabled, only "significant" changes are analyzed (based on `MIN_CHANGE_SIZE` in `config.py`)
- Diff size is limited to `MAX_DIFF_TOKENS` to manage API costs
- LLM response format is strictly JSON with fields: `change_type`, `severity`, `description`, `user_impact`, `recommendations`

### Telegram Notifications

- Telegram is **optional** - system works without bot token
- Supports separate chat IDs for different alert types (alerts, digest, discovery)
- Format can be Markdown or HTML (via `TELEGRAM_PARSE_MODE`)
- Includes silent mode option (`TELEGRAM_DISABLE_NOTIFICATION`)

### 404 Error Handling

- System tracks consecutive 404 errors per file
- After 3 consecutive 404s (configurable), triggers automatic Discovery Mode
- Discovery Mode searches for replacement versions
- If found, automatic migration is attempted
- Alert is sent via Telegram/logs regardless of migration outcome

### Migration Priorities

Migrations are delayed based on priority level (configurable in `env.example`):
- **CRITICAL**: Immediate migration
- **HIGH**: 1 hour delay (3600 seconds)
- **MEDIUM**: 24 hour delay (86400 seconds)
- **LOW**: 7 day delay (604800 seconds)

This allows for staged rollouts and reduces risk of breaking changes.

## Documentation

- **README.md**: User-facing documentation and quick start
- **DEPLOYMENT.md**: Production deployment guide for Dokploy
- **DOCKER_README.md**: Docker-specific instructions
- **docs/USAGE.md**: Detailed usage guide
- **docs/version-monitoring-plan.md**: Version monitoring architecture
- **docs/tilda-dependencies-analysis.md**: Analysis of Tilda's CDN structure
- **docs/EXPANSION_SUMMARY.md**: Feature expansion summary
