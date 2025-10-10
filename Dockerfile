# Используем официальный Python образ
FROM python:3.13-slim

# Устанавливаем рабочую директорию
WORKDIR /app

# Устанавливаем системные зависимости
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Копируем файлы зависимостей
COPY pyproject.toml ./

# Устанавливаем uv для быстрой установки зависимостей
RUN pip install --no-cache-dir uv

# Устанавливаем зависимости проекта
RUN uv pip install --system --no-cache -e .

# Копируем исходный код приложения
COPY src/ ./src/
COPY locales/ ./locales/

# Создаём директорию для базы данных
RUN mkdir -p /app/data

# Устанавливаем переменную окружения для Python
ENV PYTHONUNBUFFERED=1

# Команда запуска бота
CMD ["python", "src/bot.py"]