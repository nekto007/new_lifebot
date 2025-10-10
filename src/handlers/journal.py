import sys
from pathlib import Path

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import logger

router = Router()


@router.message(Command("journal"))
async def cmd_journal(message: Message):
    """Команда /journal - показывает дневник."""
    user_id = message.from_user.id

    builder = InlineKeyboardBuilder()
    builder.button(text="Добавить запись", callback_data="journal_add")
    builder.adjust(1)

    await message.answer(
        "Пока нет записей. Сегодня вечером я спрошу, как прошёл день 🌙",
        reply_markup=builder.as_markup(),
    )

    logger.info(f"User {user_id} viewed /journal - no entries yet")
