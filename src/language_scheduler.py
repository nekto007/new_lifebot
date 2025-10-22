"""Language learning reminder scheduler jobs."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from api.language_api import get_user_language_api
from apscheduler.triggers.cron import CronTrigger
from audio_service import audio_service
from config import logger
from db import LanguageHabit, LanguageProgress, SessionLocal, User, UserLanguageSettings
from sqlalchemy import func, select


class LanguageReminderService:
    """Управляет напоминаниями для языковых привычек."""

    def __init__(self, bot, scheduler):
        """Инициализирует сервис с экземпляром бота и планировщика."""
        self.bot = bot
        self.scheduler = scheduler

    async def schedule_reading_reminder(self, user_id: int, reminder_time: str):
        """
        Планирует напоминание о чтении для пользователя.

        Args:
            user_id: ID пользователя
            reminder_time: Время напоминания в формате "HH:MM"
        """
        async with SessionLocal() as session:
            # Получаем пользователя для timezone
            result = await session.execute(select(User).where(User.user_id == user_id))
            user = result.scalar_one_or_none()
            if not user:
                logger.warning(f"User {user_id} not found for reading reminder scheduling")
                return

            job_id = f"language_reading_{user_id}"

            # Удаляем предыдущее задание, если есть
            if self.scheduler.get_job(job_id):
                self.scheduler.remove_job(job_id)

            # Парсим время
            hour, minute = map(int, reminder_time.split(":"))

            # Создаём триггер с учётом часового пояса пользователя
            tz = ZoneInfo(user.tz) if user.tz else ZoneInfo("UTC")
            trigger = CronTrigger(hour=hour, minute=minute, timezone=tz)

            self.scheduler.add_job(
                self._send_reading_reminder,
                trigger=trigger,
                id=job_id,
                args=[user_id],
                replace_existing=True,
            )

            logger.info(f"Scheduled reading reminder for user {user_id} at {reminder_time} {user.tz}")

    async def _send_reading_reminder(self, user_id: int):
        """Отправляет напоминание о чтении."""
        async with SessionLocal() as session:
            # Получаем привычку чтения
            result = await session.execute(
                select(LanguageHabit).where(
                    LanguageHabit.user_id == user_id,
                    LanguageHabit.habit_type == "reading",
                    LanguageHabit.is_active == True,  # noqa: E712
                )
            )
            habit = result.scalar_one_or_none()

            if not habit:
                return

            # Проверяем прогресс за сегодня
            today = datetime.utcnow().date()
            progress_result = await session.execute(
                select(LanguageProgress).where(
                    LanguageProgress.habit_id == habit.id,
                    func.date(LanguageProgress.date) == today,
                )
            )
            progress = progress_result.scalar_one_or_none()

            words_today = progress.words_read if progress else 0
            words_left = max(0, habit.daily_goal - words_today)

            if words_left == 0:
                # Цель уже достигнута
                message = f"🎉 Отлично! Вы уже прочитали {words_today} слов сегодня!\n" f"Цель выполнена! ✅"
                try:
                    await self.bot.send_message(user_id, message)
                    logger.info(f"Sent reading completion message to user {user_id}")
                except Exception as e:
                    logger.error(f"Failed to send reading completion to user {user_id}: {e}")
                return

            # Формируем напоминание
            message_text = (
                f"📚 <b>Время для чтения!</b>\n\n"
                f"📖 Книга: <i>{habit.current_book_title or 'Не выбрана'}</i>\n"
                f"🎯 Цель: {habit.daily_goal} слов в день\n"
                f"✅ Прочитано: {words_today} слов\n"
                f"📝 Осталось: {words_left} слов (~{words_left // 200} мин)\n\n"
            )

            # Check if audio was sent earlier
            if progress and progress.audio_sent:
                message_text += "🎧 Вы уже прослушали аудио.\n"

            if habit.current_book_id:
                message_text += "\nПродолжить чтение: /read"
            else:
                message_text += "\nВыберите книгу: /choose_book"

            try:
                await self.bot.send_message(user_id, message_text)

                # Mark text as sent for audio workflow tracking
                if progress:
                    progress.text_sent = True
                    progress.text_sent_at = datetime.utcnow()
                    await session.commit()

                logger.info(f"Sent reading reminder to user {user_id}")
            except Exception as e:
                logger.error(f"Failed to send reading reminder to user {user_id}: {e}")

    async def check_reading_streaks(self):
        """Проверяет streak для всех пользователей (запускается раз в день)."""
        async with SessionLocal() as session:
            result = await session.execute(
                select(LanguageHabit).where(
                    LanguageHabit.habit_type == "reading",
                    LanguageHabit.is_active == True,  # noqa: E712
                )
            )
            habits = result.scalars().all()

            for habit in habits:
                today = datetime.utcnow().date()
                yesterday = today - timedelta(days=1)

                # Проверяем вчерашний прогресс
                yesterday_result = await session.execute(
                    select(LanguageProgress).where(
                        LanguageProgress.habit_id == habit.id,
                        func.date(LanguageProgress.date) == yesterday,
                    )
                )
                yesterday_progress = yesterday_result.scalar_one_or_none()

                if yesterday_progress and yesterday_progress.words_read >= habit.daily_goal:
                    # Streak продолжается
                    habit.current_streak += 1
                    habit.longest_streak = max(habit.longest_streak, habit.current_streak)
                    habit.last_completed = datetime.utcnow()
                else:
                    # Streak прерван
                    if habit.current_streak > 0:
                        try:
                            await self.bot.send_message(
                                habit.user_id,
                                f"❌ Ваш streak прерван!\n"
                                f"Было: {habit.current_streak} дней\n"
                                f"Начните заново сегодня!",
                            )
                        except Exception as e:
                            logger.error(f"Failed to send streak broken message: {e}")
                    habit.current_streak = 0

            await session.commit()
            logger.info(f"Checked reading streaks for {len(habits)} habits")

    def remove_language_jobs(self, user_id: int):
        """Удаляет все языковые задачи пользователя из планировщика."""
        job_ids = [
            f"language_reading_{user_id}",
            f"language_audio_{user_id}",
            f"language_questions_{user_id}",
        ]
        for job_id in job_ids:
            if self.scheduler.get_job(job_id):
                self.scheduler.remove_job(job_id)
                logger.info(f"Removed job {job_id}")

    # ===== AUDIO WORKFLOW (3-part: audio → text → questions) =====

    async def schedule_audio_workflow(
        self, user_id: int, audio_time: str, reading_time: str, questions_time: str
    ):
        """
        Планирует 3-этапный рабочий процесс обучения:
        1. Утро (audio_time): Отправка аудио фрагмента для прослушивания
        2. День (reading_time): Отправка текста для чтения
        3. Вечер (questions_time): Отправка вопросов на понимание

        Args:
            user_id: ID пользователя
            audio_time: Время отправки аудио (например, "08:00")
            reading_time: Время отправки текста (например, "10:00")
            questions_time: Время отправки вопросов (например, "20:00")
        """
        async with SessionLocal() as session:
            result = await session.execute(select(User).where(User.user_id == user_id))
            user = result.scalar_one_or_none()
            if not user:
                logger.warning(f"User {user_id} not found for audio workflow scheduling")
                return

            tz = ZoneInfo(user.tz) if user.tz else ZoneInfo("UTC")

            # Remove old jobs
            self.remove_language_jobs(user_id)

            # Schedule audio (morning)
            audio_hour, audio_minute = map(int, audio_time.split(":"))
            audio_trigger = CronTrigger(hour=audio_hour, minute=audio_minute, timezone=tz)
            self.scheduler.add_job(
                self._send_audio_fragment,
                trigger=audio_trigger,
                id=f"language_audio_{user_id}",
                args=[user_id],
                replace_existing=True,
            )
            logger.info(f"Scheduled audio for user {user_id} at {audio_time} {user.tz}")

            # Schedule reading (midday)
            reading_hour, reading_minute = map(int, reading_time.split(":"))
            reading_trigger = CronTrigger(hour=reading_hour, minute=reading_minute, timezone=tz)
            self.scheduler.add_job(
                self._send_reading_reminder,
                trigger=reading_trigger,
                id=f"language_reading_{user_id}",
                args=[user_id],
                replace_existing=True,
            )
            logger.info(f"Scheduled reading for user {user_id} at {reading_time} {user.tz}")

            # Schedule questions (evening)
            questions_hour, questions_minute = map(int, questions_time.split(":"))
            questions_trigger = CronTrigger(hour=questions_hour, minute=questions_minute, timezone=tz)
            self.scheduler.add_job(
                self._send_comprehension_questions,
                trigger=questions_trigger,
                id=f"language_questions_{user_id}",
                args=[user_id],
                replace_existing=True,
            )
            logger.info(f"Scheduled questions for user {user_id} at {questions_time} {user.tz}")

    async def _send_audio_fragment(self, user_id: int):
        """Отправляет аудио фрагмент для прослушивания (утро, за 1-2 часа до чтения)."""
        async with SessionLocal() as session:
            # Get reading habit
            habit_result = await session.execute(
                select(LanguageHabit).where(
                    LanguageHabit.user_id == user_id,
                    LanguageHabit.habit_type == "reading",
                    LanguageHabit.is_active == True,  # noqa: E712
                )
            )
            habit = habit_result.scalar_one_or_none()
            if not habit or not habit.current_book_id:
                logger.info(f"No active reading habit for user {user_id}, skipping audio")
                return

            # Get settings
            settings_result = await session.execute(
                select(UserLanguageSettings).where(UserLanguageSettings.user_id == user_id)
            )
            settings = settings_result.scalar_one_or_none()
            if not settings or not settings.audio_enabled:
                logger.info(f"Audio disabled for user {user_id}")
                return

            # Get API client
            api = await get_user_language_api(session, user_id)
            if not api:
                logger.warning(f"No API token for user {user_id}")
                await self.bot.send_message(user_id, "❌ Не настроен API токен. Используйте /language_setup")
                return

            # Get or create today's progress
            today = datetime.utcnow().date()
            progress_result = await session.execute(
                select(LanguageProgress).where(
                    LanguageProgress.habit_id == habit.id,
                    func.date(LanguageProgress.date) == today,
                )
            )
            progress = progress_result.scalar_one_or_none()

            # Check if audio already sent today
            if progress and progress.audio_sent:
                logger.info(f"Audio already sent today for user {user_id}")
                return

            try:
                # Fetch next fragment
                target_length = settings.preferred_fragment_length if settings else 1000
                fragment_data = await api.read_next(book_id=habit.current_book_id, length=target_length)

                fragment = fragment_data.get("fragment", {})
                text = fragment.get("text", "").replace("\\n", "\n")

                if not text:
                    logger.error(f"Empty fragment text for user {user_id}")
                    return

                # Generate audio
                book = fragment_data.get("book", {})
                chapter = fragment_data.get("chapter", {})

                # Отправляем прогресс-индикатор
                progress_msg = await self.bot.send_message(
                    user_id,
                    f"⏳ <b>Генерирую аудио...</b>\n\n"
                    f"📖 {book.get('title', 'Книга')}\n"
                    f"Глава {chapter.get('number', '?')}: {chapter.get('title', 'Глава')}\n\n"
                    f"<i>Пожалуйста, подождите несколько секунд</i>",
                )

                audio_buffer = await audio_service.generate_audio(text, language="en")

                # Удаляем прогресс-индикатор после генерации
                try:
                    await self.bot.delete_message(user_id, progress_msg.message_id)
                except Exception:
                    pass  # Не критично, если не удалось удалить

                if audio_buffer:
                    # Send audio message
                    caption = (
                        f"🎧 <b>Аудио для прослушивания</b>\n\n"
                        f"📖 {book.get('title', 'Книга')}\n"
                        f"Глава {chapter.get('number', '?')}: {chapter.get('title', 'Глава')}\n\n"
                        f"Прослушайте этот фрагмент, чтобы подготовиться к чтению.\n"
                        f"📝 Текст для чтения придёт позже."
                    )

                    await self.bot.send_voice(user_id, voice=audio_buffer, caption=caption)
                else:
                    # Fallback: отправляем текст без аудио
                    logger.warning(f"Audio generation failed for user {user_id}, sending text-only preview")

                    # Обрезаем текст для preview
                    preview_text = text[:500] + "..." if len(text) > 500 else text

                    fallback_message = (
                        f"📖 <b>Текст для прослушивания</b>\n\n"
                        f"📖 {book.get('title', 'Книга')}\n"
                        f"Глава {chapter.get('number', '?')}: {chapter.get('title', 'Глава')}\n\n"
                        f"⚠️ <i>Аудио временно недоступно. "
                        f"Вот текст для предварительного ознакомления:</i>\n\n"
                        f"{preview_text}\n\n"
                        f"📝 Полный текст для чтения придёт позже."
                    )

                    await self.bot.send_message(user_id, fallback_message)

                # Update progress
                if not progress:
                    progress = LanguageProgress(
                        habit_id=habit.id,
                        date=datetime.utcnow(),
                        words_read=0,
                        fragments_read=0,
                        lessons_completed=0,
                        audio_sent=False,
                        text_sent=False,
                        questions_sent=False,
                        questions_answered=False,
                        questions_correct=0,
                        questions_total=0,
                    )
                    session.add(progress)

                progress.audio_sent = True
                progress.audio_sent_at = datetime.utcnow()
                # Store fragment for later use
                if progress.extra_data is None:
                    progress.extra_data = {}
                progress.extra_data["pending_fragment"] = fragment_data

                await session.commit()
                logger.info(f"Sent audio fragment to user {user_id}")

                # Prefetch следующего фрагмента в фоне для мгновенной доставки завтра
                try:
                    await self._prefetch_next_audio(user_id, habit, api, target_length)
                except Exception as prefetch_error:
                    logger.warning(f"Prefetch failed for user {user_id}: {prefetch_error}")
                    # Не критично, не прерываем основной флоу

            except Exception as e:
                logger.error(f"Failed to send audio to user {user_id}: {e}")

    async def _prefetch_next_audio(self, user_id: int, habit, api, target_length: int):
        """
        Prefetch следующего фрагмента и генерация аудио в фоне.
        Аудио будет закешировано и доступно для мгновенной доставки.
        """
        try:
            logger.info(f"Starting prefetch for user {user_id}")

            # Получаем следующий фрагмент (без продвижения прогресса)
            next_fragment_data = await api.read_next(book_id=habit.current_book_id, length=target_length)

            next_fragment = next_fragment_data.get("fragment", {})
            next_text = next_fragment.get("text", "").replace("\\n", "\n")

            if not next_text:
                logger.warning(f"Empty next fragment for user {user_id}, skipping prefetch")
                return

            # Генерируем аудио (оно будет автоматически закешировано)
            audio_buffer = await audio_service.generate_audio(next_text, language="en")

            if audio_buffer:
                logger.info(f"Successfully prefetched and cached audio for user {user_id}")
            else:
                logger.warning(f"Prefetch audio generation returned None for user {user_id}")

        except Exception as e:
            logger.error(f"Error during prefetch for user {user_id}: {e}")
            raise

    async def _send_comprehension_questions(self, user_id: int):
        """Отправляет вопросы на понимание прочитанного (вечер)."""
        async with SessionLocal() as session:
            # Get reading habit
            habit_result = await session.execute(
                select(LanguageHabit).where(
                    LanguageHabit.user_id == user_id,
                    LanguageHabit.habit_type == "reading",
                    LanguageHabit.is_active == True,  # noqa: E712
                )
            )
            habit = habit_result.scalar_one_or_none()
            if not habit or not habit.current_book_id:
                return

            # Get today's progress
            today = datetime.utcnow().date()
            progress_result = await session.execute(
                select(LanguageProgress).where(
                    LanguageProgress.habit_id == habit.id,
                    func.date(LanguageProgress.date) == today,
                )
            )
            progress = progress_result.scalar_one_or_none()

            # Check if text was sent and questions not yet sent
            if not progress or not progress.text_sent:
                logger.info(f"Text not sent yet for user {user_id}, skipping questions")
                return

            if progress.questions_sent:
                logger.info(f"Questions already sent today for user {user_id}")
                return

            # Get API client
            api = await get_user_language_api(session, user_id)
            if not api:
                return

            try:
                # Get fragment text from extra_data
                fragment_text = None
                if progress.extra_data and "pending_fragment" in progress.extra_data:
                    fragment_data = progress.extra_data["pending_fragment"]
                    fragment = fragment_data.get("fragment", {})
                    fragment_text = fragment.get("text", "")

                # Fetch comprehension questions
                questions_data = await api.get_comprehension_questions(
                    book_id=habit.current_book_id, fragment_text=fragment_text, question_count=3
                )

                questions = questions_data.get("questions", [])
                if not questions:
                    logger.warning(f"No questions returned for user {user_id}")
                    return

                # Send questions (we'll implement the handler later)
                message_text = (
                    "❓ <b>Вопросы на понимание прочитанного</b>\n\n"
                    "Ответьте на вопросы по сегодняшнему фрагменту:\n\n"
                )

                for idx, q in enumerate(questions, 1):
                    message_text += f"{idx}. {q.get('question', '')}\n"

                message_text += "\nИспользуйте команду /answer_questions для ответов."

                await self.bot.send_message(user_id, message_text)

                # Update progress
                progress.questions_sent = True
                progress.questions_sent_at = datetime.utcnow()
                progress.questions_total = len(questions)

                # Store questions for later checking
                if progress.extra_data is None:
                    progress.extra_data = {}
                progress.extra_data["questions"] = questions

                await session.commit()
                logger.info(f"Sent comprehension questions to user {user_id}")

            except Exception as e:
                logger.error(f"Failed to send questions to user {user_id}: {e}")
