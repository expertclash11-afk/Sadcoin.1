import asyncio
import html
import os

from aiogram import Bot, Dispatcher, F
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    MenuButtonWebApp,
    Message,
    WebAppInfo,
)
from aiohttp import web

import game
import server
from game import CASES, ITEMS, START_ENERGY, TASKS, GameError

TOKEN = os.getenv("BOT_TOKEN")
WEBAPP_URL = os.getenv("WEBAPP_URL") or os.getenv("RENDER_EXTERNAL_URL")
CHANNEL = os.getenv("CHANNEL")         
PORT = int(os.getenv("PORT", "8080"))


def kb(rows):
    out = []
    for r in rows:
        out.append([
            b if isinstance(b, InlineKeyboardButton) else InlineKeyboardButton(text=b[0], callback_data=b[1])
            for b in r
        ])
    return InlineKeyboardMarkup(inline_keyboard=out)


def main_menu():
    rows = []
    if WEBAPP_URL:
        rows.append([InlineKeyboardButton(text="🎮 Играть (Mini App)", web_app=WebAppInfo(url=WEBAPP_URL))])
    rows += [
        [("🐱 Тапать", "tap")],
        [("🎁 Кейсы", "cases"), ("🎒 Инвентарь", "inv")],
        [("📋 Задания", "tasks"), ("🔄 Обмен", "trade")],
        [("⬆️ Улучшения", "up"), ("🏆 Топ", "top")],
    ]
    return kb(rows)


def back():
    return kb([[("⬅️ Меню", "menu")]])


def main_text(u) -> str:
    return (
        f"🐱 <b>SadCat Coin</b>\n\n"
        f"💰 Баланс: <b>{u['coins']:,}</b> sadcoin\n"
        f"⚡ Энергия: {int(u['energy'])}/{START_ENERGY}\n"
        f"👆 За тап: +{u['tap_power']}\n"
        f"⏱ Пассивный доход: {u['passive']:,}/час\n"
        f"🆔 Твой ID: <code>{u['id']}</code>"
    )


def who(uid: int) -> str:
    row = game.db.execute("SELECT name, username FROM users WHERE id=?", (uid,)).fetchone()
    if not row:
        return str(uid)
    if row["username"]:
        return "@" + html.escape(row["username"])
    return html.escape(row["name"] or str(uid))


async def show(cb: CallbackQuery, text: str, markup):
    try:
        await cb.message.edit_text(text, reply_markup=markup, parse_mode="HTML")
    except TelegramBadRequest:
        pass


def ident(obj):
    return obj.from_user.id, obj.from_user.full_name, obj.from_user.username or ""


dp = Dispatcher()


@dp.message(CommandStart())
async def start(m: Message):
    args = (m.text or "").split(maxsplit=1)
    is_new = not game.user_exists(m.from_user.id)
    u = game.get_user(*ident(m))
    if is_new and len(args) > 1 and args[1].startswith("ref_"):
        try:
            ref = int(args[1][4:])
        except ValueError:
            ref = None
        if ref and game.register_referral(m.from_user.id, ref):
            try:
                await m.bot.send_message(
                    ref,
                    f"👥 По твоей ссылке зашёл друг! Он будет засчитан после "
                    f"{game.REF_MIN_TAPS} тапов. Смотри 📋 Задания.",
                )
            except Exception:
                pass
    await m.answer(main_text(u), reply_markup=main_menu(), parse_mode="HTML")


@dp.callback_query(F.data == "menu")
async def menu(cb: CallbackQuery):
    u = game.get_user(*ident(cb))
    await show(cb, main_text(u), main_menu())
    await cb.answer()


@dp.callback_query(F.data == "tap")
async def tap(cb: CallbackQuery):
    u = game.get_user(*ident(cb))
    if u["energy"] < 1:
        await cb.answer("😿 Кот устал, энергия восстанавливается", show_alert=False)
        return
    n = game.tap(u["id"], 1)
    if n == 0:
        await cb.answer()
        return
    u = game.get_user(u["id"])
    text = (
        f"😺 <b>Мяу!</b> +{u['tap_power']}\n\n"
        f"💰 {u['coins']:,} sadcoin\n⚡ {int(u['energy'])}/{START_ENERGY}"
    )
    await show(cb, text, kb([[("🐱 ТАП!", "tap")], [("⬅️ Меню", "menu")]]))
    await cb.answer()


@dp.callback_query(F.data == "cases")
async def cases(cb: CallbackQuery):
    u = game.get_user(*ident(cb))
    lines = [f"🎁 <b>Кейсы</b>\n💰 Баланс: {u['coins']:,}\n"]
    rows = []
    for key, (name, price, drops) in CASES.items():
        total = sum(drops.values())
        lines.append(f"{name} — {price:,}")
        for item, w in drops.items():
            iname, rarity, val = ITEMS[item]
            lines.append(f"   {iname} ({rarity}, {val:,}) — {w * 100 / total:.1f}%")
        rows.append([(f"Открыть {name} · {price:,}", f"open:{key}")])
    rows.append([("⬅️ Меню", "menu")])
    await show(cb, "\n".join(lines), kb(rows))
    await cb.answer()


@dp.callback_query(F.data.startswith("open:"))
async def open_case(cb: CallbackQuery):
    key = cb.data.split(":")[1]
    game.get_user(*ident(cb))
    try:
        item = game.open_case(cb.from_user.id, key)
    except GameError as e:
        await cb.answer(str(e), show_alert=True)
        return
    name, price, _ = CASES[key]
    iname, rarity, val = ITEMS[item]
    extra = "\n\n🌌🌌🌌 <b>МИФИЧЕСКАЯ НАХОДКА!</b> 🌌🌌🌌" if rarity == "Мифическая" else ""
    text = (
        f"🎉 Из {name} выпало:\n\n<b>{iname}</b>\n"
        f"Редкость: {rarity}\nЦена продажи: {val:,} sadcoin{extra}"
    )
    await show(cb, text, kb([[(f"Ещё раз · {price:,}", f"open:{key}")],
                             [("🎒 Инвентарь", "inv"), ("⬅️ Кейсы", "cases")]]))
    await cb.answer()


@dp.callback_query(F.data == "inv")
async def inventory(cb: CallbackQuery):
    items = game.inv_get(cb.from_user.id)
    if not items:
        await show(cb, "🎒 Инвентарь пуст. Открой кейс!", kb([[("🎁 Кейсы", "cases")], [("⬅️ Меню", "menu")]]))
        await cb.answer()
        return
    lines = ["🎒 <b>Инвентарь</b>\n"]
    rows = []
    for r in items:
        iname, rarity, val = ITEMS[r["item"]]
        lines.append(f"{iname} ×{r['qty']} — {val:,} за шт. ({rarity})")
        rows.append([(f"Продать {iname} за {val:,}", f"sell:{r['item']}")])
    rows.append([("💸 Продать всё", "sellall"), ("🔄 Обмен", "trade")])
    rows.append([("⬅️ Меню", "menu")])
    await show(cb, "\n".join(lines), kb(rows))
    await cb.answer()


@dp.callback_query(F.data.startswith("sell:"))
async def sell(cb: CallbackQuery):
    try:
        val = game.sell(cb.from_user.id, cb.data.split(":")[1])
    except GameError as e:
        await cb.answer(str(e))
        return
    await cb.answer(f"Продано за {val:,} 💰")
    await inventory(cb)


@dp.callback_query(F.data == "sellall")
async def sell_all(cb: CallbackQuery):
    total = game.sell_all(cb.from_user.id)
    await cb.answer(f"Продано всё за {total:,} 💰", show_alert=True)
    await inventory(cb)


@dp.callback_query(F.data == "up")
async def upgrades(cb: CallbackQuery):
    u = game.get_user(*ident(cb))
    tc, pc = game.tap_upgrade_cost(u), game.passive_upgrade_cost(u)
    text = (
        f"⬆️ <b>Улучшения</b>\n💰 {u['coins']:,}\n\n"
        f"👆 Сила тапа: {u['tap_power']} → {u['tap_power'] + 1}\n   Цена: {tc:,}\n\n"
        f"⏱ Пассивный доход: {u['passive']}/час → {u['passive'] + 100}/час\n   Цена: {pc:,}"
    )
    await show(cb, text, kb([
        [(f"👆 Сила тапа · {tc:,}", "buy:tap")],
        [(f"⏱ Доход/час · {pc:,}", "buy:pass")],
        [("⬅️ Меню", "menu")],
    ]))
    await cb.answer()


@dp.callback_query(F.data.startswith("buy:"))
async def buy(cb: CallbackQuery):
    try:
        game.buy_upgrade(cb.from_user.id, cb.data.split(":")[1])
    except GameError as e:
        await cb.answer(str(e), show_alert=True)
        return
    await cb.answer("Улучшено! ✅")
    await upgrades(cb)


async def tasks_view(cb: CallbackQuery):
    u = game.get_user(*ident(cb))
    me = await cb.bot.me()
    link = f"https://t.me/{me.username}?start=ref_{u['id']}"
    done = game.done_tasks(u["id"])
    total, ok = game.ref_counts(u["id"])
    lines = [
        "📋 <b>Задания</b>\n",
        f"🔗 Твоя ссылка для друзей:\n{link}",
        f"Приглашено: {total}, засчитано: {ok}\n"
        f"<i>Друг засчитывается, когда сделает {game.REF_MIN_TAPS} тапов.</i>\n",
    ]
    rows = []

    left = game.daily_left(u)
    if left <= 0:
        rows.append([(f"🎁 Ежедневный бонус +{game.DAILY_REWARD:,}", "daily")])
    else:
        lines.append(f"🎁 Ежедневный бонус через {int(left // 3600)}ч {int(left % 3600 // 60)}м\n")

    for key, (title, kind, goal, reward) in TASKS.items():
        p = game.task_progress(u, kind)
        if key in done:
            lines.append(f"✅ {title} — выполнено")
        else:
            lines.append(f"▫️ {title}: {min(p, goal):,}/{goal:,} → +{reward:,}")
            if p >= goal:
                rows.append([(f"Забрать +{reward:,} · {title}", f"claim:{key}")])

    if CHANNEL and "channel" not in done:
        lines.append(f"📢 Подпишись на {CHANNEL} → +{game.CHANNEL_REWARD:,}")
        rows.append([("📢 Проверить подписку", "claim_channel")])

    rows.append([("⬅️ Меню", "menu")])
    await show(cb, "\n".join(lines), kb(rows))


@dp.callback_query(F.data == "tasks")
async def tasks(cb: CallbackQuery):
    await tasks_view(cb)
    await cb.answer()


@dp.callback_query(F.data.startswith("claim:"))
async def claim(cb: CallbackQuery):
    try:
        reward = game.claim_task(cb.from_user.id, cb.data.split(":")[1])
        await cb.answer(f"+{reward:,} sadcoin! 🎉", show_alert=True)
    except GameError as e:
        await cb.answer(str(e), show_alert=True)
    await tasks_view(cb)


@dp.callback_query(F.data == "daily")
async def daily(cb: CallbackQuery):
    try:
        reward = game.claim_daily(cb.from_user.id)
        await cb.answer(f"+{reward:,} sadcoin! 🎁", show_alert=True)
    except GameError as e:
        await cb.answer(str(e), show_alert=True)
    await tasks_view(cb)


@dp.callback_query(F.data == "claim_channel")
async def claim_channel(cb: CallbackQuery):
    if not CHANNEL:
        await cb.answer()
        return
    try:
        member = await cb.bot.get_chat_member(CHANNEL, cb.from_user.id)
        ok = member.status in ("member", "administrator", "creator")
    except Exception:
        ok = False
    if not ok:
        await cb.answer("Подписка не найдена 😿", show_alert=True)
        return
    if game.give_task_reward(cb.from_user.id, "channel", game.CHANNEL_REWARD):
        await cb.answer(f"+{game.CHANNEL_REWARD:,} sadcoin! 🎉", show_alert=True)
    await tasks_view(cb)


class Trade(StatesGroup):
    target = State()
    amount = State()


def trade_text(t) -> str:
    give = ITEMS[t["give_item"]][0]
    ask = ITEMS[t["ask_item"]][0] if t["ask_item"] else f"{t['ask_coins']:,} sadcoin"
    return (
        f"🔄 <b>Предложение обмена</b> #{t['id']}\n"
        f"От: {who(t['from_id'])}\nОтдаёт: {give}\nХочет взамен: {ask}\n"
        f"<i>Действует 1 час</i>"
    )


def trade_buttons(trade_id: int):
    return [(f"✅ Принять #{trade_id}", f"tracc:{trade_id}"), (f"❌ Отклонить #{trade_id}", f"trdec:{trade_id}")]


CANCEL_KB = kb([[("❌ Отмена", "trcancel")]])


@dp.callback_query(F.data == "trade")
async def trade_menu(cb: CallbackQuery):
    text = (
        "🔄 <b>Обмен между игроками</b>\n\n"
        "Предложи другому игроку предмет в обмен на монеты или на другой предмет.\n"
        f"Обмен открывается после {game.TRADE_MIN_TAPS} тапов. Лимит — {game.TRADE_DAILY_LIMIT} предложений в сутки."
    )
    await show(cb, text, kb([[("📤 Предложить обмен", "trnew")], [("📥 Входящие", "trin")], [("⬅️ Меню", "menu")]]))
    await cb.answer()


@dp.callback_query(F.data == "trnew")
async def trade_new(cb: CallbackQuery, state: FSMContext):
    u = game.get_user(*ident(cb))
    if u["taps"] < game.TRADE_MIN_TAPS:
        await cb.answer(f"Обмен откроется после {game.TRADE_MIN_TAPS} тапов (сейчас {u['taps']})", show_alert=True)
        return
    if not game.inv_get(u["id"]):
        await cb.answer("У тебя нет предметов. Открой кейс!", show_alert=True)
        return
    await state.clear()
    await state.set_state(Trade.target)
    await show(cb, "Отправь @username или ID игрока, с которым хочешь обменяться.\n"
                   "Игрок должен уже играть в боте.", CANCEL_KB)
    await cb.answer()


@dp.callback_query(F.data == "trcancel")
async def trade_cancel(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await menu(cb)


@dp.message(Trade.target)
async def trade_target(m: Message, state: FSMContext):
    target = game.find_user(m.text or "")
    if not target or target["id"] == m.from_user.id:
        await m.answer("Не нашёл такого игрока (или это ты). Попробуй ещё раз.", reply_markup=CANCEL_KB)
        return
    items = game.inv_get(m.from_user.id)
    if not items:
        await state.clear()
        await m.answer("У тебя нет предметов для обмена.", reply_markup=main_menu())
        return
    await state.update_data(target=target["id"])
    await state.set_state(None)
    rows = [[(f"{ITEMS[r['item']][0]} ×{r['qty']}", f"trg:{r['item']}")] for r in items]
    rows.append([("❌ Отмена", "trcancel")])
    await m.answer(f"Обмен с {who(target['id'])}.\nЧто отдаёшь?", reply_markup=kb(rows), parse_mode="HTML")


@dp.callback_query(F.data.startswith("trg:"))
async def trade_give(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    if "target" not in data:
        await cb.answer("Сессия обмена устарела, начни заново", show_alert=True)
        return
    item = cb.data.split(":")[1]
    if item not in ITEMS:
        await cb.answer()
        return
    await state.update_data(give=item)
    await show(cb, f"Отдаёшь: {ITEMS[item][0]}\nЧто хочешь взамен?",
               kb([[("💰 Монеты", "trc"), ("🎒 Предмет", "tri")], [("❌ Отмена", "trcancel")]]))
    await cb.answer()


@dp.callback_query(F.data == "trc")
async def trade_coins(cb: CallbackQuery, state: FSMContext):
    await state.set_state(Trade.amount)
    await show(cb, "Сколько sadcoin хочешь получить? Отправь число.", CANCEL_KB)
    await cb.answer()


@dp.callback_query(F.data == "tri")
async def trade_item_pick(cb: CallbackQuery):
    rows = [[(name, f"trw:{key}")] for key, (name, _, _) in ITEMS.items()]
    rows.append([("❌ Отмена", "trcancel")])
    await show(cb, "Какой предмет хочешь получить?", kb(rows))
    await cb.answer()


async def send_offer(bot: Bot, from_id: int, state: FSMContext, ask_item=None, ask_coins=0):
    data = await state.get_data()
    if "target" not in data or "give" not in data:
        return "Сессия обмена устарела, начни заново."
    try:
        tid = game.create_trade(from_id, data["target"], data["give"], ask_item, ask_coins)
    except GameError as e:
        return f"❌ {e}"
    await state.clear()
    t = game.get_trade(tid)
    try:
        await bot.send_message(t["to_id"], trade_text(t), reply_markup=kb([trade_buttons(tid)]), parse_mode="HTML")
    except Exception:
        game.decline_trade(tid, from_id)
        return "Не удалось отправить предложение (игрок мог заблокировать бота)."
    return f"✅ Предложение #{tid} отправлено игроку {who(t['to_id'])}. Он получит его в чате."


@dp.message(Trade.amount)
async def trade_amount(m: Message, state: FSMContext):
    raw = (m.text or "").replace(" ", "").replace(",", "").replace("_", "")
    if not raw.isdigit() or int(raw) <= 0:
        await m.answer("Нужно положительное число, например 5000.", reply_markup=CANCEL_KB)
        return
    msg = await send_offer(m.bot, m.from_user.id, state, ask_coins=int(raw))
    await m.answer(msg, reply_markup=main_menu(), parse_mode="HTML")


@dp.callback_query(F.data.startswith("trw:"))
async def trade_want_item(cb: CallbackQuery, state: FSMContext):
    key = cb.data.split(":")[1]
    if key not in ITEMS:
        await cb.answer()
        return
    msg = await send_offer(cb.bot, cb.from_user.id, state, ask_item=key)
    await show(cb, msg, back())
    await cb.answer()


@dp.callback_query(F.data.startswith("tracc:"))
async def trade_accept(cb: CallbackQuery):
    try:
        t = game.accept_trade(int(cb.data.split(":")[1]), cb.from_user.id)
    except GameError as e:
        await cb.answer(str(e), show_alert=True)
        return
    await show(cb, "✅ Обмен завершён!\n\n" + trade_text(t), back())
    await cb.answer("Готово! 🎉")
    try:
        await cb.bot.send_message(t["from_id"], f"✅ Игрок {who(t['to_id'])} принял твой обмен #{t['id']}!",
                                  parse_mode="HTML")
    except Exception:
        pass


@dp.callback_query(F.data.startswith("trdec:"))
async def trade_decline(cb: CallbackQuery):
    try:
        t = game.decline_trade(int(cb.data.split(":")[1]), cb.from_user.id)
    except GameError as e:
        await cb.answer(str(e), show_alert=True)
        return
    await show(cb, f"❌ Обмен #{t['id']} отклонён.", back())
    await cb.answer()
    try:
        await cb.bot.send_message(t["from_id"], f"❌ Игрок {who(t['to_id'])} отклонил обмен #{t['id']}.",
                                  parse_mode="HTML")
    except Exception:
        pass


@dp.callback_query(F.data == "trin")
async def trade_incoming(cb: CallbackQuery):
    offers = game.incoming_trades(cb.from_user.id)
    if not offers:
        await show(cb, "📥 Входящих предложений нет.", kb([[("⬅️ Обмен", "trade")]]))
        await cb.answer()
        return
    lines = ["📥 <b>Входящие предложения</b>\n"]
    rows = []
    for t in offers:
        ask = ITEMS[t["ask_item"]][0] if t["ask_item"] else f"{t['ask_coins']:,} sadcoin"
        lines.append(f"#{t['id']} от {who(t['from_id'])}: {ITEMS[t['give_item']][0]} ⇄ {ask}")
        rows.append(trade_buttons(t["id"]))
    rows.append([("⬅️ Обмен", "trade")])
    await show(cb, "\n".join(lines), kb(rows))
    await cb.answer()


@dp.callback_query(F.data == "top")
async def top(cb: CallbackQuery):
    lines = ["🏆 <b>Топ-10</b>\n"]
    for i, r in enumerate(game.top_users(10), 1):
        lines.append(f"{i}. {html.escape(r['name'] or 'Аноним')} — {r['coins']:,}")
    await show(cb, "\n".join(lines), back())
    await cb.answer()


async def main():
    if not TOKEN:
        raise SystemExit("Задай токен: export BOT_TOKEN=... (получи у @BotFather)")
    bot = Bot(TOKEN)
    me = await bot.me()

    runner = web.AppRunner(server.create_app(TOKEN, me.username))
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()
    print(f"Mini App слушает порт {PORT}")

    if WEBAPP_URL:
        try:
            await bot.set_chat_menu_button(
                menu_button=MenuButtonWebApp(text="🎮 Играть", web_app=WebAppInfo(url=WEBAPP_URL))
            )
        except Exception as e:
            print("Не удалось поставить кнопку меню:", e)
    else:
        print("WEBAPP_URL не задан — кнопка Mini App в боте скрыта (см. README)")

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
      
