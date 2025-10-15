"""Обработчики команд для делегирования задач между пользователями."""

import sys
from datetime import date as dt_date
from datetime import datetime, timedelta
from pathlib import Path

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import or_, select

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import logger
from db import DelegatedTask, SessionLocal, Task, User, UserRelationship

router = Router()


class DelegateTaskStates(StatesGroup):
    """Состояния FSM для делегирования задачи."""

    select_user = State()
    enter_title = State()
    enter_deadline = State()


async def get_user(user_id: int) -> User | None:
    """Получает пользователя из БД."""
    async with SessionLocal() as session:
        result = await session.execute(select(User).where(User.user_id == user_id))
        return result.scalar_one_or_none()


async def get_trusted_users(user_id: int) -> list[User]:
    """Получает список пользователей, которым можно делегировать задачи."""
    async with SessionLocal() as session:
        # Получаем связи
        result = await session.execute(
            select(UserRelationship).where(
                or_(UserRelationship.user_id == user_id, UserRelationship.related_user_id == user_id)
            )
        )
        relationships = result.scalars().all()

        related_user_ids = set()
        for rel in relationships:
            if rel.user_id == user_id:
                related_user_ids.add(rel.related_user_id)
            else:
                related_user_ids.add(rel.user_id)

        if not related_user_ids:
            return []

        result = await session.execute(select(User).where(User.user_id.in_(related_user_ids)))
        return list(result.scalars().all())


@router.message(Command("trust"))
async def cmd_trust(message: Message):
    """Команда /trust - добавляет пользователя в доверенные для делегирования."""
    user_id = message.from_user.id

    user = await get_user(user_id)
    if not user or not user.lang:
        await message.answer(
            "Привет! Сначала нужно пройти настройку.\n\n" "Используй команду /start для начала работы."
        )
        return

    args = message.text.split(maxsplit=1)
    if len(args) > 1:
        try:
            related_user_id = int(args[1])

            related_user = await get_user(related_user_id)
            if not related_user:
                await message.answer(
                    f"Пользователь с ID {related_user_id} не найден в боте.\n\n"
                    "Попросите его сначала запустить бота командой /start"
                )
                return

            async with SessionLocal() as session:
                result = await session.execute(
                    select(UserRelationship).where(
                        or_(
                            (UserRelationship.user_id == user_id)
                            & (UserRelationship.related_user_id == related_user_id),
                            (UserRelationship.user_id == related_user_id)
                            & (UserRelationship.related_user_id == user_id),
                        )
                    )
                )
                existing = result.scalar_one_or_none()

                if existing:
                    await message.answer(
                        f"Пользователь {related_user.first_name} уже в вашем списке доверенных."
                    )
                    return

                relationship = UserRelationship(
                    user_id=user_id,
                    related_user_id=related_user_id,
                    relationship_type="can_delegate",
                )
                session.add(relationship)
                await session.commit()

                logger.info(f"User {user_id} added {related_user_id} to trusted users")

                await message.answer(
                    f"✅ Добавил {related_user.first_name} в доверенные пользователи!\n\n"
                    "Теперь вы можете делегировать задачи с помощью /delegate"
                )

        except ValueError:
            await message.answer(
                "Неверный формат. Используйте:\n"
                "/trust &lt;user_id&gt;\n\n"
                "Где user_id - это числовой Telegram ID пользователя."
            )
    else:
        await message.answer(
            "Чтобы добавить пользователя в доверенные:\n\n"
            "Используйте команду:\n"
            "/trust &lt;user_id&gt;\n\n"
            "Где user_id - это Telegram ID пользователя.\n\n"
            "Пример: /trust 123456789\n\n"
            "Чтобы узнать свой ID, можно использовать бота @userinfobot"
        )


@router.message(Command("delegate"))
async def cmd_delegate(message: Message, state: FSMContext):
    """Команда /delegate - начинает процесс делегирования задачи."""
    user_id = message.from_user.id

    user = await get_user(user_id)
    if not user or not user.lang:
        await message.answer(
            "Привет! Сначала нужно пройти настройку.\n\n" "Используй команду /start для начала работы."
        )
        return

    # Получаем список доверенных пользователей
    trusted_users = await get_trusted_users(user_id)

    if not trusted_users:
        await message.answer(
            "У вас пока нет доверенных пользователей для делегирования.\n\n"
            "Используйте /trust для добавления пользователя."
        )
        return

    builder = InlineKeyboardBuilder()
    for trusted_user in trusted_users:
        builder.button(text=f"{trusted_user.first_name}", callback_data=f"DELEGATE_TO:{trusted_user.user_id}")
    builder.adjust(1)

    await state.set_state(DelegateTaskStates.select_user)
    await message.answer("Кому делегировать задачу?", reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("DELEGATE_TO:"))
async def delegate_select_user_callback(callback: CallbackQuery, state: FSMContext):
    """Обрабатывает выбор пользователя для делегирования."""
    current_state = await state.get_state()
    if current_state != DelegateTaskStates.select_user:
        await callback.answer("Эта кнопка уже неактуальна", show_alert=True)
        return

    assigned_to_user_id = int(callback.data.split(":")[1])

    assigned_to_user = await get_user(assigned_to_user_id)
    if not assigned_to_user:
        await callback.answer("Пользователь не найден", show_alert=True)
        return

    await state.update_data(assigned_to_user_id=assigned_to_user_id)
    await state.set_state(DelegateTaskStates.enter_title)

    await callback.message.edit_text(
        f"Делегируем задачу для <b>{assigned_to_user.first_name}</b>\n\n" "Текст задачи?"
    )
    await callback.answer()


@router.message(DelegateTaskStates.enter_title)
async def process_delegate_title(message: Message, state: FSMContext):
    """Обрабатывает ввод названия делегированной задачи."""
    title = message.text.strip()

    if not title:
        await message.answer("Название задачи не может быть пустым. Попробуй ещё раз:")
        return

    if len(title) > 255:
        await message.answer("Слишком длинное название (макс. 255 символов). Попробуй короче:")
        return

    await state.update_data(title=title)
    await state.set_state(DelegateTaskStates.enter_deadline)

    builder = InlineKeyboardBuilder()
    builder.button(text="Завтра", callback_data="DELEGATE_DEADLINE:tomorrow")
    builder.button(text="Через 3 дня", callback_data="DELEGATE_DEADLINE:3days")
    builder.button(text="Через неделю", callback_data="DELEGATE_DEADLINE:week")
    builder.button(text="Через 2 недели", callback_data="DELEGATE_DEADLINE:2weeks")
    builder.adjust(2)

    await message.answer(
        "Дедлайн? (Enter — завтра)\n\n" "Можно ввести: 2025-10-15, 15.10, завтра, пт",
        reply_markup=builder.as_markup(),
    )


def parse_deadline_input(text: str) -> datetime | None:
    """Парсит дедлайн из пользовательского ввода."""
    text = text.lower().strip()

    if text in ["завтра", "tomorrow", ""]:
        return datetime.now() + timedelta(days=1)

    if text.endswith("days"):
        try:
            days = int(text.replace("days", ""))
            return datetime.now() + timedelta(days=days)
        except ValueError:
            pass

    if text in ["неделю", "week"]:
        return datetime.now() + timedelta(days=7)

    if text in ["2weeks", "2недели"]:
        return datetime.now() + timedelta(days=14)

    weekdays_ru = {
        "пн": 0,
        "понедельник": 0,
        "вт": 1,
        "вторник": 1,
        "ср": 2,
        "среда": 2,
        "чт": 3,
        "четверг": 3,
        "пт": 4,
        "пятница": 4,
        "сб": 5,
        "суббота": 5,
        "вс": 6,
        "воскресенье": 6,
    }

    if text in weekdays_ru:
        target_weekday = weekdays_ru[text]
        today = dt_date.today()
        current_weekday = today.weekday()

        days_ahead = target_weekday - current_weekday
        if days_ahead <= 0:
            days_ahead += 7

        return datetime.combine(today + timedelta(days=days_ahead), datetime.min.time())

    try:
        return datetime.strptime(text, "%Y-%m-%d")
    except ValueError:
        pass

    try:
        return datetime.strptime(text, "%d.%m.%Y")
    except ValueError:
        pass

    try:
        parsed = datetime.strptime(text, "%d.%m")
        year = dt_date.today().year
        result = parsed.replace(year=year)

        if result.date() < dt_date.today():
            result = result.replace(year=year + 1)

        return result
    except ValueError:
        pass

    return None


@router.callback_query(F.data.startswith("DELEGATE_DEADLINE:"))
async def delegate_deadline_button_callback(callback: CallbackQuery, state: FSMContext):
    """Обрабатывает клик по кнопке выбора дедлайна."""
    current_state = await state.get_state()
    if current_state != DelegateTaskStates.enter_deadline:
        await callback.answer("Эта кнопка уже неактуальна", show_alert=True)
        return

    deadline_code = callback.data.split(":")[1]

    deadline_map = {
        "tomorrow": "завтра",
        "3days": "3days",
        "week": "week",
        "2weeks": "2weeks",
    }

    deadline_str = deadline_map.get(deadline_code, "завтра")
    parsed_deadline = parse_deadline_input(deadline_str)

    if not parsed_deadline:
        await callback.answer("Ошибка парсинга дедлайна", show_alert=True)
        return

    await create_delegated_task(callback, state, parsed_deadline)


@router.message(DelegateTaskStates.enter_deadline)
async def process_delegate_deadline_text(message: Message, state: FSMContext):
    """Обрабатывает текстовый ввод дедлайна."""
    deadline_input = message.text.strip()

    parsed_deadline = parse_deadline_input(deadline_input)

    if not parsed_deadline:
        await message.answer(
            f"Дедлайн «{deadline_input}» не распознан. Попробуй ещё раз.\n\n"
            "Примеры: 2025-10-15, 15.10, завтра, пт"
        )
        return

    await create_delegated_task(message, state, parsed_deadline)


async def create_delegated_task(source, state: FSMContext, deadline: datetime):
    """Создаёт делегированную задачу."""
    data = await state.get_data()
    title = data["title"]
    assigned_to_user_id = data["assigned_to_user_id"]

    if isinstance(source, CallbackQuery):
        user_id = source.from_user.id
        bot = source.bot
    else:
        user_id = source.from_user.id
        bot = source.bot

    async with SessionLocal() as session:
        assigned_by_user = await get_user(user_id)
        assigned_to_user = await get_user(assigned_to_user_id)

        if not assigned_by_user or not assigned_to_user:
            if isinstance(source, CallbackQuery):
                await source.answer("Пользователь не найден", show_alert=True)
            else:
                await source.answer("Пользователь не найден")
            return

        # Создаём задачу
        new_task = Task(
            user_id=assigned_to_user_id,  # Задача принадлежит исполнителю
            title=title,
            due_date=deadline.date(),
            time_of_day=None,
            priority=1,  # Делегированные задачи всегда высокий приоритет
            status="pending",
        )
        session.add(new_task)
        await session.flush()  # Получаем ID задачи

        # Создаём запись о делегировании
        delegated_task = DelegatedTask(
            task_id=new_task.id,
            assigned_by_user_id=user_id,
            assigned_to_user_id=assigned_to_user_id,
            status="pending_acceptance",
            deadline=deadline,
            reminder_count=0,
        )
        session.add(delegated_task)
        await session.commit()

        logger.info(
            f"User {user_id} delegated task '{title}' to user {assigned_to_user_id}, " f"deadline: {deadline}"
        )

        # Отправляем уведомление исполнителю
        builder = InlineKeyboardBuilder()
        builder.button(text="Принять ✅", callback_data=f"DELEGATE_ACCEPT:{delegated_task.id}")
        builder.button(text="Отклонить ❌", callback_data=f"DELEGATE_REJECT:{delegated_task.id}")
        builder.adjust(1)

        try:
            await bot.send_message(
                assigned_to_user_id,
                f"📨 <b>Новая задача от {assigned_by_user.first_name}:</b>\n\n"
                f"«{title}»\n\n"
                f"⏰ Дедлайн: {deadline.strftime('%d.%m.%Y %H:%M')}",
                reply_markup=builder.as_markup(),
            )
        except Exception as e:
            logger.error(f"Failed to send delegation notification to {assigned_to_user_id}: {e}")

        # Подтверждение отправителю
        if isinstance(source, CallbackQuery):
            await source.message.edit_text(
                f"Делегировал задачу «{title}» пользователю {assigned_to_user.first_name}.\n\n"
                f"Дедлайн: {deadline.strftime('%d.%m.%Y')}\n\n"
                "Ждём подтверждения от исполнителя."
            )
            await source.answer()
        else:
            await source.answer(
                f"Делегировал задачу «{title}» пользователю {assigned_to_user.first_name}.\n\n"
                f"Дедлайн: {deadline.strftime('%d.%m.%Y')}\n\n"
                "Ждём подтверждения от исполнителя."
            )

    await state.clear()


@router.callback_query(F.data.startswith("DELEGATE_ACCEPT:"))
async def delegate_accept_callback(callback: CallbackQuery):
    """Обрабатывает принятие делегированной задачи."""
    user_id = callback.from_user.id
    delegated_task_id = int(callback.data.split(":")[1])

    async with SessionLocal() as session:
        # Получаем делегированную задачу
        delegated_task = await session.get(DelegatedTask, delegated_task_id)

        if not delegated_task:
            await callback.answer("Задача не найдена", show_alert=True)
            return

        if delegated_task.assigned_to_user_id != user_id:
            await callback.answer("Это не ваша задача", show_alert=True)
            return

        if delegated_task.status != "pending_acceptance":
            await callback.answer("Задача уже обработана", show_alert=True)
            return

        # Обновляем статус
        delegated_task.status = "accepted"
        await session.commit()

        # Получаем задачу и автора
        task = await session.get(Task, delegated_task.task_id)
        assigned_by_user = await get_user(delegated_task.assigned_by_user_id)

        logger.info(f"User {user_id} accepted delegated task {delegated_task_id}")

        # Уведомляем автора
        try:
            await callback.bot.send_message(
                delegated_task.assigned_by_user_id,
                f"✅ {callback.from_user.first_name} принял(а) задачу:\n\n«{task.title}»",
            )
        except Exception as e:
            logger.error(f"Failed to notify task author: {e}")

        # Обновляем сообщение у исполнителя
        await callback.message.edit_text(
            f"📋 Задача от {assigned_by_user.first_name}:\n\n"
            f"«{task.title}»\n\n"
            f"⏰ Дедлайн: {delegated_task.deadline.strftime('%d.%m.%Y %H:%M')}\n\n"
            "✅ <b>Принято</b>\n\n"
            "Буду напоминать по мере приближения дедлайна."
        )

    await callback.answer("✅ Задача принята!")


@router.callback_query(F.data.startswith("DELEGATE_REJECT:"))
async def delegate_reject_callback(callback: CallbackQuery):
    """Обрабатывает отклонение делегированной задачи."""
    user_id = callback.from_user.id
    delegated_task_id = int(callback.data.split(":")[1])

    async with SessionLocal() as session:
        # Получаем делегированную задачу
        delegated_task = await session.get(DelegatedTask, delegated_task_id)

        if not delegated_task:
            await callback.answer("Задача не найдена", show_alert=True)
            return

        if delegated_task.assigned_to_user_id != user_id:
            await callback.answer("Это не ваша задача", show_alert=True)
            return

        if delegated_task.status != "pending_acceptance":
            await callback.answer("Задача уже обработана", show_alert=True)
            return

        # Обновляем статус
        delegated_task.status = "rejected"
        await session.commit()

        # Получаем задачу и автора
        task = await session.get(Task, delegated_task.task_id)
        assigned_by_user = await get_user(delegated_task.assigned_by_user_id)

        logger.info(f"User {user_id} rejected delegated task {delegated_task_id}")

        # Уведомляем автора
        try:
            await callback.bot.send_message(
                delegated_task.assigned_by_user_id,
                f"❌ {callback.from_user.first_name} отклонил(а) задачу:\n\n«{task.title}»",
            )
        except Exception as e:
            logger.error(f"Failed to notify task author: {e}")

        # Обновляем сообщение у исполнителя
        await callback.message.edit_text(
            f"Задача от {assigned_by_user.first_name}:\n\n" f"«{task.title}»\n\n" "❌ <b>Отклонено</b>"
        )

    await callback.answer("❌ Задача отклонена")


@router.message(Command("delegated"))
async def cmd_delegated(message: Message):
    """Команда /delegated - показывает задачи, которые вы назначили другим."""
    user_id = message.from_user.id

    user = await get_user(user_id)
    if not user or not user.lang:
        await message.answer(
            "Привет! Сначала нужно пройти настройку.\n\n" "Используй команду /start для начала работы."
        )
        return

    async with SessionLocal() as session:
        # Получаем делегированные задачи
        result = await session.execute(
            select(DelegatedTask)
            .where(DelegatedTask.assigned_by_user_id == user_id)
            .order_by(DelegatedTask.created_at.desc())
        )
        delegated_tasks = result.scalars().all()

        if not delegated_tasks:
            await message.answer(
                "Вы пока не делегировали задачи.\n\n"
                "Используйте /delegate для создания делегированной задачи."
            )
            return

        # Предзагружаем все задачи и пользователей батчами (fix N+1)
        task_ids = [dt.task_id for dt in delegated_tasks]
        user_ids = [dt.assigned_to_user_id for dt in delegated_tasks]

        # Загружаем задачи одним запросом
        tasks_result = await session.execute(select(Task).where(Task.id.in_(task_ids)))
        tasks_map = {task.id: task for task in tasks_result.scalars().all()}

        # Загружаем пользователей одним запросом
        users_result = await session.execute(select(User).where(User.user_id.in_(user_ids)))
        users_map = {user.user_id: user for user in users_result.scalars().all()}

        # Формируем список
        lines = []
        status_emoji = {
            "pending_acceptance": "⏳",
            "accepted": "✅",
            "rejected": "❌",
            "completed": "🎉",
            "overdue": "⚠️",
        }

        for dt in delegated_tasks:
            task = tasks_map.get(dt.task_id)
            assigned_to = users_map.get(dt.assigned_to_user_id)

            if not task or not assigned_to:
                continue

            emoji = status_emoji.get(dt.status, "")
            deadline_str = dt.deadline.strftime("%d.%m")

            lines.append(
                f"{emoji} <b>{task.title}</b>\n"
                f"   → {assigned_to.first_name} | {deadline_str} | {dt.status}"
            )

        text = "\n\n".join(lines)
        await message.answer(f"<b>Ваши делегированные задачи:</b>\n\n{text}")


@router.message(Command("assigned"))
async def cmd_assigned(message: Message):
    """Команда /assigned - показывает задачи, назначенные вам."""
    user_id = message.from_user.id

    user = await get_user(user_id)
    if not user or not user.lang:
        await message.answer(
            "Привет! Сначала нужно пройти настройку.\n\n" "Используй команду /start для начала работы."
        )
        return

    async with SessionLocal() as session:
        # Получаем назначенные задачи
        result = await session.execute(
            select(DelegatedTask)
            .where(
                DelegatedTask.assigned_to_user_id == user_id,
                DelegatedTask.status.in_(["pending_acceptance", "accepted"]),
            )
            .order_by(DelegatedTask.deadline)
        )
        delegated_tasks = result.scalars().all()

        if not delegated_tasks:
            await message.answer("У вас нет назначенных задач.")
            return

        # Предзагружаем все задачи и пользователей батчами (fix N+1)
        task_ids = [dt.task_id for dt in delegated_tasks]
        user_ids = [dt.assigned_by_user_id for dt in delegated_tasks]

        # Загружаем задачи одним запросом
        tasks_result = await session.execute(select(Task).where(Task.id.in_(task_ids)))
        tasks_map = {task.id: task for task in tasks_result.scalars().all()}

        # Загружаем пользователей одним запросом
        users_result = await session.execute(select(User).where(User.user_id.in_(user_ids)))
        users_map = {user.user_id: user for user in users_result.scalars().all()}

        # Формируем список
        lines = []
        status_emoji = {"pending_acceptance": "⏳", "accepted": "✅"}

        for dt in delegated_tasks:
            task = tasks_map.get(dt.task_id)
            assigned_by = users_map.get(dt.assigned_by_user_id)

            if not task or not assigned_by:
                continue

            emoji = status_emoji.get(dt.status, "")
            deadline_str = dt.deadline.strftime("%d.%m")

            # Показываем сколько осталось времени
            days_left = (dt.deadline.date() - dt_date.today()).days
            if days_left < 0:
                time_left = f"⚠️ Просрочено на {abs(days_left)} дн"
            elif days_left == 0:
                time_left = "🔥 Сегодня!"
            elif days_left == 1:
                time_left = "Завтра"
            else:
                time_left = f"{days_left} дн"

            lines.append(
                f"{emoji} <b>{task.title}</b>\n"
                f"   от {assigned_by.first_name} | {deadline_str} | {time_left}"
            )

        text = "\n\n".join(lines)

        builder = InlineKeyboardBuilder()
        for dt in delegated_tasks[:10]:  # Лимит 10 задач
            task = tasks_map.get(dt.task_id)
            if task:
                builder.button(text=f"✏️ {task.title[:15]}...", callback_data=f"DT_EDIT:{dt.id}")
        builder.adjust(1)

        await message.answer(
            f"<b>Назначенные вам задачи:</b>\n\n{text}",
            reply_markup=builder.as_markup() if delegated_tasks else None,
        )


@router.callback_query(F.data.startswith("DT_EDIT:"))
async def delegated_task_edit_callback(callback: CallbackQuery):
    """Показывает меню управления делегированной задачей."""
    user_id = callback.from_user.id
    delegated_task_id = int(callback.data.split(":")[1])

    async with SessionLocal() as session:
        delegated_task = await session.get(DelegatedTask, delegated_task_id)

        if not delegated_task or delegated_task.assigned_to_user_id != user_id:
            await callback.answer("Задача не найдена", show_alert=True)
            return

        task = await session.get(Task, delegated_task.task_id)
        assigned_by = await get_user(delegated_task.assigned_by_user_id)

        # Кнопки управления
        builder = InlineKeyboardBuilder()

        if delegated_task.status == "accepted":
            builder.button(text="✅ Выполнено", callback_data=f"DT_DONE:{delegated_task_id}")

        builder.button(text="« Назад", callback_data="back_to_menu")
        builder.adjust(1)

        days_left = (delegated_task.deadline.date() - dt_date.today()).days

        await callback.message.edit_text(
            f"📋 Задача от {assigned_by.first_name}:\n\n"
            f"<b>{task.title}</b>\n\n"
            f"⏰ Дедлайн: {delegated_task.deadline.strftime('%d.%m.%Y')}\n"
            f"📊 Статус: {delegated_task.status}\n"
            f"⏱ Осталось: {days_left} дн",
            reply_markup=builder.as_markup(),
        )

    await callback.answer()


@router.callback_query(F.data.startswith("DT_DONE:"))
async def delegated_task_done_callback(callback: CallbackQuery):
    """Отмечает делегированную задачу как выполненную."""
    user_id = callback.from_user.id
    delegated_task_id = int(callback.data.split(":")[1])

    async with SessionLocal() as session:
        delegated_task = await session.get(DelegatedTask, delegated_task_id)

        if not delegated_task or delegated_task.assigned_to_user_id != user_id:
            await callback.answer("Задача не найдена", show_alert=True)
            return

        # Обновляем статусы
        delegated_task.status = "completed"
        task = await session.get(Task, delegated_task.task_id)
        task.status = "done"
        await session.commit()

        # Уведомляем автора
        assigned_by = await get_user(delegated_task.assigned_by_user_id)

        try:
            await callback.bot.send_message(
                delegated_task.assigned_by_user_id,
                f"🎉 {callback.from_user.first_name} выполнил(а) задачу:\n\n«{task.title}»",
            )
        except Exception as e:
            logger.error(f"Failed to notify task author: {e}")

        logger.info(f"User {user_id} completed delegated task {delegated_task_id}")

        await callback.message.edit_text(
            f"📋 Задача от {assigned_by.first_name}:\n\n" f"«{task.title}»\n\n" "🎉 <b>Выполнено!</b>"
        )

    await callback.answer("🎉 Отлично! Задача выполнена!")
