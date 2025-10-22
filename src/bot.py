import asyncio

from aiogram import Bot, Dispatcher
from config import TELEGRAM_TOKEN, default_bot_properties, logger
from db import init_db
from handlers import router
from middleware import RateLimitMiddleware
from scheduler import ReminderScheduler


async def _main():
    logger.info("Запуск бота…")
    await init_db()

    bot = Bot(token=TELEGRAM_TOKEN, default=default_bot_properties)
    dp = Dispatcher()

    # Регистрируем rate limiting middleware (защита от спама)
    # Лимит: 20 сообщений в минуту на пользователя
    dp.message.middleware(RateLimitMiddleware(rate_limit=20, time_window=60))

    dp.include_router(router)

    # Инициализируем и запускаем планировщик
    scheduler = ReminderScheduler(bot)
    scheduler.start()

    # Планируем напоминания для всех пользователей
    await scheduler.reschedule_all_users()

    # Сохраняем scheduler в dispatcher workflow_data для доступа из обработчиков
    dp.workflow_data.update(scheduler=scheduler)

    try:
        await dp.start_polling(bot, skip_updates=True)
    finally:
        # Останавливаем планировщик при завершении
        scheduler.shutdown()
        await bot.session.close()


def main():
    asyncio.run(_main())


if __name__ == "__main__":
    main()
