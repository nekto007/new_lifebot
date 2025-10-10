"""Настройки пользователя: язык, часовой пояс, тихие часы, пинги."""

import sys
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
from db import SessionLocal, User

router = Router()


async def get_user(user_id: int) -> User | None:
    """Получает пользователя из БД по Telegram ID."""
    async with SessionLocal() as session:
        result = await session.execute(select(User).where(User.user_id == user_id))
        return result.scalar_one_or_none()


# FSM States для настроек
class SettingsStates(StatesGroup):
    edit_lang = State()
    edit_tz = State()
    edit_quiet_from = State()
    edit_quiet_to = State()
    edit_morning_ping = State()
    edit_evening_ping = State()


@router.message(Command("settings"))
async def cmd_settings(message: Message):
    """Команда /settings - показывает меню настроек."""
    user_id = message.from_user.id

    user = await get_user(user_id)
    if not user or not user.lang:
        await message.answer(
            "Привет! Сначала нужно пройти настройку.\n\n" "Используй команду /start для начала работы."
        )
        return

    # Формируем текст с текущими настройками
    lang_name = "Русский" if user.lang == "ru" else "English"
    tz = user.tz or "UTC"

    quiet_from_str = user.quiet_hours_from.strftime("%H:%M") if user.quiet_hours_from else "Не установлено"
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
    builder.adjust(1)

    await message.answer(
        f"Настройки профиля:\n\n"
        f"Язык: <b>{lang_name}</b>\n"
        f"Часовой пояс: <b>{tz}</b>\n"
        f"Тихие часы: <b>{quiet_from_str} - {quiet_to_str}</b>\n"
        f"Утренний пинг: <b>{morning_ping_str}</b>\n"
        f"Вечерний отчёт: <b>{evening_ping_str}</b>\n\n"
        "Что хочешь изменить?",
        reply_markup=builder.as_markup(),
    )
    logger.info(f"User {user_id} viewed /settings")


# ===== ЯЗЫК =====
@router.callback_query(F.data == "settings_lang")
async def settings_lang_menu(callback: CallbackQuery, state: FSMContext):
    """Меню выбора языка."""
    builder = InlineKeyboardBuilder()
    builder.button(text="Русский", callback_data="SET_LANG:ru")
    builder.button(text="English", callback_data="SET_LANG:en")
    builder.button(text="Назад", callback_data="settings_back")
    builder.adjust(1)

    await callback.message.edit_text("Выбери язык интерфейса:", reply_markup=builder.as_markup())
    await callback.answer()


@router.callback_query(F.data.startswith("SET_LANG:"))
async def settings_lang_set(callback: CallbackQuery):
    """Устанавливает язык."""
    lang_code = callback.data.split(":")[1]
    user_id = callback.from_user.id

    async with SessionLocal() as session:
        result = await session.execute(select(User).where(User.user_id == user_id))
        user = result.scalar_one_or_none()
        if not user:
            await callback.answer("Пользователь не найден", show_alert=True)
            return

        user.lang = lang_code
        await session.commit()

    lang_name = "Русский" if lang_code == "ru" else "English"
    await callback.message.edit_text(f"Готово! Язык изменён на <b>{lang_name}</b>.")
    await callback.answer()
    logger.info(f"User {user_id} changed language to {lang_code}")


# ===== ЧАСОВОЙ ПОЯС =====
@router.callback_query(F.data == "settings_tz")
async def settings_tz_menu(callback: CallbackQuery, state: FSMContext):
    """Меню выбора часового пояса."""
    common_tzs = [
        ("Europe/Moscow", "Москва (UTC+3)"),
        ("Europe/London", "Лондон (UTC+0)"),
        ("America/New_York", "Нью-Йорк (UTC-5)"),
        ("Asia/Shanghai", "Шанхай (UTC+8)"),
        ("UTC", "UTC"),
    ]

    builder = InlineKeyboardBuilder()
    for tz_id, tz_name in common_tzs:
        builder.button(text=tz_name, callback_data=f"SET_TZ:{tz_id}")
    builder.button(text="Назад", callback_data="settings_back")
    builder.adjust(1)

    await callback.message.edit_text("Выбери часовой пояс:", reply_markup=builder.as_markup())
    await callback.answer()


@router.callback_query(F.data.startswith("SET_TZ:"))
async def settings_tz_set(callback: CallbackQuery):
    """Устанавливает часовой пояс."""
    tz = callback.data.split("SET_TZ:")[1]
    user_id = callback.from_user.id

    async with SessionLocal() as session:
        result = await session.execute(select(User).where(User.user_id == user_id))
        user = result.scalar_one_or_none()
        if not user:
            await callback.answer("Пользователь не найден", show_alert=True)
            return

        user.tz = tz
        await session.commit()

    await callback.message.edit_text(
        f"Готово! Часовой пояс изменён на <b>{tz}</b>.\n\n"
        "Пересоздал расписание напоминаний (при следующем перезапуске бота)."
    )
    await callback.answer()
    logger.info(f"User {user_id} changed timezone to {tz}")


# ===== ТИХИЕ ЧАСЫ =====
@router.callback_query(F.data == "settings_quiet")
async def settings_quiet_menu(callback: CallbackQuery, state: FSMContext):
    """Меню настройки тихих часов."""
    user_id = callback.from_user.id
    user = await get_user(user_id)

    quiet_from_str = user.quiet_hours_from.strftime("%H:%M") if user.quiet_hours_from else "Не установлено"
    quiet_to_str = user.quiet_hours_to.strftime("%H:%M") if user.quiet_hours_to else "Не установлено"

    builder = InlineKeyboardBuilder()
    builder.button(text="Установить начало", callback_data="SET_QUIET_FROM")
    builder.button(text="Установить конец", callback_data="SET_QUIET_TO")
    builder.button(text="Отключить", callback_data="SET_QUIET_OFF")
    builder.button(text="Назад", callback_data="settings_back")
    builder.adjust(1)

    await callback.message.edit_text(
        f"Тихие часы (без уведомлений):\n\n"
        f"С: <b>{quiet_from_str}</b>\n"
        f"До: <b>{quiet_to_str}</b>\n\n"
        "Что хочешь изменить?",
        reply_markup=builder.as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data == "SET_QUIET_FROM")
async def settings_quiet_from_prompt(callback: CallbackQuery, state: FSMContext):
    """Запрашивает время начала тихих часов."""
    await state.set_state(SettingsStates.edit_quiet_from)
    await callback.message.edit_text(
        "Введи время начала тихих часов в формате <b>ЧЧ:ММ</b>\n" "Например: 22:00"
    )
    await callback.answer()


@router.message(StateFilter(SettingsStates.edit_quiet_from))
async def settings_quiet_from_save(message: Message, state: FSMContext):
    """Сохраняет время начала тихих часов."""
    user_id = message.from_user.id

    try:
        hour, minute = map(int, message.text.split(":"))
        if not (0 <= hour < 24 and 0 <= minute < 60):
            raise ValueError

        time_value = dt_time(hour, minute)

        async with SessionLocal() as session:
            result = await session.execute(select(User).where(User.user_id == user_id))
            user = result.scalar_one_or_none()
            if not user:
                await message.answer("Пользователь не найден")
                await state.clear()
                return

            user.quiet_hours_from = time_value
            await session.commit()

        await message.answer(f"Готово! Начало тихих часов: <b>{time_value.strftime('%H:%M')}</b>")
        await state.clear()
        logger.info(f"User {user_id} set quiet_hours_from to {time_value}")

    except (ValueError, AttributeError):
        await message.answer("Неверный формат времени. Используй формат <b>ЧЧ:ММ</b>\n" "Например: 22:00")


@router.callback_query(F.data == "SET_QUIET_TO")
async def settings_quiet_to_prompt(callback: CallbackQuery, state: FSMContext):
    """Запрашивает время окончания тихих часов."""
    await state.set_state(SettingsStates.edit_quiet_to)
    await callback.message.edit_text(
        "Введи время окончания тихих часов в формате <b>ЧЧ:ММ</b>\n" "Например: 08:00"
    )
    await callback.answer()


@router.message(StateFilter(SettingsStates.edit_quiet_to))
async def settings_quiet_to_save(message: Message, state: FSMContext):
    """Сохраняет время окончания тихих часов."""
    user_id = message.from_user.id

    try:
        hour, minute = map(int, message.text.split(":"))
        if not (0 <= hour < 24 and 0 <= minute < 60):
            raise ValueError

        time_value = dt_time(hour, minute)

        async with SessionLocal() as session:
            result = await session.execute(select(User).where(User.user_id == user_id))
            user = result.scalar_one_or_none()
            if not user:
                await message.answer("Пользователь не найден")
                await state.clear()
                return

            user.quiet_hours_to = time_value
            await session.commit()

        await message.answer(f"Готово! Конец тихих часов: <b>{time_value.strftime('%H:%M')}</b>")
        await state.clear()
        logger.info(f"User {user_id} set quiet_hours_to to {time_value}")

    except (ValueError, AttributeError):
        await message.answer("Неверный формат времени. Используй формат <b>ЧЧ:ММ</b>\n" "Например: 08:00")


@router.callback_query(F.data == "SET_QUIET_OFF")
async def settings_quiet_off(callback: CallbackQuery):
    """Отключает тихие часы."""
    user_id = callback.from_user.id

    async with SessionLocal() as session:
        result = await session.execute(select(User).where(User.user_id == user_id))
        user = result.scalar_one_or_none()
        if not user:
            await callback.answer("Пользователь не найден", show_alert=True)
            return

        user.quiet_hours_from = None
        user.quiet_hours_to = None
        await session.commit()

    await callback.message.edit_text("Готово! Тихие часы отключены.")
    await callback.answer()
    logger.info(f"User {user_id} disabled quiet hours")


# ===== УТРЕННИЙ ПИНГ =====
@router.callback_query(F.data == "settings_morning")
async def settings_morning_prompt(callback: CallbackQuery, state: FSMContext):
    """Запрашивает время утреннего пинга."""
    user_id = callback.from_user.id
    user = await get_user(user_id)

    current_time = user.morning_ping_time.strftime("%H:%M") if user.morning_ping_time else "Не установлено"

    builder = InlineKeyboardBuilder()
    builder.button(text="Изменить время", callback_data="SET_TIME_MORNING")
    builder.button(text="Отключить", callback_data="SET_MORNING_OFF")
    builder.button(text="Назад", callback_data="settings_back")
    builder.adjust(1)

    await callback.message.edit_text(
        f"Утренний пинг:\n\n" f"Текущее время: <b>{current_time}</b>\n\n" "Что хочешь изменить?",
        reply_markup=builder.as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data == "SET_TIME_MORNING")
async def settings_morning_time_prompt(callback: CallbackQuery, state: FSMContext):
    """Запрашивает новое время утреннего пинга."""
    await state.set_state(SettingsStates.edit_morning_ping)
    await callback.message.edit_text("Введи время утреннего пинга в формате <b>ЧЧ:ММ</b>\n" "Например: 08:00")
    await callback.answer()


@router.message(StateFilter(SettingsStates.edit_morning_ping))
async def settings_morning_save(message: Message, state: FSMContext):
    """Сохраняет время утреннего пинга."""
    user_id = message.from_user.id

    try:
        hour, minute = map(int, message.text.split(":"))
        if not (0 <= hour < 24 and 0 <= minute < 60):
            raise ValueError

        time_value = dt_time(hour, minute)

        async with SessionLocal() as session:
            result = await session.execute(select(User).where(User.user_id == user_id))
            user = result.scalar_one_or_none()
            if not user:
                await message.answer("Пользователь не найден")
                await state.clear()
                return

            user.morning_ping_time = time_value
            await session.commit()

        await message.answer(
            f"Готово! Утренний пинг установлен на <b>{time_value.strftime('%H:%M')}</b>\n\n"
            "Расписание будет обновлено при следующем перезапуске бота."
        )
        await state.clear()
        logger.info(f"User {user_id} set morning_ping_time to {time_value}")

    except (ValueError, AttributeError):
        await message.answer("Неверный формат времени. Используй формат <b>ЧЧ:ММ</b>\n" "Например: 08:00")


@router.callback_query(F.data == "SET_MORNING_OFF")
async def settings_morning_off(callback: CallbackQuery):
    """Отключает утренний пинг."""
    user_id = callback.from_user.id

    async with SessionLocal() as session:
        result = await session.execute(select(User).where(User.user_id == user_id))
        user = result.scalar_one_or_none()
        if not user:
            await callback.answer("Пользователь не найден", show_alert=True)
            return

        user.morning_ping_time = None
        await session.commit()

    await callback.message.edit_text("Готово! Утренний пинг отключён.")
    await callback.answer()
    logger.info(f"User {user_id} disabled morning ping")


# ===== ВЕЧЕРНИЙ ОТЧЁТ =====
@router.callback_query(F.data == "settings_evening")
async def settings_evening_prompt(callback: CallbackQuery, state: FSMContext):
    """Запрашивает время вечернего отчёта."""
    user_id = callback.from_user.id
    user = await get_user(user_id)

    current_time = user.evening_ping_time.strftime("%H:%M") if user.evening_ping_time else "Не установлено"

    builder = InlineKeyboardBuilder()
    builder.button(text="Изменить время", callback_data="SET_TIME_EVENING")
    builder.button(text="Отключить", callback_data="SET_EVENING_OFF")
    builder.button(text="Назад", callback_data="settings_back")
    builder.adjust(1)

    await callback.message.edit_text(
        f"Вечерний отчёт:\n\n" f"Текущее время: <b>{current_time}</b>\n\n" "Что хочешь изменить?",
        reply_markup=builder.as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data == "SET_TIME_EVENING")
async def settings_evening_time_prompt(callback: CallbackQuery, state: FSMContext):
    """Запрашивает новое время вечернего отчёта."""
    await state.set_state(SettingsStates.edit_evening_ping)
    await callback.message.edit_text(
        "Введи время вечернего отчёта в формате <b>ЧЧ:ММ</b>\n" "Например: 21:00"
    )
    await callback.answer()


@router.message(StateFilter(SettingsStates.edit_evening_ping))
async def settings_evening_save(message: Message, state: FSMContext):
    """Сохраняет время вечернего отчёта."""
    user_id = message.from_user.id

    try:
        hour, minute = map(int, message.text.split(":"))
        if not (0 <= hour < 24 and 0 <= minute < 60):
            raise ValueError

        time_value = dt_time(hour, minute)

        async with SessionLocal() as session:
            result = await session.execute(select(User).where(User.user_id == user_id))
            user = result.scalar_one_or_none()
            if not user:
                await message.answer("Пользователь не найден")
                await state.clear()
                return

            user.evening_ping_time = time_value
            await session.commit()

        await message.answer(
            f"Готово! Вечерний отчёт установлен на <b>{time_value.strftime('%H:%M')}</b>\n\n"
            "Расписание будет обновлено при следующем перезапуске бота."
        )
        await state.clear()
        logger.info(f"User {user_id} set evening_ping_time to {time_value}")

    except (ValueError, AttributeError):
        await message.answer("Неверный формат времени. Используй формат <b>ЧЧ:ММ</b>\n" "Например: 21:00")


@router.callback_query(F.data == "SET_EVENING_OFF")
async def settings_evening_off(callback: CallbackQuery):
    """Отключает вечерний отчёт."""
    user_id = callback.from_user.id

    async with SessionLocal() as session:
        result = await session.execute(select(User).where(User.user_id == user_id))
        user = result.scalar_one_or_none()
        if not user:
            await callback.answer("Пользователь не найден", show_alert=True)
            return

        user.evening_ping_time = None
        await session.commit()

    await callback.message.edit_text("Готово! Вечерний отчёт отключён.")
    await callback.answer()
    logger.info(f"User {user_id} disabled evening ping")


# ===== ВОЗВРАТ В МЕНЮ =====
@router.callback_query(F.data == "settings_back")
async def settings_back(callback: CallbackQuery):
    """Возврат в главное меню настроек."""
    user_id = callback.from_user.id
    user = await get_user(user_id)

    if not user:
        await callback.answer("Пользователь не найден", show_alert=True)
        return

    # Формируем текст с текущими настройками
    lang_name = "Русский" if user.lang == "ru" else "English"
    tz = user.tz or "UTC"

    quiet_from_str = user.quiet_hours_from.strftime("%H:%M") if user.quiet_hours_from else "Не установлено"
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
