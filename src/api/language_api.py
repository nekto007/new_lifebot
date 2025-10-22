# src/api/language_api.py


from config import LANGUAGE_API_TIMEOUT, LANGUAGE_API_URL

from .base import BaseAPIClient


class LanguageAPI(BaseAPIClient):
    """Клиент для Language Learning API"""

    def __init__(self, user_token: str):
        """
        Инициализирует API клиент с токеном конкретного пользователя.

        Args:
            user_token: API токен пользователя (из UserLanguageSettings)
        """
        headers = {
            "X-Telegram-Token": user_token,
            "Content-Type": "application/json",
        }
        super().__init__(base_url=LANGUAGE_API_URL, headers=headers, timeout=LANGUAGE_API_TIMEOUT)

    # ===== BOOKS =====

    async def get_books(self) -> list[dict]:
        """Получить список всех книг"""
        response = await self.get("/books")
        return response.get("books", [])

    async def start_book(self, book_id: int) -> dict:
        """Начать чтение книги с начала"""
        return await self.post("/start-book", json={"book_id": book_id})

    async def read_next(self, book_id: int, length: int = 1000) -> dict:
        """Получить следующий фрагмент книги"""
        response = await self.get("/read-next", params={"book_id": book_id, "length": length})
        return response

    async def get_reading_progress(self, book_id: int | None = None) -> dict:
        """Получить прогресс чтения"""
        params = {"book_id": book_id} if book_id else None
        return await self.get("/reading-progress", params=params)

    # ===== GRAMMAR =====

    async def get_latest_grammar(self) -> dict:
        """Получить последнюю грамматическую тему"""
        return await self.get("/latest-grammar")

    # ===== EXCERPTS =====

    async def get_random_excerpt(self, book_id: int | None = None, length: int = 500) -> dict:
        """Получить случайный отрывок из книги"""
        params = {"length": length}
        if book_id:
            params["book_id"] = book_id

        return await self.get("/book-excerpt", params=params)

    # ===== COMPREHENSION QUESTIONS =====

    async def get_comprehension_questions(
        self, book_id: int, fragment_text: str | None = None, question_count: int = 3
    ) -> dict:
        """
        Получить вопросы на понимание прочитанного текста

        Args:
            book_id: ID книги
            fragment_text: Текст фрагмента (опционально, если API генерирует вопросы на основе прогресса)
            question_count: Количество вопросов

        Returns:
            Dict с вопросами и вариантами ответов
        """
        payload = {"book_id": book_id, "question_count": question_count}
        if fragment_text:
            payload["fragment_text"] = fragment_text

        return await self.post("/comprehension-questions", json=payload)


# Helper function to get API client for specific user
async def get_user_language_api(session, user_id: int) -> LanguageAPI | None:
    """
    Получает API клиент для конкретного пользователя с его токеном.

    Args:
        session: Database session
        user_id: Telegram user ID

    Returns:
        LanguageAPI instance or None if user has no token configured
    """
    from db import UserLanguageSettings
    from sqlalchemy import select

    result = await session.execute(
        select(UserLanguageSettings).where(UserLanguageSettings.user_id == user_id)
    )
    settings = result.scalar_one_or_none()

    if not settings or not settings.api_token:
        return None

    return LanguageAPI(user_token=settings.api_token)
