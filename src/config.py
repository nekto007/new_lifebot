import logging
import os
from logging.handlers import RotatingFileHandler

from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from dotenv import load_dotenv

load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./data.db")

# Language Learning API settings
# Note: Each user configures their own token via /language_setup command
LANGUAGE_API_URL = os.getenv("LANGUAGE_API_URL", "http://localhost:5001/api/telegram")
LANGUAGE_API_TIMEOUT = int(os.getenv("LANGUAGE_API_TIMEOUT", "30"))
LANGUAGE_CACHE_TTL = int(os.getenv("LANGUAGE_CACHE_TTL", "300"))

# Настройка логирования
logger = logging.getLogger("new_life_bot")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logger.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))
log_file = "bot.log"
file_handler = RotatingFileHandler(log_file, maxBytes=2 * 1024 * 1024, backupCount=5, encoding="utf-8")
file_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
console_handler = logging.StreamHandler()
console_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
logger.addHandler(file_handler)
logger.addHandler(console_handler)

# Фабрика свойств бота (parse_mode можно использовать глобально)
default_bot_properties = DefaultBotProperties(parse_mode=ParseMode.HTML)
