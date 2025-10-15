"""Rate limiting middleware для защиты от спама."""

import time
from collections import defaultdict
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject


class RateLimitMiddleware(BaseMiddleware):
    """
    Middleware для ограничения частоты запросов от пользователей.

    Ограничение: не более rate_limit сообщений в time_window секунд.
    """

    def __init__(self, rate_limit: int = 20, time_window: int = 60):
        """
        Args:
            rate_limit: Максимальное количество сообщений
            time_window: Временное окно в секундах
        """
        self.rate_limit = rate_limit
        self.time_window = time_window

        self.user_requests: dict[int, list] = defaultdict(list)
        super().__init__()

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        """Проверяет rate limit перед выполнением хендлера."""

        if not isinstance(event, Message):
            return await handler(event, data)

        user_id = event.from_user.id
        current_time = time.time()

        user_timestamps = self.user_requests[user_id]

        user_timestamps[:] = [ts for ts in user_timestamps if current_time - ts < self.time_window]

        # Проверяем, не превышен ли лимит
        if len(user_timestamps) >= self.rate_limit:
            # Превышен лимит - отправляем предупреждение
            await event.reply("⚠️ Слишком много запросов. Пожалуйста, подождите немного.")
            return

        user_timestamps.append(current_time)

        return await handler(event, data)
