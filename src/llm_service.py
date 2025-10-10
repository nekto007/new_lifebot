# src/llm_service.py

import os
from datetime import datetime, timedelta

from config import logger
from db import HabitContent, HabitTemplate, SessionLocal
from sqlalchemy import select


class LLMService:
    """Сервис для работы с LLM API"""

    def __init__(self):
        self.api_key = os.getenv("OPENAI_API_KEY")
        self.model = os.getenv("LLM_MODEL", "gpt-3.5-turbo")
        self.use_llm = bool(self.api_key)

        if not self.use_llm:
            logger.warning("OPENAI_API_KEY not set - LLM features will use fallback content")

    async def generate_habit_content(
        self,
        habit_id: int,
        habit_title: str,
        template: HabitTemplate | None = None,
        custom_prompt: str | None = None,
    ) -> str:
        """
        Генерирует контент для привычки.

        Args:
            habit_id: ID привычки
            habit_title: Название привычки
            template: Шаблон привычки (если есть)
            custom_prompt: Кастомный промпт пользователя

        Returns:
            Сгенерированный текст контента
        """
        # Проверяем, есть ли свежий контент в кэше (не старше 7 дней)
        async with SessionLocal() as session:
            result = await session.execute(
                select(HabitContent)
                .where(HabitContent.habit_id == habit_id)
                .where(HabitContent.used_count < 5)  # Не показывали больше 5 раз
                .order_by(HabitContent.generated_at.desc())
            )
            cached = result.scalars().first()

            if cached:
                # Проверяем возраст контента
                age = datetime.now() - cached.generated_at
                if age < timedelta(days=7):
                    logger.info(f"Using cached content for habit {habit_id}, age: {age.days} days")
                    return cached.content

        # Нет кэша - генерируем новый контент
        if self.use_llm:
            content = await self._generate_with_llm(habit_title, template, custom_prompt)
        else:
            content = self._generate_fallback(habit_title, template)

        # Сохраняем в БД
        await self._save_content(habit_id, content)

        return content

    async def _generate_with_llm(
        self, habit_title: str, template: HabitTemplate | None, custom_prompt: str | None
    ) -> str:
        """Генерирует контент через LLM API"""
        try:
            import aiohttp

            # Формируем промпт
            if custom_prompt:
                system_prompt = custom_prompt
            elif template and template.default_prompt:
                system_prompt = template.default_prompt
            else:
                system_prompt = self._get_default_prompt(habit_title, template)

            user_message = f"Сгенерируй задание для привычки '{habit_title}'"

            # Вызываем OpenAI API
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }

            payload = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
                "max_completion_tokens": 5000,  # Increased for reasoning models like gpt-5-nano
            }

            import ssl

            # Создаём SSL контекст без проверки сертификатов (для разработки)
            ssl_context = ssl.create_default_context()
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE

            connector = aiohttp.TCPConnector(ssl=ssl_context)
            async with aiohttp.ClientSession(connector=connector) as session:
                async with session.post(
                    "https://api.openai.com/v1/chat/completions", headers=headers, json=payload
                ) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        logger.error(f"LLM API error: {response.status} - {error_text}")
                        return self._generate_fallback(habit_title, template)

                    data = await response.json()
                    logger.info(f"OpenAI API response: {data}")
                    content = data["choices"][0]["message"]["content"].strip()

                    if not content:
                        logger.warning(f"OpenAI returned empty content for '{habit_title}', using fallback")
                        return self._generate_fallback(habit_title, template)

                    logger.info(f"Generated LLM content for '{habit_title}': {content[:50]}...")
                    return content

        except Exception as e:
            logger.error(f"Error generating LLM content: {e}")
            return self._generate_fallback(habit_title, template)

    def _get_default_prompt(self, habit_title: str, template: HabitTemplate | None) -> str:
        """Возвращает дефолтный промпт в зависимости от категории"""
        if not template:
            return (
                "Ты - персональный тренер по привычкам. "
                "Создай короткое (1-3 строки), конкретное и выполнимое задание. "
                "Используй числа и будь конкретным. Пиши по-русски, без эмодзи."
            )

        prompts = {
            "fitness": (
                "Ты - фитнес-тренер. Создай короткую программу упражнений (2-4 упражнения). "
                "Укажи количество повторений или время. Задание должно занимать 5-15 минут. "
                "Форматируй как список: '10 приседаний\\n5 отжиманий\\n1 минута планки'. "
                "Пиши по-русски, без эмодзи."
            ),
            "reading": (
                "Ты - литературный консультант. Предложи что почитать или дай задание по чтению. "
                "Будь конкретным: укажи количество страниц или время. "
                "Пример: 'Прочитай 10 страниц книги' или 'Почитай 15 минут перед сном'. "
                "Пиши по-русски, без эмодзи."
            ),
            "meditation": (
                "Ты - инструктор по медитации. Предложи короткую практику медитации (3-10 минут). "
                "Опиши технику кратко и ясно. Пример: 'Посиди 5 минут в тишине, наблюдая за дыханием'. "
                "Пиши по-русски, без эмодзи."
            ),
            "health": (
                "Ты - консультант по здоровью. Создай простое задание для улучшения здоровья. "
                "Будь конкретным и измеримым. Пример: 'Выпей 2 стакана воды' или 'Прогуляйся 15 минут'. "
                "Пиши по-русски, без эмодзи."
            ),
        }

        return prompts.get(template.category, prompts["fitness"])

    def _generate_fallback(self, habit_title: str, template: HabitTemplate | None) -> str:
        """Генерирует простой fallback контент без LLM"""
        title_lower = habit_title.lower()

        # Базовые шаблоны для популярных привычек
        fallbacks = {
            "зарядка": [
                "10 приседаний\n5 отжиманий\n1 минута планка",
                "15 приседаний\n10 отжиманий\n30 секунд планка",
                "20 приседаний\n3 берпи\n1 минута растяжка",
            ],
            "чтение": [
                "Прочитай 10 страниц книги",
                "Почитай 15 минут перед сном",
                "Прочитай одну главу",
            ],
            "медитация": [
                "5 минут медитации с фокусом на дыхании",
                "3 минуты осознанного дыхания",
                "10 минут медитации в тишине",
            ],
            "вода": ["Выпей 2 стакана воды", "Выпей 500мл воды", "Выпей стакан воды прямо сейчас"],
        }

        # Ищем подходящий шаблон
        for keyword, templates in fallbacks.items():
            if keyword in title_lower:
                import random

                return random.choice(templates)

        # Дефолт
        return f"Выполни {habit_title}"

    async def _save_content(self, habit_id: int, content: str) -> None:
        """Сохраняет сгенерированный контент в БД"""
        async with SessionLocal() as session:
            habit_content = HabitContent(
                habit_id=habit_id, content=content, generated_at=datetime.now(), used_count=0
            )
            session.add(habit_content)
            await session.commit()
            logger.info(f"Saved new content for habit {habit_id}")

    async def mark_content_used(self, habit_id: int, content: str) -> None:
        """Отмечает, что контент был использован (показан пользователю)"""
        async with SessionLocal() as session:
            result = await session.execute(
                select(HabitContent)
                .where(HabitContent.habit_id == habit_id)
                .where(HabitContent.content == content)
                .order_by(HabitContent.generated_at.desc())
            )
            habit_content = result.scalars().first()

            if habit_content:
                habit_content.used_count += 1
                habit_content.last_used = datetime.now()
                await session.commit()
                logger.info(f"Marked content as for habit {habit_id}, count: {habit_content.used_count}")


# Инициализация глобального сервиса
llm_service = LLMService()


async def find_habit_template(habit_title: str) -> HabitTemplate | None:
    """
    Ищет шаблон привычки по названию.

    Args:
        habit_title: Название привычки от пользователя

    Returns:
        Найденный шаблон или None
    """
    async with SessionLocal() as session:
        # Получаем все шаблоны
        result = await session.execute(select(HabitTemplate))
        templates = result.scalars().all()

        title_lower = habit_title.lower()

        # Ищем совпадение по ключевым словам
        for template in templates:
            keywords = template.keywords.lower().split(",")
            for keyword in keywords:
                if keyword.strip() in title_lower:
                    logger.info(f"Found template '{template.name}' for habit '{habit_title}'")
                    return template

        return None
