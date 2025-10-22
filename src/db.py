# src/db.py
from datetime import date, datetime, time

from config import DATABASE_URL
from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    Time,
    func,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase): ...


class UserProfile(Base):
    __tablename__ = "user_profiles"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tg_user_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    language: Mapped[str] = mapped_column(String(10))
    timezone: Mapped[str] = mapped_column(String(64))
    quiet_start: Mapped[time | None] = mapped_column(Time, nullable=True)
    quiet_end: Mapped[time | None] = mapped_column(Time, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class Habits(Base):
    __tablename__ = "habits"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.user_id"), index=True)
    title: Mapped[str] = mapped_column(String(255))
    schedule_type: Mapped[str] = mapped_column(String(255))
    rrule: Mapped[str | None] = mapped_column(String(255), nullable=True)
    weekday_mask: Mapped[int | None] = mapped_column(Integer, nullable=True)
    time_of_day: Mapped[time | None] = mapped_column(Time, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=True, default=True)
    template_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("habit_templates.id"), nullable=True)
    include_content: Mapped[bool] = mapped_column(Boolean, default=False)
    content_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class HabitTemplate(Base):
    """Шаблоны известных привычек (зарядка, чтение, медитация и т.д.)"""

    __tablename__ = "habit_templates"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255))  # "Зарядка", "Чтение", "Медитация"
    keywords: Mapped[str] = mapped_column(String(500))  # "зарядка,workout,exercise,тренировка"
    category: Mapped[str] = mapped_column(String(50))  # "fitness", "reading", "meditation", "health"
    has_content: Mapped[bool] = mapped_column(Boolean, default=False)  # может ли генерировать контент
    default_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)  # базовый промпт для LLM
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class HabitContent(Base):
    """Сгенерированный LLM контент для привычек"""

    __tablename__ = "habit_contents"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    habit_id: Mapped[int] = mapped_column(Integer, ForeignKey("habits.id"), index=True)
    content: Mapped[str] = mapped_column(Text)  # сгенерированное задание
    generated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    used_count: Mapped[int] = mapped_column(Integer, default=0)  # сколько раз показали
    last_used: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True
    )  # когда последний раз показали


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    first_name: Mapped[str] = mapped_column(String(255))
    lang: Mapped[str | None] = mapped_column(String(10), nullable=True)
    tz: Mapped[str | None] = mapped_column(String(64), nullable=True)
    quiet_hours_from: Mapped[time | None] = mapped_column(Time, nullable=True)
    quiet_hours_to: Mapped[time | None] = mapped_column(Time, nullable=True)
    morning_ping_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    evening_ping_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Task(Base):
    __tablename__ = "tasks"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.user_id"), index=True)
    title: Mapped[str] = mapped_column(String(255))
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    time_of_day: Mapped[time | None] = mapped_column(Time, nullable=True)
    priority: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class HabitCompletion(Base):
    __tablename__ = "habit_completions"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    habit_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("habits.id"), index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.user_id"), index=True)
    completion_date: Mapped[date] = mapped_column(Date, index=True)
    status: Mapped[str] = mapped_column(String(20))  # 'done', 'skipped', 'snoozed'
    completed_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class UserRelationship(Base):
    """Связи между пользователями для делегирования задач"""

    __tablename__ = "user_relationships"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.user_id"), index=True)
    related_user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.user_id"), index=True)
    relationship_type: Mapped[str] = mapped_column(
        String(50), default="can_delegate"
    )  # 'can_delegate', 'family'
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class DelegatedTask(Base):
    """Делегированные задачи между пользователями"""

    __tablename__ = "delegated_tasks"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(Integer, ForeignKey("tasks.id"), index=True)
    assigned_by_user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.user_id"), index=True)
    assigned_to_user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.user_id"), index=True)
    status: Mapped[str] = mapped_column(
        String(50), default="pending_acceptance"
    )  # pending_acceptance, accepted, rejected, completed, overdue
    deadline: Mapped[datetime] = mapped_column(DateTime)
    reminder_count: Mapped[int] = mapped_column(Integer, default=0)
    last_reminder_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class LanguageHabit(Base):
    """Языковая привычка пользователя"""

    __tablename__ = "language_habits"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.user_id"), nullable=False, index=True)

    habit_type: Mapped[str] = mapped_column(String(50), nullable=False)  # 'reading', 'grammar', 'words'
    name: Mapped[str] = mapped_column(String(200), nullable=False)

    # Настройки привычки
    daily_goal: Mapped[int] = mapped_column(Integer, default=500)  # Например, 500 слов в день
    reminder_time: Mapped[str | None] = mapped_column(String(5), nullable=True)  # "09:00"
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # Прогресс
    current_streak: Mapped[int] = mapped_column(Integer, default=0)
    longest_streak: Mapped[int] = mapped_column(Integer, default=0)
    last_completed: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Данные для чтения
    current_book_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # ID книги на сайте
    current_book_title: Mapped[str | None] = mapped_column(String(200), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class LanguageProgress(Base):
    """Ежедневный прогресс по языковой привычке"""

    __tablename__ = "language_progress"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    habit_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("language_habits.id"), nullable=False, index=True
    )

    date: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # Прогресс
    words_read: Mapped[int] = mapped_column(Integer, default=0)
    fragments_read: Mapped[int] = mapped_column(Integer, default=0)
    lessons_completed: Mapped[int] = mapped_column(Integer, default=0)

    # Audio workflow tracking
    audio_sent: Mapped[bool] = mapped_column(Boolean, default=False)  # Аудио отправлено
    audio_sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    text_sent: Mapped[bool] = mapped_column(Boolean, default=False)  # Текст отправлен
    text_sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    questions_sent: Mapped[bool] = mapped_column(Boolean, default=False)  # Вопросы отправлены
    questions_sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    questions_answered: Mapped[bool] = mapped_column(Boolean, default=False)  # Вопросы отвечены
    questions_correct: Mapped[int] = mapped_column(Integer, default=0)  # Количество правильных ответов
    questions_total: Mapped[int] = mapped_column(Integer, default=0)  # Всего вопросов

    # Дополнительные данные
    extra_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    completed: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class UserLanguageSettings(Base):
    """Настройки пользователя для изучения языка"""

    __tablename__ = "user_language_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.user_id"), unique=True, nullable=False)

    # API токен для сайта (хранится локально)
    api_token: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Настройки
    preferred_fragment_length: Mapped[int] = mapped_column(
        Integer, default=1000
    )  # Длина фрагмента для чтения
    reminder_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    reminder_times: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # ["09:00", "20:00"]

    # Audio workflow schedule (3-part workflow: audio → text → questions)
    audio_time: Mapped[str | None] = mapped_column(String(5), nullable=True)  # "08:00" - время отправки аудио
    reading_time: Mapped[str | None] = mapped_column(
        String(5), nullable=True
    )  # "10:00" - время отправки текста
    questions_time: Mapped[str | None] = mapped_column(
        String(5), nullable=True
    )  # "20:00" - время отправки вопросов
    audio_enabled: Mapped[bool] = mapped_column(Boolean, default=True)  # Включена ли отправка аудио

    # Кэш данных (для офлайн режима)
    cached_books: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    cache_updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


engine = create_async_engine(DATABASE_URL, echo=False)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
