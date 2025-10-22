import random
import sys
from datetime import date, datetime
from datetime import time as dt_time
from pathlib import Path

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import logger
from db import HabitCompletion, Habits, SessionLocal, User

router = Router()

# Список эмодзи для положительного подкрепления
COMPLETION_EMOJIS = ["🔥", "💪", "⚡", "✨", "🌟", "🎯", "👏", "🚀"]


# FSM States для создания привычки
class AddHabitStates(StatesGroup):
    title = State()
    content_choice = State()  # Спрашиваем про контент (для известных привычек)
    # Для языковых привычек (language_reading, language_grammar)
    language_token_input = State()  # Ввод API токена, если его нет
    language_book_selection = State()  # Выбор книги из списка
    schedule_type = State()
    weekdays = State()  # Только для weekly
    time = State()
    confirmation = State()


# FSM States для редактирования привычки
class EditHabitStates(StatesGroup):
    edit_title = State()
    edit_schedule = State()
    edit_weekdays = State()
    edit_time = State()


@router.message(Command("listhabits"))
async def cmd_listhabits(message: Message):
    """Команда /listhabits - показывает список привычек с кнопками управления."""
    user_id = message.from_user.id

    async with SessionLocal() as session:
        result = await session.execute(
            select(Habits).where(Habits.user_id == user_id).order_by(Habits.created_at)
        )
        habits = result.scalars().all()

    # Проверка пустого состояния
    if not habits:
        builder = InlineKeyboardBuilder()
        builder.button(text="Добавить привычку", callback_data="add_habit_start")
        builder.adjust(1)

        await message.answer(
            'У тебя ещё нет привычек. Начни с маленькой, например: "Чтение 10м".',
            reply_markup=builder.as_markup(),
        )
        logger.info(f"User {user_id} viewed /listhabits - empty list")
        return

    # Показываем список с кнопками управления
    habits_text = "Твои привычки:\n\n"
    builder = InlineKeyboardBuilder()

    for i, habit in enumerate(habits, start=1):
        status = "✅" if habit.active else "⏸"
        time_str = habit.time_of_day.strftime("%H:%M") if habit.time_of_day else "—"
        habits_text += f"{i}. {status} <b>{habit.title}</b> — {habit.schedule_type}, {time_str}\n"

        # Кнопки для каждой привычки
        builder.button(text=f"✏️ {i}", callback_data=f"H_EDIT:{habit.id}")

    # Кнопка добавления новой привычки
    builder.button(text="➕ Добавить ещё", callback_data="add_habit_start")

    # Adjust: по 4 кнопки редактирования в ряд, затем кнопка добавления
    rows = []
    for i in range(0, len(habits), 4):
        rows.append(min(4, len(habits) - i))
    rows.append(1)  # Кнопка "Добавить ещё"
    builder.adjust(*rows)

    await message.answer(habits_text, reply_markup=builder.as_markup())
    logger.info(f"User {user_id} viewed /listhabits - {len(habits)} habits")


@router.message(Command("addhabit"))
async def cmd_addhabit(message: Message, state: FSMContext):
    """Команда /addhabit - начинает мастер создания привычки."""
    await state.clear()
    await message.answer(
        "Название привычки? (кратко)\n\n" "Например: <i>Чтение 10м</i>, <i>Зарядка</i>, <i>Медитация</i>"
    )
    await state.set_state(AddHabitStates.title)
    await state.update_data(user_id=message.from_user.id)
    logger.info(f"User {message.from_user.id} started /addhabit wizard")


@router.callback_query(F.data == "add_habit_start")
async def start_add_habit_from_callback(callback: CallbackQuery, state: FSMContext):
    """Начинает мастер создания привычки из кнопки."""
    await state.clear()
    await callback.message.edit_text(
        "Название привычки? (кратко)\n\n" "Например: <i>Чтение 10м</i>, <i>Зарядка</i>, <i>Медитация</i>"
    )
    await state.set_state(AddHabitStates.title)
    await state.update_data(user_id=callback.from_user.id)
    await callback.answer()
    logger.info(f"User {callback.from_user.id} started /addhabit wizard from button")


@router.message(StateFilter(AddHabitStates.title))
async def process_habit_title(message: Message, state: FSMContext):
    """Обработка ввода названия привычки."""
    title = message.text.strip()

    MAX_TITLE_LENGTH = 50
    if len(title) > MAX_TITLE_LENGTH:
        await message.answer(f"Название слишком длинное (>{MAX_TITLE_LENGTH}). Попробуй короче.")
        return

    await state.update_data(title=title)

    # Проверяем, есть ли шаблон для этой привычки
    from llm_service import find_habit_template

    template = await find_habit_template(title)

    if template and template.has_content:
        # Нашли шаблон - сохраняем в state
        await state.update_data(template_id=template.id, template_name=template.name)

        # Для языковых привычек - сначала проверяем токен
        if template.category in ("language_reading", "language_grammar"):
            from db import UserLanguageSettings

            user_id = message.from_user.id

            async with SessionLocal() as session:
                result = await session.execute(
                    select(UserLanguageSettings).where(UserLanguageSettings.user_id == user_id)
                )
                settings = result.scalar_one_or_none()

                if not settings or not settings.api_token:
                    # Токена нет - просим ввести
                    await message.answer(
                        f"📚 <b>{title}</b>\n\n"
                        "Для этой привычки нужен API токен от Language Learning сервиса.\n\n"
                        "Введи свой API токен:"
                    )
                    await state.set_state(AddHabitStates.language_token_input)
                    return

                # Токен есть
                await state.update_data(language_api_token=settings.api_token)

                # Для грамматики НЕ нужна книга - сразу к расписанию
                if template.category == "language_grammar":
                    await state.update_data(include_content=True)
                    await ask_habit_schedule(message, title, state)
                    return

                # Для чтения - переходим к выбору книги
                await ask_language_book_selection(message, state, settings.api_token)
                return

        # Обычный flow - спрашиваем про контент
        builder = InlineKeyboardBuilder()
        builder.button(text="Да, присылай задания", callback_data="content_yes")
        builder.button(text="Нет, только напоминание", callback_data="content_no")
        builder.adjust(1)

        # Примеры контента в зависимости от категории
        example_content = {
            "fitness": "Например: '10 приседаний, 5 отжиманий, 1 берпи'",
            "reading": "Например: 'Прочитай 10 страниц'",
            "meditation": "Например: '5 минут медитации с фокусом на дыхании'",
            "health": "Например: 'Выпей 2 стакана воды'",
            "language_reading": "Фрагменты книги из Language API",
            "language_grammar": "Уроки грамматики из Language API",
        }.get(template.category, "Например: конкретное задание для этой привычки")

        await message.answer(
            f"Отлично! Привычка: <b>{title}</b>\n\n"
            f"Я знаю эту привычку! Хочешь, чтобы я присылал тебе задания вместе с напоминанием?\n\n"
            f"{example_content}",
            reply_markup=builder.as_markup(),
        )
        await state.set_state(AddHabitStates.content_choice)
    else:
        # Шаблона нет - переходим к расписанию
        await state.update_data(template_id=None, include_content=False)
        await ask_habit_schedule(message, title, state)


@router.message(StateFilter(AddHabitStates.language_token_input))
async def handle_language_token_input(message: Message, state: FSMContext):
    """Обрабатывает ввод API токена для Language Learning."""
    from api.language_api import LanguageAPI
    from db import UserLanguageSettings

    user_id = message.from_user.id
    token = message.text.strip()

    if not token or len(token) < 10:
        await message.answer("Токен слишком короткий. Попробуй ещё раз:")
        return

    # Проверяем токен - пытаемся получить список книг
    try:
        api = LanguageAPI(user_token=token)
        books = await api.get_books()
        await api.close()

        if not books:
            await message.answer("Токен валидный, но книг не найдено.\n\n" "Введи другой токен:")
            return

    except Exception as e:
        logger.error(f"Failed to validate Language API token: {e}")
        await message.answer(
            "❌ Не удалось проверить токен. Возможно, он неправильный.\n\n"
            "Проверь токен и попробуй ещё раз:"
        )
        return

    # Токен валидный - сохраняем
    async with SessionLocal() as session:
        result = await session.execute(
            select(UserLanguageSettings).where(UserLanguageSettings.user_id == user_id)
        )
        settings = result.scalar_one_or_none()

        if settings:
            settings.api_token = token
        else:
            settings = UserLanguageSettings(user_id=user_id, api_token=token)
            session.add(settings)

        await session.commit()

    await state.update_data(language_api_token=token)
    await message.answer("✅ Токен сохранён!")

    # Получаем template для проверки категории
    data = await state.get_data()
    template_id = data.get("template_id")

    if template_id:
        from db import HabitTemplate

        async with SessionLocal() as session:
            template = await session.get(HabitTemplate, template_id)

            # Для грамматики НЕ нужна книга - сразу к расписанию
            if template and template.category == "language_grammar":
                await state.update_data(include_content=True)
                title = data.get("title", "Привычка")
                await ask_habit_schedule(message, title, state)
                return

    # Для чтения - переходим к выбору книги
    await ask_language_book_selection(message, state, token)


@router.callback_query(StateFilter(AddHabitStates.language_book_selection), F.data.startswith("lang_book:"))
async def handle_language_book_selection(callback: CallbackQuery, state: FSMContext):
    """Обрабатывает выбор книги для языковой привычки."""
    from api.language_api import LanguageAPI

    # Извлекаем book_id из callback_data
    book_id = int(callback.data.split(":")[1])

    # Получаем токен из state
    data = await state.get_data()
    api_token = data.get("language_api_token")

    if not api_token:
        await callback.answer("Ошибка: токен не найден", show_alert=True)
        return

    # Получаем информацию о книге
    try:
        api = LanguageAPI(user_token=api_token)
        books = await api.get_books()
        await api.close()

        # Находим выбранную книгу
        selected_book = next((b for b in books if b.get("id") == book_id), None)

        if not selected_book:
            await callback.answer("Книга не найдена", show_alert=True)
            return

        book_title = selected_book.get("title", "Неизвестная книга")

        # Сохраняем в state
        await state.update_data(language_book_id=book_id, language_book_title=book_title)

        await callback.message.edit_text(f"✅ Выбрана книга: <b>{book_title}</b>")
        await callback.answer()

        # Для языковых привычек контент всегда включен, пропускаем вопрос про контент
        await state.update_data(include_content=True)

        # Переходим к расписанию
        title = data.get("title", "Привычка")
        await ask_habit_schedule(callback.message, title, state)

    except Exception as e:
        logger.error(f"Failed to get book info: {e}")
        await callback.answer("Ошибка при получении информации о книге", show_alert=True)


async def ask_language_book_selection(message: Message, state: FSMContext, api_token: str):
    """Показывает список книг для выбора."""
    from api.language_api import LanguageAPI

    try:
        api = LanguageAPI(user_token=api_token)
        books = await api.get_books()
        await api.close()

        if not books:
            await message.answer(
                "❌ Книги не найдены.\n\n" "Попробуй позже или обратись к администратору API."
            )
            # Переходим к расписанию без книги (создастся привычка без language_habit_id)
            data = await state.get_data()
            title = data.get("title", "Привычка")
            await ask_habit_schedule(message, title, state)
            return

        # Показываем первые 10 книг
        builder = InlineKeyboardBuilder()
        for book in books[:10]:
            book_id = book.get("id")
            book_title = book.get("title", "Без названия")
            # Обрезаем название до 40 символов для кнопки
            button_text = book_title if len(book_title) <= 40 else book_title[:37] + "..."
            builder.button(text=button_text, callback_data=f"lang_book:{book_id}")

        builder.adjust(1)

        books_count = len(books)
        data = await state.get_data()
        title = data.get("title", "Привычка")

        await message.answer(
            f"📚 <b>{title}</b>\n\n" f"Найдено книг: {books_count}\n" f"Выбери книгу для этой привычки:",
            reply_markup=builder.as_markup(),
        )
        await state.set_state(AddHabitStates.language_book_selection)

    except Exception as e:
        logger.error(f"Failed to get books from Language API: {e}")
        await message.answer(
            "❌ Ошибка при загрузке списка книг.\n\n" "Проверь, что Language API работает и токен правильный."
        )
        # Переходим к расписанию без книги
        data = await state.get_data()
        title = data.get("title", "Привычка")
        await ask_habit_schedule(message, title, state)


async def ask_habit_schedule(message: Message, title: str, state: FSMContext):
    """Спрашивает тип расписания привычки."""
    builder = InlineKeyboardBuilder()
    builder.button(text="Ежедневно", callback_data="schedule_daily")
    builder.button(text="По дням недели", callback_data="schedule_weekly")
    builder.adjust(1)

    await message.answer(
        f"Отлично! Привычка: <b>{title}</b>\n\nВыбери расписание:", reply_markup=builder.as_markup()
    )
    await state.set_state(AddHabitStates.schedule_type)


@router.callback_query(StateFilter(AddHabitStates.content_choice), F.data.in_(["content_yes", "content_no"]))
async def process_content_choice(callback: CallbackQuery, state: FSMContext):
    """Обрабатывает выбор пользователя: присылать контент или нет."""
    include_content = callback.data == "content_yes"
    await state.update_data(include_content=include_content)

    data = await state.get_data()
    title = data["title"]

    if include_content:
        await callback.message.edit_text("Супер! Буду присылать задания с напоминаниями ✅")
    else:
        await callback.message.edit_text("Хорошо, только напоминания ✅")

    await ask_habit_schedule(callback.message, title, state)
    await callback.answer()


@router.callback_query(StateFilter(AddHabitStates.schedule_type), F.data.startswith("schedule_"))
async def process_schedule_type(callback: CallbackQuery, state: FSMContext):
    """Обработка выбора типа расписания."""
    schedule_type = callback.data.split("schedule_")[1]
    await state.update_data(schedule_type=schedule_type)

    if schedule_type == "daily":
        # Пропускаем выбор дней недели для daily
        await callback.message.edit_text("Расписание: <b>Ежедневно</b> ✅")
        await ask_habit_time(callback.message, state)
    elif schedule_type == "weekly":
        # Показываем кнопки для выбора дней недели
        builder = InlineKeyboardBuilder()
        weekdays = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
        for i, day in enumerate(weekdays, start=0):
            builder.button(text=day, callback_data=f"wd_{i}")
        builder.button(text="✅ Готово", callback_data="weekdays_confirm")
        builder.adjust(7, 1)  # 7 дней в ряд, потом кнопка подтверждения

        await callback.message.edit_text(
            "Расписание: <b>По дням недели</b>\n\n"
            "Выбери дни (можно несколько), затем нажми <b>Готово</b>:",
            reply_markup=builder.as_markup(),
        )
        await state.set_state(AddHabitStates.weekdays)
        await state.update_data(selected_weekdays=[])

    await callback.answer()


@router.callback_query(StateFilter(AddHabitStates.weekdays), F.data.startswith("wd_"))
async def toggle_weekday(callback: CallbackQuery, state: FSMContext):
    """Переключает выбор дня недели."""
    weekday_index = int(callback.data.split("_")[1])
    data = await state.get_data()
    selected = data.get("selected_weekdays", [])

    if weekday_index in selected:
        selected.remove(weekday_index)
    else:
        selected.append(weekday_index)

    await state.update_data(selected_weekdays=selected)

    # Обновляем клавиатуру с отметками
    builder = InlineKeyboardBuilder()
    weekdays = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    for i, day in enumerate(weekdays):
        mark = "✅" if i in selected else ""
        builder.button(text=f"{mark} {day}", callback_data=f"wd_{i}")
    builder.button(text="✅ Готово", callback_data="weekdays_confirm")
    builder.adjust(7, 1)

    await callback.message.edit_reply_markup(reply_markup=builder.as_markup())
    await callback.answer()


@router.callback_query(StateFilter(AddHabitStates.weekdays), F.data == "weekdays_confirm")
async def confirm_weekdays(callback: CallbackQuery, state: FSMContext):
    """Подтверждает выбор дней недели."""
    data = await state.get_data()
    selected = data.get("selected_weekdays", [])

    if not selected:
        await callback.answer("Выбери хотя бы один день", show_alert=True)
        return

    weekdays_names = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    selected_names = ", ".join([weekdays_names[i] for i in sorted(selected)])

    await callback.message.edit_text(f"Дни: <b>{selected_names}</b> ✅")
    await ask_habit_time(callback.message, state)
    await callback.answer()


async def ask_habit_time(message: Message, state: FSMContext):
    """Спрашивает время напоминания о привычке."""
    common_times = ["06:00", "07:00", "08:00", "12:00", "18:00", "20:00", "21:00"]

    builder = InlineKeyboardBuilder()
    for t in common_times:
        builder.button(text=t, callback_data=f"time_{t}")
    builder.button(text="Ввести вручную ⌨️", callback_data="time_custom")
    builder.adjust(4)

    await message.answer("Во сколько напоминать? (формат HH:MM)", reply_markup=builder.as_markup())
    await state.set_state(AddHabitStates.time)


@router.callback_query(StateFilter(AddHabitStates.time), F.data.startswith("time_"))
async def process_habit_time(callback: CallbackQuery, state: FSMContext):
    """Обработка выбора времени привычки."""
    time_data = callback.data.split("time_")[1]

    if time_data == "custom":
        await callback.message.edit_text(
            "Введи время в формате <b>HH:MM</b>\n\n" "Например: <code>07:30</code>"
        )
        await state.update_data(time_custom=True)
        await callback.answer()
        return

    # Парсим время
    from .start import validate_time_format

    is_valid, parsed_time = validate_time_format(time_data)

    if is_valid:
        await state.update_data(habit_time=parsed_time, time_custom=False)
        await callback.message.edit_text(f"Время: <b>{time_data}</b> ✅")
        await show_habit_confirmation(callback.message, state)
    else:
        await callback.answer("Ошибка формата времени", show_alert=True)

    await callback.answer()


@router.message(StateFilter(AddHabitStates.time))
async def process_habit_time_custom(message: Message, state: FSMContext):
    """Обработка ручного ввода времени."""
    data = await state.get_data()
    if not data.get("time_custom"):
        return

    from .start import validate_time_format

    is_valid, parsed_time = validate_time_format(message.text)

    if not is_valid:
        await message.answer(
            f"Хм, не распознал время «{message.text}».\n\n"
            "Формат: <b>HH:MM</b>, пример: <code>07:30</code>\n\n"
            "Попробуешь ещё?"
        )
        return

    await state.update_data(habit_time=parsed_time, time_custom=False)
    await message.answer(f"Время: <b>{parsed_time.strftime('%H:%M')}</b> ✅")
    await show_habit_confirmation(message, state)


async def show_habit_confirmation(message: Message, state: FSMContext):
    """Показывает подтверждение создания привычки."""
    data = await state.get_data()

    title = data["title"]
    schedule_type = data["schedule_type"]
    habit_time = data["habit_time"]

    schedule_human = "Ежедневно"
    if schedule_type == "weekly":
        weekdays_names = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
        selected = data.get("selected_weekdays", [])
        selected_names = ", ".join([weekdays_names[i] for i in sorted(selected)])
        schedule_human = selected_names

    time_str = habit_time.strftime("%H:%M")

    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Создать", callback_data="habit_confirm_create")
    builder.button(text="❌ Отменить", callback_data="habit_confirm_cancel")
    builder.adjust(1)

    await message.answer(
        f"Подтверждение:\n\n" f"📌 <b>{title}</b>\n" f"📅 {schedule_human}\n" f"🕐 {time_str}\n\n" "Создаём?",
        reply_markup=builder.as_markup(),
    )
    await state.set_state(AddHabitStates.confirmation)


@router.callback_query(StateFilter(AddHabitStates.confirmation), F.data == "habit_confirm_create")
async def create_habit(callback: CallbackQuery, state: FSMContext, scheduler=None):
    """Создаёт привычку в БД."""
    data = await state.get_data()

    # Подготавливаем данные
    title = data["title"]
    schedule_type = data["schedule_type"]
    habit_time = data["habit_time"]
    user_id = data["user_id"]

    # Формируем RRULE для weekly
    rrule = None
    if schedule_type == "weekly":
        weekdays = data.get("selected_weekdays", [])
        days_map = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]
        byday = ",".join([days_map[i] for i in sorted(weekdays)])
        rrule = f"FREQ=WEEKLY;BYDAY={byday}"

    # Получаем данные о шаблоне и контенте
    template_id = data.get("template_id")
    include_content = data.get("include_content", False)

    # Получаем данные для языковых привычек
    language_book_id = data.get("language_book_id")
    language_book_title = data.get("language_book_title")

    # Создаём привычку
    async with SessionLocal() as session:
        language_habit_id = None

        # Если это языковая привычка - создаём LanguageHabit
        if template_id:
            from db import HabitTemplate, LanguageHabit

            template = await session.get(HabitTemplate, template_id)

            if template and template.category in ("language_reading", "language_grammar"):
                # Создаём LanguageHabit
                # Для reading нужен book_id, для grammar - НЕ нужен
                language_habit = LanguageHabit(
                    user_id=user_id,
                    habit_type="reading" if template.category == "language_reading" else "grammar",
                    name=title,
                    current_book_id=language_book_id,  # Для grammar будет None
                    current_book_title=language_book_title,  # Для grammar будет None
                    is_active=True,
                    daily_goal=1000,  # Дефолтная цель - 1000 слов
                )
                session.add(language_habit)
                await session.flush()  # Получаем ID до commit
                language_habit_id = language_habit.id

                if template.category == "language_reading":
                    logger.info(
                        f"Created LanguageHabit {language_habit_id} for user {user_id}: "
                        f"{title} (book_id={language_book_id})"
                    )
                else:
                    logger.info(
                        f"Created LanguageHabit {language_habit_id} for user {user_id}: " f"{title} (grammar)"
                    )

        # Создаём Habit
        habit = Habits(
            user_id=user_id,
            title=title,
            schedule_type=schedule_type,
            rrule=rrule if schedule_type == "weekly" else None,
            time_of_day=habit_time,
            active=True,
            template_id=template_id,
            include_content=include_content,
            language_habit_id=language_habit_id,  # Связываем с LanguageHabit
        )
        session.add(habit)
        await session.commit()
        await session.refresh(habit)

        habit_id = habit.id

    # Планируем напоминания немедленно
    try:
        if scheduler:
            await scheduler.schedule_user_reminders(user_id)
            logger.info(f"User {user_id} created habit {habit_id}, reminders scheduled immediately")
        else:
            logger.warning(f"Scheduler not found in workflow_data for user {user_id}")
    except Exception as e:
        logger.error(f"Failed to schedule reminders for user {user_id}: {e}")

    # Создаём кнопки для дальнейших действий
    builder = InlineKeyboardBuilder()
    builder.button(text="➕ Добавить ещё привычку", callback_data="add_habit_start")
    builder.button(text="📋 Главное меню", callback_data="back_to_menu")
    builder.adjust(1)

    await callback.message.edit_text(
        f"Создал привычку <b>{title}</b> ({schedule_type}) на {habit_time.strftime('%H:%M')}.\n\n"
        "Напоминания запланированы! ✅",
        reply_markup=builder.as_markup(),
    )

    await state.clear()
    await callback.answer()
    logger.info(f"User {user_id} created habit {habit_id}: {title}")


@router.callback_query(StateFilter(AddHabitStates.confirmation), F.data == "habit_confirm_cancel")
async def cancel_habit_creation(callback: CallbackQuery, state: FSMContext):
    """Отменяет создание привычки."""
    await callback.message.edit_text("Отменил создание привычки.")
    await state.clear()
    await callback.answer()
    logger.info(f"User {callback.from_user.id} cancelled habit creation")


def is_in_quiet_hours(current_time: dt_time, quiet_from: dt_time, quiet_to: dt_time) -> bool:
    """Проверяет, попадает ли текущее время в тихие часы."""
    if quiet_from is None or quiet_to is None:
        return False

    # Если тихие часы переходят через полночь (например, 22:30 - 07:00)
    if quiet_from > quiet_to:
        return current_time >= quiet_from or current_time <= quiet_to
    else:
        return quiet_from <= current_time <= quiet_to


async def check_duplicate_completion(user_id: int, habit_id: int, completion_date: date) -> bool:
    """Проверяет, была ли привычка уже отмечена как выполненная сегодня."""
    async with SessionLocal() as session:
        result = await session.execute(
            select(HabitCompletion).where(
                HabitCompletion.user_id == user_id,
                HabitCompletion.habit_id == habit_id,
                HabitCompletion.completion_date == completion_date,
                HabitCompletion.status == "done",
            )
        )
        existing = result.scalar_one_or_none()
        return existing is not None


# Callback handlers по схеме из callback_data.py:
# H_D:{habit_id}:{date} — done (сделал)
@router.callback_query(F.data.startswith("H_D:"))
async def habit_done_callback(callback: CallbackQuery):
    """Обработчик кнопки 'Сделал' для привычки."""
    user_id = callback.from_user.id

    # Парсим callback_data: H_D:{habit_id}:{date}
    parts = callback.data.split(":")
    if len(parts) != 3:
        await callback.answer("Ошибка формата данных", show_alert=True)
        return

    habit_id = int(parts[1])
    completion_date_str = parts[2]  # YYYYMMDD
    completion_date = datetime.strptime(completion_date_str, "%Y%m%d").date()

    # Получаем привычку
    async with SessionLocal() as session:
        habit = await session.get(Habits, habit_id)
        if not habit:
            await callback.answer("Привычка не найдена", show_alert=True)
            return

        # Проверка на дубликат
        if await check_duplicate_completion(user_id, habit_id, completion_date):
            await callback.message.edit_text("Уже записал это достижение 👌")
            await callback.answer()
            logger.info(f"User {user_id} tried to complete habit {habit_id} again on {completion_date}")
            return

        # Создаем запись о выполнении
        completion = HabitCompletion(
            habit_id=habit_id,
            user_id=user_id,
            completion_date=completion_date,
            status="done",
        )
        session.add(completion)
        await session.commit()

    # Случайный эмодзи для положительного подкрепления
    emoji = random.choice(COMPLETION_EMOJIS)

    await callback.message.edit_text(
        f"Отлично, зачёл «{habit.title}» за {completion_date.strftime('%d.%m.%Y')} {emoji}"
    )

    await callback.answer()
    logger.info(f"User {user_id} completed habit {habit_id} on {completion_date}")


# H_S:{habit_id}:{date} — skip (пропустить)
@router.callback_query(F.data.startswith("H_S:"))
async def habit_skip_callback(callback: CallbackQuery):
    """Обработчик кнопки 'Пропустить' для привычки."""
    user_id = callback.from_user.id

    # Парсим callback_data
    parts = callback.data.split(":")
    if len(parts) != 3:
        await callback.answer("Ошибка формата данных", show_alert=True)
        return

    habit_id = int(parts[1])
    completion_date_str = parts[2]
    completion_date = datetime.strptime(completion_date_str, "%Y%m%d").date()

    # Получаем привычку
    async with SessionLocal() as session:
        habit = await session.get(Habits, habit_id)
        if not habit:
            await callback.answer("Привычка не найдена", show_alert=True)
            return

        # Создаем запись о пропуске
        completion = HabitCompletion(
            habit_id=habit_id,
            user_id=user_id,
            completion_date=completion_date,
            status="skipped",
        )
        session.add(completion)
        await session.commit()

    await callback.message.edit_text("Окей, пометил как пропуск. Вечером разберём, что помешало.")

    await callback.answer()
    logger.info(f"User {user_id} skipped habit {habit_id} on {completion_date}")


# H_Z:{habit_id}:{minutes} — snooze (отложить)
@router.callback_query(F.data.startswith("H_Z:"))
async def habit_snooze_callback(callback: CallbackQuery):
    """Обработчик кнопки 'Отложить' для привычки."""
    user_id = callback.from_user.id

    # Парсим callback_data
    parts = callback.data.split(":")
    if len(parts) != 3:
        await callback.answer("Ошибка формата данных", show_alert=True)
        return

    habit_id = int(parts[1])
    snooze_minutes = int(parts[2])

    # Получаем привычку и пользователя
    async with SessionLocal() as session:
        habit = await session.get(Habits, habit_id)

        # Получаем пользователя по user_id (Telegram ID), а не по primary key
        result = await session.execute(select(User).where(User.user_id == user_id))
        user = result.scalar_one_or_none()

        if not habit:
            await callback.answer("Привычка не найдена", show_alert=True)
            return

        if not user:
            await callback.answer("Пользователь не найден", show_alert=True)
            return

        # Проверяем тихие часы
        current_time = datetime.now().time()
        if is_in_quiet_hours(current_time, user.quiet_hours_from, user.quiet_hours_to):
            await callback.message.edit_text("Тихие часы — напомню утром 🌅")
            await callback.answer()
            logger.info(f"User {user_id} tried to snooze habit {habit_id} during quiet hours")
            return

    await callback.message.edit_text(f"Хорошо, напомню через {snooze_minutes} минут ⏰")

    await callback.answer()
    logger.info(f"User {user_id} snoozed habit {habit_id} for {snooze_minutes} minutes")


# H_TOGGLE:{habit_id}:{on|off} — toggle active status
@router.callback_query(F.data.startswith("H_TOGGLE:"))
async def habit_toggle_callback(callback: CallbackQuery, scheduler=None):
    """Переключает активность привычки (вкл/выкл)."""
    user_id = callback.from_user.id

    # Парсим callback_data: H_TOGGLE:{habit_id}:{on|off}
    parts = callback.data.split(":")
    if len(parts) != 3:
        await callback.answer("Ошибка формата данных", show_alert=True)
        return

    habit_id = int(parts[1])
    action = parts[2]  # "on" или "off"

    async with SessionLocal() as session:
        habit = await session.get(Habits, habit_id)
        if not habit or habit.user_id != user_id:
            await callback.answer("Привычка не найдена", show_alert=True)
            return

        # Переключаем статус
        habit.active = action == "on"
        await session.commit()

        # status_emoji = "✅" if habit.active else "⏸"
        status_text = "включена" if habit.active else "приостановлена"

    # Обновляем расписание напоминаний сразу без перезапуска
    if scheduler:
        await scheduler.schedule_user_reminders(user_id)

    await callback.answer(f"Привычка «{habit.title}» {status_text}", show_alert=False)
    logger.info(f"User {user_id} toggled habit {habit_id} to {'active' if habit.active else 'paused'}")

    # Обновляем сообщение с актуальным статусом
    await refresh_habits_list(callback.message, user_id)


# H_DEL:{habit_id} — delete habit with confirmation
@router.callback_query(F.data.startswith("H_DEL:"))
async def habit_delete_callback(callback: CallbackQuery):
    """Запрашивает подтверждение удаления привычки."""
    user_id = callback.from_user.id

    # Парсим callback_data
    parts = callback.data.split(":")
    if len(parts) != 2:
        await callback.answer("Ошибка формата данных", show_alert=True)
        return

    habit_id = int(parts[1])

    async with SessionLocal() as session:
        habit = await session.get(Habits, habit_id)
        if not habit or habit.user_id != user_id:
            await callback.answer("Привычка не найдена", show_alert=True)
            return

        habit_title = habit.title

    # Показываем подтверждение
    builder = InlineKeyboardBuilder()
    builder.button(text="🗑 Да, удалить", callback_data=f"H_DEL_CONFIRM:{habit_id}")
    builder.button(text="❌ Отмена", callback_data="H_DEL_CANCEL")
    builder.adjust(1)

    await callback.message.edit_text(
        f"Удалить привычку <b>{habit_title}</b>?\n\n" "История выполнения также будет удалена.",
        reply_markup=builder.as_markup(),
    )
    await callback.answer()


# H_DEL_CONFIRM:{habit_id} — confirm deletion
@router.callback_query(F.data.startswith("H_DEL_CONFIRM:"))
async def habit_delete_confirm_callback(callback: CallbackQuery, scheduler=None):
    """Удаляет привычку после подтверждения."""
    user_id = callback.from_user.id

    habit_id = int(callback.data.split(":")[1])

    async with SessionLocal() as session:
        habit = await session.get(Habits, habit_id)
        if not habit or habit.user_id != user_id:
            await callback.answer("Привычка не найдена", show_alert=True)
            return

        habit_title = habit.title

        # Удаляем все связанные выполнения (каскадно, если настроено в БД)
        # Или явно удаляем:
        await session.execute(select(HabitCompletion).where(HabitCompletion.habit_id == habit_id))
        completions = (
            (await session.execute(select(HabitCompletion).where(HabitCompletion.habit_id == habit_id)))
            .scalars()
            .all()
        )

        for completion in completions:
            await session.delete(completion)

        await session.delete(habit)
        await session.commit()

    # Обновляем расписание напоминаний (удаляем задание)
    if scheduler:
        await scheduler.schedule_user_reminders(user_id)

    await callback.message.edit_text(
        f"Привычка <b>{habit_title}</b> удалена.\n\n" "Всегда можешь создать новую! /addhabit"
    )
    await callback.answer()
    logger.info(f"User {user_id} deleted habit {habit_id}")


# H_DEL_CANCEL — cancel deletion
@router.callback_query(F.data == "H_DEL_CANCEL")
async def habit_delete_cancel_callback(callback: CallbackQuery):
    """Отменяет удаление привычки."""
    user_id = callback.from_user.id

    await callback.message.edit_text("Отменил удаление.")
    await callback.answer()

    # Возвращаемся к списку привычек
    await refresh_habits_list(callback.message, user_id)


# H_EDIT:{habit_id} — edit menu
@router.callback_query(F.data.startswith("H_EDIT:"))
async def habit_edit_menu_callback(callback: CallbackQuery):
    """Показывает меню редактирования привычки."""
    user_id = callback.from_user.id

    habit_id = int(callback.data.split(":")[1])

    async with SessionLocal() as session:
        habit = await session.get(Habits, habit_id)
        if not habit or habit.user_id != user_id:
            await callback.answer("Привычка не найдена", show_alert=True)
            return

        status_emoji = "✅" if habit.active else "⏸"
        time_str = habit.time_of_day.strftime("%H:%M") if habit.time_of_day else "—"

        builder = InlineKeyboardBuilder()
        builder.button(text="📝 Изменить название", callback_data=f"H_ED_TTL:{habit_id}")
        builder.button(text="📅 Изменить расписание", callback_data=f"H_ED_SCH:{habit_id}")
        builder.button(text="🕐 Изменить время", callback_data=f"H_ED_TIM:{habit_id}")

        # Кнопка вкл/выкл
        toggle_text = "⏸ Приостановить" if habit.active else "▶️ Активировать"
        toggle_action = "off" if habit.active else "on"
        builder.button(text=toggle_text, callback_data=f"H_TOGGLE:{habit_id}:{toggle_action}")

        builder.button(text="🗑 Удалить", callback_data=f"H_DEL:{habit_id}")
        builder.button(text="◀️ Назад к списку", callback_data="back_to_habits_list")
        builder.button(text="« Назад в меню", callback_data="back_to_menu")
        builder.adjust(1)

    await callback.message.edit_text(
        f"Привычка: <b>{habit.title}</b>\n\n"
        f"Статус: {status_emoji}\n"
        f"Расписание: {habit.schedule_type}\n"
        f"Время: {time_str}\n\n"
        "Что хочешь изменить?",
        reply_markup=builder.as_markup(),
    )
    await callback.answer()


# Back to habits list
@router.callback_query(F.data == "back_to_habits_list")
async def back_to_habits_list_callback(callback: CallbackQuery):
    """Возвращается к списку привычек."""
    user_id = callback.from_user.id
    await refresh_habits_list(callback.message, user_id)
    await callback.answer()


async def refresh_habits_list(message: Message, user_id: int):
    """Обновляет список привычек в сообщении."""
    async with SessionLocal() as session:
        result = await session.execute(
            select(Habits).where(Habits.user_id == user_id).order_by(Habits.created_at)
        )
        habits = result.scalars().all()

    if not habits:
        builder = InlineKeyboardBuilder()
        builder.button(text="Добавить привычку", callback_data="add_habit_start")
        builder.adjust(1)

        await message.edit_text(
            'У тебя ещё нет привычек. Начни с маленькой, например: "Чтение 10м".',
            reply_markup=builder.as_markup(),
        )
        return

    # Показываем список с кнопками управления для каждой привычки
    habits_text = "Твои привычки:\n\n"
    builder = InlineKeyboardBuilder()

    for i, habit in enumerate(habits, start=1):
        status = "✅" if habit.active else "⏸"
        time_str = habit.time_of_day.strftime("%H:%M") if habit.time_of_day else "—"
        habits_text += f"{i}. {status} <b>{habit.title}</b> — {habit.schedule_type}, {time_str}\n"

        # Кнопки для каждой привычки
        builder.button(text=f"✏️ {i}", callback_data=f"H_EDIT:{habit.id}")

    # Кнопка добавления новой привычки
    builder.button(text="➕ Добавить ещё", callback_data="add_habit_start")

    # Adjust: по 4 кнопки редактирования в ряд, затем кнопка добавления
    rows = []
    for i in range(0, len(habits), 4):
        rows.append(min(4, len(habits) - i))
    rows.append(1)  # Кнопка "Добавить ещё"
    builder.adjust(*rows)

    await message.edit_text(habits_text, reply_markup=builder.as_markup())


# H_ED_TTL:{habit_id} — edit title
@router.callback_query(F.data.startswith("H_ED_TTL:"))
async def habit_edit_title_start(callback: CallbackQuery, state: FSMContext):
    """Начинает редактирование названия привычки."""
    user_id = callback.from_user.id
    habit_id = int(callback.data.split(":")[1])

    async with SessionLocal() as session:
        habit = await session.get(Habits, habit_id)
        if not habit or habit.user_id != user_id:
            await callback.answer("Привычка не найдена", show_alert=True)
            return

        await state.update_data(editing_habit_id=habit_id, original_title=habit.title)

    await callback.message.edit_text(f"Текущее название: <b>{habit.title}</b>\n\n" "Введи новое название:")
    await state.set_state(EditHabitStates.edit_title)
    await callback.answer()


@router.message(StateFilter(EditHabitStates.edit_title))
async def habit_edit_title_process(message: Message, state: FSMContext):
    """Обрабатывает новое название привычки."""
    new_title = message.text.strip()
    MAX_TITLE_LENGTH = 50

    if len(new_title) > MAX_TITLE_LENGTH:
        await message.answer(f"Название слишком длинное (>{MAX_TITLE_LENGTH}). Попробуй короче.")
        return

    data = await state.get_data()
    habit_id = data["editing_habit_id"]
    user_id = message.from_user.id

    async with SessionLocal() as session:
        habit = await session.get(Habits, habit_id)
        if not habit or habit.user_id != user_id:
            await message.answer("Привычка не найдена")
            await state.clear()
            return

        old_title = habit.title
        habit.title = new_title
        await session.commit()

    await message.answer(f"Название изменено:\n" f"<s>{old_title}</s> → <b>{new_title}</b> ✅")
    await state.clear()
    logger.info(f"User {user_id} renamed habit {habit_id} from '{old_title}' to '{new_title}'")


# H_ED_TIM:{habit_id} — edit time
@router.callback_query(F.data.startswith("H_ED_TIM:"))
async def habit_edit_time_start(callback: CallbackQuery, state: FSMContext):
    """Начинает редактирование времени привычки."""
    user_id = callback.from_user.id
    habit_id = int(callback.data.split(":")[1])

    async with SessionLocal() as session:
        habit = await session.get(Habits, habit_id)
        if not habit or habit.user_id != user_id:
            await callback.answer("Привычка не найдена", show_alert=True)
            return

        current_time_str = habit.time_of_day.strftime("%H:%M") if habit.time_of_day else "—"
        await state.update_data(editing_habit_id=habit_id)

    common_times = ["06:00", "07:00", "08:00", "12:00", "18:00", "20:00", "21:00"]
    builder = InlineKeyboardBuilder()
    for t in common_times:
        builder.button(text=t, callback_data=f"edit_time_{t}")
    builder.button(text="Ввести вручную ⌨️", callback_data="edit_time_custom")
    builder.button(text="❌ Отмена", callback_data="back_to_habits_list")
    builder.adjust(4)

    await callback.message.edit_text(
        f"Текущее время: <b>{current_time_str}</b>\n\n" "Выбери новое время:",
        reply_markup=builder.as_markup(),
    )
    await state.set_state(EditHabitStates.edit_time)
    await callback.answer()


@router.callback_query(StateFilter(EditHabitStates.edit_time), F.data.startswith("edit_time_"))
async def habit_edit_time_process(callback: CallbackQuery, state: FSMContext, scheduler=None):
    """Обрабатывает выбор нового времени."""
    time_data = callback.data.split("edit_time_")[1]

    if time_data == "custom":
        await callback.message.edit_text(
            "Введи время в формате <b>HH:MM</b>\n\n" "Например: <code>07:30</code>"
        )
        await state.update_data(time_custom=True)
        await callback.answer()
        return

    from .start import validate_time_format

    is_valid, parsed_time = validate_time_format(time_data)

    if not is_valid:
        await callback.answer("Ошибка формата времени", show_alert=True)
        return

    data = await state.get_data()
    habit_id = data["editing_habit_id"]
    user_id = callback.from_user.id

    async with SessionLocal() as session:
        habit = await session.get(Habits, habit_id)
        if not habit or habit.user_id != user_id:
            await callback.answer("Привычка не найдена", show_alert=True)
            await state.clear()
            return

        old_time = habit.time_of_day.strftime("%H:%M") if habit.time_of_day else "—"
        habit.time_of_day = parsed_time
        await session.commit()

    # Обновляем расписание напоминаний сразу без перезапуска
    if scheduler:
        await scheduler.schedule_user_reminders(user_id)

    await callback.message.edit_text(
        f"Время изменено:\n" f"<s>{old_time}</s> → <b>{time_data}</b> ✅\n\n" "Напоминание обновлено!"
    )
    await state.clear()
    await callback.answer()
    logger.info(f"User {user_id} changed habit {habit_id} time from {old_time} to {time_data}")


@router.message(StateFilter(EditHabitStates.edit_time))
async def habit_edit_time_custom(message: Message, state: FSMContext, scheduler=None):
    """Обрабатывает ручной ввод времени."""
    data = await state.get_data()
    if not data.get("time_custom"):
        return

    from .start import validate_time_format

    is_valid, parsed_time = validate_time_format(message.text)

    if not is_valid:
        await message.answer(
            f"Хм, не распознал время «{message.text}».\n\n"
            "Формат: <b>HH:MM</b>, пример: <code>07:30</code>\n\n"
            "Попробуешь ещё?"
        )
        return

    habit_id = data["editing_habit_id"]
    user_id = message.from_user.id

    async with SessionLocal() as session:
        habit = await session.get(Habits, habit_id)
        if not habit or habit.user_id != user_id:
            await message.answer("Привычка не найдена")
            await state.clear()
            return

        old_time = habit.time_of_day.strftime("%H:%M") if habit.time_of_day else "—"
        habit.time_of_day = parsed_time
        await session.commit()

    # Обновляем расписание напоминаний сразу без перезапуска
    if scheduler:
        await scheduler.schedule_user_reminders(user_id)

    await message.answer(
        f"Время изменено:\n"
        f"<s>{old_time}</s> → <b>{parsed_time.strftime('%H:%M')}</b> ✅\n\n"
        "Напоминание обновлено!"
    )
    await state.clear()
    logger.info(
        f"User {user_id} changed habit {habit_id} time from {old_time} to {parsed_time.strftime('%H:%M')}"
    )


# H_ED_SCH:{habit_id} — edit schedule (placeholder for now)
@router.callback_query(F.data.startswith("H_ED_SCH:"))
async def habit_edit_schedule_start(callback: CallbackQuery):
    """Редактирование расписания (пока не реализовано)."""
    await callback.answer(
        "Изменение расписания пока в разработке.\n" "Удали и создай новую привычку с нужным расписанием.",
        show_alert=True,
    )
