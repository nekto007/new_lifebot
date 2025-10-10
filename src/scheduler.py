"""Планировщик задач для отправки напоминаний о привычках и вечерних отчётов."""

from datetime import datetime
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from config import logger
from db import Habits, SessionLocal, User
from sqlalchemy import select


class ReminderScheduler:
    """Управляет расписанием напоминаний для пользователей."""

    def __init__(self, bot):
        """Инициализирует планировщик с экземпляром бота."""
        self.bot = bot
        self.scheduler = AsyncIOScheduler(timezone="UTC")

    def start(self):
        """Запускает планировщик."""
        self.scheduler.start()

        # Планируем проверку делегированных задач каждый день в 09:00 UTC
        from delegation_reminders import DelegationReminderService

        delegation_service = DelegationReminderService(self.bot)
        self.scheduler.add_job(
            delegation_service.check_and_send_reminders,
            trigger=CronTrigger(hour=9, minute=0, timezone="UTC"),
            id="delegation_reminders_check",
            replace_existing=True,
        )

        logger.info("Scheduler started with delegation reminders")

    def shutdown(self):
        """Останавливает планировщик."""
        self.scheduler.shutdown()
        logger.info("Scheduler stopped")

    async def schedule_user_reminders(self, user_id: int):
        """Планирует все напоминания для конкретного пользователя."""
        async with SessionLocal() as session:
            # Получаем пользователя
            result = await session.execute(select(User).where(User.user_id == user_id))
            user = result.scalar_one_or_none()
            if not user:
                logger.warning(f"User {user_id} not found for scheduling")
                return

            # Планируем утренний пинг
            if user.morning_ping_time:
                await self._schedule_morning_ping(user)

            # Планируем вечерний отчёт
            if user.evening_ping_time:
                await self._schedule_evening_report(user)

            # Планируем напоминания о привычках
            result = await session.execute(
                select(Habits).where(Habits.user_id == user_id, Habits.active.is_(True))
            )
            habits = result.scalars().all()

            for habit in habits:
                await self._schedule_habit_reminder(user, habit)

        logger.info(f"Scheduled reminders for user {user_id}")

    async def _schedule_morning_ping(self, user: User):
        """Планирует утренний пинг для пользователя."""
        job_id = f"morning_ping_{user.user_id}"

        # Удаляем предыдущее задание, если есть
        if self.scheduler.get_job(job_id):
            self.scheduler.remove_job(job_id)

        # Создаём триггер с учётом часового пояса пользователя
        tz = ZoneInfo(user.tz) if user.tz else ZoneInfo("UTC")
        trigger = CronTrigger(
            hour=user.morning_ping_time.hour, minute=user.morning_ping_time.minute, timezone=tz
        )

        self.scheduler.add_job(
            self._send_morning_ping,
            trigger=trigger,
            id=job_id,
            args=[user.user_id],
            replace_existing=True,
        )

        logger.info(
            f"Scheduled morning ping for user {user.user_id} at "
            f"{user.morning_ping_time.strftime('%H:%M')} {user.tz}"
        )

    async def _schedule_evening_report(self, user: User):
        """Планирует вечерний отчёт для пользователя."""
        job_id = f"evening_report_{user.user_id}"

        if self.scheduler.get_job(job_id):
            self.scheduler.remove_job(job_id)

        tz = ZoneInfo(user.tz) if user.tz else ZoneInfo("UTC")
        trigger = CronTrigger(
            hour=user.evening_ping_time.hour, minute=user.evening_ping_time.minute, timezone=tz
        )

        self.scheduler.add_job(
            self._send_evening_report,
            trigger=trigger,
            id=job_id,
            args=[user.user_id],
            replace_existing=True,
        )

        logger.info(
            f"Scheduled evening report for user {user.user_id} at "
            f"{user.evening_ping_time.strftime('%H:%M')} {user.tz}"
        )

    async def _schedule_habit_reminder(self, user: User, habit: Habits):
        """Планирует напоминание о конкретной привычке."""
        if not habit.time_of_day or not habit.active:
            return

        job_id = f"habit_{habit.id}_user_{user.user_id}"
        pregen_job_id = f"pregen_{habit.id}_user_{user.user_id}"

        if self.scheduler.get_job(job_id):
            self.scheduler.remove_job(job_id)

        if self.scheduler.get_job(pregen_job_id):
            self.scheduler.remove_job(pregen_job_id)

        tz = ZoneInfo(user.tz) if user.tz else ZoneInfo("UTC")

        # Парсим расписание привычки
        trigger = None
        pregen_trigger = None

        if habit.schedule_type == "daily":
            trigger = CronTrigger(hour=habit.time_of_day.hour, minute=habit.time_of_day.minute, timezone=tz)

            # Триггер для пре-генерации контента за 5 минут до напоминания
            pregen_hour = habit.time_of_day.hour
            pregen_minute = habit.time_of_day.minute - 5

            # Обработка переноса часа (если минуты уходят в отрицательные)
            if pregen_minute < 0:
                pregen_minute += 60
                pregen_hour -= 1
                if pregen_hour < 0:
                    pregen_hour += 24

            pregen_trigger = CronTrigger(hour=pregen_hour, minute=pregen_minute, timezone=tz)
        elif habit.schedule_type == "weekly":
            # Парсим RRULE для получения дней недели
            # Формат: "FREQ=WEEKLY;BYDAY=MO,WE,FR"
            if habit.rrule:
                try:
                    # Извлекаем дни недели из RRULE
                    byday_part = [part for part in habit.rrule.split(";") if part.startswith("BYDAY=")]
                    if byday_part:
                        days_str = byday_part[0].split("=")[1]
                        # Конвертируем MO,WE,FR в формат для CronTrigger (0=mon, 6=sun)
                        days_map = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}
                        day_of_week = ",".join(
                            [str(days_map[day]) for day in days_str.split(",") if day in days_map]
                        )

                        trigger = CronTrigger(
                            day_of_week=day_of_week,
                            hour=habit.time_of_day.hour,
                            minute=habit.time_of_day.minute,
                            timezone=tz,
                        )

                        # Триггер для пре-генерации (тот же день недели, но за 5 минут до)
                        pregen_hour = habit.time_of_day.hour
                        pregen_minute = habit.time_of_day.minute - 5

                        if pregen_minute < 0:
                            pregen_minute += 60
                            pregen_hour -= 1
                            if pregen_hour < 0:
                                pregen_hour += 24

                        pregen_trigger = CronTrigger(
                            day_of_week=day_of_week,
                            hour=pregen_hour,
                            minute=pregen_minute,
                            timezone=tz,
                        )
                except Exception as e:
                    logger.error(f"Failed to parse RRULE for habit {habit.id}: {e}")
                    return
            else:
                # Если нет RRULE, считаем что каждый день (fallback)
                trigger = CronTrigger(
                    hour=habit.time_of_day.hour, minute=habit.time_of_day.minute, timezone=tz
                )

                pregen_hour = habit.time_of_day.hour
                pregen_minute = habit.time_of_day.minute - 5

                if pregen_minute < 0:
                    pregen_minute += 60
                    pregen_hour -= 1
                    if pregen_hour < 0:
                        pregen_hour += 24

                pregen_trigger = CronTrigger(hour=pregen_hour, minute=pregen_minute, timezone=tz)

        if trigger:
            self.scheduler.add_job(
                self._send_habit_reminder,
                trigger=trigger,
                id=job_id,
                args=[user.user_id, habit.id],
                replace_existing=True,
            )

            # Планируем пре-генерацию контента только если привычка требует контент
            if pregen_trigger and habit.include_content:
                self.scheduler.add_job(
                    self._pregenerate_habit_content,
                    trigger=pregen_trigger,
                    id=pregen_job_id,
                    args=[habit.id],
                    replace_existing=True,
                )
                logger.info(
                    f"Scheduled content pre-generation for habit '{habit.title}' (ID {habit.id}) "
                    f"at {pregen_hour:02d}:{pregen_minute:02d} {user.tz}"
                )

            schedule_info = f"{habit.schedule_type}"
            if habit.schedule_type == "weekly" and habit.rrule:
                schedule_info += f" ({habit.rrule})"

            logger.info(
                f"Scheduled habit '{habit.title}' for user {user.user_id} at "
                f"{habit.time_of_day.strftime('%H:%M')} {user.tz} - {schedule_info}"
            )

    async def _pregenerate_habit_content(self, habit_id: int):
        """Пре-генерирует контент для привычки за 5 минут до напоминания."""
        from db import HabitTemplate
        from llm_service import llm_service

        async with SessionLocal() as session:
            habit = await session.get(Habits, habit_id)

            if not habit or not habit.active or not habit.include_content:
                return

            try:
                # Получаем шаблон, если он есть
                template = None
                if habit.template_id:
                    template = await session.get(HabitTemplate, habit.template_id)

                # Генерируем контент заранее
                content = await llm_service.generate_habit_content(
                    habit_id=habit.id,
                    habit_title=habit.title,
                    template=template,
                    custom_prompt=habit.content_prompt,
                )

                logger.info(
                    f"Pre-generated content for habit {habit_id} ('{habit.title}'): " f"{content[:50]}..."
                )
            except Exception as e:
                logger.error(f"Failed to pre-generate content for habit {habit_id}: {e}")

    async def _send_morning_ping(self, user_id: int):
        """Отправляет утренний пинг пользователю."""
        from utils import get_phrase

        async with SessionLocal() as session:
            result = await session.execute(select(User).where(User.user_id == user_id))
            user = result.scalar_one_or_none()
            if not user:
                return

            # Проверяем тихие часы
            if await self._is_quiet_hours(user):
                logger.info(f"Skipping morning ping for user {user_id} - quiet hours")
                return

            message = get_phrase("morning_greeting", first_name=user.first_name)

            try:
                await self.bot.send_message(user_id, message)
                logger.info(f"Sent morning ping to user {user_id}")
            except Exception as e:
                logger.error(f"Failed to send morning ping to user {user_id}: {e}")

    async def _send_evening_report(self, user_id: int):
        """Отправляет запрос на вечерний отчёт."""
        from aiogram.utils.keyboard import InlineKeyboardBuilder
        from utils import get_phrase

        async with SessionLocal() as session:
            result = await session.execute(select(User).where(User.user_id == user_id))
            user = result.scalar_one_or_none()
            if not user:
                return

            if await self._is_quiet_hours(user):
                logger.info(f"Skipping evening report for user {user_id} - quiet hours")
                return

            message = get_phrase("evening_summary", done=0, total=0, tasks_done=0, tasks_total=0)

            builder = InlineKeyboardBuilder()
            builder.button(text="Заполню текстом ✍️", callback_data="J_ADD")
            builder.button(text="Пропустить сегодня", callback_data="J_SKIP")
            builder.adjust(1)

            try:
                await self.bot.send_message(user_id, message, reply_markup=builder.as_markup())
                logger.info(f"Sent evening report to user {user_id}")
            except Exception as e:
                logger.error(f"Failed to send evening report to user {user_id}: {e}")

    async def _send_habit_reminder(self, user_id: int, habit_id: int):
        """Отправляет напоминание о привычке."""
        from datetime import date as dt_date

        from aiogram.utils.keyboard import InlineKeyboardBuilder
        from db import HabitTemplate
        from llm_service import llm_service
        from utils import format_date

        async with SessionLocal() as session:
            result = await session.execute(select(User).where(User.user_id == user_id))
            user = result.scalar_one_or_none()
            habit = await session.get(Habits, habit_id)

            if not user or not habit or not habit.active:
                return

            if await self._is_quiet_hours(user):
                logger.info(f"Skipping habit reminder for user {user_id}, " f"habit {habit_id} - quiet hours")
                return

            # Формируем сообщение
            today = dt_date.today()
            date_str = format_date(today, "YYYYMMDD")
            time_str = habit.time_of_day.strftime("%H:%M") if habit.time_of_day else ""

            # Базовое сообщение
            message = f"🔔 <b>{habit.title}</b> ({time_str})\n\n"

            # Если нужен контент - генерируем
            if habit.include_content:
                try:
                    # Получаем шаблон, если он есть
                    template = None
                    if habit.template_id:
                        template = await session.get(HabitTemplate, habit.template_id)

                    # Генерируем контент
                    content = await llm_service.generate_habit_content(
                        habit_id=habit.id,
                        habit_title=habit.title,
                        template=template,
                        custom_prompt=habit.content_prompt,
                    )

                    # Добавляем контент к сообщению
                    message += f"{content}\n\n"

                    # Отмечаем, что контент был использован
                    await llm_service.mark_content_used(habit.id, content)

                    logger.info(f"Generated content for habit {habit_id}: {content[:50]}...")
                except Exception as e:
                    logger.error(f"Failed to generate content for habit {habit_id}: {e}")
                    # Продолжаем без контента

            message += "Отметишь?"

            builder = InlineKeyboardBuilder()
            builder.button(text="Сделал ✅", callback_data=f"H_D:{habit_id}:{date_str}")
            builder.button(text="Отложить 15м ⏰", callback_data=f"H_Z:{habit_id}:15")
            builder.button(text="Пропустить ➖", callback_data=f"H_S:{habit_id}:{date_str}")
            builder.adjust(1)

            try:
                await self.bot.send_message(user_id, message, reply_markup=builder.as_markup())
                logger.info(f"Sent habit reminder to user {user_id}, habit {habit_id}")
            except Exception as e:
                logger.error(f"Failed to send habit reminder to user {user_id}, " f"habit {habit_id}: {e}")

    async def _is_quiet_hours(self, user: User) -> bool:
        """Проверяет, находится ли текущее время в тихих часах пользователя."""
        if not user.quiet_hours_from or not user.quiet_hours_to:
            return False

        tz = ZoneInfo(user.tz) if user.tz else ZoneInfo("UTC")
        now = datetime.now(tz).time()

        quiet_from = user.quiet_hours_from
        quiet_to = user.quiet_hours_to

        # Обработка случая, когда тихие часы пересекают полночь
        if quiet_from > quiet_to:
            return now >= quiet_from or now < quiet_to
        else:
            return quiet_from <= now < quiet_to

    def remove_user_jobs(self, user_id: int):
        """Удаляет все задачи пользователя из планировщика."""
        jobs_to_remove = []

        for job in self.scheduler.get_jobs():
            if str(user_id) in job.id:
                jobs_to_remove.append(job.id)

        for job_id in jobs_to_remove:
            self.scheduler.remove_job(job_id)

        logger.info(f"Removed {len(jobs_to_remove)} jobs for user {user_id}")

    async def reschedule_all_users(self):
        """Перепланирует напоминания для всех пользователей (при старте бота)."""
        async with SessionLocal() as session:
            result = await session.execute(select(User))
            users = result.scalars().all()

            for user in users:
                if user.lang:  # Онбординг пройден
                    await self.schedule_user_reminders(user.user_id)

        logger.info(f"Rescheduled reminders for {len(users)} users")
