# src/handlers/language/grammar.py

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from api import APIAuthError, APIError, get_user_language_api
from db import SessionLocal
from utils import escape_html

router = Router()


@router.message(Command("grammar"))
async def cmd_grammar(message: Message):
    """Получить последний урок грамматики"""
    user_id = message.from_user.id

    async with SessionLocal() as session:
        api = await get_user_language_api(session, user_id)
        if not api:
            await message.answer("🔑 Требуется настройка API. Используйте /language_setup")
            return

        try:
            data = await api.get_latest_grammar()

            if not data.get("success"):
                await message.answer("📚 Грамматические темы не найдены.")
                return

            lesson = data["lesson"]
            module_info = lesson["module"]

            # Формируем сообщение (сокращённо, т.к. контент может быть большим)
            description = lesson.get("description", "")
            if len(description) > 500:
                description = description[:500] + "..."

            # Экранируем HTML для безопасности
            title = escape_html(lesson["title"])
            module_title = escape_html(module_info["title"])
            level_code = escape_html(module_info["level"]["code"])
            level_name = escape_html(module_info["level"]["name"])
            description_safe = escape_html(description)
            status = escape_html(lesson["progress"]["status"])

            message_text = (
                f"📖 <b>{title}</b>\n\n"
                f"📚 Модуль: {module_title}\n"
                f"🎓 Уровень: {level_code} - {level_name}\n\n"
                f"<i>{description_safe}</i>\n\n"
                f"📊 Статус: {status}\n"
                f"⭐ Оценка: {lesson['progress']['score']}/100"
            )

            await message.answer(message_text)

        except APIAuthError:
            await message.answer("❌ Токен недействителен. Используйте /language_setup")
        except APIError as e:
            await message.answer(f"❌ Ошибка: {e}")
        finally:
            await api.close()


@router.message(Command("random_excerpt"))
async def cmd_random_excerpt(message: Message):
    """Получить случайный отрывок для практики"""
    user_id = message.from_user.id

    async with SessionLocal() as session:
        api = await get_user_language_api(session, user_id)
        if not api:
            await message.answer("🔑 Требуется настройка API. Используйте /language_setup")
            return

        try:
            data = await api.get_random_excerpt(length=800)

            excerpt = data["excerpt"]
            book = excerpt["book"]
            chapter = excerpt["chapter"]

            # Экранируем HTML для безопасности
            book_title = escape_html(book["title"])
            author = escape_html(book["author"])
            chapter_title = escape_html(chapter["title"])
            text_safe = escape_html(excerpt["text"])

            message_text = (
                f"📖 <b>Случайный отрывок</b>\n\n"
                f"📚 Из книги: <i>{book_title}</i>\n"
                f"✍️ Автор: {author}\n"
                f"📄 Глава {chapter['number']}: {chapter_title}\n"
                f"━━━━━━━━━━━━━━━━━━━━\n\n"
                f"{text_safe}\n\n"
                f"━━━━━━━━━━━━━━━━━━━━"
            )

            await message.answer(message_text)

        except APIAuthError:
            await message.answer("❌ Токен недействителен. Используйте /language_setup")
        except APIError as e:
            await message.answer(f"❌ Ошибка: {e}")
        finally:
            await api.close()
