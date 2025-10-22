"""Утилиты для работы с фразами, форматированием и прогресс-барами."""

import json
import random
from pathlib import Path
from typing import Any


def load_phrases(lang: str = "ru") -> dict[str, list[str]]:
    """Загружает фразы из JSON файла для указанного языка."""
    phrases_path = Path(__file__).parent.parent.parent / "locales" / f"phrases_{lang}.json"

    if not phrases_path.exists():
        # Fallback to Russian if language not found
        phrases_path = Path(__file__).parent.parent.parent / "locales" / "phrases_ru.json"

    with open(phrases_path, encoding="utf-8") as f:
        return json.load(f)


def get_phrase(key: str, lang: str = "ru", **kwargs: Any) -> str:
    """
    Получает случайную фразу по ключу и форматирует её с переданными параметрами.

    Args:
        key: Ключ фразы в JSON
        lang: Язык (по умолчанию 'ru')
        **kwargs: Параметры для форматирования (title, date, first_name и т.д.)

    Returns:
        Отформатированная фраза

    Example:
        >>> get_phrase("habit_done", title="Чтение", date="25.10.2025", emoji="🔥")
        "Отлично, зачёл «Чтение» за 25.10.2025 🔥"
    """
    phrases = load_phrases(lang)

    if key not in phrases:
        return f"[Missing phrase: {key}]"

    phrase_list = phrases[key]
    selected_phrase = random.choice(phrase_list)

    return selected_phrase.format(**kwargs)


def make_progress_bar(current: int, total: int, length: int = 5) -> str:
    """
    Создаёт текстовый прогресс-бар.

    Args:
        current: Текущее значение
        total: Максимальное значение
        length: Длина прогресс-бара (количество символов)

    Returns:
        Прогресс-бар в виде строки

    Example:
        >>> make_progress_bar(3, 5)
        "[■■■□□] 3/5"
        >>> make_progress_bar(4, 5, length=10)
        "[■■■■■■■■□□] 4/5"
    """
    if total == 0:
        filled = 0
    else:
        filled = int((current / total) * length)

    empty = length - filled

    bar = "■" * filled + "□" * empty

    return f"[{bar}] {current}/{total}"


def format_percent(value: float) -> str:
    """
    Форматирует процент, округляя до целого числа.

    Args:
        value: Значение в процентах (0-100)

    Returns:
        Отформатированная строка

    Example:
        >>> format_percent(87.5)
        "88%"
        >>> format_percent(100.0)
        "100%"
    """
    return f"{round(value)}%"


def format_date(date_obj, format_str: str = "DD.MM.YYYY") -> str:
    """
    Форматирует дату согласно спецификации.

    Args:
        date_obj: Объект datetime.date
        format_str: Формат ('DD.MM.YYYY' для текста, 'YYYYMMDD' для callback_data)

    Returns:
        Отформатированная дата

    Example:
        >>> from datetime import date
        >>> format_date(date(2025, 10, 25))
        "25.10.2025"
        >>> format_date(date(2025, 10, 25), "YYYYMMDD")
        "20251025"
    """
    if format_str == "DD.MM.YYYY":
        return date_obj.strftime("%d.%m.%Y")
    elif format_str == "YYYYMMDD":
        return date_obj.strftime("%Y%m%d")
    else:
        return str(date_obj)


def format_time(time_obj) -> str:
    """
    Форматирует время в формат HH:MM (24ч).

    Args:
        time_obj: Объект datetime.time

    Returns:
        Время в формате HH:MM

    Example:
        >>> from datetime import time
        >>> format_time(time(7, 30))
        "07:30"
    """
    return time_obj.strftime("%H:%M")


def calculate_percent(done: int, total: int) -> float:
    """
    Вычисляет процент выполнения.

    Args:
        done: Количество выполненных
        total: Общее количество

    Returns:
        Процент (0-100)
    """
    if total == 0:
        return 0.0
    return (done / total) * 100
