import sys
from pathlib import Path

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import logger

router = Router()


@router.message(Command("help"))
async def cmd_help(message: Message):
    """Команда /help - показывает список доступных команд."""
    help_text = (
        "<b>📋 Основные команды:</b>\n\n"
        "<b>Сегодня:</b>\n"
        "/today — сводка по дню\n"
        "/menu — главное меню\n\n"
        "<b>Привычки:</b>\n"
        "/addhabit — добавить привычку\n"
        "/habits — список привычек\n\n"
        "<b>Задачи:</b>\n"
        "/addtask — создать задачу\n"
        "/tasks — список задач\n\n"
        "<b>Делегирование:</b>\n"
        "/trust &lt;user_id&gt; — добавить доверенного пользователя\n"
        "/delegate — делегировать задачу\n"
        "/delegated — мои делегированные задачи\n"
        "/assigned — задачи, назначенные мне\n\n"
        "<b>Статистика и журнал:</b>\n"
        "/stats — статистика выполнения\n"
        "/journal — записи в дневнике\n\n"
        "<b>Настройки:</b>\n"
        "/settings — настройки профиля\n"
        "/strict — режим антислива\n\n"
        "💡 <i>Нужна помощь? Просто напиши словами!</i>"
    )

    await message.answer(help_text)
    logger.info(f"User {message.from_user.id} viewed /help")
