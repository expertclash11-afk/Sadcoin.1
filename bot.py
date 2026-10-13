import asyncio, logging, os, time
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, CommandObject
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter
import game as g

TOKEN = os.getenv("BOT_TOKEN", "")
dp = Dispatcher()
BOT_USERNAME = ""


def n(x):
    return f"{int(x):,}".replace(",", " ")


def kb(*rows):
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=t, callback_data=d) for t, d in r] for r in rows])


BACK = [("⬅️ Меню", "m")]


def bar(v, mx, w=10):
    f = int(w * v / mx) if mx else 0
    return "▰" * f + "▱" * (w - f)


# ---------- screens ----------
def s_menu(u):
    t = (f"😿 <b>SadCoin</b>\n\n💰 Монеты: <b>{n(u['coins'])}</b>\n"
         f"⚡ Энергия: {n(u['energy'])}/{n(u['max_energy'])}\n"
         f"👆 За тап: {u['tap_power']} | ⛏ В час: {n(u['passive'])}")
    return t, kb([("🐱 ТАПАТЬ", "t")],
                 [("🚀 Улучшения", "up"), ("📦 Кейсы", "cs")],
                 [("🎒 Инвентарь", "inv"), ("📋 Задания", "tk")],
                 [("🎁 Бонус", "dl"), ("👥 Друзья", "fr")],
                 [("🏆 Топ", "top"), ("👤 Профиль", "pr")])


def s_tap(u):
    t = (f"💰 <b>{n(u['coins'])}</b>\n⚡ {bar(u['energy'], u['max_energy'])} {n(u['energy'])}/{n(u['max_energy'])}\n"
         f"👆 +{u['tap_power']} за тап")
    return t, kb([("🐱 ТАП!", "t")], BACK)


def s_up(u):
    tc, pc = g.tap_upgrade_cost(u), g.passive_upgrade_cost(u)
    t = (f"🚀 <b>Улучшения</b>\n💰 {n(u['coins'])}\n\n"
         f"👆 Сила тапа: {u['tap_power']} → {u['tap_power'] + 1}\nЦена: {n(tc)}\n\n"
         f"⛏ Пассивный доход: {n(u['passive'])}/ч → {n(u['passive'] + 100)}/ч\nЦена: {n(pc)}")
    return t, kb([(f"👆 +1 тап ({n(tc)})", "ub:tap")], [(f"⛏ +100/ч ({n(pc)})", "ub:pass")], BACK)


def s_cases(u):
    t = f"📦 <b>Кейсы</b>\n💰 {n(u['coins'])}\n\n"
    rows = []
    for k, (name, price, drops) in g.CASES.items():
        tot = sum(drops.values())
        t += f"{name} — {n(price)}\n" + "".join(
            f"   {g.ITEMS[i][0]} {w / tot * 100:.1f}%\n" for i, w in drops.items()) + "\n"
        rows.append([(f"{name} ({n(price)})", f"co:{k}")])
    return t, kb(*rows, BACK)


def s_inv(uid):
    items = g.inv_get(uid)
    if not items:
        return "🎒 Инвентарь пуст. Открой кейс!", kb([("📦 Кейсы", "cs")], BACK)
    t, rows, total = "🎒 <b>Инвентарь</b>\n\n", [], 0
    for r in items:
        nm, rar, pr = g.ITEMS[r["item"]]
        total += pr * r["qty"]
        t += f"{nm} ×{r['qty']} ({rar}) — {n(pr)}\n"
        rows.append([(f"Продать {nm} ({n(pr)})", f"s:{r['item']}")])
    rows.append([(f"💸 Продать всё ({n(total)})", "sa")])
    return t, kb(*rows, BACK)


def s_tasks(u):
    done = g.done_tasks(u["id"])
    t, rows = "📋 <b>Задания</b>\n\n", []
    for k, (name, kind, goal, rew) in g.TASKS.items():
        p = min(g.task_progress(u, kind), goal)
        if k in done:
            t += f"✅ {name}\n"
        else:
            t += f"▫️ {name}: {n(p)}/{n(goal)} → 💰{n(rew)}\n"
            if p >= goal:
                rows.append([(f"🎁 Забрать: {name}", f"tc:{k}")])
    return t, kb(*rows, BACK)


def s_daily(u):
    left = g.daily_left(u)
    if left > 0:
        h, m = int(left // 3600), int(left % 3600 // 60)
        return f"🎁 Бонус будет через {h}ч {m}м", kb(BACK)
    return f"🎁 Ежедневный бонус: <b>{n(g.DAILY_REWARD)}</b> монет!", kb([("Забрать", "dc")], BACK)


def s_friends(u):
    tot, paid = g.ref_counts(u["id"])
    link = f"https://t.me/{BOT_USERNAME}?start=ref_{u['id']}"
    t = (f"👥 <b>Друзья</b>\n\nПриглашено: {tot} (активных: {paid})\n"
         f"За каждого, кто сделал {g.REF_MIN_TAPS} тапов: 💰{n(g.REF_REWARD)}\n\n🔗 Твоя ссылка:\n{link}")
    return t, kb(BACK)


def s_top():
    rows = g.top_users(10)
    medals = ["🥇", "🥈", "🥉"]
    t = "🏆 <b>Топ-10</b>\n\n" + "\n".join(
        f"{medals[i] if i < 3 else str(i + 1) + '.'} {r['name']} — {n(r['coins'])}" for i, r in enumerate(rows))
    return t, kb(BACK)


def s_profile(u):
    tot, paid = g.ref_counts(u["id"])
    t = (f"👤 <b>{u['name']}</b>\n\n💰 {n(u['coins'])}\n👆 Тапов: {n(u['taps'])}\n"
         f"📦 Кейсов: {u['cases_opened']}\n👥 Друзей: {tot}\n⛏ В час: {n(u['passive'])}")
    return t, kb(BACK)


# ---------- handlers ----------
async def show(c: CallbackQuery, scr):
    text, markup = scr
    try:
        await c.message.edit_text(text, reply_markup=markup, parse_mode="HTML", disable_web_page_preview=True)
    except TelegramBadRequest:
        pass
    except TelegramRetryAfter:
        pass


@dp.message(CommandStart())
async def start(m: Message, command: CommandObject):
    uid = m.from_user.id
    is_new = not g.user_exists(uid)
    if is_new and command.args and command.args.startswith("ref_"):
        try:
            g.register_referral(uid, int(command.args[4:]))
        except ValueError:
            pass
    u = g.get_user(uid, m.from_user.full_name, m.from_user.username)
    t, k = s_menu(u)
    await m.answer("Добро пожаловать в SadCoin! 😿\n\n" + t, reply_markup=k, parse_mode="HTML")


@dp.callback_query()
async def cb(c: CallbackQuery):
    uid, d = c.from_user.id, c.data
    u = g.get_user(uid, c.from_user.full_name, c.from_user.username)
    try:
        if d == "m":
            await show(c, s_menu(u))
        elif d == "t":
            if g.tap(uid) == 0 and u["energy"] < 1:
                await c.answer("⚡ Нет энергии, подожди", show_alert=False)
                return
            await show(c, s_tap(g.get_user(uid)))
        elif d == "up":
            await show(c, s_up(u))
        elif d.startswith("ub:"):
            kind = d[3:]
            cost = g.tap_upgrade_cost(u) if kind == "tap" else g.passive_upgrade_cost(u)
            if u["coins"] < cost:
                raise g.GameError("Недостаточно монет")
            g.buy_upgrade(uid, kind)
            await c.answer("✅ Улучшено!")
            await show(c, s_up(g.get_user(uid)))
            return
        elif d == "cs":
            await show(c, s_cases(u))
        elif d.startswith("co:"):
            key = d[3:]
            item = g.open_case(uid, key)
            nm, rar, pr = g.ITEMS[item]
            u = g.get_user(uid)
            t = f"🎉 Выпало: <b>{nm}</b>\nРедкость: {rar}\nЦена: {n(pr)}\n\n💰 {n(u['coins'])}"
            await show(c, (t, kb([("🔁 Ещё раз", d)], [("🎒 Инвентарь", "inv")], BACK)))
        elif d == "inv":
            await show(c, s_inv(uid))
        elif d.startswith("s:"):
            v = g.sell(uid, d[2:])
            await c.answer(f"+{n(v)} 💰")
            await show(c, s_inv(uid))
            return
        elif d == "sa":
            v = g.sell_all(uid)
            await c.answer(f"+{n(v)} 💰")
            await show(c, s_inv(uid))
            return
        elif d == "tk":
            await show(c, s_tasks(u))
        elif d.startswith("tc:"):
            r = g.claim_task(uid, d[3:])
            await c.answer(f"🎁 +{n(r)}")
            await show(c, s_tasks(g.get_user(uid)))
            return
        elif d == "dl":
            await show(c, s_daily(u))
        elif d == "dc":
            r = g.claim_daily(uid)
            await c.answer(f"🎁 +{n(r)}")
            await show(c, s_daily(g.get_user(uid)))
            return
        elif d == "fr":
            await show(c, s_friends(u))
        elif d == "top":
            await show(c, s_top())
        elif d == "pr":
            await show(c, s_profile(u))
    except g.GameError as e:
        await c.answer(str(e), show_alert=True)
        return
    await c.answer()


async def main():
    global BOT_USERNAME
    logging.basicConfig(level=logging.INFO)
    if not TOKEN:
        raise SystemExit("Задай переменную окружения BOT_TOKEN")
    bot = Bot(TOKEN)
    BOT_USERNAME = (await bot.get_me()).username
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
                       
