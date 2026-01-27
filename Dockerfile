# ============================================
# Stage 1: Builder - Установка зависимостей
# ============================================
FROM python:3.13-slim AS builder

# Установить системные зависимости для компиляции Python пакетов
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    gcc \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

# Создать директорию для зависимостей
WORKDIR /install

# Копировать только requirements.txt для кэширования слоя
COPY requirements.txt .

# Установить Python зависимости в отдельную директорию
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ============================================
# Stage 2: Runtime - Финальный образ
# ============================================
FROM python:3.13-slim

# Метаданные образа
LABEL maintainer="tilda-update-checker"
LABEL description="Tilda CDN Update Checker - автоматический мониторинг изменений"
LABEL version="1.0.0"

# Установить runtime зависимости (только необходимые)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Создать непривилегированного пользователя
RUN useradd -m -u 1000 -s /bin/bash tilda && \
    mkdir -p /app /app/data /app/logs && \
    chown -R tilda:tilda /app

# Установить рабочую директорию
WORKDIR /app

# Копировать установленные зависимости из builder stage
COPY --from=builder /install /usr/local

# Копировать файлы приложения
COPY --chown=tilda:tilda . .

# Копировать healthcheck скрипт
COPY --chown=tilda:tilda healthcheck.py /app/healthcheck.py

# Копировать и сделать исполняемым entrypoint скрипт
COPY --chown=tilda:tilda entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

# Переключиться на непривилегированного пользователя
USER tilda

# Установить переменные окружения
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/home/tilda/.local/bin:${PATH}" \
    DATABASE_PATH=data/tilda_checker.db \
    LOG_FILE=logs/tilda_checker.log

# Volumes для персистентных данных
VOLUME ["/app/data", "/app/logs"]

# Healthcheck для мониторинга
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python /app/healthcheck.py

# Entrypoint
ENTRYPOINT ["/app/entrypoint.sh"]

# По умолчанию запускать в daemon режиме
CMD ["--daemon"]



