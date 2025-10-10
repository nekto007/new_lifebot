from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

router = Router()


@router.message(Command("health"))
async def on_health(message: Message):
    await message.reply("OK")
