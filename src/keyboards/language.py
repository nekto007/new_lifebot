# src/keyboards/language.py


from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def get_books_keyboard(books: list[dict]) -> InlineKeyboardMarkup:
    """Клавиатура для выбора книги"""
    buttons = []

    for book in books[:10]:  # Показываем первые 10
        level_emoji = {
            "A1": "🟢",
            "A2": "🟢",
            "B1": "🟡",
            "B2": "🟡",
            "C1": "🔴",
            "C2": "🔴",
        }.get(book.get("level", ""), "📘")

        # Формируем текст кнопки без автора (автор будет в описании после выбора)
        title = book["title"]

        # Если название слишком длинное - умно сокращаем
        max_length = 40  # Максимальная длина для кнопки
        if len(title) > max_length:
            # Пытаемся обрезать по словам
            words = title.split()
            shortened = ""
            for word in words:
                if len(shortened + word) + 3 <= max_length:  # +3 для "..."
                    shortened += word + " "
                else:
                    break
            title = shortened.strip() + "..."

        button_text = f"{level_emoji} {title}"
        buttons.append([InlineKeyboardButton(text=button_text, callback_data=f"book:{book['id']}")])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_reading_keyboard() -> InlineKeyboardMarkup:
    """Основная клавиатура для чтения"""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📚 Выбрать книгу", callback_data="choose_book")],
            [InlineKeyboardButton(text="📊 Прогресс", callback_data="reading_progress")],
        ]
    )


def get_reading_actions_keyboard(show_back: bool = False) -> InlineKeyboardMarkup:
    """Клавиатура действий после чтения фрагмента"""
    buttons = []

    # Первый ряд - Назад и Далее (если есть назад)
    if show_back:
        buttons.append(
            [
                InlineKeyboardButton(text="◀️ Назад", callback_data="read:back"),
                InlineKeyboardButton(text="Далее ▶️", callback_data="read:continue"),
            ]
        )
    else:
        buttons.append([InlineKeyboardButton(text="▶️ Читать дальше", callback_data="read:continue")])

    # Второй ряд - Прогресс и Сменить книгу
    buttons.append(
        [
            InlineKeyboardButton(text="📊 Прогресс", callback_data="read:progress"),
            InlineKeyboardButton(text="📚 Сменить книгу", callback_data="choose_book"),
        ]
    )

    return InlineKeyboardMarkup(inline_keyboard=buttons)
