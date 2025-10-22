# src/handlers/language/__init__.py
from aiogram import Router

from . import grammar, reading, settings

router = Router()
router.include_router(settings.router)  # Настройки первыми, чтобы проверить токен
router.include_router(reading.router)
router.include_router(grammar.router)

__all__ = ["router"]
