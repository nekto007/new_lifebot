import sys
from pathlib import Path

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import logger
from db import Habits, SessionLocal, Task

router = Router()


@router.message(Command("menu"))
async def cmd_menu(message: Message):
    """Команда /menu - главное меню."""
    builder = InlineKeyboardBuilder()

    # Первый ряд - привычки
    builder.button(text="Добавить привычку", callback_data="add_habit_start")
    builder.button(text="Список привычек", callback_data="list_habits")

    # Второй ряд - задачи
    builder.button(text="Добавить задачу", callback_data="add_task_start")
    builder.button(text="Список задач", callback_data="list_tasks")

    # Третий ряд - делегирование
    builder.button(text="Делегировать 👥", callback_data="show_delegate")
    builder.button(text="Назначено мне 📥", callback_data="show_assigned")

    # Четвёртый ряд - основное
    builder.button(text="Сегодня 📅", callback_data="show_today")
    builder.button(text="Статистика 📊", callback_data="show_stats")

    # Пятый ряд - дополнительно
    builder.button(text="Журнал 📖", callback_data="show_journal")
    builder.button(text="Экспорт 💾", callback_data="show_export")

    # Шестой ряд - Language Learning
    builder.button(text="Изучение языков 🎧", callback_data="show_language")

    # Седьмой ряд - настройки и помощь
    builder.button(text="Настройки ⚙️", callback_data="show_settings")
    builder.button(text="Помощь ❓", callback_data="show_help")

    builder.adjust(2, 2, 2, 2, 2, 1, 2)

    await message.answer("Что делаем?", reply_markup=builder.as_markup())
    logger.info(f"User {message.from_user.id} opened /menu")


# Обработчики для кнопок меню


@router.callback_query(F.data == "list_habits")
async def menu_list_habits(callback: CallbackQuery):
    """Показывает список привычек из меню."""
    user_id = callback.from_user.id

    async with SessionLocal() as session:
        result = await session.execute(
            select(Habits).where(Habits.user_id == user_id).order_by(Habits.created_at)
        )
        habits = result.scalars().all()

    # Проверка пустого состояния
    if not habits:
        builder = InlineKeyboardBuilder()
        builder.button(text="Добавить привычку", callback_data="add_habit_start")
        builder.button(text="« Назад в меню", callback_data="back_to_menu")
        builder.adjust(1)

        await callback.message.edit_text(
            'У тебя ещё нет привычек. Начни с маленькой, например: "Чтение 10м".',
            reply_markup=builder.as_markup(),
        )
        await callback.answer()
        logger.info(f"User {user_id} viewed habits list from menu - empty")
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
    builder.button(text="« Назад в меню", callback_data="back_to_menu")

    # Adjust: по 4 кнопки редактирования в ряд, затем кнопка добавления
    rows = []
    for i in range(0, len(habits), 4):
        rows.append(min(4, len(habits) - i))
    rows.append(1)  # Кнопка "Добавить ещё"
    rows.append(1)  # Кнопка "Назад в меню"
    builder.adjust(*rows)

    await callback.message.edit_text(habits_text, reply_markup=builder.as_markup())
    await callback.answer()
    logger.info(f"User {user_id} viewed habits list from menu - {len(habits)} habits")


@router.callback_query(F.data == "add_task_start")
async def menu_add_task(callback: CallbackQuery, state: FSMContext):
    """Начинает процесс добавления задачи из меню."""
    from .tasks import AddTaskStates

    await state.set_state(AddTaskStates.enter_title)
    await callback.message.edit_text("Текст задачи?")
    await callback.answer()
    logger.info(f"User {callback.from_user.id} started adding task from menu")


@router.callback_query(F.data == "list_tasks")
async def menu_list_tasks(callback: CallbackQuery):
    """Показывает фильтры задач из меню."""
    builder = InlineKeyboardBuilder()
    builder.button(text="Сегодня", callback_data="TASKS_FILTER:today")
    builder.button(text="Неделя", callback_data="TASKS_FILTER:week")
    builder.button(text="Все", callback_data="TASKS_FILTER:all")
    builder.button(text="Активные", callback_data="TASKS_FILTER:active")
    builder.button(text="Выполненные", callback_data="TASKS_FILTER:done")
    builder.button(text="« Назад в меню", callback_data="back_to_menu")
    builder.adjust(2, 3, 1)

    await callback.message.edit_text("Показать задачи за…", reply_markup=builder.as_markup())
    await callback.answer()
    logger.info(f"User {callback.from_user.id} opened tasks filter from menu")


@router.callback_query(F.data == "show_today")
async def menu_show_today(callback: CallbackQuery):
    """Показывает сводку на сегодня из меню."""
    from datetime import datetime

    from .today import get_user_habits_count, get_user_tasks_count

    user_id = callback.from_user.id

    habits_count = await get_user_habits_count(user_id)
    tasks_done, tasks_total = await get_user_tasks_count(user_id)

    # Текущая дата
    today = datetime.now().strftime("%d.%m.%Y")

    # Проверяем пустые состояния
    if habits_count == 0 and tasks_total == 0:
        # Совсем пусто - предлагаем добавить первую привычку
        builder = InlineKeyboardBuilder()
        builder.button(text="Добавить привычку", callback_data="add_habit_start")
        builder.button(text="« Назад в меню", callback_data="back_to_menu")
        builder.adjust(1)

        await callback.message.edit_text(
            f"Сегодня {today} 📅\n\n" "Привычек пока нет. Добавим первую?",
            reply_markup=builder.as_markup(),
        )
        await callback.answer()
        logger.info(f"User {user_id} viewed /today from menu - no habits, no tasks")
        return

    if habits_count == 0:
        # Нет привычек, но есть задачи
        builder = InlineKeyboardBuilder()
        builder.button(text="Добавить привычку", callback_data="add_habit_start")
        builder.button(text="Показать задачи", callback_data="list_tasks")
        builder.button(text="« Назад в меню", callback_data="back_to_menu")
        builder.adjust(1)

        await callback.message.edit_text(
            f"Сегодня {today} 📅\n\n"
            f"Привычек пока нет. Задачи: {tasks_done}/{tasks_total}.\n\n"
            "Добавим первую?",
            reply_markup=builder.as_markup(),
        )
        await callback.answer()
        logger.info(f"User {user_id} viewed /today from menu - no habits, {tasks_total} tasks")
        return

    if tasks_total == 0:
        # Есть привычки, но нет задач
        builder = InlineKeyboardBuilder()
        builder.button(text="Добавить задачу", callback_data="add_task_start")
        builder.button(text="Показать привычки", callback_data="list_habits")
        builder.button(text="« Назад в меню", callback_data="back_to_menu")
        builder.adjust(1)

        await callback.message.edit_text(
            f"Сегодня {today} 📅\n\n"
            f"Привычки: 0/{habits_count}.\n\n"
            "Сегодня без задач? Хочешь добавить?",
            reply_markup=builder.as_markup(),
        )
        await callback.answer()
        logger.info(f"User {user_id} viewed /today from menu - {habits_count} habits, no tasks")
        return

    # Есть и привычки, и задачи
    builder = InlineKeyboardBuilder()
    builder.button(text="Показать привычки", callback_data="list_habits")
    builder.button(text="Показать задачи", callback_data="list_tasks")
    builder.button(text="« Назад в меню", callback_data="back_to_menu")
    builder.adjust(1)

    await callback.message.edit_text(
        f"Сегодня {today} 📅\n\n" f"Привычки: 0/{habits_count}\n" f"Задачи: {tasks_done}/{tasks_total}",
        reply_markup=builder.as_markup(),
    )
    await callback.answer()
    logger.info(
        f"User {user_id} viewed /today from menu - {habits_count} habits, "
        f"{tasks_done}/{tasks_total} tasks"
    )


@router.callback_query(F.data == "show_stats")
async def menu_show_stats(callback: CallbackQuery):
    """Показывает статистику из меню."""
    await callback.message.edit_text(
        "📊 Статистика\n\n"
        "Детальная статистика в разработке.\n\n"
        "Используй /stats для базовой статистики."
    )

    builder = InlineKeyboardBuilder()
    builder.button(text="« Назад в меню", callback_data="back_to_menu")
    builder.adjust(1)

    await callback.message.edit_reply_markup(reply_markup=builder.as_markup())
    await callback.answer()
    logger.info(f"User {callback.from_user.id} viewed stats from menu")


@router.callback_query(F.data == "show_settings")
async def menu_show_settings(callback: CallbackQuery):
    """Открывает настройки из меню."""
    from db import User

    user_id = callback.from_user.id

    async with SessionLocal() as session:
        result = await session.execute(select(User).where(User.user_id == user_id))
        user = result.scalar_one_or_none()

        if not user or not user.lang:
            await callback.message.edit_text(
                "Привет! Сначала нужно пройти настройку.\n\n" "Используй команду /start для начала работы."
            )
            await callback.answer()
            return

        # Формируем текст с текущими настройками
        lang_name = "Русский" if user.lang == "ru" else "English"
        tz = user.tz or "UTC"

        quiet_from_str = (
            user.quiet_hours_from.strftime("%H:%M") if user.quiet_hours_from else "Не установлено"
        )
        quiet_to_str = user.quiet_hours_to.strftime("%H:%M") if user.quiet_hours_to else "Не установлено"

        morning_ping_str = (
            user.morning_ping_time.strftime("%H:%M") if user.morning_ping_time else "Не установлено"
        )
        evening_ping_str = (
            user.evening_ping_time.strftime("%H:%M") if user.evening_ping_time else "Не установлено"
        )

        builder = InlineKeyboardBuilder()
        builder.button(text="Язык", callback_data="settings_lang")
        builder.button(text="Часовой пояс", callback_data="settings_tz")
        builder.button(text="Тихие часы", callback_data="settings_quiet")
        builder.button(text="Утренний пинг", callback_data="settings_morning")
        builder.button(text="Вечерний отчёт", callback_data="settings_evening")
        builder.button(text="« Назад в меню", callback_data="back_to_menu")
        builder.adjust(1)

        await callback.message.edit_text(
            f"Настройки профиля:\n\n"
            f"Язык: <b>{lang_name}</b>\n"
            f"Часовой пояс: <b>{tz}</b>\n"
            f"Тихие часы: <b>{quiet_from_str} - {quiet_to_str}</b>\n"
            f"Утренний пинг: <b>{morning_ping_str}</b>\n"
            f"Вечерний отчёт: <b>{evening_ping_str}</b>\n\n"
            "Что хочешь изменить?",
            reply_markup=builder.as_markup(),
        )

    await callback.answer()
    logger.info(f"User {callback.from_user.id} opened settings from menu")


@router.callback_query(F.data == "show_delegate")
async def menu_show_delegate(callback: CallbackQuery):
    """Показывает меню делегирования."""
    builder = InlineKeyboardBuilder()
    builder.button(text="Делегировать задачу", callback_data="delegate_new")
    builder.button(text="Мои делегированные", callback_data="delegate_my")
    builder.button(text="« Назад в меню", callback_data="back_to_menu")
    builder.adjust(1)

    await callback.message.edit_text(
        "👥 Делегирование задач\n\n" "Что хочешь сделать?", reply_markup=builder.as_markup()
    )
    await callback.answer()
    logger.info(f"User {callback.from_user.id} opened delegation menu")


@router.callback_query(F.data == "show_assigned")
async def menu_show_assigned(callback: CallbackQuery):
    """Показывает задачи, назначенные пользователю."""
    from datetime import date as dt_date

    from db import DelegatedTask, User

    user_id = callback.from_user.id

    async with SessionLocal() as session:
        # Получаем назначенные задачи
        result = await session.execute(
            select(DelegatedTask)
            .where(
                DelegatedTask.assigned_to_user_id == user_id,
                DelegatedTask.status.in_(["pending_acceptance", "accepted"]),
            )
            .order_by(DelegatedTask.deadline)
        )
        delegated_tasks = result.scalars().all()

        if not delegated_tasks:
            builder = InlineKeyboardBuilder()
            builder.button(text="« Назад в меню", callback_data="back_to_menu")
            builder.adjust(1)

            await callback.message.edit_text(
                "📥 У вас нет назначенных задач.", reply_markup=builder.as_markup()
            )
            await callback.answer()
            return

        # Предзагружаем все задачи и пользователей батчами (fix N+1)
        task_ids = [dt.task_id for dt in delegated_tasks]
        user_ids = [dt.assigned_by_user_id for dt in delegated_tasks]

        # Загружаем задачи одним запросом
        tasks_result = await session.execute(select(Task).where(Task.id.in_(task_ids)))
        tasks_map = {task.id: task for task in tasks_result.scalars().all()}

        # Загружаем пользователей одним запросом
        users_result = await session.execute(select(User).where(User.user_id.in_(user_ids)))
        users_map = {user.user_id: user for user in users_result.scalars().all()}

        # Формируем список
        lines = []
        for dt in delegated_tasks:
            task = tasks_map.get(dt.task_id)
            assigned_by = users_map.get(dt.assigned_by_user_id)

            if not task or not assigned_by:
                continue

            status_emoji = {"pending_acceptance": "⏳", "accepted": "✅"}

            emoji = status_emoji.get(dt.status, "")
            deadline_str = dt.deadline.strftime("%d.%m")

            # Показываем сколько осталось времени
            days_left = (dt.deadline.date() - dt_date.today()).days
            if days_left < 0:
                time_left = f"⚠️ Просрочено на {abs(days_left)} дн"
            elif days_left == 0:
                time_left = "🔥 Сегодня!"
            elif days_left == 1:
                time_left = "Завтра"
            else:
                time_left = f"{days_left} дн"

            lines.append(
                f"{emoji} <b>{task.title}</b>\n"
                f"   от {assigned_by.first_name} | {deadline_str} | {time_left}"
            )

        text = "\n\n".join(lines)

        builder = InlineKeyboardBuilder()
        for dt in delegated_tasks[:10]:  # Лимит 10 задач
            task = tasks_map.get(dt.task_id)
            if task:
                builder.button(text=f"✏️ {task.title[:15]}...", callback_data=f"DT_EDIT:{dt.id}")
        builder.button(text="« Назад в меню", callback_data="back_to_menu")
        builder.adjust(1)

        await callback.message.edit_text(
            f"<b>📥 Назначенные вам задачи:</b>\n\n{text}", reply_markup=builder.as_markup()
        )

    await callback.answer()
    logger.info(f"User {callback.from_user.id} viewed assigned tasks from menu")


@router.callback_query(F.data == "back_to_menu")
async def menu_back(callback: CallbackQuery):
    """Возвращается в главное меню."""
    builder = InlineKeyboardBuilder()

    # Первый ряд - привычки
    builder.button(text="Добавить привычку", callback_data="add_habit_start")
    builder.button(text="Список привычек", callback_data="list_habits")

    # Второй ряд - задачи
    builder.button(text="Добавить задачу", callback_data="add_task_start")
    builder.button(text="Список задач", callback_data="list_tasks")

    # Третий ряд - делегирование
    builder.button(text="Делегировать 👥", callback_data="show_delegate")
    builder.button(text="Назначено мне 📥", callback_data="show_assigned")

    # Четвёртый ряд - основное
    builder.button(text="Сегодня 📅", callback_data="show_today")
    builder.button(text="Статистика 📊", callback_data="show_stats")

    # Пятый ряд - дополнительно
    builder.button(text="Журнал 📖", callback_data="show_journal")
    builder.button(text="Экспорт 💾", callback_data="show_export")

    # Шестой ряд - Language Learning
    builder.button(text="Изучение языков 🎧", callback_data="show_language")

    # Седьмой ряд - настройки и помощь
    builder.button(text="Настройки ⚙️", callback_data="show_settings")
    builder.button(text="Помощь ❓", callback_data="show_help")

    builder.adjust(2, 2, 2, 2, 2, 1, 2)

    await callback.message.edit_text("Что делаем?", reply_markup=builder.as_markup())
    await callback.answer()
    logger.info(f"User {callback.from_user.id} returned to menu")


@router.callback_query(F.data == "show_journal")
async def menu_show_journal(callback: CallbackQuery):
    """Показывает журнал из меню."""
    builder = InlineKeyboardBuilder()
    builder.button(text="Добавить запись", callback_data="journal_add")
    builder.button(text="Показать за неделю", callback_data="journal_week")
    builder.button(text="Показать за месяц", callback_data="journal_month")
    builder.button(text="« Назад в меню", callback_data="back_to_menu")
    builder.adjust(1)

    await callback.message.edit_text(
        "📖 <b>Журнал привычек</b>\n\n"
        "Здесь ты можешь вести записи о выполнении привычек.\n\n"
        "Что хочешь сделать?",
        reply_markup=builder.as_markup(),
    )
    await callback.answer()
    logger.info(f"User {callback.from_user.id} opened journal from menu")


@router.callback_query(F.data == "show_export")
async def menu_show_export(callback: CallbackQuery):
    """Показывает меню экспорта/импорта."""
    builder = InlineKeyboardBuilder()
    builder.button(text="Экспорт данных 📤", callback_data="export_data")
    builder.button(text="Импорт данных 📥", callback_data="import_data")
    builder.button(text="« Назад в меню", callback_data="back_to_menu")
    builder.adjust(1)

    await callback.message.edit_text(
        "💾 <b>Экспорт и импорт</b>\n\n"
        "Сохрани свои данные или загрузи из резервной копии.\n\n"
        "Что хочешь сделать?",
        reply_markup=builder.as_markup(),
    )
    await callback.answer()
    logger.info(f"User {callback.from_user.id} opened export menu")


@router.callback_query(F.data == "show_language")
async def menu_show_language(callback: CallbackQuery):
    """Показывает меню Language Learning."""
    from db import UserLanguageSettings

    user_id = callback.from_user.id

    async with SessionLocal() as session:
        result = await session.execute(
            select(UserLanguageSettings).where(UserLanguageSettings.user_id == user_id)
        )
        settings = result.scalar_one_or_none()

        if not settings or not settings.api_token:
            # API не настроен
            builder = InlineKeyboardBuilder()
            builder.button(text="Настроить API", callback_data="lang_setup_start")
            builder.button(text="« Назад в меню", callback_data="back_to_menu")
            builder.adjust(1)

            await callback.message.edit_text(
                "🎧 <b>Изучение языков</b>\n\n"
                "Для использования функций изучения языков нужен API токен.\n\n"
                "Настрой API токен, чтобы начать:",
                reply_markup=builder.as_markup(),
            )
        else:
            # API настроен
            builder = InlineKeyboardBuilder()
            builder.button(text="Выбрать книгу 📚", callback_data="lang_choose_book")
            builder.button(text="Читать 📖", callback_data="lang_read")
            builder.button(text="Грамматика 📝", callback_data="lang_grammar")
            builder.button(text="Настроить расписание 🔔", callback_data="lang_schedule")
            builder.button(text="Статус API ✅", callback_data="lang_status")
            builder.button(text="« Назад в меню", callback_data="back_to_menu")
            builder.adjust(2, 2, 1, 1, 1)

            await callback.message.edit_text(
                "🎧 <b>Изучение языков</b>\n\n" "Что хочешь сделать?",
                reply_markup=builder.as_markup(),
            )

    await callback.answer()
    logger.info(f"User {callback.from_user.id} opened language menu")


@router.callback_query(F.data == "lang_setup_start")
async def menu_lang_setup(callback: CallbackQuery):
    """Перенаправляет на настройку Language API."""
    await callback.message.edit_text(
        "🔑 <b>Настройка Language Learning API</b>\n\n"
        "Для использования функций чтения книг нужен API токен.\n\n"
        "<b>Как получить токен:</b>\n"
        "1. Зарегистрируйтесь на сайте Language Learning\n"
        "2. Войдите в личный кабинет\n"
        "3. Перейдите в раздел API Settings\n"
        "4. Сгенерируйте токен для Telegram\n\n"
        "Используйте команду /language_setup для продолжения настройки."
    )
    await callback.answer()
    logger.info(f"User {callback.from_user.id} started language setup from menu")


@router.callback_query(F.data == "lang_choose_book")
async def menu_lang_choose_book(callback: CallbackQuery):
    """Перенаправляет на выбор книги."""
    await callback.message.edit_text(
        "📚 <b>Выбор книги</b>\n\n" "Используйте команду /choose_book для выбора книги для чтения."
    )
    await callback.answer()


@router.callback_query(F.data == "lang_read")
async def menu_lang_read(callback: CallbackQuery):
    """Перенаправляет на чтение."""
    await callback.message.edit_text(
        "📖 <b>Чтение</b>\n\n" "Используйте команду /read для чтения текущего фрагмента."
    )
    await callback.answer()


@router.callback_query(F.data == "lang_grammar")
async def menu_lang_grammar(callback: CallbackQuery):
    """Перенаправляет на грамматику."""
    await callback.message.edit_text(
        "📝 <b>Грамматика</b>\n\n" "Используйте команду /grammar для изучения грамматики."
    )
    await callback.answer()


@router.callback_query(F.data == "lang_schedule")
async def menu_lang_schedule(callback: CallbackQuery):
    """Перенаправляет на настройку расписания."""
    await callback.message.edit_text(
        "🔔 <b>Расписание аудио-воркфлоу</b>\n\n"
        "Используйте команду /audio_schedule для настройки 3-этапного рабочего процесса:\n"
        "1️⃣ Утро: Аудио фрагмента\n"
        "2️⃣ День: Текст для чтения\n"
        "3️⃣ Вечер: Вопросы на понимание"
    )
    await callback.answer()


@router.callback_query(F.data == "lang_status")
async def menu_lang_status(callback: CallbackQuery):
    """Перенаправляет на статус API."""
    await callback.message.edit_text(
        "✅ <b>Статус API</b>\n\n" "Используйте команду /language_status для проверки статуса API."
    )
    await callback.answer()


@router.callback_query(F.data == "show_help")
async def menu_show_help(callback: CallbackQuery):
    """Показывает помощь из меню."""
    builder = InlineKeyboardBuilder()
    builder.button(text="« Назад в меню", callback_data="back_to_menu")
    builder.adjust(1)

    help_text = (
        "❓ <b>Помощь</b>\n\n"
        "<b>Основные команды:</b>\n"
        "/start - Начать работу с ботом\n"
        "/menu - Главное меню\n"
        "/today - Сводка на сегодня\n\n"
        "<b>Привычки:</b>\n"
        "/addhabit - Добавить привычку\n"
        "/listhabits - Список привычек\n\n"
        "<b>Задачи:</b>\n"
        "/addtask - Добавить задачу\n"
        "/tasks - Список задач\n\n"
        "<b>Делегирование:</b>\n"
        "/trust &lt;user_id&gt; - Добавить в доверенные\n"
        "/delegate - Делегировать задачу\n"
        "/delegated - Мои делегированные\n"
        "/assigned - Назначено мне\n\n"
        "<b>Другое:</b>\n"
        "/stats - Статистика\n"
        "/journal - Журнал\n"
        "/settings - Настройки\n\n"
    )

    await callback.message.edit_text(help_text, reply_markup=builder.as_markup())
    await callback.answer()
    logger.info(f"User {callback.from_user.id} opened help from menu")
