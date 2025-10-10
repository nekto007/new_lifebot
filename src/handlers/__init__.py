from aiogram import Router

from .delegate import router as delegate_router
from .habits import router as habits_router
from .health import router as health_router
from .help import router as help_router
from .journal import router as journal_router
from .menu import router as menu_router
from .settings import router as settings_router
from .start import router as start_router
from .stats import router as stats_router
from .tasks import router as tasks_router
from .today import router as today_router

# Объединяем все роутеры
router = Router()
router.include_router(start_router)
router.include_router(health_router)
router.include_router(today_router)
router.include_router(habits_router)
router.include_router(tasks_router)
router.include_router(delegate_router)
router.include_router(stats_router)
router.include_router(journal_router)
router.include_router(help_router)
router.include_router(menu_router)
router.include_router(settings_router)
