# src/api/base.py

import logging
from typing import Any

import aiohttp
from tenacity import (
    AsyncRetrying,
    before_sleep_log,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)


class APIError(Exception):
    """Базовое исключение для API"""

    pass


class APIConnectionError(APIError):
    """Ошибка подключения к API"""

    pass


class APIAuthError(APIError):
    """Ошибка аутентификации"""

    pass


class BaseAPIClient:
    """Базовый клиент для работы с внешним API"""

    def __init__(self, base_url: str, headers: dict, timeout: int = 30):
        self.base_url = base_url.rstrip("/")
        self.headers = headers
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self._session: aiohttp.ClientSession | None = None

    async def _get_session(self) -> aiohttp.ClientSession:
        """Получить или создать HTTP сессию"""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(headers=self.headers, timeout=self.timeout)
        return self._session

    async def close(self):
        """Закрыть HTTP сессию"""
        if self._session and not self._session.closed:
            await self._session.close()

    async def _request(
        self, method: str, endpoint: str, params: dict | None = None, json: dict | None = None
    ) -> dict[str, Any]:
        """
        Базовый метод для HTTP запросов с retry логикой.

        Retry стратегия:
        - Максимум 3 попытки
        - Exponential backoff: 1s, 2s, 4s
        - Retry только при сетевых ошибках (не при 401/403)
        """
        url = f"{self.base_url}/{endpoint.lstrip('/')}"

        # Определяем retry стратегию
        retry_strategy = AsyncRetrying(
            retry=retry_if_exception_type((aiohttp.ClientError, aiohttp.ServerTimeoutError)),
            stop=stop_after_attempt(3),
            wait=wait_exponential(multiplier=1, min=1, max=10),
            before_sleep=before_sleep_log(logger, logging.WARNING),
            reraise=True,
        )

        try:
            async for attempt in retry_strategy:
                with attempt:
                    session = await self._get_session()
                    async with session.request(method, url, params=params, json=json) as response:
                        data = await response.json()

                        # Не делаем retry на ошибках авторизации
                        if response.status == 401:
                            raise APIAuthError("Invalid API token")

                        # Не делаем retry на клиентских ошибках (кроме timeout)
                        if response.status == 403:
                            raise APIAuthError("Access forbidden")

                        if 400 <= response.status < 500:
                            error_msg = data.get("error", "Unknown error")
                            raise APIError(f"API error: {error_msg}")

                        # Retry на серверных ошибках (5xx)
                        if response.status >= 500:
                            error_msg = data.get("error", "Server error")
                            logger.warning(f"Server error (will retry): {response.status} - {error_msg}")
                            raise aiohttp.ClientError(f"Server error: {error_msg}")

                        return data

        except aiohttp.ClientError as e:
            logger.error(f"API connection error after retries: {e}")
            raise APIConnectionError(f"Failed to connect to API after retries: {e}") from e
        except (APIAuthError, APIError):
            # Пробрасываем эти ошибки дальше без изменений
            raise
        except Exception as e:
            logger.error(f"Unexpected API error: {e}")
            raise APIError(f"API error: {e}") from e

    async def get(self, endpoint: str, params: dict | None = None) -> dict:
        """GET запрос"""
        return await self._request("GET", endpoint, params=params)

    async def post(self, endpoint: str, json: dict | None = None) -> dict:
        """POST запрос"""
        return await self._request("POST", endpoint, json=json)
