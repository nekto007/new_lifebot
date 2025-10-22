import re
import sys
from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from config import logger
from db import SessionLocal, User

router = Router()


# FSM States для онбординга
class OnboardingStates(StatesGroup):
    language_selection = State()
    timezone_detection = State()
    timezone_confirmation = State()
    quiet_hours_selection = State()
    quiet_hours_custom = State()
    default_habits_selection = State()
    morning_ping_time = State()
    evening_ping_time = State()
    completed = State()


# Вспомогательные функции
def detect_timezone_from_telegram(user_language_code: str = None) -> str:
    """Определяет часовой пояс на основе языка пользователя или других данных."""
    # Простая эвристика: если язык ru, предполагаем Europe/Moscow
    if user_language_code == "ru":
        return "Europe/Moscow"
    return "UTC"


def validate_time_format(time_str: str) -> tuple[bool, time | None]:
    """Валидирует формат времени HH:MM."""
    pattern = r"^([0-1]?[0-9]|2[0-3]):([0-5][0-9])$"
    match = re.match(pattern, time_str.strip())
    if match:
        hour, minute = int(match.group(1)), int(match.group(2))
        return True, time(hour, minute)
    return False, None


def format_timezone_confirmation(tz_name: str) -> str:
    """Форматирует текущее время в указанном часовом поясе."""
    try:
        tz = ZoneInfo(tz_name)
        current_time = datetime.now(tz).strftime("%H:%M")
        return f"{tz_name} (сейчас {current_time})"
    except Exception:
        return tz_name


async def save_user_data(user_id: int, data: dict):
    """Сохраняет данные пользователя в БД."""
    from sqlalchemy import select

    async with SessionLocal() as session:
        # Используем select вместо get для совместимости с async
        result = await session.execute(select(User).where(User.user_id == user_id))
        user = result.scalar_one_or_none()

        if not user:
            user = User(user_id=user_id)
            session.add(user)

        # Обновляем поля
        if "first_name" in data:
            user.first_name = data["first_name"]
        if "lang" in data:
            user.lang = data["lang"]
        if "tz" in data:
            user.tz = data["tz"]
        if "quiet_hours_from" in data:
            user.quiet_hours_from = data["quiet_hours_from"]
        if "quiet_hours_to" in data:
            user.quiet_hours_to = data["quiet_hours_to"]
        if "morning_ping_time" in data:
            user.morning_ping_time = data["morning_ping_time"]
        if "evening_ping_time" in data:
            user.evening_ping_time = data["evening_ping_time"]

        await session.commit()
        await session.refresh(user)
        logger.info(f"Saved user {user_id} with lang={user.lang}")


async def get_user_onboarding_state(user_id: int) -> dict | None:
    """Получает состояние онбординга пользователя из БД."""
    async with SessionLocal() as session:
        result = await session.execute(select(User).where(User.user_id == user_id))
        user = result.scalar_one_or_none()
        if user and user.lang:
            # Пользователь уже прошел онбординг
            return {
                "completed": True,
                "lang": user.lang,
                "tz": user.tz,
                "quiet_hours_from": user.quiet_hours_from,
                "quiet_hours_to": user.quiet_hours_to,
            }
        return None


# Обработчики команд и состояний
@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    """Обработчик команды /start - начало или повтор онбординга."""
    user_state = await get_user_onboarding_state(message.from_user.id)

    # Если онбординг уже пройден - показываем приветствие и предлагаем /menu
    if user_state and user_state.get("completed"):
        await message.answer(
            f"С возвращением, {message.from_user.first_name}! 👋\n\n"
            "Ты уже настроил бота. Используй /menu для доступа к функциям.",
        )
        return

    # Проверяем, есть ли незавершенный онбординг
    current_state = await state.get_state()
    if current_state and current_state != OnboardingStates.language_selection.state:
        builder = InlineKeyboardBuilder()
        builder.button(text="Продолжить ✅", callback_data="onboarding_resume")
        builder.button(text="Начать заново 🔄", callback_data="onboarding_restart")
        builder.adjust(1)

        await message.answer(
            "У тебя есть незавершенная настройка. Хочешь продолжить или начать заново?",
            reply_markup=builder.as_markup(),
        )
        return

    # Начинаем новый онбординг
    await start_onboarding(message, state)


async def start_onboarding(message: Message, state: FSMContext):
    """Начинает процесс онбординга с выбора языка."""
    await state.clear()

    builder = InlineKeyboardBuilder()
    builder.button(text="Русский 🇷🇺", callback_data="lang_ru")
    builder.button(text="English 🇬🇧", callback_data="lang_en")
    builder.adjust(2)

    await state.update_data(
        first_name=message.from_user.first_name,
        user_id=message.from_user.id,
        started_at=datetime.now().isoformat(),
    )

    await message.answer(
        f"Привет, {message.from_user.first_name}! 👋\n\n"
        "Я — <b>Дисциплинатор</b>. Помогу прокачать дисциплину и держать курс на цели.\n\n"
        "<b>Что я умею:</b>\n"
        "✅ Трекинг привычек с умными напоминаниями\n"
        "📋 Управление задачами с дедлайнами\n"
        "👥 Делегирование задач другим людям\n"
        "🎧 Изучение языков с аудио-воркфлоу\n"
        "🤖 AI-генерация заданий для привычек\n"
        "📊 Статистика и отчёты\n"
        "⚙️ Персонализация под твой режим\n\n"
        "Выбери язык для начала:",
        reply_markup=builder.as_markup(),
    )

    await state.set_state(OnboardingStates.language_selection)
    logger.info(f"User {message.from_user.id} started onboarding")


@router.callback_query(F.data == "onboarding_resume")
async def resume_onboarding(callback: CallbackQuery):
    """Продолжает незавершенный онбординг."""
    await callback.message.edit_text("Продолжаем настройку! 🚀")
    await callback.answer()


@router.callback_query(F.data == "onboarding_restart")
async def restart_onboarding(callback: CallbackQuery, state: FSMContext):
    """Начинает онбординг заново."""
    await callback.message.delete()
    await start_onboarding(callback.message, state)
    await callback.answer()


@router.callback_query(StateFilter(OnboardingStates.language_selection), F.data.startswith("lang_"))
async def process_language_selection(callback: CallbackQuery, state: FSMContext):
    """Обработка выбора языка."""
    lang = callback.data.split("_")[1]
    await state.update_data(lang=lang)

    # Определяем часовой пояс
    detected_tz = detect_timezone_from_telegram(lang)
    await state.update_data(detected_tz=detected_tz)

    builder = InlineKeyboardBuilder()
    builder.button(text=f"Оставить {detected_tz} ✅", callback_data=f"tz_keep_{detected_tz}")
    builder.button(text="Изменить 🌍", callback_data="tz_change")
    builder.adjust(1)

    tz_display = format_timezone_confirmation(detected_tz)

    await callback.message.edit_text(
        f"Отлично! Теперь укажи свой часовой пояс.\n\n" f"Определил: <b>{tz_display}</b>\n\n" "Всё верно?",
        reply_markup=builder.as_markup(),
    )

    await state.set_state(OnboardingStates.timezone_confirmation)
    await callback.answer()
    logger.info(f"User {callback.from_user.id} selected language: {lang}")


@router.callback_query(StateFilter(OnboardingStates.timezone_confirmation), F.data.startswith("tz_keep_"))
async def process_timezone_keep(callback: CallbackQuery, state: FSMContext):
    """Пользователь оставляет определенный часовой пояс."""
    tz_name = callback.data.split("tz_keep_")[1]
    await state.update_data(tz=tz_name)

    await show_quiet_hours_selection(callback.message, state, edit=True)
    await callback.answer()


@router.callback_query(StateFilter(OnboardingStates.timezone_confirmation), F.data == "tz_change")
async def process_timezone_change(callback: CallbackQuery, state: FSMContext):
    """Пользователь хочет изменить часовой пояс."""
    # Показываем популярные часовые пояса
    builder = InlineKeyboardBuilder()
    common_timezones = [
        ("Europe/Moscow", "Москва (MSK)"),
        ("Europe/London", "Лондон (GMT)"),
        ("America/New_York", "Нью-Йорк (EST)"),
        ("Asia/Tokyo", "Токио (JST)"),
        ("Europe/Paris", "Париж (CET)"),
        ("Asia/Dubai", "Дубай (GST)"),
    ]

    for tz_name, tz_label in common_timezones:
        builder.button(text=tz_label, callback_data=f"tz_select_{tz_name}")

    builder.adjust(2)

    await callback.message.edit_text("Выбери свой часовой пояс:", reply_markup=builder.as_markup())

    await state.set_state(OnboardingStates.timezone_detection)
    await callback.answer()


@router.callback_query(StateFilter(OnboardingStates.timezone_detection), F.data.startswith("tz_select_"))
async def process_timezone_select(callback: CallbackQuery, state: FSMContext):
    """Обработка выбора конкретного часового пояса."""
    tz_name = callback.data.split("tz_select_")[1]
    await state.update_data(tz=tz_name)

    tz_display = format_timezone_confirmation(tz_name)
    builder = InlineKeyboardBuilder()
    builder.button(text="Подтвердить ✅", callback_data="tz_confirm")
    builder.button(text="Выбрать другой", callback_data="tz_change")
    builder.adjust(1)

    await callback.message.edit_text(
        f"Проверим: сейчас <b>{tz_display}</b> в твоей зоне.\n\nВсё верно?",
        reply_markup=builder.as_markup(),
    )

    await state.set_state(OnboardingStates.timezone_confirmation)
    await callback.answer()


@router.callback_query(StateFilter(OnboardingStates.timezone_confirmation), F.data == "tz_confirm")
async def confirm_timezone(callback: CallbackQuery, state: FSMContext):
    """Подтверждение часового пояса."""
    await show_quiet_hours_selection(callback.message, state, edit=True)
    await callback.answer()


async def show_quiet_hours_selection(message: Message, state: FSMContext, edit: bool = False):
    """Показывает выбор тихих часов."""
    builder = InlineKeyboardBuilder()
    builder.button(text="22:30 – 07:00", callback_data="quiet_22:30-07:00")
    builder.button(text="23:00 – 07:30", callback_data="quiet_23:00-07:30")
    builder.button(text="00:00 – 08:00", callback_data="quiet_00:00-08:00")
    builder.button(text="Настроить вручную ⚙️", callback_data="quiet_custom")
    builder.button(text="Не беспокоить круглосуточно 🔕", callback_data="quiet_always")
    builder.adjust(1)

    text = "Когда не беспокоить уведомлениями?\n\n" "Выбери диапазон <b>тихих часов</b> или настрой вручную:"

    if edit:
        await message.edit_text(text, reply_markup=builder.as_markup())
    else:
        await message.answer(text, reply_markup=builder.as_markup())

    await state.set_state(OnboardingStates.quiet_hours_selection)


@router.callback_query(StateFilter(OnboardingStates.quiet_hours_selection), F.data.startswith("quiet_"))
async def process_quiet_hours(callback: CallbackQuery, state: FSMContext):
    """Обработка выбора тихих часов."""
    quiet_data = callback.data.split("quiet_")[1]

    if quiet_data == "custom":
        await callback.message.edit_text(
            "Введи время начала тихих часов в формате <b>HH:MM</b>\n\n" "Например: <code>22:30</code>"
        )
        await state.set_state(OnboardingStates.quiet_hours_custom)
        await state.update_data(quiet_custom_step="start")
        await callback.answer()
        return

    if quiet_data == "always":
        await state.update_data(quiet_hours_from=None, quiet_hours_to=None)
    else:
        # Парсим диапазон вида "22:30-07:00"
        start_str, end_str = quiet_data.split("-")
        _, start_time = validate_time_format(start_str)
        _, end_time = validate_time_format(end_str)
        await state.update_data(quiet_hours_from=start_time, quiet_hours_to=end_time)

    await show_default_habits_selection(callback.message, state, edit=True)
    await callback.answer()


@router.message(StateFilter(OnboardingStates.quiet_hours_custom))
async def process_quiet_hours_custom_input(message: Message, state: FSMContext):
    """Обработка ручного ввода тихих часов."""
    data = await state.get_data()
    step = data.get("quiet_custom_step")

    is_valid, parsed_time = validate_time_format(message.text)

    if not is_valid:
        await message.answer(
            f"Хм, не распознал время «{message.text}».\n\n"
            "Формат: <b>HH:MM</b>, пример: <code>07:30</code>\n\n"
            "Попробуешь ещё?"
        )
        return

    if step == "start":
        await state.update_data(quiet_hours_from=parsed_time, quiet_custom_step="end")
        await message.answer(
            f"Начало: <b>{parsed_time.strftime('%H:%M')}</b> ✅\n\n"
            "Теперь введи время окончания тихих часов:"
        )
    elif step == "end":
        await state.update_data(quiet_hours_to=parsed_time)

        data = await state.get_data()
        start = data["quiet_hours_from"]

        await message.answer(
            f"Тихие часы: <b>{start.strftime('%H:%M')} – {parsed_time.strftime('%H:%M')}</b> ✅"
        )

        await show_default_habits_selection(message, state, edit=False)


async def show_default_habits_selection(message: Message, state: FSMContext, edit: bool = False):
    """Показывает предложение базовых привычек."""
    builder = InlineKeyboardBuilder()
    builder.button(text="Добавить всё ✅", callback_data="habits_add_all")
    builder.button(text="Выбрать по одной", callback_data="habits_choose")
    builder.button(text="Пропустить ⏭", callback_data="habits_skip")
    builder.adjust(1)

    text = (
        "Предлагаю базовый набор привычек для старта:\n\n"
        "• <b>Фокус 60 мин</b> — глубокая работа без отвлечений\n"
        "• <b>Зарядка 10 мин</b> — утренняя активность\n"
        "• <b>Чтение 10 мин</b> — развитие кругозора\n\n"
        "Добавляем?"
    )

    if edit:
        await message.edit_text(text, reply_markup=builder.as_markup())
    else:
        await message.answer(text, reply_markup=builder.as_markup())

    await state.set_state(OnboardingStates.default_habits_selection)


@router.callback_query(
    StateFilter(OnboardingStates.default_habits_selection),
    F.data.startswith("habits_"),
)
async def process_default_habits(callback: CallbackQuery, state: FSMContext):
    """Обработка выбора базовых привычек."""
    action = callback.data.split("habits_")[1]

    if action == "add_all":
        await state.update_data(default_habits=["focus_60", "exercise_10", "reading_10"])
        await callback.message.edit_text("Отлично! Добавил все привычки ✅")
    elif action == "choose":
        await callback.message.edit_text(
            "Выбор отдельных привычек будет доступен в следующей версии. "
            "Пока добавляю все базовые привычки ✅"
        )
        await state.update_data(default_habits=["focus_60", "exercise_10", "reading_10"])
    else:  # skip
        await state.update_data(default_habits=[])
        await callback.message.edit_text("Хорошо, пропускаем привычки 👌")

    await show_morning_ping_selection(callback.message, state, edit=False)
    await callback.answer()


async def show_morning_ping_selection(message: Message, state: FSMContext, edit: bool = False):
    """Показывает выбор времени утреннего пинга."""
    builder = InlineKeyboardBuilder()

    morning_times = ["06:00", "06:30", "07:00", "07:30", "08:00", "08:30", "09:00"]
    for t in morning_times:
        builder.button(text=t, callback_data=f"morning_{t}")

    builder.button(text="Ввести вручную ⌨️", callback_data="morning_custom")
    builder.adjust(3)

    text = "Во сколько присылать <b>утренний пинг</b>?\n\nВыбери время или введи вручную:"

    if edit:
        await message.edit_text(text, reply_markup=builder.as_markup())
    else:
        await message.answer(text, reply_markup=builder.as_markup())

    await state.set_state(OnboardingStates.morning_ping_time)


@router.callback_query(StateFilter(OnboardingStates.morning_ping_time), F.data.startswith("morning_"))
async def process_morning_ping(callback: CallbackQuery, state: FSMContext):
    """Обработка выбора времени утреннего пинга."""
    time_data = callback.data.split("morning_")[1]

    if time_data == "custom":
        await callback.message.edit_text(
            "Введи время утреннего пинга в формате <b>HH:MM</b>\n\n" "Например: <code>07:30</code>"
        )
        await state.update_data(morning_custom=True)
        await callback.answer()
        return

    _, parsed_time = validate_time_format(time_data)
    await state.update_data(morning_ping_time=parsed_time)

    await callback.message.edit_text(f"Утренний пинг: <b>{time_data}</b> ✅")
    await show_evening_ping_selection(callback.message, state, edit=False)
    await callback.answer()


@router.message(StateFilter(OnboardingStates.morning_ping_time))
async def process_morning_ping_custom(message: Message, state: FSMContext):
    """Обработка ручного ввода времени утреннего пинга."""
    data = await state.get_data()
    if not data.get("morning_custom"):
        return

    is_valid, parsed_time = validate_time_format(message.text)

    if not is_valid:
        await message.answer(
            f"Хм, не распознал время «{message.text}».\n\n"
            "Формат: <b>HH:MM</b>, пример: <code>07:30</code>\n\n"
            "Попробуешь ещё?"
        )
        return

    await state.update_data(morning_ping_time=parsed_time, morning_custom=False)
    await message.answer(f"Утренний пинг: <b>{parsed_time.strftime('%H:%M')}</b> ✅")
    await show_evening_ping_selection(message, state, edit=False)


async def show_evening_ping_selection(message: Message, state: FSMContext, edit: bool = False):
    """Показывает выбор времени вечернего отчёта."""
    builder = InlineKeyboardBuilder()

    evening_times = ["19:00", "19:30", "20:00", "20:30", "21:00", "21:30", "22:00"]
    for t in evening_times:
        builder.button(text=t, callback_data=f"evening_{t}")

    builder.button(text="Ввести вручную ⌨️", callback_data="evening_custom")
    builder.adjust(3)

    text = "Во сколько присылать <b>вечерний отчёт</b>?\n\nВыбери время или введи вручную:"

    if edit:
        await message.edit_text(text, reply_markup=builder.as_markup())
    else:
        await message.answer(text, reply_markup=builder.as_markup())

    await state.set_state(OnboardingStates.evening_ping_time)


@router.callback_query(StateFilter(OnboardingStates.evening_ping_time), F.data.startswith("evening_"))
async def process_evening_ping(callback: CallbackQuery, state: FSMContext):
    """Обработка выбора времени вечернего отчёта."""
    time_data = callback.data.split("evening_")[1]

    if time_data == "custom":
        await callback.message.edit_text(
            "Введи время вечернего отчёта в формате <b>HH:MM</b>\n\n" "Например: <code>20:00</code>"
        )
        await state.update_data(evening_custom=True)
        await callback.answer()
        return

    _, parsed_time = validate_time_format(time_data)
    await state.update_data(evening_ping_time=parsed_time)

    await callback.message.edit_text(f"Вечерний отчёт: <b>{time_data}</b> ✅")
    await complete_onboarding(callback.message, state)
    await callback.answer()


@router.message(StateFilter(OnboardingStates.evening_ping_time))
async def process_evening_ping_custom(message: Message, state: FSMContext):
    """Обработка ручного ввода времени вечернего отчёта."""
    data = await state.get_data()
    if not data.get("evening_custom"):
        return

    is_valid, parsed_time = validate_time_format(message.text)

    if not is_valid:
        await message.answer(
            f"Хм, не распознал время «{message.text}».\n\n"
            "Формат: <b>HH:MM</b>, пример: <code>20:00</code>\n\n"
            "Попробуешь ещё?"
        )
        return

    await state.update_data(evening_ping_time=parsed_time, evening_custom=False)
    await message.answer(f"Вечерний отчёт: <b>{parsed_time.strftime('%H:%M')}</b> ✅")
    await complete_onboarding(message, state)


async def complete_onboarding(message: Message, state: FSMContext):
    """Завершает онбординг и сохраняет данные."""
    data = await state.get_data()

    # Сохраняем в БД
    await save_user_data(
        data["user_id"],
        {
            "first_name": data["first_name"],
            "lang": data["lang"],
            "tz": data["tz"],
            "quiet_hours_from": data.get("quiet_hours_from"),
            "quiet_hours_to": data.get("quiet_hours_to"),
            "morning_ping_time": data.get("morning_ping_time"),
            "evening_ping_time": data.get("evening_ping_time"),
        },
    )

    await state.set_state(OnboardingStates.completed)
    await state.clear()

    await message.answer(
        "🎉 <b>Готово!</b>\n\n"
        f"Настройка завершена, {data['first_name']}!\n\n"
        "Теперь набери /today, чтобы увидеть сводку на сегодня, "
        "или /menu для доступа ко всем функциям.\n\n"
        "Удачи! 💪"
    )

    # Планировщик автоматически подхватит нового пользователя при следующем запуске
    logger.info(f"User {data['user_id']} completed onboarding, scheduler will pick up on next restart")
