# 🐳 Docker Quick Start

Быстрый запуск **Tilda Update Checker** в Docker контейнере.

## Предварительные требования

- Docker 20.10+
- Docker Compose 2.0+ (опционально)

## Вариант 1: Docker Compose (рекомендуется)

### 1. Подготовка

```bash
# Клонировать репозиторий
git clone https://github.com/yourusername/tilda-update-checker.git
cd tilda-update-checker

# Создать .env файл
cp env.example .env

# Отредактировать .env (опционально добавить API ключи)
nano .env  # или vim, code, etc.
```

### 2. Запуск

```bash
# Запустить в фоновом режиме
docker-compose up -d

# Посмотреть логи
docker-compose logs -f

# Остановить
docker-compose down
```

### 3. Проверка

```bash
# Проверить статус
docker-compose ps

# Посмотреть dashboard
docker-compose exec tilda-checker python main.py --dashboard

# Посмотреть последние анонсы
docker-compose exec tilda-checker python main.py --show-announcements
```

---

## Вариант 2: Чистый Docker

### 1. Сборка образа

```bash
docker build -t tilda-update-checker .
```

### 2. Запуск

```bash
docker run -d \
  --name tilda-checker \
  --restart unless-stopped \
  -v $(pwd)/data:/app/data \
  -v $(pwd)/logs:/app/logs \
  --env-file .env \
  tilda-update-checker
```

### 3. Управление

```bash
# Посмотреть логи
docker logs -f tilda-checker

# Остановить
docker stop tilda-checker

# Запустить
docker start tilda-checker

# Удалить
docker rm -f tilda-checker
```

---

## Вариант 3: Однократная проверка

Запустить проверку один раз без daemon режима:

```bash
docker run --rm \
  -v $(pwd)/data:/app/data \
  -v $(pwd)/logs:/app/logs \
  --env-file .env \
  tilda-update-checker --once
```

---

## Volumes

Важные директории, которые нужно монтировать:

| Путь в контейнере | Назначение | Обязательно |
|-------------------|------------|-------------|
| `/app/data` | База данных SQLite | ✅ Да |
| `/app/logs` | Логи приложения | ✅ Да |

**⚠️ Без volumes данные будут потеряны при перезапуске контейнера!**

---

## Environment Variables

Минимальная конфигурация (в `.env`):

```env
# Python
PYTHONUNBUFFERED=1
TZ=Europe/Moscow

# Database
DATABASE_PATH=data/tilda_checker.db

# Logging
LOG_LEVEL=INFO
LOG_FILE=logs/tilda_checker.log

# Monitoring
TILDA_CHECK_INTERVAL=3600
```

Опциональные переменные:

```env
# OpenAI API (для LLM анализа)
OPENAI_API_KEY=sk-your-api-key-here

# Telegram (для уведомлений)
TELEGRAM_BOT_TOKEN=your-bot-token
TELEGRAM_CHAT_ID=your-chat-id
```

---

## CLI Команды

Выполнение команд внутри контейнера:

```bash
# Discovery Mode
docker exec tilda-checker python main.py --discover

# Показать версионные обновления
docker exec tilda-checker python main.py --show-version-updates

# Миграция конкретного файла
docker exec tilda-checker python main.py --migrate tilda-cart --to-version 1.2

# История версий
docker exec tilda-checker python main.py --version-history tilda-cart

# Dashboard
docker exec tilda-checker python main.py --dashboard

# Статус миграций
docker exec tilda-checker python main.py --migration-status
```

---

## Troubleshooting

### Контейнер не запускается

```bash
# Посмотреть логи
docker logs tilda-checker

# Проверить образ
docker images | grep tilda

# Пересоздать контейнер
docker rm -f tilda-checker
docker-compose up -d
```

### База данных не сохраняется

Проверьте, что volumes правильно примонтированы:

```bash
docker inspect tilda-checker | grep -A 10 "Mounts"
```

### Проблемы с правами

```bash
# Дать права на директории
chmod -R 755 data logs
chown -R $(whoami):$(whoami) data logs
```

---

## Production Deployment

Для production рекомендуется использовать **Dokploy**:

**📖 [Полная инструкция по деплою через Dokploy](DEPLOYMENT.md)**

Dokploy предоставляет:
- Автоматический деплой при git push
- Web UI для управления
- Мониторинг ресурсов
- Быстрый откат версий
- Multi-server поддержку

---

## Полезные команды

```bash
# Войти в shell контейнера
docker exec -it tilda-checker bash

# Посмотреть процессы
docker top tilda-checker

# Посмотреть статистику
docker stats tilda-checker

# Экспортировать базу данных
docker cp tilda-checker:/app/data/tilda_checker.db ./backup.db

# Импортировать базу данных
docker cp ./backup.db tilda-checker:/app/data/tilda_checker.db
docker restart tilda-checker
```

---

## Обновление образа

После изменений в коде:

```bash
# Пересобрать образ
docker-compose build

# Или
docker build -t tilda-update-checker .

# Перезапустить с новым образом
docker-compose up -d

# Или
docker stop tilda-checker
docker rm tilda-checker
docker run -d ... tilda-update-checker
```

---

## Размер образа

| Компонент | Размер |
|-----------|--------|
| Base image (python:3.13-slim) | ~50MB |
| Dependencies | ~80-100MB |
| Application code | ~5MB |
| **Total** | **~150-200MB** |

---

Готово! Приложение запущено в Docker 🐳



