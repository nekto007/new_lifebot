"""Сервис напоминаний о делегированных задачах с эскалацией."""

from datetime import datetime, timedelta

from config import logger
from db import DelegatedTask, SessionLocal, Task, User
from sqlalchemy import select


class DelegationReminderService:
    """Управляет напоминаниями для делегированных задач."""

    def __init__(self, bot):
        """Инициализирует сервис с экземпляром бота."""
        self.bot = bot

    async def check_and_send_reminders(self):
        """
        Проверяет все принятые делегированные задачи и отправляет напоминания.
        Вызывается по расписанию (например, раз в день утром).
        """
        async with SessionLocal() as session:
            # Получаем все принятые делегированные задачи
            result = await session.execute(select(DelegatedTask).where(DelegatedTask.status == "accepted"))
            delegated_tasks = result.scalars().all()

            now = datetime.now()

            for dt in delegated_tasks:
                await self._process_reminder(dt, now, session)

    async def _process_reminder(self, delegated_task: DelegatedTask, now: datetime, session):
        """Обрабатывает напоминание для конкретной делегированной задачи."""
        time_until_deadline = delegated_task.deadline - now

        # Проверяем, не просрочена ли задача
        if time_until_deadline.total_seconds() < 0:
            await self._send_overdue_reminder(delegated_task, session)
            return

        # Вычисляем прогресс до дедлайна
        task_age = now - delegated_task.created_at
        total_duration = delegated_task.deadline - delegated_task.created_at
        progress = task_age.total_seconds() / total_duration.total_seconds()

        # Логика эскалации напоминаний
        days_left = time_until_deadline.days

        # 1. Напоминание на 50% времени (только один раз)
        if progress >= 0.5 and delegated_task.reminder_count == 0:
            await self._send_halfway_reminder(delegated_task, days_left, session)

        # 2. Напоминание за 1 день до дедлайна
        elif days_left == 1 and delegated_task.reminder_count < 2:
            await self._send_one_day_reminder(delegated_task, session)

        # 3. Напоминание в день дедлайна
        elif days_left == 0 and delegated_task.reminder_count < 3:
            await self._send_today_reminder(delegated_task, session)

    async def _send_halfway_reminder(self, delegated_task: DelegatedTask, days_left: int, session):
        """Отправляет напоминание на половине пути до дедлайна."""
        task = await session.get(Task, delegated_task.task_id)
        assigned_by_user = await self._get_user(delegated_task.assigned_by_user_id)
        assigned_to_user = await self._get_user(delegated_task.assigned_to_user_id)

        if not task or not assigned_by_user or not assigned_to_user:
            return

        message = (
            f"📋 Напоминание о задаче от {assigned_by_user.first_name}:\n\n"
            f"«{task.title}»\n\n"
            f"⏰ Осталось {days_left} дней до дедлайна "
            f"({delegated_task.deadline.strftime('%d.%m.%Y')})\n\n"
            f"Не забудь выполнить!"
        )

        try:
            await self.bot.send_message(delegated_task.assigned_to_user_id, message)
            delegated_task.reminder_count += 1
            delegated_task.last_reminder_at = datetime.now()
            await session.commit()
            logger.info(f"Sent halfway reminder for delegated task {delegated_task.id}")
        except Exception as e:
            logger.error(f"Failed to send halfway reminder for task {delegated_task.id}: {e}")

    async def _send_one_day_reminder(self, delegated_task: DelegatedTask, session):
        """Отправляет напоминание за 1 день до дедлайна."""
        task = await session.get(Task, delegated_task.task_id)
        assigned_by_user = await self._get_user(delegated_task.assigned_by_user_id)
        assigned_to_user = await self._get_user(delegated_task.assigned_to_user_id)

        if not task or not assigned_by_user or not assigned_to_user:
            return

        message = (
            f"❗️ Напоминание о задаче от {assigned_by_user.first_name}:\n\n"
            f"«{task.title}»\n\n"
            f"⏰ <b>Завтра дедлайн!</b> ({delegated_task.deadline.strftime('%d.%m.%Y')})\n\n"
            f"Успей выполнить!"
        )

        try:
            await self.bot.send_message(delegated_task.assigned_to_user_id, message)
            delegated_task.reminder_count += 1
            delegated_task.last_reminder_at = datetime.now()
            await session.commit()
            logger.info(f"Sent 1-day reminder for delegated task {delegated_task.id}")
        except Exception as e:
            logger.error(f"Failed to send 1-day reminder for task {delegated_task.id}: {e}")

    async def _send_today_reminder(self, delegated_task: DelegatedTask, session):
        """Отправляет напоминание в день дедлайна."""
        task = await session.get(Task, delegated_task.task_id)
        assigned_by_user = await self._get_user(delegated_task.assigned_by_user_id)
        assigned_to_user = await self._get_user(delegated_task.assigned_to_user_id)

        if not task or not assigned_by_user or not assigned_to_user:
            return

        message = (
            f"🔥 СРОЧНО! Напоминание о задаче от {assigned_by_user.first_name}:\n\n"
            f"«{task.title}»\n\n"
            f"⏰ <b>Сегодня дедлайн!</b> ({delegated_task.deadline.strftime('%d.%m.%Y')})\n\n"
            f"Нужно выполнить прямо сейчас!"
        )

        try:
            await self.bot.send_message(delegated_task.assigned_to_user_id, message)
            delegated_task.reminder_count += 1
            delegated_task.last_reminder_at = datetime.now()
            await session.commit()
            logger.info(f"Sent today reminder for delegated task {delegated_task.id}")
        except Exception as e:
            logger.error(f"Failed to send today reminder for task {delegated_task.id}: {e}")

    async def _send_overdue_reminder(self, delegated_task: DelegatedTask, session):
        """Отправляет напоминание о просроченной задаче."""
        task = await session.get(Task, delegated_task.task_id)
        assigned_by_user = await self._get_user(delegated_task.assigned_by_user_id)
        assigned_to_user = await self._get_user(delegated_task.assigned_to_user_id)

        if not task or not assigned_by_user or not assigned_to_user:
            return

        # Обновляем статус на overdue (если ещё не обновлён)
        if delegated_task.status != "overdue":
            delegated_task.status = "overdue"
            await session.commit()

        # Проверяем, когда последний раз отправляли напоминание
        if delegated_task.last_reminder_at:
            time_since_last = datetime.now() - delegated_task.last_reminder_at
            # Отправляем напоминание максимум раз в день
            if time_since_last < timedelta(days=1):
                return

        days_overdue = (datetime.now() - delegated_task.deadline).days

        # Напоминание исполнителю
        message_to_assignee = (
            f"⚠️ ПРОСРОЧЕНА задача от {assigned_by_user.first_name}:\n\n"
            f"«{task.title}»\n\n"
            f"⏰ Дедлайн был: {delegated_task.deadline.strftime('%d.%m.%Y')}\n"
            f"⏱ Просрочено на {days_overdue} дн\n\n"
            f"Пожалуйста, выполни как можно скорее!"
        )

        # Напоминание автору задачи
        message_to_author = (
            f"⚠️ Задача просрочена:\n\n"
            f"«{task.title}»\n\n"
            f"👤 Исполнитель: {assigned_to_user.first_name}\n"
            f"⏰ Дедлайн был: {delegated_task.deadline.strftime('%d.%m.%Y')}\n"
            f"⏱ Просрочено на {days_overdue} дн"
        )

        try:
            # Отправляем исполнителю
            await self.bot.send_message(delegated_task.assigned_to_user_id, message_to_assignee)

            # Отправляем автору
            await self.bot.send_message(delegated_task.assigned_by_user_id, message_to_author)

            delegated_task.reminder_count += 1
            delegated_task.last_reminder_at = datetime.now()
            await session.commit()

            logger.info(
                f"Sent overdue reminder for delegated task {delegated_task.id} "
                f"(overdue by {days_overdue} days)"
            )
        except Exception as e:
            logger.error(f"Failed to send overdue reminder for task {delegated_task.id}: {e}")

    async def _get_user(self, user_id: int) -> User:
        """Получает пользователя из БД."""
        async with SessionLocal() as session:
            result = await session.execute(select(User).where(User.user_id == user_id))
            return result.scalar_one_or_none()
