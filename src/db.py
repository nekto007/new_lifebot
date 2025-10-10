# src/db.py
from datetime import date, datetime, time

from config import DATABASE_URL
from sqlalchemy import BigInteger, Boolean, Date, DateTime, ForeignKey, Integer, String, Text, Time, func
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


engine = create_async_engine(DATABASE_URL, echo=False)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
