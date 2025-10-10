import sys
from datetime import datetime
from pathlib import Path

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import logger
from db import Habits, SessionLocal, Task, User

router = Router()


async def get_user_habits_count(user_id: int) -> int:
    """Получает количество активных привычек пользователя."""
    async with SessionLocal() as session:
        result = await session.execute(
            select(Habits).where(Habits.user_id == user_id, Habits.active.is_(True))
        )
        habits = result.scalars().all()
        return len(habits)


async def get_user_tasks_count(user_id: int) -> tuple[int, int]:
    """Получает количество задач (выполненных, всего)."""
    async with SessionLocal() as session:
        # Все задачи на сегодня
        result_all = await session.execute(select(Task).where(Task.user_id == user_id))
        all_tasks = result_all.scalars().all()

        # Выполненные задачи
        result_done = await session.execute(
            select(Task).where(Task.user_id == user_id, Task.status == "done")
        )
        done_tasks = result_done.scalars().all()

        return len(done_tasks), len(all_tasks)


async def has_user(user_id: int) -> bool:
    """Проверяет, существует ли пользователь и завершен ли онбординг."""
    from sqlalchemy import select

    async with SessionLocal() as session:
        result = await session.execute(select(User).where(User.user_id == user_id))
        user = result.scalar_one_or_none()
        logger.info(f"Checking user {user_id}: exists={user is not None}, lang={user.lang if user else None}")
        # Проверяем, что пользователь существует И завершил онбординг (есть lang)
        return user is not None and user.lang is not None


@router.message(Command("today"))
async def cmd_today(message: Message):
    """Команда /today - показывает сводку на сегодня."""
    user_id = message.from_user.id

    # Проверяем, прошел ли пользователь онбординг
    if not await has_user(user_id):
        await message.answer(
            "Привет! Сначала нужно пройти настройку.\n\n" "Используй команду /start для начала работы."
        )
        return

    habits_count = await get_user_habits_count(user_id)
    tasks_done, tasks_total = await get_user_tasks_count(user_id)

    # Текущая дата
    today = datetime.now().strftime("%d.%m.%Y")

    # Проверяем пустые состояния
    if habits_count == 0 and tasks_total == 0:
        # Совсем пусто - предлагаем добавить первую привычку
        builder = InlineKeyboardBuilder()
        builder.button(text="Добавить привычку", callback_data="add_first_habit")
        builder.adjust(1)

        await message.answer(
            f"Сегодня {today} 📅\n\n" "Привычек пока нет. Добавим первую?» [Добавить привычку]",
            reply_markup=builder.as_markup(),
        )
        logger.info(f"User {user_id} viewed /today - no habits, no tasks")
        return

    if habits_count == 0:
        # Нет привычек, но есть задачи
        builder = InlineKeyboardBuilder()
        builder.button(text="Добавить привычку", callback_data="add_first_habit")
        builder.button(text="Показать задачи", callback_data="today_show_tasks")
        builder.adjust(1)

        await message.answer(
            f"Сегодня {today} 📅\n\n"
            f"Привычек пока нет. Задачи: {tasks_done}/{tasks_total}.\n\n"
            "Добавим первую?",
            reply_markup=builder.as_markup(),
        )
        logger.info(f"User {user_id} viewed /today - no habits, {tasks_total} tasks")
        return

    if tasks_total == 0:
        # Есть привычки, но нет задач
        builder = InlineKeyboardBuilder()
        builder.button(text="Поставить 3 главные задачи", callback_data="today_add_3_main")
        builder.button(text="Показать привычки", callback_data="today_show_habits")
        builder.adjust(1)

        await message.answer(
            f"Сегодня {today} 📅\n\n"
            f"Привычки: 0/{habits_count}.\n\n"
            "Сегодня без задач? Хочешь поставить 3 главные?",
            reply_markup=builder.as_markup(),
        )
        logger.info(f"User {user_id} viewed /today - {habits_count} habits, no tasks")
        return

    # Есть и привычки, и задачи
    builder = InlineKeyboardBuilder()

    builder.button(text="Добавить 3 главные", callback_data="today_add_3_main")

    builder.button(text="Показать привычки", callback_data="today_show_habits")
    builder.button(text="Показать задачи", callback_data="today_show_tasks")
    builder.adjust(1)

    await message.answer(
        f"Сегодня {today} 📅\n\n" f"Привычки: 0/{habits_count}\n" f"Задачи: {tasks_done}/{tasks_total}",
        reply_markup=builder.as_markup(),
    )

    logger.info(f"User {user_id} viewed /today - {habits_count} habits, " f"{tasks_done}/{tasks_total} tasks")


# Обработчики для кнопок из /today


@router.callback_query(F.data == "add_first_habit")
async def today_add_first_habit(callback: CallbackQuery, state: FSMContext):
    """Начинает добавление первой привычки из /today."""
    from .habits import AddHabitStates

    await state.clear()
    await callback.message.edit_text(
        "Название привычки? (кратко)\n\n" "Например: <i>Чтение 10м</i>, <i>Зарядка</i>, <i>Медитация</i>"
    )
    await state.set_state(AddHabitStates.title)
    await state.update_data(user_id=callback.from_user.id)
    await callback.answer()
    logger.info(f"User {callback.from_user.id} started adding first habit from /today")


@router.callback_query(F.data == "today_show_habits")
async def today_show_habits(callback: CallbackQuery):
    """Показывает список привычек из /today."""
    user_id = callback.from_user.id

    async with SessionLocal() as session:
        result = await session.execute(
            select(Habits).where(Habits.user_id == user_id).order_by(Habits.created_at)
        )
        habits = result.scalars().all()

    if not habits:
        builder = InlineKeyboardBuilder()
        builder.button(text="Добавить привычку", callback_data="add_first_habit")
        builder.adjust(1)

        await callback.message.edit_text(
            'У тебя ещё нет привычек. Начни с маленькой, например: "Чтение 10м".',
            reply_markup=builder.as_markup(),
        )
        await callback.answer()
        return

    # Показываем список
    habits_text = "Твои привычки:\n\n"
    builder = InlineKeyboardBuilder()

    for i, habit in enumerate(habits, start=1):
        status = "✅" if habit.active else "⏸"
        time_str = habit.time_of_day.strftime("%H:%M") if habit.time_of_day else "—"
        habits_text += f"{i}. {status} <b>{habit.title}</b> — {habit.schedule_type}, {time_str}\n"
        builder.button(text=f"✏️ {i}", callback_data=f"H_EDIT:{habit.id}")

    builder.button(text="➕ Добавить ещё", callback_data="add_first_habit")

    rows = []
    for i in range(0, len(habits), 4):
        rows.append(min(4, len(habits) - i))
    rows.append(1)
    builder.adjust(*rows)

    await callback.message.edit_text(habits_text, reply_markup=builder.as_markup())
    await callback.answer()


@router.callback_query(F.data == "today_show_tasks")
async def today_show_tasks(callback: CallbackQuery):
    """Показывает фильтры задач из /today."""
    builder = InlineKeyboardBuilder()
    builder.button(text="Сегодня", callback_data="TASKS_FILTER:today")
    builder.button(text="Неделя", callback_data="TASKS_FILTER:week")
    builder.button(text="Все", callback_data="TASKS_FILTER:all")
    builder.button(text="Активные", callback_data="TASKS_FILTER:active")
    builder.button(text="Выполненные", callback_data="TASKS_FILTER:done")
    builder.adjust(2, 3)

    await callback.message.edit_text("Показать задачи за…", reply_markup=builder.as_markup())
    await callback.answer()


@router.callback_query(F.data == "today_add_3_main")
async def today_add_3_main(callback: CallbackQuery):
    """Предлагает добавить 3 главные задачи."""
    await callback.message.edit_text(
        'Функция "3 главные задачи дня" в разработке.\n\n' "Пока используй /addtask для добавления задач."
    )
    await callback.answer()
    logger.info(f"User {callback.from_user.id} clicked add 3 main tasks (placeholder)")
