# src/utils/validators.py

import html
import re
from datetime import datetime, time


def escape_html(text: str) -> str:
    """
    Экранирует HTML специальные символы для безопасного отображения.

    Args:
        text: Исходный текст

    Returns:
        Текст с экранированными HTML символами
    """
    if not text:
        return ""
    return html.escape(text, quote=True)


def validate_time_format(time_str: str) -> tuple[bool, str | None]:
    """
    Проверяет формат времени HH:MM с подробной валидацией.

    Args:
        time_str: Строка времени для проверки

    Returns:
        Tuple (is_valid, error_message)
    """
    if not time_str:
        return False, "Время не может быть пустым"

    pattern = r"^([0-1]?[0-9]|2[0-3]):[0-5][0-9]$"
    if not re.match(pattern, time_str):
        return False, "Неверный формат. Используйте HH:MM (например, 08:00)"

    # Дополнительная проверка: парсим время
    try:
        parts = time_str.split(":")
        hour = int(parts[0])
        minute = int(parts[1])

        if not (0 <= hour <= 23):
            return False, "Часы должны быть от 0 до 23"

        if not (0 <= minute <= 59):
            return False, "Минуты должны быть от 0 до 59"

        return True, None

    except (ValueError, IndexError):
        return False, "Не удалось распарсить время"


def validate_time_sequence(
    audio_time: str, reading_time: str, questions_time: str
) -> tuple[bool, str | None]:
    """
    Проверяет логическую последовательность времен: audio < reading < questions.

    Args:
        audio_time: Время отправки аудио (HH:MM)
        reading_time: Время отправки текста (HH:MM)
        questions_time: Время отправки вопросов (HH:MM)

    Returns:
        Tuple (is_valid, error_message)
    """
    try:
        audio_t = datetime.strptime(audio_time, "%H:%M").time()
        reading_t = datetime.strptime(reading_time, "%H:%M").time()
        questions_t = datetime.strptime(questions_time, "%H:%M").time()

        # Проверяем последовательность
        if not (audio_t < reading_t < questions_t):
            return (
                False,
                "⚠️ Время должно идти по порядку:\n"
                "Аудио → Чтение → Вопросы\n\n"
                f"Текущие значения:\n"
                f"🎧 Аудио: {audio_time}\n"
                f"📖 Чтение: {reading_time}\n"
                f"❓ Вопросы: {questions_time}",
            )

        # Проверяем разумные интервалы (хотя бы 30 минут между этапами)
        def time_diff_minutes(t1: time, t2: time) -> int:
            """Разница между двумя временами в минутах"""
            dt1 = datetime.combine(datetime.today(), t1)
            dt2 = datetime.combine(datetime.today(), t2)
            return int((dt2 - dt1).total_seconds() / 60)

        audio_to_reading = time_diff_minutes(audio_t, reading_t)
        reading_to_questions = time_diff_minutes(reading_t, questions_t)

        if audio_to_reading < 30:
            return (
                False,
                f"⚠️ Между аудио и чтением должно быть минимум 30 минут.\n"
                f"Сейчас: {audio_to_reading} минут",
            )

        if reading_to_questions < 30:
            return (
                False,
                f"⚠️ Между чтением и вопросами должно быть минимум 30 минут.\n"
                f"Сейчас: {reading_to_questions} минут",
            )

        return True, None

    except ValueError:
        return False, "Ошибка парсинга времени"


def sanitize_text_input(text: str, max_length: int = 5000) -> str:
    """
    Очищает текстовый ввод пользователя от лишних символов.

    Args:
        text: Исходный текст
        max_length: Максимальная длина

    Returns:
        Очищенный текст
    """
    if not text:
        return ""

    # Убираем лишние пробелы
    text = text.strip()

    # Обрезаем до максимальной длины
    if len(text) > max_length:
        text = text[:max_length]

    return text


def validate_api_token(token: str) -> tuple[bool, str | None]:
    """
    Базовая валидация API токена.

    Args:
        token: API токен

    Returns:
        Tuple (is_valid, error_message)
    """
    if not token:
        return False, "Токен не может быть пустым"

    # Убираем пробелы
    token = token.strip()

    # Минимальная длина токена (обычно токены длиннее)
    if len(token) < 20:
        return False, "Токен слишком короткий. Убедитесь, что скопировали его полностью"

    # Проверяем, что токен не содержит подозрительных символов
    # (обычно токены - это hex, base64 или alphanumeric)
    if not re.match(r"^[A-Za-z0-9_\-\.=]+$", token):
        return (
            False,
            "Токен содержит недопустимые символы. " "Токены обычно содержат только буквы, цифры, и _-.",
        )

    return True, None
