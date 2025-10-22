# src/handlers/language/settings.py

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message
from api import APIAuthError, APIError, LanguageAPI
from config import logger
from db import SessionLocal, UserLanguageSettings
from sqlalchemy import select

router = Router()


class LanguageSetupStates(StatesGroup):
    waiting_for_token = State()
    configuring_audio_time = State()
    configuring_reading_time = State()
    configuring_questions_time = State()


@router.message(Command("language_setup"))
async def cmd_language_setup(message: Message, state: FSMContext):
    """Настройка Language Learning API токена"""
    user_id = message.from_user.id

    async with SessionLocal() as session:
        result = await session.execute(
            select(UserLanguageSettings).where(UserLanguageSettings.user_id == user_id)
        )
        settings = result.scalar_one_or_none()

        if settings and settings.api_token:
            await message.answer(
                "✅ <b>У вас уже настроен API токен</b>\n\n"
                "Хотите изменить его? Отправьте новый токен или /cancel для отмены.",
            )
        else:
            await message.answer(
                "🔑 <b>Настройка Language Learning API</b>\n\n"
                "Для использования функций чтения книг нужен API токен.\n\n"
                "<b>Как получить токен:</b>\n"
                "1. Зарегистрируйтесь на сайте Language Learning\n"
                "2. Войдите в личный кабинет\n"
                "3. Перейдите в раздел API Settings\n"
                "4. Сгенерируйте токен для Telegram\n\n"
                "Отправьте ваш токен или /cancel для отмены:"
            )

    await state.set_state(LanguageSetupStates.waiting_for_token)


@router.message(LanguageSetupStates.waiting_for_token, F.text == "/cancel")
async def cancel_setup(message: Message, state: FSMContext):
    """Отмена настройки"""
    await state.clear()
    await message.answer("❌ Настройка отменена.")


@router.message(LanguageSetupStates.waiting_for_token)
async def process_token(message: Message, state: FSMContext):
    """Обработка введенного токена"""
    token = message.text.strip()
    user_id = message.from_user.id

    # Удаляем сообщение с токеном для безопасности
    try:
        await message.delete()
    except Exception:
        pass  # Если не получилось удалить - не страшно

    # Проверяем токен, пытаясь получить список книг
    processing_msg = await message.answer("⏳ Проверяю токен...")

    try:
        api = LanguageAPI(user_token=token)
        # Пробуем выполнить простой запрос для проверки токена
        books = await api.get_books()
        await api.close()

        # Токен работает, сохраняем
        async with SessionLocal() as session:
            result = await session.execute(
                select(UserLanguageSettings).where(UserLanguageSettings.user_id == user_id)
            )
            settings = result.scalar_one_or_none()

            if not settings:
                settings = UserLanguageSettings(user_id=user_id, api_token=token)
                session.add(settings)
            else:
                settings.api_token = token

            await session.commit()

        await processing_msg.edit_text(
            f"✅ <b>Токен успешно сохранен!</b>\n\n"
            f"📚 Найдено книг: {len(books)}\n\n"
            f"Теперь вы можете:\n"
            f"• /choose_book - выбрать книгу\n"
            f"• /read - начать чтение\n"
            f"• /grammar - изучать грамматику"
        )
        await state.clear()
        logger.info(f"User {user_id} configured Language API token")

    except APIAuthError:
        await processing_msg.edit_text(
            "❌ <b>Неверный токен</b>\n\n"
            "Токен не прошел проверку. Убедитесь, что:\n"
            "• Токен скопирован полностью\n"
            "• Токен не истек\n"
            "• Токен предназначен для Telegram интеграции\n\n"
            "Попробуйте еще раз или /cancel для отмены:"
        )

    except APIError as e:
        await processing_msg.edit_text(
            f"❌ <b>Ошибка проверки токена</b>\n\n"
            f"Не удалось подключиться к API: {e}\n\n"
            f"Попробуйте еще раз или /cancel для отмены:"
        )
        logger.error(f"Token validation error for user {user_id}: {e}")

    except Exception as e:
        await processing_msg.edit_text(
            "❌ <b>Непредвиденная ошибка</b>\n\n"
            "Попробуйте позже или обратитесь в поддержку.\n\n"
            "Используйте /cancel для отмены."
        )
        logger.error(f"Unexpected error validating token for user {user_id}: {e}")


@router.message(Command("language_status"))
async def cmd_language_status(message: Message):
    """Показать статус настройки Language API"""
    user_id = message.from_user.id

    async with SessionLocal() as session:
        result = await session.execute(
            select(UserLanguageSettings).where(UserLanguageSettings.user_id == user_id)
        )
        settings = result.scalar_one_or_none()

        if not settings or not settings.api_token:
            await message.answer(
                "❌ <b>Language API не настроен</b>\n\n" "Используйте /language_setup для настройки."
            )
        else:
            # Проверяем работоспособность токена
            try:
                api = LanguageAPI(user_token=settings.api_token)
                books = await api.get_books()
                await api.close()

                status_text = (
                    "✅ <b>Language API настроен и работает</b>\n\n"
                    f"📚 Доступно книг: {len(books)}\n"
                    f"🔧 Fragment length: {settings.preferred_fragment_length} символов\n"
                    f"🔔 Напоминания: {'включены' if settings.reminder_enabled else 'выключены'}\n\n"
                    f"Команды:\n"
                    f"• /choose_book - выбрать книгу\n"
                    f"• /read - читать\n"
                    f"• /language_setup - изменить токен"
                )
            except APIAuthError:
                status_text = (
                    "⚠️ <b>Токен недействителен</b>\n\n" "Используйте /language_setup для обновления токена."
                )
            except Exception as e:
                status_text = (
                    f"⚠️ <b>Ошибка подключения к API</b>\n\n"
                    f"Попробуйте позже или проверьте токен.\n\n"
                    f"Ошибка: {str(e)[:100]}"
                )

            await message.answer(status_text)


# ===== AUDIO WORKFLOW CONFIGURATION =====


@router.message(Command("audio_schedule"))
async def cmd_audio_schedule(message: Message, state: FSMContext):
    """Настроить расписание для аудио-рабочего процесса"""
    user_id = message.from_user.id

    async with SessionLocal() as session:
        result = await session.execute(
            select(UserLanguageSettings).where(UserLanguageSettings.user_id == user_id)
        )
        settings = result.scalar_one_or_none()

        if not settings or not settings.api_token:
            await message.answer("❌ Сначала настройте Language API через /language_setup")
            return

        current_status = (
            f"📅 <b>Текущее расписание аудио-рабочего процесса</b>\n\n"
            f"🎧 Аудио: {settings.audio_time or 'не настроено'}\n"
            f"📖 Чтение: {settings.reading_time or 'не настроено'}\n"
            f"❓ Вопросы: {settings.questions_time or 'не настроено'}\n"
            f"Статус: {'✅ Включено' if settings.audio_enabled else '❌ Выключено'}\n\n"
        )

        if settings.audio_time and settings.reading_time and settings.questions_time:
            current_status += (
                "Хотите изменить расписание?\n"
                "• /audio_time - изменить время аудио\n"
                "• /reading_time - изменить время чтения\n"
                "• /questions_time - изменить время вопросов\n"
                "• /audio_toggle - включить/выключить аудио\n"
                "• /cancel - отмена"
            )
            await message.answer(current_status)
        else:
            current_status += (
                "⚙️ <b>Настройте 3-этапный рабочий процесс:</b>\n\n"
                "1️⃣ <b>Утро:</b> Аудио фрагмента (за 1-2 часа до чтения)\n"
                "2️⃣ <b>День:</b> Текст для чтения\n"
                "3️⃣ <b>Вечер:</b> Вопросы на понимание\n\n"
                "Отправьте время для отправки аудио (формат HH:MM, например 08:00):"
            )
            await message.answer(current_status)
            await state.set_state(LanguageSetupStates.configuring_audio_time)


@router.message(Command("audio_time"))
async def cmd_configure_audio_time(message: Message, state: FSMContext):
    """Изменить время отправки аудио"""
    await message.answer(
        "🎧 <b>Время отправки аудио</b>\n\n" "Отправьте время в формате HH:MM (например, 08:00):"
    )
    await state.set_state(LanguageSetupStates.configuring_audio_time)


@router.message(Command("reading_time"))
async def cmd_configure_reading_time(message: Message, state: FSMContext):
    """Изменить время отправки текста"""
    await message.answer(
        "📖 <b>Время отправки текста для чтения</b>\n\n" "Отправьте время в формате HH:MM (например, 10:00):"
    )
    await state.set_state(LanguageSetupStates.configuring_reading_time)


@router.message(Command("questions_time"))
async def cmd_configure_questions_time(message: Message, state: FSMContext):
    """Изменить время отправки вопросов"""
    await message.answer(
        "❓ <b>Время отправки вопросов</b>\n\n" "Отправьте время в формате HH:MM (например, 20:00):"
    )
    await state.set_state(LanguageSetupStates.configuring_questions_time)


@router.message(Command("audio_toggle"))
async def cmd_toggle_audio(message: Message):
    """Включить/выключить отправку аудио"""
    user_id = message.from_user.id

    async with SessionLocal() as session:
        result = await session.execute(
            select(UserLanguageSettings).where(UserLanguageSettings.user_id == user_id)
        )
        settings = result.scalar_one_or_none()

        if not settings:
            await message.answer("❌ Сначала настройте Language API через /language_setup")
            return

        settings.audio_enabled = not settings.audio_enabled
        await session.commit()

        status = "включена" if settings.audio_enabled else "выключена"
        await message.answer(f"{'✅' if settings.audio_enabled else '❌'} Отправка аудио {status}")


def _validate_time(time_str: str) -> bool:
    """Проверяет формат времени HH:MM"""
    import re

    pattern = r"^([0-1]?[0-9]|2[0-3]):[0-5][0-9]$"
    return bool(re.match(pattern, time_str))


@router.message(LanguageSetupStates.configuring_audio_time)
async def process_audio_time(message: Message, state: FSMContext):
    """Обработка времени отправки аудио"""
    time_str = message.text.strip()
    user_id = message.from_user.id

    if not _validate_time(time_str):
        await message.answer("❌ Неверный формат времени. Используйте HH:MM (например, 08:00)")
        return

    async with SessionLocal() as session:
        result = await session.execute(
            select(UserLanguageSettings).where(UserLanguageSettings.user_id == user_id)
        )
        settings = result.scalar_one_or_none()

        if not settings:
            await message.answer("❌ Настройки не найдены")
            await state.clear()
            return

        settings.audio_time = time_str
        await session.commit()

    await message.answer(
        f"✅ Время отправки аудио установлено: {time_str}\n\n"
        f"Теперь отправьте время для чтения текста (формат HH:MM):"
    )
    await state.set_state(LanguageSetupStates.configuring_reading_time)


@router.message(LanguageSetupStates.configuring_reading_time)
async def process_reading_time(message: Message, state: FSMContext):
    """Обработка времени отправки текста"""
    time_str = message.text.strip()
    user_id = message.from_user.id

    if not _validate_time(time_str):
        await message.answer("❌ Неверный формат времени. Используйте HH:MM (например, 10:00)")
        return

    async with SessionLocal() as session:
        result = await session.execute(
            select(UserLanguageSettings).where(UserLanguageSettings.user_id == user_id)
        )
        settings = result.scalar_one_or_none()

        if not settings:
            await message.answer("❌ Настройки не найдены")
            await state.clear()
            return

        settings.reading_time = time_str
        await session.commit()

    await message.answer(
        f"✅ Время отправки текста установлено: {time_str}\n\n"
        f"Теперь отправьте время для вопросов (формат HH:MM):"
    )
    await state.set_state(LanguageSetupStates.configuring_questions_time)


@router.message(LanguageSetupStates.configuring_questions_time)
async def process_questions_time(message: Message, state: FSMContext):
    """Обработка времени отправки вопросов"""
    time_str = message.text.strip()
    user_id = message.from_user.id

    if not _validate_time(time_str):
        await message.answer("❌ Неверный формат времени. Используйте HH:MM (например, 20:00)")
        return

    async with SessionLocal() as session:
        result = await session.execute(
            select(UserLanguageSettings).where(UserLanguageSettings.user_id == user_id)
        )
        settings = result.scalar_one_or_none()

        if not settings:
            await message.answer("❌ Настройки не найдены")
            await state.clear()
            return

        settings.questions_time = time_str
        await session.commit()

        # Now schedule the workflow
        from bot import bot, scheduler
        from language_scheduler import LanguageReminderService

        reminder_service = LanguageReminderService(bot, scheduler)
        await reminder_service.schedule_audio_workflow(
            user_id=user_id,
            audio_time=settings.audio_time,
            reading_time=settings.reading_time,
            questions_time=settings.questions_time,
        )

    await message.answer(
        f"🎉 <b>Расписание настроено!</b>\n\n"
        f"🎧 Аудио: {settings.audio_time}\n"
        f"📖 Чтение: {settings.reading_time}\n"
        f"❓ Вопросы: {settings.questions_time}\n\n"
        f"<b>Как это работает:</b>\n"
        f"1️⃣ Утром вы получите аудио фрагмента\n"
        f"2️⃣ Днём — текст этого же фрагмента для чтения\n"
        f"3️⃣ Вечером — вопросы на понимание\n\n"
        f"Команды:\n"
        f"• /audio_schedule - посмотреть расписание\n"
        f"• /audio_toggle - выключить/включить аудио"
    )
    await state.clear()
