import asyncio
import logging
import random
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder

# Укажи токен твоего бота, полученный у @BotFather
API_TOKEN = "YOUR_BOT_TOKEN_HERE"

bot = Bot(token=API_TOKEN)
dp = Dispatcher()

# База данных пользователей в памяти (user_id: balance)
# В будущем ее можно заменить на SQLite или PostgreSQL
user_balances = {}

def get_balance(user_id: int) -> int:
    """Получить баланс пользователя (если нет — даем стартовый бонус)"""
    if user_id not in user_balances:
        user_balances[user_id] = 1000  # Стартовый бонус: 1000 коинов
    return user_balances[user_id]

def update_balance(user_id: int, amount: int):
    """Изменить баланс пользователя"""
    user_balances[user_id] = get_balance(user_id) + amount

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    user_id = message.from_user.id
    balance = get_balance(user_id)
    
    builder = InlineKeyboardBuilder()
    builder.button(text="🎮 Играть в Апгрейд", callback_data="game_upgrade")
    builder.button(text="💰 Мой баланс", callback_data="balance")
    builder.adjust(1)
    
    await message.answer(
        f"👋 Привет! Добро пожаловать в игровой бот.\n\n"
        f"💳 Твой баланс: **{balance} коинов** 🪙\n\n"
        f"Выбери действие в меню ниже:",
        reply_markup=builder.as_markup(),
        parse_mode="Markdown"
    )

@dp.callback_query(F.data == "balance")
async def cb_balance(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    balance = get_balance(user_id)
    await callback.answer(f"Твой текущий баланс: {balance} коинов 🪙", show_alert=True)

@dp.callback_query(F.data == "game_upgrade")
async def cb_upgrade_menu(callback: types.CallbackQuery):
    builder = InlineKeyboardBuilder()
    builder.button(text="🟢 Риск 50% (Шанс x2)", callback_data="upgrade_50")
    builder.button(text="🟡 Риск 25% (Шанс x4)", callback_data="upgrade_25")
    builder.button(text="🔙 Назад в меню", callback_data="back_to_main")
    builder.adjust(1)
    
    await callback.message.edit_text(
        "📈 **ИГРА: АПГРЕЙД**\n\n"
        "Ставка фиксированная: **100 коинов** 🪙\n"
        "Выбери режим риска:",
        reply_markup=builder.as_markup(),
        parse_mode="Markdown"
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("upgrade_"))
async def cb_play_upgrade(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    balance = get_balance(user_id)
    bet = 100  # Фиксированная ставка

    if balance < bet:
        await callback.answer("❌ У тебя недостаточно коинов для ставки!", show_alert=True)
        return

    risk_type = callback.data.split("_")[1]
    
    if risk_type == "50":
        chance = 50
        multiplier = 2
    elif risk_type == "25":
        chance = 25
        multiplier = 4
    else:
        return

    # Списываем ставку
    update_balance(user_id, -bet)
    
    # Розыгрыш (рандом от 1 до 100)
    win = random.randint(1, 100) <= chance
    
    builder = InlineKeyboardBuilder()
    builder.button(text="🔄 Играть еще", callback_data="game_upgrade")
    builder.button(text="🔙 Назад в меню", callback_data="back_to_main")
    builder.adjust(1)

    if win:
        win_amount = bet * multiplier
        update_balance(user_id, win_amount)
        new_balance = get_balance(user_id)
        text = (
            f"🎉 **ПОБЕДА!**\n\n"
            f"Удача на твоей стороне!\n"
            f"Выигрыш: **+{win_amount} коинов** (x{multiplier})\n"
            f"💳 Баланс: **{new_balance} коинов** 🪙"
        )
    else:
        new_balance = get_balance(user_id)
        text = (
            f"😢 **ПРОИГРЫШ**\n\n"
            f"В этот раз не повезло.\n"
            f"Потеряно: **-{bet} коинов**\n"
            f"💳 Баланс: **{new_balance} коинов** 🪙"
        )

    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data == "back_to_main")
async def cb_back(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    balance = get_balance(user_id)
    
    builder = InlineKeyboardBuilder()
    builder.button(text="🎮 Играть в Апгрейд", callback_data="game_upgrade")
    builder.button(text="💰 Мой баланс", callback_data="balance")
    builder.adjust(1)
    
    await callback.message.edit_text(
        f"👋 Главное меню:\n\n"
        f"💳 Твой баланс: **{balance} коинов** 🪙",
        reply_markup=builder.as_markup(),
        parse_mode="Markdown"
    )
    await callback.answer()

async def main():
    logging.basicConfig(level=logging.INFO)
    print("Бот запущен и готов к работе...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
    
