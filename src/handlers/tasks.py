"""Обработчики команд для управления задачами."""

import sys
from datetime import date as dt_date
from datetime import datetime
from datetime import time as dt_time
from pathlib import Path

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import logger
from db import SessionLocal, Task, User

router = Router()


class AddTaskStates(StatesGroup):
    """Состояния FSM для добавления задачи."""

    enter_title = State()
    enter_date = State()
    enter_time = State()
    enter_priority = State()


class EditTaskStates(StatesGroup):
    """Состояния FSM для редактирования задачи."""

    reschedule_date = State()


def parse_date_input(text: str, user_tz: str = "UTC") -> dt_date | None:
    """
    Парсит дату из пользовательского ввода.

    Поддерживаемые форматы:
    - 2025-10-05
    - 05.10.2025
    - завтра, сегодня
    - пн, вт, ср, чт, пт, сб, вс
    """
    text = text.lower().strip()

    # Сегодня
    if text in ["сегодня", "today", ""]:
        return dt_date.today()

    # Завтра
    if text in ["завтра", "tomorrow"]:
        from datetime import timedelta

        return dt_date.today() + timedelta(days=1)

    # Послезавтра
    if text in ["послезавтра", "aftertomorrow"]:
        from datetime import timedelta

        return dt_date.today() + timedelta(days=2)

    # Дни недели
    weekdays_ru = {
        "пн": 0,
        "понедельник": 0,
        "вт": 1,
        "вторник": 1,
        "ср": 2,
        "среда": 2,
        "чт": 3,
        "четверг": 3,
        "пт": 4,
        "пятница": 4,
        "сб": 5,
        "суббота": 5,
        "вс": 6,
        "воскресенье": 6,
    }

    if text in weekdays_ru:
        from datetime import timedelta

        target_weekday = weekdays_ru[text]
        today = dt_date.today()
        current_weekday = today.weekday()

        days_ahead = target_weekday - current_weekday
        if days_ahead <= 0:  # Если день уже был на этой неделе, берём следующую
            days_ahead += 7

        return today + timedelta(days=days_ahead)

    # Формат ISO: 2025-10-05
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        pass

    # Формат DD.MM.YYYY: 05.10.2025
    try:
        return datetime.strptime(text, "%d.%m.%Y").date()
    except ValueError:
        pass

    # Формат DD.MM: 05.10 (текущий или следующий год)
    try:
        parsed = datetime.strptime(text, "%d.%m")
        year = dt_date.today().year
        result = parsed.replace(year=year).date()

        # Если дата уже прошла в этом году, берём следующий год
        if result < dt_date.today():
            result = result.replace(year=year + 1)

        return result
    except ValueError:
        pass

    return None


def parse_time_input(text: str) -> dt_time | None:
    """
    Парсит время из пользовательского ввода.

    Поддерживаемые форматы:
    - HH:MM (14:30)
    - HH (14 → 14:00)
    - пусто (без времени)
    """
    text = text.strip()

    if not text or text in ["-", "нет", "no"]:
        return None

    # HH:MM
    try:
        return datetime.strptime(text, "%H:%M").time()
    except ValueError:
        pass

    # HH
    try:
        hour = int(text)
        if 0 <= hour <= 23:
            return dt_time(hour=hour, minute=0)
    except ValueError:
        pass

    return None


async def get_user(user_id: int) -> User | None:
    """Получает пользователя из БД."""
    async with SessionLocal() as session:
        result = await session.execute(select(User).where(User.user_id == user_id))
        return result.scalar_one_or_none()


@router.message(Command("addtask"))
async def cmd_addtask(message: Message, state: FSMContext):
    """Команда /addtask - начинает процесс добавления задачи."""
    user_id = message.from_user.id

    # Проверяем, прошел ли пользователь онбординг
    user = await get_user(user_id)
    if not user or not user.lang:
        await message.answer(
            "Привет! Сначала нужно пройти настройку.\n\n" "Используй команду /start для начала работы."
        )
        return

    await state.set_state(AddTaskStates.enter_title)
    await message.answer("Текст задачи?")


@router.callback_query(F.data == "add_task_start")
async def add_task_from_button(callback: CallbackQuery, state: FSMContext):
    """Начинает процесс добавления задачи из кнопки."""
    user_id = callback.from_user.id

    # Проверяем, прошел ли пользователь онбординг
    user = await get_user(user_id)
    if not user or not user.lang:
        await callback.message.edit_text(
            "Привет! Сначала нужно пройти настройку.\n\n" "Используй команду /start для начала работы."
        )
        await callback.answer()
        return

    await state.set_state(AddTaskStates.enter_title)
    await callback.message.edit_text("Текст задачи?")
    await callback.answer()


@router.message(AddTaskStates.enter_title)
async def process_task_title(message: Message, state: FSMContext):
    """Обрабатывает ввод названия задачи."""
    title = message.text.strip()

    if not title:
        await message.answer("Название задачи не может быть пустым. Попробуй ещё раз:")
        return

    if len(title) > 255:
        await message.answer("Слишком длинное название (макс. 255 символов). Попробуй короче:")
        return

    await state.update_data(title=title)
    await state.set_state(AddTaskStates.enter_date)

    # Показываем кнопки с быстрым выбором даты
    builder = InlineKeyboardBuilder()
    builder.button(text="Сегодня", callback_data="TASK_DATE:today")
    builder.button(text="Завтра", callback_data="TASK_DATE:tomorrow")
    builder.button(text="Пн", callback_data="TASK_DATE:mon")
    builder.button(text="Вт", callback_data="TASK_DATE:tue")
    builder.button(text="Ср", callback_data="TASK_DATE:wed")
    builder.button(text="Чт", callback_data="TASK_DATE:thu")
    builder.button(text="Пт", callback_data="TASK_DATE:fri")
    builder.adjust(2, 5)

    await message.answer(
        "Дата? (Enter — сегодня)\n\n" "Можно ввести: 2025-10-05, 05.10, завтра, пт",
        reply_markup=builder.as_markup(),
    )


@router.callback_query(F.data.startswith("TASK_DATE:"))
async def process_task_date_button(callback: CallbackQuery, state: FSMContext):
    """Обрабатывает клик по кнопке выбора даты."""
    current_state = await state.get_state()
    if current_state != AddTaskStates.enter_date:
        await callback.answer("Эта кнопка уже неактуальна", show_alert=True)
        return

    date_code = callback.data.split(":")[1]

    date_map = {
        "today": "сегодня",
        "tomorrow": "завтра",
        "mon": "пн",
        "tue": "вт",
        "wed": "ср",
        "thu": "чт",
        "fri": "пт",
    }

    date_str = date_map.get(date_code, "сегодня")
    parsed_date = parse_date_input(date_str)

    if not parsed_date:
        await callback.answer("Ошибка парсинга даты", show_alert=True)
        return

    await state.update_data(due_date=parsed_date)
    await state.set_state(AddTaskStates.enter_time)

    # Показываем кнопки с быстрым выбором времени
    builder = InlineKeyboardBuilder()
    builder.button(text="Без времени", callback_data="TASK_TIME:none")
    builder.button(text="09:00", callback_data="TASK_TIME:09:00")
    builder.button(text="12:00", callback_data="TASK_TIME:12:00")
    builder.button(text="15:00", callback_data="TASK_TIME:15:00")
    builder.button(text="18:00", callback_data="TASK_TIME:18:00")
    builder.adjust(1, 4)

    await callback.message.edit_text(
        f"Дата: {parsed_date.strftime('%d.%m.%Y')}\n\n"
        "Время? (Enter — без времени)\n\n"
        "Можно ввести: 14:30, 14, или оставить пустым",
        reply_markup=builder.as_markup(),
    )
    await callback.answer()


@router.message(AddTaskStates.enter_date)
async def process_task_date_text(message: Message, state: FSMContext):
    """Обрабатывает текстовый ввод даты."""
    date_input = message.text.strip()

    user = await get_user(message.from_user.id)
    user_tz = user.tz if user else "UTC"

    parsed_date = parse_date_input(date_input, user_tz)

    if not parsed_date:
        await message.answer(
            f"Дата «{date_input}» не распознана. Попробуй ещё раз.\n\n"
            "Примеры: 2025-10-05, 05.10, завтра, пт"
        )
        return

    await state.update_data(due_date=parsed_date)
    await state.set_state(AddTaskStates.enter_time)

    # Показываем кнопки с быстрым выбором времени
    builder = InlineKeyboardBuilder()
    builder.button(text="Без времени", callback_data="TASK_TIME:none")
    builder.button(text="09:00", callback_data="TASK_TIME:09:00")
    builder.button(text="12:00", callback_data="TASK_TIME:12:00")
    builder.button(text="15:00", callback_data="TASK_TIME:15:00")
    builder.button(text="18:00", callback_data="TASK_TIME:18:00")
    builder.adjust(1, 4)

    await message.answer(
        "Время? (Enter — без времени)\n\n" "Можно ввести: 14:30, 14, или оставить пустым",
        reply_markup=builder.as_markup(),
    )


@router.callback_query(F.data.startswith("TASK_TIME:"))
async def process_task_time_button(callback: CallbackQuery, state: FSMContext):
    """Обрабатывает клик по кнопке выбора времени."""
    current_state = await state.get_state()
    if current_state != AddTaskStates.enter_time:
        await callback.answer("Эта кнопка уже неактуальна", show_alert=True)
        return

    time_str = callback.data.split(":")[1]

    if time_str == "none":
        parsed_time = None
    else:
        # Формат TASK_TIME:HH:MM → берём HH:MM
        time_str = ":".join(callback.data.split(":")[1:3])
        parsed_time = parse_time_input(time_str)

    await state.update_data(time_of_day=parsed_time)
    await state.set_state(AddTaskStates.enter_priority)

    # Показываем кнопки выбора приоритета
    builder = InlineKeyboardBuilder()
    builder.button(text="1️⃣ Высокий", callback_data="TASK_PRIORITY:1")
    builder.button(text="2️⃣ Средний", callback_data="TASK_PRIORITY:2")
    builder.button(text="3️⃣ Низкий", callback_data="TASK_PRIORITY:3")
    builder.adjust(1)

    data = await state.get_data()
    due_date = data.get("due_date")
    time_info = f" в {parsed_time.strftime('%H:%M')}" if parsed_time else ""

    await callback.message.edit_text(
        f"Дата: {due_date.strftime('%d.%m.%Y')}{time_info}\n\n"
        "Приоритет?\n"
        "1 — высокий\n"
        "2 — средний\n"
        "3 — низкий",
        reply_markup=builder.as_markup(),
    )
    await callback.answer()


@router.message(AddTaskStates.enter_time)
async def process_task_time_text(message: Message, state: FSMContext):
    """Обрабатывает текстовый ввод времени."""
    time_input = message.text.strip()

    parsed_time = parse_time_input(time_input)

    # Пустой ввод или "-" = без времени (это ОК)
    if not time_input or time_input == "-":
        parsed_time = None
    elif parsed_time is None:
        # Не смогли распарсить непустой ввод
        await message.answer(
            f"Время «{time_input}» не распознано. Попробуй ещё раз.\n\n"
            "Примеры: 14:30, 14, или Enter для пропуска"
        )
        return

    await state.update_data(time_of_day=parsed_time)
    await state.set_state(AddTaskStates.enter_priority)

    # Показываем кнопки выбора приоритета
    builder = InlineKeyboardBuilder()
    builder.button(text="1️⃣ Высокий", callback_data="TASK_PRIORITY:1")
    builder.button(text="2️⃣ Средний", callback_data="TASK_PRIORITY:2")
    builder.button(text="3️⃣ Низкий", callback_data="TASK_PRIORITY:3")
    builder.adjust(1)

    await message.answer(
        "Приоритет?\n" "1 — высокий\n" "2 — средний\n" "3 — низкий",
        reply_markup=builder.as_markup(),
    )


@router.callback_query(F.data.startswith("TASK_PRIORITY:"))
async def process_task_priority_button(callback: CallbackQuery, state: FSMContext):
    """Обрабатывает клик по кнопке выбора приоритета и создаёт задачу."""
    current_state = await state.get_state()
    if current_state != AddTaskStates.enter_priority:
        await callback.answer("Эта кнопка уже неактуальна", show_alert=True)
        return

    priority = int(callback.data.split(":")[1])

    # Получаем все данные из состояния
    data = await state.get_data()
    title = data["title"]
    due_date = data["due_date"]
    time_of_day = data.get("time_of_day")

    user_id = callback.from_user.id

    # Создаём задачу в БД
    async with SessionLocal() as session:
        new_task = Task(
            user_id=user_id,
            title=title,
            due_date=due_date,
            time_of_day=time_of_day,
            priority=priority,
            status="pending",
        )
        session.add(new_task)
        await session.commit()
        await session.refresh(new_task)

        logger.info(f"User {user_id} created task '{title}' " f"for {due_date} (priority {priority})")

    # Формируем сообщение подтверждения
    priority_labels = {1: "высокий", 2: "средний", 3: "низкий"}
    time_info = f" в {time_of_day.strftime('%H:%M')}" if time_of_day else ""

    # Создаём кнопки для дальнейших действий
    builder = InlineKeyboardBuilder()
    builder.button(text="➕ Добавить ещё задачу", callback_data="add_task_start")
    builder.button(text="📋 Главное меню", callback_data="back_to_menu")
    builder.adjust(1)

    await callback.message.edit_text(
        f"Создал задачу «{title}» на {due_date.strftime('%d.%m.%Y')}{time_info}. "
        f"Приоритет {priority_labels[priority]}. ✅",
        reply_markup=builder.as_markup(),
    )

    await state.clear()
    await callback.answer()


@router.message(AddTaskStates.enter_priority)
async def process_task_priority_text(message: Message, state: FSMContext):
    """Обрабатывает текстовый ввод приоритета и создаёт задачу."""
    priority_input = message.text.strip()

    try:
        priority = int(priority_input)
        if priority not in [1, 2, 3]:
            raise ValueError
    except ValueError:
        await message.answer("Приоритет должен быть 1, 2 или 3. Попробуй ещё раз:")
        return

    # Получаем все данные из состояния
    data = await state.get_data()
    title = data["title"]
    due_date = data["due_date"]
    time_of_day = data.get("time_of_day")

    user_id = message.from_user.id

    # Создаём задачу в БД
    async with SessionLocal() as session:
        new_task = Task(
            user_id=user_id,
            title=title,
            due_date=due_date,
            time_of_day=time_of_day,
            priority=priority,
            status="pending",
        )
        session.add(new_task)
        await session.commit()
        await session.refresh(new_task)

        logger.info(f"User {user_id} created task '{title}' " f"for {due_date} (priority {priority})")

    # Формируем сообщение подтверждения
    priority_labels = {1: "высокий", 2: "средний", 3: "низкий"}
    time_info = f" в {time_of_day.strftime('%H:%M')}" if time_of_day else ""

    # Создаём кнопки для дальнейших действий
    builder = InlineKeyboardBuilder()
    builder.button(text="➕ Добавить ещё задачу", callback_data="add_task_start")
    builder.button(text="📋 Главное меню", callback_data="back_to_menu")
    builder.adjust(1)

    await message.answer(
        f"Создал задачу «{title}» на {due_date.strftime('%d.%m.%Y')}{time_info}. "
        f"Приоритет {priority_labels[priority]}. ✅",
        reply_markup=builder.as_markup(),
    )

    await state.clear()


@router.message(Command("tasks"))
async def cmd_tasks(message: Message):
    """Команда /tasks - показывает список задач с фильтрами."""
    user_id = message.from_user.id

    # Проверяем, прошел ли пользователь онбординг
    user = await get_user(user_id)
    if not user or not user.lang:
        await message.answer(
            "Привет! Сначала нужно пройти настройку.\n\n" "Используй команду /start для начала работы."
        )
        return

    # Показываем кнопки фильтров
    builder = InlineKeyboardBuilder()
    builder.button(text="Сегодня", callback_data="TASKS_FILTER:today")
    builder.button(text="Неделя", callback_data="TASKS_FILTER:week")
    builder.button(text="Все", callback_data="TASKS_FILTER:all")
    builder.button(text="Активные", callback_data="TASKS_FILTER:active")
    builder.button(text="Выполненные", callback_data="TASKS_FILTER:done")
    builder.adjust(2, 3)

    await message.answer("Показать задачи за…", reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("TASKS_FILTER:"))
async def tasks_filter_callback(callback: CallbackQuery):
    """Показывает список задач с выбранным фильтром."""
    user_id = callback.from_user.id
    filter_type = callback.data.split(":")[1]

    async with SessionLocal() as session:
        # Базовый запрос
        query = select(Task).where(Task.user_id == user_id)

        # Применяем фильтр
        today = dt_date.today()

        if filter_type == "today":
            query = query.where(Task.due_date == today)
        elif filter_type == "week":
            from datetime import timedelta

            week_end = today + timedelta(days=7)
            query = query.where(Task.due_date >= today, Task.due_date <= week_end)
        elif filter_type == "active":
            query = query.where(Task.status == "pending")
        elif filter_type == "done":
            query = query.where(Task.status == "done")
        # "all" - без дополнительного фильтра

        # Сортируем по дате, приоритету
        query = query.order_by(Task.due_date, Task.priority)

        result = await session.execute(query)
        tasks = result.scalars().all()

    if not tasks:
        filter_labels = {
            "today": "сегодня",
            "week": "на неделю",
            "all": "всего",
            "active": "активных",
            "done": "выполненных",
        }

        await callback.message.edit_text(
            f"Задач ({filter_labels.get(filter_type, filter_type)}) пока нет.\n\n"
            "Используй /addtask для создания первой задачи."
        )
        await callback.answer()
        return

    # Формируем список задач
    status_emoji = {"pending": "⏳", "done": "✅", "cancelled": "❌"}

    priority_emoji = {1: "🔴", 2: "🟡", 3: "🟢"}

    lines = []
    for i, task in enumerate(tasks, 1):
        status = status_emoji.get(task.status, "")
        priority = priority_emoji.get(task.priority, "")
        date_str = task.due_date.strftime("%d.%m") if task.due_date else "?"
        time_str = f" {task.time_of_day.strftime('%H:%M')}" if task.time_of_day else ""

        lines.append(f"{i}. {status} {priority} {task.title} — {date_str}{time_str}")

    text = "\n".join(lines)

    # Кнопки управления (показываем только для первой задачи для простоты)
    # В реальной версии можно показывать inline-кнопки для каждой
    if tasks:
        builder = InlineKeyboardBuilder()

        # Показываем кнопки для каждой задачи
        for i, task in enumerate(tasks[:10], 1):  # Лимит 10 задач
            builder.button(text=f"✏️ {i}", callback_data=f"T_EDIT:{task.id}")

        builder.adjust(5)  # 5 кнопок в ряд

        await callback.message.edit_text(
            f"Задачи:\n\n{text}\n\n" "Нажми на номер для управления задачей.",
            reply_markup=builder.as_markup(),
        )
    else:
        await callback.message.edit_text(text)

    await callback.answer()


@router.callback_query(F.data.startswith("T_EDIT:"))
async def task_edit_menu_callback(callback: CallbackQuery):
    """Показывает меню редактирования задачи."""
    user_id = callback.from_user.id
    task_id = int(callback.data.split(":")[1])

    async with SessionLocal() as session:
        task = await session.get(Task, task_id)

        if not task or task.user_id != user_id:
            await callback.answer("Задача не найдена", show_alert=True)
            return

        # Формируем описание задачи
        date_str = task.due_date.strftime("%d.%m.%Y") if task.due_date else "без даты"
        time_str = f" в {task.time_of_day.strftime('%H:%M')}" if task.time_of_day else ""
        priority_labels = {1: "высокий", 2: "средний", 3: "низкий"}
        priority_str = priority_labels.get(task.priority, "?")

        status_labels = {
            "pending": "⏳ В работе",
            "done": "✅ Выполнено",
            "cancelled": "❌ Отменено",
        }
        status_str = status_labels.get(task.status, task.status)

        # Кнопки управления
        builder = InlineKeyboardBuilder()

        if task.status == "pending":
            builder.button(text="✅ Сделано", callback_data=f"T_D:{task_id}")
        else:
            builder.button(text="↩️ Вернуть в работу", callback_data=f"T_REOPEN:{task_id}")

        builder.button(text="🔁 Перенести", callback_data=f"T_MOVE:{task_id}")
        builder.button(text="🗑 Удалить", callback_data=f"T_DEL:{task_id}")
        builder.button(text="« Назад к списку", callback_data="TASKS_FILTER:all")
        builder.button(text="« Назад в меню", callback_data="back_to_menu")
        builder.adjust(1)

        await callback.message.edit_text(
            f"Задача: <b>{task.title}</b>\n\n"
            f"📅 Дата: {date_str}{time_str}\n"
            f"🎯 Приоритет: {priority_str}\n"
            f"📊 Статус: {status_str}",
            reply_markup=builder.as_markup(),
        )

    await callback.answer()


@router.callback_query(F.data.startswith("T_D:"))
async def task_done_callback(callback: CallbackQuery):
    """Отмечает задачу как выполненную."""
    user_id = callback.from_user.id
    task_id = int(callback.data.split(":")[1])

    async with SessionLocal() as session:
        task = await session.get(Task, task_id)

        if not task or task.user_id != user_id:
            await callback.answer("Задача не найдена", show_alert=True)
            return

        task.status = "done"
        await session.commit()

        logger.info(f"User {user_id} marked task {task_id} as done")

    await callback.answer("✅ Задача выполнена!", show_alert=True)

    # Обновляем меню
    await task_edit_menu_callback(
        CallbackQuery(
            id=callback.id,
            from_user=callback.from_user,
            message=callback.message,
            chat_instance=callback.chat_instance,
            data=f"T_EDIT:{task_id}",
        )
    )


@router.callback_query(F.data.startswith("T_REOPEN:"))
async def task_reopen_callback(callback: CallbackQuery):
    """Возвращает задачу в статус pending."""
    user_id = callback.from_user.id
    task_id = int(callback.data.split(":")[1])

    async with SessionLocal() as session:
        task = await session.get(Task, task_id)

        if not task or task.user_id != user_id:
            await callback.answer("Задача не найдена", show_alert=True)
            return

        task.status = "pending"
        await session.commit()

        logger.info(f"User {user_id} reopened task {task_id}")

    await callback.answer("↩️ Задача возвращена в работу", show_alert=True)

    # Обновляем меню
    await task_edit_menu_callback(
        CallbackQuery(
            id=callback.id,
            from_user=callback.from_user,
            message=callback.message,
            chat_instance=callback.chat_instance,
            data=f"T_EDIT:{task_id}",
        )
    )


@router.callback_query(F.data.startswith("T_MOVE:"))
async def task_move_callback(callback: CallbackQuery, state: FSMContext):
    """Начинает процесс переноса задачи на другую дату."""
    user_id = callback.from_user.id
    task_id = int(callback.data.split(":")[1])

    async with SessionLocal() as session:
        task = await session.get(Task, task_id)

        if not task or task.user_id != user_id:
            await callback.answer("Задача не найдена", show_alert=True)
            return

        await state.update_data(task_id=task_id)
        await state.set_state(EditTaskStates.reschedule_date)

        # Кнопки быстрого выбора даты
        builder = InlineKeyboardBuilder()
        builder.button(text="Сегодня", callback_data="TASK_RESCHEDULE:today")
        builder.button(text="Завтра", callback_data="TASK_RESCHEDULE:tomorrow")
        builder.button(text="Пн", callback_data="TASK_RESCHEDULE:mon")
        builder.button(text="Вт", callback_data="TASK_RESCHEDULE:tue")
        builder.button(text="Ср", callback_data="TASK_RESCHEDULE:wed")
        builder.button(text="Чт", callback_data="TASK_RESCHEDULE:thu")
        builder.button(text="Пт", callback_data="TASK_RESCHEDULE:fri")
        builder.button(text="« Отмена", callback_data=f"T_EDIT:{task_id}")
        builder.adjust(2, 5, 1)

        await callback.message.edit_text(
            f"На какую дату перенести «{task.title}»?\n\n" "Можно ввести: 2025-10-05, 05.10, завтра, пт",
            reply_markup=builder.as_markup(),
        )

    await callback.answer()


@router.callback_query(F.data.startswith("TASK_RESCHEDULE:"))
async def task_reschedule_button_callback(callback: CallbackQuery, state: FSMContext):
    """Обрабатывает клик по кнопке переноса задачи."""
    current_state = await state.get_state()
    if current_state != EditTaskStates.reschedule_date:
        await callback.answer("Эта кнопка уже неактуальна", show_alert=True)
        return

    date_code = callback.data.split(":")[1]

    date_map = {
        "today": "сегодня",
        "tomorrow": "завтра",
        "mon": "пн",
        "tue": "вт",
        "wed": "ср",
        "thu": "чт",
        "fri": "пт",
    }

    date_str = date_map.get(date_code, "сегодня")
    parsed_date = parse_date_input(date_str)

    if not parsed_date:
        await callback.answer("Ошибка парсинга даты", show_alert=True)
        return

    # Получаем task_id из состояния
    data = await state.get_data()
    task_id = data["task_id"]
    user_id = callback.from_user.id

    async with SessionLocal() as session:
        task = await session.get(Task, task_id)

        if not task or task.user_id != user_id:
            await callback.answer("Задача не найдена", show_alert=True)
            await state.clear()
            return

        old_date = task.due_date
        task.due_date = parsed_date
        await session.commit()

        logger.info(f"User {user_id} rescheduled task {task_id} " f"from {old_date} to {parsed_date}")

        time_str = f" {task.time_of_day.strftime('%H:%M')}" if task.time_of_day else ""

        await callback.message.edit_text(
            f"Перенёс задачу «{task.title}» на {parsed_date.strftime('%d.%m.%Y')}{time_str}."
        )

    await state.clear()
    await callback.answer("✅ Дата изменена")


@router.message(EditTaskStates.reschedule_date)
async def task_reschedule_text(message: Message, state: FSMContext):
    """Обрабатывает текстовый ввод новой даты для задачи."""
    date_input = message.text.strip()

    user = await get_user(message.from_user.id)
    user_tz = user.tz if user else "UTC"

    parsed_date = parse_date_input(date_input, user_tz)

    if not parsed_date:
        await message.answer(
            f"Дата «{date_input}» не распознана. Попробуй ещё раз.\n\n"
            "Примеры: 2025-10-05, 05.10, завтра, пт"
        )
        return

    # Получаем task_id из состояния
    data = await state.get_data()
    task_id = data["task_id"]
    user_id = message.from_user.id

    async with SessionLocal() as session:
        task = await session.get(Task, task_id)

        if not task or task.user_id != user_id:
            await message.answer("Задача не найдена")
            await state.clear()
            return

        old_date = task.due_date
        task.due_date = parsed_date
        await session.commit()

        logger.info(f"User {user_id} rescheduled task {task_id} " f"from {old_date} to {parsed_date}")

        time_str = f" {task.time_of_day.strftime('%H:%M')}" if task.time_of_day else ""

        await message.answer(
            f"Перенёс задачу «{task.title}» на {parsed_date.strftime('%d.%m.%Y')}{time_str}."
        )

    await state.clear()


@router.callback_query(F.data.startswith("T_DEL:"))
async def task_delete_callback(callback: CallbackQuery):
    """Запрашивает подтверждение удаления задачи."""
    user_id = callback.from_user.id
    task_id = int(callback.data.split(":")[1])

    async with SessionLocal() as session:
        task = await session.get(Task, task_id)

        if not task or task.user_id != user_id:
            await callback.answer("Задача не найдена", show_alert=True)
            return

        builder = InlineKeyboardBuilder()
        builder.button(text="🗑 Да, удалить", callback_data=f"T_DEL_CONFIRM:{task_id}")
        builder.button(text="« Отмена", callback_data=f"T_EDIT:{task_id}")
        builder.adjust(1)

        await callback.message.edit_text(
            f"Точно удалить задачу «{task.title}»?\n\n" "Это действие нельзя отменить.",
            reply_markup=builder.as_markup(),
        )

    await callback.answer()


@router.callback_query(F.data.startswith("T_DEL_CONFIRM:"))
async def task_delete_confirm_callback(callback: CallbackQuery):
    """Удаляет задачу после подтверждения."""
    user_id = callback.from_user.id
    task_id = int(callback.data.split(":")[1])

    async with SessionLocal() as session:
        task = await session.get(Task, task_id)

        if not task or task.user_id != user_id:
            await callback.answer("Задача не найдена", show_alert=True)
            return

        title = task.title
        await session.delete(task)
        await session.commit()

        logger.info(f"User {user_id} deleted task {task_id} ('{title}')")

    await callback.message.edit_text(f"Удалил задачу «{title}».")
    await callback.answer("🗑 Задача удалена")
