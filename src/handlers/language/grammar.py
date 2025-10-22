# src/handlers/language/grammar.py

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from api import APIAuthError, APIError, get_user_language_api
from db import SessionLocal

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

            message_text = (
                f"📖 <b>{lesson['title']}</b>\n\n"
                f"📚 Модуль: {module_info['title']}\n"
                f"🎓 Уровень: {module_info['level']['code']} - {module_info['level']['name']}\n\n"
                f"<i>{description}</i>\n\n"
                f"📊 Статус: {lesson['progress']['status']}\n"
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

            message_text = (
                f"📖 <b>Случайный отрывок</b>\n\n"
                f"📚 Из книги: <i>{book['title']}</i>\n"
                f"✍️ Автор: {book['author']}\n"
                f"📄 Глава {chapter['number']}: {chapter['title']}\n"
                f"━━━━━━━━━━━━━━━━━━━━\n\n"
                f"{excerpt['text']}\n\n"
                f"━━━━━━━━━━━━━━━━━━━━"
            )

            await message.answer(message_text)

        except APIAuthError:
            await message.answer("❌ Токен недействителен. Используйте /language_setup")
        except APIError as e:
            await message.answer(f"❌ Ошибка: {e}")
        finally:
            await api.close()
