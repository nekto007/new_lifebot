# src/handlers/language/reading.py

import re
from datetime import datetime

from aiogram import F, Router
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from api import APIAuthError, APIConnectionError, APIError, get_user_language_api
from db import LanguageHabit, LanguageProgress, SessionLocal
from keyboards.language import (
    get_reading_actions_keyboard,
    get_reading_keyboard,
)
from sqlalchemy import func, select


def escape_markdown(text: str) -> str:
    """Экранирует специальные символы для MarkdownV2"""
    escape_chars = r"_*[]()~`>#+-=|{}.!"
    return re.sub(f"([{re.escape(escape_chars)}])", r"\\\1", text)


def trim_to_sentence(text: str, target_length: int = 1000) -> str:
    """
    Обрезает текст до последнего законченного предложения.

    Args:
        text: Исходный текст
        target_length: Желаемая длина (будет запрошено больше, чтобы не обрезать посередине)

    Returns:
        Текст, обрезанный по последнему предложению
    """
    # Если текст короче целевой длины - возвращаем как есть
    if len(text) <= target_length:
        return text

    # Обрезаем примерно до целевой длины
    rough_cut = text[: target_length + 200]  # +200 для поиска конца предложения

    # Ищем последний знак конца предложения
    sentence_endings = [". ", "! ", "? ", '."', '!"', '?"', ".\n", "!\n", "?\n"]

    best_position = -1
    for ending in sentence_endings:
        pos = rough_cut.rfind(ending)
        if pos > best_position and pos >= target_length - 100:  # Не обрезаем слишком рано
            best_position = pos + len(ending) - 1  # Включаем знак препинания

    # Если нашли подходящее предложение
    if best_position > target_length * 0.7:  # Хотя бы 70% от целевой длины
        return rough_cut[: best_position + 1].strip()

    # Если не нашли, обрезаем по последнему слову
    rough_cut = text[:target_length]
    last_space = rough_cut.rfind(" ")
    if last_space > target_length * 0.8:
        return rough_cut[:last_space].strip()

    # В крайнем случае возвращаем как есть
    return rough_cut.strip()


router = Router()


class ReadingStates(StatesGroup):
    choosing_book = State()
    reading = State()
    answering_questions = State()


async def _display_fragment(
    message: Message, fragment_data: dict, session, habit, state: FSMContext, user_id: int = None
):
    """Отображает фрагмент книги с правильным форматированием"""

    if fragment_data.get("finished"):
        await message.answer(
            f"🎉 Поздравляю! Вы закончили книгу:\n"
            f"«{fragment_data['book']['title']}»\n\n"
            f"Выберите новую книгу: /choose_book"
        )
        habit.current_book_id = None
        await session.commit()
        await state.clear()
        return

    fragment = fragment_data["fragment"]
    book = fragment["book"]
    chapter = fragment["chapter"]

    # Форматируем текст: заменяем \n на переносы строк
    raw_text = fragment["text"].replace("\\n", "\n")

    # Получаем настройки пользователя для определения желаемой длины
    if user_id:
        from db import UserLanguageSettings

        result = await session.execute(
            select(UserLanguageSettings).where(UserLanguageSettings.user_id == user_id)
        )
        settings = result.scalar_one_or_none()
        target_length = settings.preferred_fragment_length if settings else 1000
    else:
        target_length = 1000

    # Обрезаем до последнего предложения
    text = trim_to_sentence(raw_text, target_length)

    # Формируем сообщение
    message_text = (
        f"📖 <b>{book['title']}</b>\n"
        f"Глава {chapter['number']}: {chapter['title']}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"{text}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 Прогресс главы: {chapter['progress_pct']:.1f}%\n"
        f"📈 Общий прогресс: {book['overall_progress_pct']:.1f}%\n"
        f"📄 Глава {book['current_chapter']}/{book['total_chapters']}\n"
        f"📏 Символов: {len(text)}"
    )

    # Определяем, показывать ли кнопку "Назад" (если это не первый фрагмент)
    show_back = chapter["progress_pct"] > 0 or book["current_chapter"] > 1

    await message.answer(message_text, reply_markup=get_reading_actions_keyboard(show_back=show_back))


@router.message(Command("read"))
async def cmd_read(message: Message, state: FSMContext):
    """Команда для чтения ТЕКУЩЕГО фрагмента (не следующего!)"""
    user_id = message.from_user.id

    async with SessionLocal() as session:
        # Получаем API клиент пользователя
        api = await get_user_language_api(session, user_id)
        if not api:
            await message.answer(
                "🔑 <b>Требуется настройка API</b>\n\n"
                "Для использования функций чтения нужен API токен.\n"
                "Используйте /language_setup для настройки."
            )
            return

        # Получаем текущую привычку чтения
        result = await session.execute(
            select(LanguageHabit).where(
                LanguageHabit.user_id == user_id,
                LanguageHabit.habit_type == "reading",
                LanguageHabit.is_active == True,  # noqa: E712
            )
        )
        habit = result.scalar_one_or_none()

        if not habit or not habit.current_book_id:
            await message.answer(
                "📚 У вас не выбрана книга для чтения.\n" "Используйте /choose_book чтобы выбрать книгу.",
                reply_markup=get_reading_keyboard(),
            )
            return

        try:
            # Проверяем, есть ли сохраненный текущий фрагмент
            data = await state.get_data()
            cached_fragment = data.get("current_fragment")

            # Если есть кэшированный фрагмент с тем же book_id - показываем его
            if cached_fragment and cached_fragment.get("book_id") == habit.current_book_id:
                await _display_fragment(message, cached_fragment, session, habit, state, user_id)
            else:
                # Иначе получаем следующий фрагмент (первый раз или новая книга)
                # Запрашиваем 1500 символов, чтобы потом обрезать до ~1000 по предложению
                fragment_data = await api.read_next(
                    book_id=habit.current_book_id,
                    length=1500,
                )

                # Сохраняем в state как текущий
                fragment_data["book_id"] = habit.current_book_id
                await state.update_data(current_fragment=fragment_data)

                await _display_fragment(message, fragment_data, session, habit, state, user_id)

        except APIAuthError:
            await message.answer(
                "❌ <b>Ошибка авторизации</b>\n\n"
                "Ваш токен недействителен или истек.\n"
                "Используйте /language_setup для обновления токена."
            )
        except APIConnectionError:
            await message.answer("❌ Не удалось подключиться к серверу.\n" "Попробуйте позже.")
        except APIError as e:
            await message.answer(f"❌ Ошибка API: {e}")
        finally:
            await api.close()


@router.message(Command("choose_book"))
async def cmd_choose_book(message: Message, state: FSMContext):
    """Выбор книги для чтения"""
    user_id = message.from_user.id

    async with SessionLocal() as session:
        api = await get_user_language_api(session, user_id)
        if not api:
            await message.answer(
                "🔑 <b>Требуется настройка API</b>\n\n"
                "Для использования функций чтения нужен API токен.\n"
                "Используйте /language_setup для настройки."
            )
            return

        try:
            books = await api.get_books()

            if not books:
                await message.answer("📚 Книги не найдены.")
                return

            # Формируем сообщение с количеством книг
            level_counts = {}
            for book in books:
                level = book.get("level", "Unknown")
                level_counts[level] = level_counts.get(level, 0) + 1

            # Формируем текстовый список книг в Markdown
            books_list = []
            for idx, book in enumerate(books, 1):
                level_emoji = {
                    "A1": "🟢",
                    "A2": "🟢",
                    "B1": "🟡",
                    "B2": "🟡",
                    "C1": "🔴",
                    "C2": "🔴",
                }.get(book.get("level", ""), "📘")

                # Экранируем текст для MarkdownV2
                title = escape_markdown(book["title"])
                author = escape_markdown(book["author"])
                chapters = book.get("chapters_count", "?")

                books_list.append(
                    f"`{idx:2d}` {level_emoji} *{title}*\n" f"     └ {author} • {chapters} глав"
                )

            # Формируем статистику
            stats_parts = [f"{level}: {count}" for level, count in sorted(level_counts.items())]
            stats_escaped = escape_markdown(", ".join(stats_parts))

            message_text = (
                f"📚 *Выберите книгу для чтения*\n\n"
                f"📊 Доступно книг: {stats_escaped}\n\n"
                f"🟢 A1\\-A2 \\(Начинающий\\) \\| "
                f"🟡 B1\\-B2 \\(Средний\\) \\| "
                f"🔴 C1\\-C2 \\(Продвинутый\\)\n\n"
                f"{chr(10).join(books_list)}\n\n"
                f"💬 _Напишите номер книги \\(1\\-{len(books)}\\) или /cancel_"
            )

            await message.answer(message_text, parse_mode=ParseMode.MARKDOWN_V2)

            # Сохраняем список книг в state для последующего выбора
            await state.update_data(books=books)
            await state.set_state(ReadingStates.choosing_book)

        except APIAuthError:
            await message.answer(
                "❌ <b>Ошибка авторизации</b>\n\n"
                "Ваш токен недействителен.\n"
                "Используйте /language_setup для обновления."
            )
        except APIError as e:
            await message.answer(f"❌ Ошибка: {e}")
        finally:
            await api.close()


@router.message(ReadingStates.choosing_book, F.text == "/cancel")
async def cancel_book_selection(message: Message, state: FSMContext):
    """Отмена выбора книги"""
    await state.clear()
    await message.answer("❌ Выбор книги отменен.")


@router.message(ReadingStates.choosing_book)
async def process_book_number(message: Message, state: FSMContext):
    """Обработка ввода номера книги"""
    user_id = message.from_user.id

    # Проверяем, что введено число
    if not message.text.isdigit():
        await message.answer("❌ Пожалуйста, введите номер книги (число) или /cancel для отмены")
        return

    book_number = int(message.text)

    # Получаем список книг из state
    data = await state.get_data()
    books = data.get("books", [])

    if not books:
        await message.answer("❌ Список книг не найден. Попробуйте /choose_book заново")
        await state.clear()
        return

    # Проверяем корректность номера
    if book_number < 1 or book_number > len(books):
        await message.answer(f"❌ Неверный номер. Выберите от 1 до {len(books)} или /cancel")
        return

    # Получаем выбранную книгу (индекс = номер - 1)
    selected_book = books[book_number - 1]
    book_id = selected_book["id"]

    async with SessionLocal() as session:
        api = await get_user_language_api(session, user_id)
        if not api:
            await message.answer("🔑 Токен API не найден. Используйте /language_setup")
            await state.clear()
            return

        try:
            # Начинаем книгу через API
            result = await api.start_book(book_id)
            book_info = result["book"]

            # Создаём или обновляем привычку
            habit_result = await session.execute(
                select(LanguageHabit).where(
                    LanguageHabit.user_id == user_id, LanguageHabit.habit_type == "reading"
                )
            )
            habit = habit_result.scalar_one_or_none()

            if not habit:
                habit = LanguageHabit(
                    user_id=user_id, habit_type="reading", name="Daily Reading", daily_goal=500
                )
                session.add(habit)

            habit.current_book_id = book_id
            habit.current_book_title = book_info["title"]
            habit.is_active = True

            await session.commit()

            await message.answer(
                f"✅ <b>Книга выбрана:</b>\n\n"
                f"📖 «{book_info['title']}»\n"
                f"✍️ {book_info['author']}\n"
                f"📄 Глав: {book_info['chapters_count']}\n\n"
                f"Начните чтение: /read"
            )
            await state.clear()

        except APIAuthError:
            await message.answer("❌ Токен недействителен. Используйте /language_setup")
            await state.clear()
        except APIError as e:
            await message.answer(f"❌ Ошибка: {e}")
            await state.clear()
        finally:
            await api.close()


@router.message(Command("reading_progress"))
async def cmd_reading_progress(message: Message):
    """Показать прогресс чтения"""
    user_id = message.from_user.id

    async with SessionLocal() as session:
        api = await get_user_language_api(session, user_id)
        if not api:
            await message.answer("🔑 Требуется настройка API. Используйте /language_setup")
            return

        result = await session.execute(
            select(LanguageHabit).where(
                LanguageHabit.user_id == user_id, LanguageHabit.habit_type == "reading"
            )
        )
        habit = result.scalar_one_or_none()

        if not habit or not habit.current_book_id:
            await message.answer("📚 У вас нет активной книги для чтения.")
            return

        try:
            # Получаем прогресс с API
            progress_data = await api.get_reading_progress(habit.current_book_id)

            book = progress_data["book"]
            progress = progress_data["progress"]

            # Локальный прогресс за сегодня
            today = datetime.utcnow().date()
            today_progress_result = await session.execute(
                select(LanguageProgress).where(
                    LanguageProgress.habit_id == habit.id,
                    func.date(LanguageProgress.date) == today,
                )
            )
            today_progress = today_progress_result.scalar_one_or_none()

            words_today = today_progress.words_read if today_progress else 0

            message_text = (
                f"📊 <b>Прогресс чтения</b>\n\n"
                f"📖 Книга: <b>{book['title']}</b>\n"
                f"✍️ Автор: {book['author']}\n"
                f"📄 Всего глав: {book['total_chapters']}\n\n"
                f"📈 <b>Общий прогресс:</b> {progress['overall_progress_pct']:.1f}%\n"
                f"✅ Завершено глав: {progress['chapters_completed']}\n"
                f"📍 Текущая глава: {progress['current_chapter']}\n"
                f"🔄 Прогресс главы: {progress['current_chapter_progress_pct']:.1f}%\n\n"
                f"📅 <b>Сегодня:</b>\n"
                f"📝 Прочитано слов: {words_today} / {habit.daily_goal}\n"
                f"🔥 Streak: {habit.current_streak} дней"
            )

            await message.answer(message_text)

        except APIAuthError:
            await message.answer("❌ Токен недействителен. Используйте /language_setup")
        except APIError as e:
            await message.answer(f"❌ Ошибка: {e}")
        finally:
            await api.close()


@router.callback_query(F.data == "read:continue")
async def callback_continue_reading(callback: CallbackQuery, state: FSMContext):
    """Продолжить чтение - получить СЛЕДУЮЩИЙ фрагмент"""
    await callback.answer()
    user_id = callback.from_user.id

    async with SessionLocal() as session:
        api = await get_user_language_api(session, user_id)
        if not api:
            await callback.message.answer("🔑 Токен API не найден")
            return

        result = await session.execute(
            select(LanguageHabit).where(
                LanguageHabit.user_id == user_id,
                LanguageHabit.habit_type == "reading",
                LanguageHabit.is_active == True,  # noqa: E712
            )
        )
        habit = result.scalar_one_or_none()

        if not habit or not habit.current_book_id:
            await callback.message.answer("📚 Книга не выбрана")
            return

        try:
            # Получаем СЛЕДУЮЩИЙ фрагмент
            # Запрашиваем 1500 символов, чтобы обрезать до ~1000 по предложению
            fragment_data = await api.read_next(book_id=habit.current_book_id, length=1500)

            # Сохраняем предыдущий фрагмент в историю
            data = await state.get_data()
            current = data.get("current_fragment")
            if current:
                # Сохраняем в историю
                history = data.get("fragment_history", [])
                history.append(current)
                # Храним только последние 5
                if len(history) > 5:
                    history = history[-5:]
                await state.update_data(fragment_history=history)

            # Обновляем текущий фрагмент
            fragment_data["book_id"] = habit.current_book_id
            await state.update_data(current_fragment=fragment_data)

            # Обновляем прогресс в БД
            today = datetime.utcnow().date()
            progress_result = await session.execute(
                select(LanguageProgress).where(
                    LanguageProgress.habit_id == habit.id,
                    func.date(LanguageProgress.date) == today,
                )
            )
            progress = progress_result.scalar_one_or_none()

            if not progress:
                progress = LanguageProgress(
                    habit_id=habit.id,
                    date=datetime.utcnow(),
                    words_read=0,
                    fragments_read=0,
                    lessons_completed=0,
                )
                session.add(progress)

            # Обновляем статистику
            if not fragment_data.get("finished"):
                fragment = fragment_data["fragment"]
                progress.words_read = (progress.words_read or 0) + len(fragment["text"].split())
                progress.fragments_read = (progress.fragments_read or 0) + 1

            await session.commit()

            # Показываем фрагмент
            await _display_fragment(callback.message, fragment_data, session, habit, state, user_id)

        except APIError as e:
            await callback.message.answer(f"❌ Ошибка: {e}")
        finally:
            await api.close()


@router.callback_query(F.data == "read:back")
async def callback_back_reading(callback: CallbackQuery, state: FSMContext):
    """Вернуться к предыдущему фрагменту"""
    await callback.answer()
    user_id = callback.from_user.id

    async with SessionLocal() as session:
        result = await session.execute(
            select(LanguageHabit).where(
                LanguageHabit.user_id == user_id, LanguageHabit.habit_type == "reading"
            )
        )
        habit = result.scalar_one_or_none()

        if not habit:
            await callback.message.answer("📚 Книга не выбрана")
            return

        # Получаем историю фрагментов
        data = await state.get_data()
        history = data.get("fragment_history", [])

        if not history:
            await callback.answer("Вы уже в начале!", show_alert=True)
            return

        # Берём последний из истории
        previous_fragment = history.pop()

        # Обновляем state
        await state.update_data(current_fragment=previous_fragment, fragment_history=history)

        # Показываем предыдущий фрагмент
        await _display_fragment(callback.message, previous_fragment, session, habit, state, user_id)


@router.callback_query(F.data == "read:progress")
async def callback_show_progress(callback: CallbackQuery):
    """Показать прогресс (кнопка)"""
    await callback.answer()
    await cmd_reading_progress(callback.message)


@router.callback_query(F.data == "choose_book")
async def callback_choose_book(callback: CallbackQuery, state: FSMContext):
    """Кнопка выбора книги"""
    await callback.answer()
    # Создаем временное сообщение для вызова команды
    await cmd_choose_book(callback.message, state)


@router.callback_query(F.data == "reading_progress")
async def callback_reading_progress(callback: CallbackQuery):
    """Кнопка прогресса чтения"""
    await callback.answer()
    await cmd_reading_progress(callback.message)


# ===== COMPREHENSION QUESTIONS =====


@router.message(Command("answer_questions"))
async def cmd_answer_questions(message: Message, state: FSMContext):
    """Начать отвечать на вопросы на понимание"""
    user_id = message.from_user.id

    async with SessionLocal() as session:
        # Get reading habit
        result = await session.execute(
            select(LanguageHabit).where(
                LanguageHabit.user_id == user_id,
                LanguageHabit.habit_type == "reading",
                LanguageHabit.is_active == True,  # noqa: E712
            )
        )
        habit = result.scalar_one_or_none()

        if not habit:
            await message.answer("📚 У вас нет активной привычки чтения")
            return

        # Get today's progress
        today = datetime.utcnow().date()
        progress_result = await session.execute(
            select(LanguageProgress).where(
                LanguageProgress.habit_id == habit.id,
                func.date(LanguageProgress.date) == today,
            )
        )
        progress = progress_result.scalar_one_or_none()

        # Check if questions are available
        if not progress or not progress.questions_sent:
            await message.answer(
                "❌ Вопросы ещё не отправлены.\n\n" "Вопросы приходят автоматически вечером после чтения."
            )
            return

        if progress.questions_answered:
            await message.answer(
                f"✅ Вы уже ответили на вопросы сегодня!\n\n"
                f"Правильных ответов: {progress.questions_correct}/{progress.questions_total}"
            )
            return

        # Get questions from extra_data
        questions = progress.extra_data.get("questions", []) if progress.extra_data else []
        if not questions:
            await message.answer("❌ Вопросы не найдены")
            return

        # Save questions to state and start FSM
        await state.update_data(questions=questions, current_question=0, answers=[], progress_id=progress.id)
        await state.set_state(ReadingStates.answering_questions)

        # Show first question
        await _show_question(message, questions[0], 1, len(questions))


async def _show_question(message: Message, question: dict, number: int, total: int):
    """Показывает вопрос с вариантами ответов"""
    question_text = question.get("question", "")
    options = question.get("options", [])

    message_text = f"❓ <b>Вопрос {number}/{total}</b>\n\n" f"{question_text}\n\n"

    for idx, option in enumerate(options, 1):
        message_text += f"{idx}. {option}\n"

    message_text += "\n💬 <i>Отправьте номер ответа (1-4) или /cancel для отмены</i>"

    await message.answer(message_text)


@router.message(ReadingStates.answering_questions, Command("cancel"))
async def cancel_questions(message: Message, state: FSMContext):
    """Отменить ответы на вопросы"""
    await state.clear()
    await message.answer("❌ Ответы на вопросы отменены")


@router.message(ReadingStates.answering_questions)
async def process_answer(message: Message, state: FSMContext):
    """Обрабатывает ответ пользователя на вопрос"""
    text = message.text.strip()

    # Validate input
    if not text.isdigit():
        await message.answer("❌ Пожалуйста, введите номер ответа (1-4)")
        return

    answer_idx = int(text) - 1

    data = await state.get_data()
    questions = data.get("questions", [])
    current_idx = data.get("current_question", 0)
    answers = data.get("answers", [])

    if current_idx >= len(questions):
        await message.answer("❌ Все вопросы уже отвечены")
        await state.clear()
        return

    current_question = questions[current_idx]
    options = current_question.get("options", [])

    # Validate answer index
    if answer_idx < 0 or answer_idx >= len(options):
        await message.answer(f"❌ Неверный номер. Выберите от 1 до {len(options)}")
        return

    # Check if answer is correct
    correct_idx = current_question.get("correct_answer", 0)
    is_correct = answer_idx == correct_idx

    # Save answer
    answers.append(
        {
            "question_idx": current_idx,
            "user_answer": answer_idx,
            "correct_answer": correct_idx,
            "is_correct": is_correct,
        }
    )

    # Show feedback
    if is_correct:
        await message.answer("✅ Правильно!")
    else:
        correct_option = options[correct_idx]
        await message.answer(f"❌ Неправильно\n\n" f"Правильный ответ: {correct_option}")

    # Move to next question
    next_idx = current_idx + 1

    if next_idx < len(questions):
        # More questions remain
        await state.update_data(current_question=next_idx, answers=answers)
        await _show_question(message, questions[next_idx], next_idx + 1, len(questions))
    else:
        # All questions answered
        correct_count = sum(1 for a in answers if a["is_correct"])
        total_count = len(answers)

        # Update progress in database
        async with SessionLocal() as session:
            progress_id = data.get("progress_id")
            result = await session.execute(select(LanguageProgress).where(LanguageProgress.id == progress_id))
            progress = result.scalar_one_or_none()

            if progress:
                progress.questions_answered = True
                progress.questions_correct = correct_count
                progress.questions_total = total_count

                # Store detailed answers
                if progress.extra_data is None:
                    progress.extra_data = {}
                progress.extra_data["user_answers"] = answers

                await session.commit()

        # Show final results
        percentage = (correct_count / total_count * 100) if total_count > 0 else 0

        result_emoji = "🎉" if percentage >= 80 else "👍" if percentage >= 60 else "📚"

        if percentage >= 80:
            result_text = "Отлично!"
        elif percentage >= 60:
            result_text = "Хорошо!"
        else:
            result_text = "Продолжайте практиковаться!"

        await message.answer(
            f"{result_emoji} <b>Результаты</b>\n\n"
            f"Правильных ответов: {correct_count}/{total_count}\n"
            f"Процент: {percentage:.0f}%\n\n"
            f"{result_text}"
        )

        await state.clear()
