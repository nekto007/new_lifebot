# 🤖 Habit Tracker Bot

Telegram-бот для трекинга привычек и управления задачами с поддержкой делегирования и AI-генерации контента.

## 🎯 Основные возможности

### 📊 Трекинг привычек
- **Гибкое расписание**: ежедневные и еженедельные привычки
- **Умные напоминания**: с учётом часового пояса и тихих часов
- **AI-контент**: автоматическая генерация заданий для привычек (зарядка, чтение и т.д.)
- **Статистика**: отслеживание прогресса и истории выполнения

### ✅ Управление задачами
- **Дедлайны и приоритеты**: организация задач по важности
- **Быстрые действия**: кнопки для создания и управления задачами
- **Фильтрация**: просмотр задач по статусу и дате

### 👥 Делегирование задач
- **Белый список**: доверенные контакты для делегирования
- **Автоматические напоминания**: эскалация по мере приближения дедлайна
- **Двусторонние уведомления**: автор и исполнитель всегда в курсе статуса

### ⚙️ Персонализация
- **Многоязычность**: русский и английский интерфейс
- **Часовые пояса**: правильное время напоминаний
- **Тихие часы**: отключение уведомлений на ночь
- **Утренний пинг и вечерний отчёт**: настраиваемые ежедневные сводки

## 🚀 Быстрый старт

### Предварительные требования

- [Docker](https://docs.docker.com/get-docker/) и [Docker Compose](https://docs.docker.com/compose/install/)
- Telegram Bot Token (получить у [@BotFather](https://t.me/botfather))
- (Опционально) [OpenAI API Key](https://platform.openai.com/api-keys) для генерации AI-контента

### Установка и запуск

1. **Клонируйте репозиторий:**
```bash
git clone https://github.com/nekto007/new_lifebot
cd new_me
```

2. **Создайте файл `.env` из примера:**
```bash
cp .env.example .env
```

3. **Настройте переменные окружения в `.env`:**
```env
# Обязательно: токен вашего Telegram бота
TELEGRAM_TOKEN="123456789:ABCdefGHIjklMNOpqrsTUVwxyz"

# Опционально: OpenAI API для AI-контента
OPENAI_API_KEY="sk-..."
LLM_MODEL="gpt-5-nano"
```

4. **Запустите бота:**
```bash
docker-compose up -d
```

Готово! 🎉 Бот запущен и готов к работе.

5. **Проверьте логи (опционально):**
```bash
docker-compose logs -f bot
```

### Управление ботом

```bash
# Посмотреть логи
docker-compose logs -f bot

# Остановить бота
docker-compose down

# Перезапустить бота
docker-compose restart

# Обновить бота после изменений кода
docker-compose up -d --build

# Посмотреть статус
docker-compose ps

# Зайти внутрь контейнера (для отладки)
docker-compose exec bot /bin/bash
```

## 📋 Основные команды бота

### Начало работы
- `/start` - Регистрация и настройка профиля
- `/help` - Список всех команд
- `/menu` - Главное интерактивное меню

### Привычки
- `/addhabit` - Создать новую привычку
- `/habits` - Список всех привычек

### Задачи
- `/addtask` - Создать новую задачу
- `/tasks` - Список всех задач
- `/today` - Задачи на сегодня

### Делегирование
- `/trust <user_id>` - Добавить пользователя в доверенные
- `/delegate` - Делегировать задачу
- `/delegated` - Список делегированных задач
- `/assigned` - Задачи, назначенные вам

### Статистика и настройки
- `/stats` - Статистика выполнения
- `/journal` - История привычек
- `/settings` - Настройки профиля

## 🗄️ Данные и резервное копирование

Все данные хранятся в папках:
- `./data/` - база данных SQLite
- `./logs/` - логи приложения

Эти папки автоматически монтируются в контейнер, поэтому данные сохраняются при перезапуске.

### Резервное копирование

```bash
# Создать бэкап базы данных
cp data/data.db data/data.db.backup-$(date +%Y%m%d)

# Восстановить из бэкапа
cp data/data.db.backup-20251011 data/data.db
docker-compose restart
```

## 🔧 Конфигурация

### Переменные окружения (.env)

```env
# Обязательные параметры
TELEGRAM_TOKEN="ваш_токен_бота"

# База данных (уже настроено в docker-compose.yml)
DATABASE_URL="sqlite+aiosqlite:///./data/data.db"

# OpenAI для генерации контента (опционально)
OPENAI_API_KEY="ваш_ключ_openai"
LLM_MODEL="gpt-4o-mini"

# Логирование (опционально)
LOG_LEVEL="INFO"  # DEBUG, INFO, WARNING, ERROR
```


### Просмотр логов

```bash
# Все логи
docker-compose logs -f

# Только последние 100 строк
docker-compose logs --tail=100 bot

# Логи за последний час
docker-compose logs --since 1h bot
```

### Проверка базы данных

```bash
# Зайти в контейнер
docker-compose exec bot /bin/bash

# Открыть базу данных
sqlite3 /app/data/data.db

# Выполнить SQL-запрос
sqlite> SELECT COUNT(*) FROM users;
sqlite> .quit
```

## 🏗️ Архитектура

```
new_me/
├── src/
│   ├── bot.py                    # Точка входа приложения
│   ├── config.py                 # Конфигурация и логирование
│   ├── db.py                     # Модели базы данных (SQLAlchemy)
│   ├── scheduler.py              # Планировщик напоминаний (APScheduler)
│   ├── llm_service.py            # Интеграция с OpenAI
│   ├── delegation_reminders.py   # Напоминания для делегированных задач
│   ├── init_templates.py         # Инициализация шаблонов привычек
│   └── handlers/                 # Обработчики команд и callback'ов
│       ├── start.py              # Онбординг и регистрация
│       ├── habits.py             # Управление привычками
│       ├── tasks.py              # Управление задачами
│       ├── delegate.py           # Делегирование задач
│       ├── settings.py           # Настройки пользователя
│       ├── stats.py              # Статистика
│       ├── menu.py               # Главное меню
│       └── ...
├── locales/                      # Локализация (ru/en)
├── data/                         # База данных (монтируется из хоста)
├── logs/                         # Логи (монтируются из хоста)
├── Dockerfile                    # Docker-образ приложения
├── docker-compose.yml            # Оркестрация контейнеров
├── pyproject.toml                # Зависимости (uv/pip)
└── README.md                     # Этот файл
```

## 🛠️ Технологический стек

- **[Python 3.13](https://www.python.org/)** - Язык программирования
- **[aiogram 3.x](https://github.com/aiogram/aiogram)** - Async Telegram Bot framework
- **[SQLAlchemy 2.0](https://www.sqlalchemy.org/)** - Async ORM
- **[APScheduler](https://apscheduler.readthedocs.io/)** - Планировщик задач
- **[OpenAI API](https://platform.openai.com/)** - AI-генерация контента (опционально)
- **[Docker](https://www.docker.com/)** - Контейнеризация

## 🐛 Решение проблем

### Бот не запускается

```bash
# Проверьте логи на ошибки
docker-compose logs bot

# Проверьте, что указан правильный токен
cat .env | grep TELEGRAM_TOKEN

# Пересоберите образ
docker-compose down
docker-compose up -d --build
```

### База данных повреждена

```bash
# Остановите бота
docker-compose down

# Восстановите из бэкапа
cp data/data.db.backup-YYYYMMDD data/data.db

# Запустите снова
docker-compose up -d
```

### Контейнер постоянно перезапускается

```bash
# Посмотрите последние логи
docker-compose logs --tail=50 bot

# Проверьте статус
docker-compose ps

# Проверьте переменные окружения
docker-compose exec bot env | grep TELEGRAM
```

## 💻 Разработка без Docker

Если нужно запустить бота локально для разработки:

### Установка

```bash
# Установите Python 3.11+
python --version

# Установите uv (рекомендуется)
pip install uv

# Установите зависимости
uv pip install -e .

# Или через pip
pip install -e .
```

### Запуск

```bash
# Создайте .env
cp .env.example .env
# Отредактируйте .env

# Инициализируйте шаблоны (опционально)
python src/init_templates.py

# Запустите бота
python src/bot.py
```

### Pre-commit hooks

```bash
pip install pre-commit
pre-commit install
```

Хуки автоматически форматируют код при коммите:
- `black` - форматирование
- `ruff` - линтинг и автоисправления

## 📝 Известные ограничения

1. **Делегирование**: Требуется Telegram ID для `/trust` (можно узнать у [@userinfobot](https://t.me/userinfobot))
2. **LLM контент**: Пре-генерация за 5 минут до напоминания
3. **Напоминания о делегировании**: Проверка раз в день в 09:00 UTC

## 📄 Лицензия

This project is licensed under the MIT License - see the LICENSE file for details.
