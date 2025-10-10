import sys
from pathlib import Path

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import logger
from db import Habits, SessionLocal, Task

router = Router()


@router.message(Command("stats"))
async def cmd_stats(message: Message):
    """Команда /stats - показывает статистику."""
    user_id = message.from_user.id

    # Проверяем наличие данных
    async with SessionLocal() as session:
        habits_result = await session.execute(select(Habits).where(Habits.user_id == user_id))
        habits = habits_result.scalars().all()

        tasks_result = await session.execute(select(Task).where(Task.user_id == user_id))
        tasks = tasks_result.scalars().all()

    # Проверка пустого состояния
    if not habits and not tasks:
        await message.answer("Пока мало данных для статистики — вернусь к тебе через пару дней 📊")
        logger.info(f"User {user_id} viewed /stats - no data yet")
        return

    builder = InlineKeyboardBuilder()
    builder.button(text="День", callback_data="stats_period_day")
    builder.button(text="Неделя", callback_data="stats_period_week")
    builder.button(text="Месяц", callback_data="stats_period_month")
    builder.adjust(3)

    stats_text = "Статистика за сегодня:\n\n"
    stats_text += f"Привычки: {len(habits)}\n"
    stats_text += f"Задачи: {len(tasks)}\n\n"
    stats_text += "Детальная статистика будет доступна в следующей версии."

    await message.answer(stats_text, reply_markup=builder.as_markup())
    logger.info(f"User {user_id} viewed /stats - {len(habits)} habits, {len(tasks)} tasks")
