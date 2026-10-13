import os, random, sqlite3, time

DB_PATH = os.getenv("DB_PATH", "game.db")
db = sqlite3.connect(DB_PATH, check_same_thread=False)
db.row_factory = sqlite3.Row
db.executescript("""
CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, name TEXT, username TEXT,
 coins INTEGER DEFAULT 0, energy REAL DEFAULT 500, tap_power INTEGER DEFAULT 1, passive INTEGER DEFAULT 0,
 taps INTEGER DEFAULT 0, cases_opened INTEGER DEFAULT 0, last_tap REAL DEFAULT 0, updated REAL, daily_at REAL DEFAULT 0);
CREATE TABLE IF NOT EXISTS inv(uid INTEGER, item TEXT, qty INTEGER, PRIMARY KEY(uid,item));
CREATE TABLE IF NOT EXISTS tasks_done(uid INTEGER, key TEXT, PRIMARY KEY(uid,key));
CREATE TABLE IF NOT EXISTS refs(new_id INTEGER PRIMARY KEY, ref_id INTEGER, paid INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS trades(id INTEGER PRIMARY KEY AUTOINCREMENT, from_id INTEGER, to_id INTEGER,
 give_item TEXT, ask_item TEXT, ask_coins INTEGER DEFAULT 0, status TEXT DEFAULT 'open', created REAL);
""")

START_ENERGY = 500
REGEN_PER_SEC = 1
REF_MIN_TAPS, REF_REWARD = 100, 5000
DAILY_REWARD, CHANNEL_REWARD = 2000, 10000
TRADE_MIN_TAPS, TRADE_DAILY_LIMIT, TRADE_TTL = 100, 10, 3600

# Предметы (включая мега-редкий космический предмет)
ITEMS = {
    "mouse": ("🐭 Игрушечная мышь", "Обычная", 150),
    "fish": ("🐟 Грустная рыбка", "Обычная", 400),
    "yarn": ("🧶 Клубок печали", "Редкая", 1500),
    "potion": ("🧪 Зелье Мяу-эликсира", "Редкая", 3500),
    "crown": ("👑 Корона кота", "Эпическая", 8000),
    "sword": ("⚔️ Меч СадКата", "Эпическая", 18000),
    "star": ("🌟 Звезда SadCat", "Мифическая", 50000),
    "blackhole": ("🪐 Черная дыра SadCat", "МЕГА-ЛЕГЕНДАРНАЯ", 500000),
}

# Кейсы сбалансированы под новые предметы
CASES = {
    "basic": ("📦 Обычный кейс", 500, {"mouse": 600, "fish": 320, "yarn": 70, "crown": 10}),
    "premium": ("💎 Премиум кейс", 5000, {"fish": 450, "yarn": 300, "potion": 150, "crown": 80, "star": 20}),
    "epic": ("🔮 Эпический кейс", 25000, {"potion": 300, "crown": 350, "sword": 250, "star": 95, "blackhole": 5}),
    "legendary": ("👑 Легендарный кейс", 100000, {"sword": 400, "star": 450, "blackhole": 150}),
}

TASKS = {
    "taps100": ("Сделай 100 тапов", "taps", 100, 1000),
    "taps5000": ("Сделай 5 000 тапов", "taps", 5000, 10000),
    "cases5": ("Открой 5 кейсов", "cases", 5, 3000),
    "friends3": ("Пригласи 3 друзей", "refs", 3, 25000),
}


class GameError(Exception):
    pass


def user_exists(uid):
    return db.execute("SELECT 1 FROM users WHERE id=?", (uid,)).fetchone() is not None


def get_user(uid, name=None, username=None):
    now = time.time()
    r = db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if not r:
        db.execute("INSERT INTO users(id,name,username,energy,updated) VALUES(?,?,?,?,?)",
                   (uid, name or str(uid), username or "", START_ENERGY, now))
        db.commit()
        r = db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    dt = now - r["updated"]
    energy = min(START_ENERGY, r["energy"] + dt * REGEN_PER_SEC)
    gained, upd = 0, now
    if r["passive"] > 0:
        gained = int(r["passive"] * min(dt, 43200) / 3600)
        if gained and dt <= 43200:
            upd = r["updated"] + gained * 3600 / r["passive"]
    db.execute("UPDATE users SET energy=?, coins=coins+?, updated=?, name=COALESCE(?,name), username=COALESCE(?,username) WHERE id=?",
               (energy, gained, upd, name, username, uid))
    db.commit()
    return dict(db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone())


def _coins(uid, delta):
    db.execute("UPDATE users SET coins=coins+? WHERE id=?", (delta, uid))


def _inv_add(uid, item, n=1):
    db.execute("INSERT INTO inv(uid,item,qty) VALUES(?,?,?) ON CONFLICT(uid,item) DO UPDATE SET qty=qty+?",
               (uid, item, n, n))


def _inv_take(uid, item, n=1):
    r = db.execute("SELECT qty FROM inv WHERE uid=? AND item=?", (uid, item)).fetchone()
    if not r or r["qty"] < n:
        raise GameError("Нет такого предмета")
    db.execute("UPDATE inv SET qty=qty-? WHERE uid=? AND item=?", (n, uid, item))
    db.execute("DELETE FROM inv WHERE qty<=0")


def inv_get(uid):
    return db.execute("SELECT item, qty FROM inv WHERE uid=? AND qty>0 ORDER BY item", (uid,)).fetchall()


def tap(uid, n=1):
    u = get_user(uid)
    now = time.time()
    dt = now - u["last_tap"]
    if dt < 0.08:
        return 0
    cnt = max(0, min(int(n), int(u["energy"]), int(dt * 12) + 1))
    if cnt == 0:
        return 0
    db.execute("UPDATE users SET coins=coins+?, energy=energy-?, taps=taps+?, last_tap=? WHERE id=?",
               (cnt * u["tap_power"], cnt, cnt, now, uid))
    if u["taps"] + cnt >= REF_MIN_TAPS:
        r = db.execute("SELECT ref_id FROM refs WHERE new_id=? AND paid=0", (uid,)).fetchone()
        if r:
            db.execute("UPDATE refs SET paid=1 WHERE new_id=?", (uid,))
            _coins(r["ref_id"], REF_REWARD)
    db.commit()
    return cnt


def tap_upgrade_cost(u):
    return int(200 * 1.8 ** (u["tap_power"] - 1))


def passive_upgrade_cost(u):
    return int(1000 * 1.6 ** (u["passive"] // 100))


def buy_upgrade(uid, kind):
    u = get_user(uid)
    cost = tap_upgrade_cost(u) if kind == "tap" else passive_upgrade_cost(u)
    if kind not in ("tap", "pass"):
        raise GameError("Неизвестное улучшение")
    if u["coins"] < cost:
        raise GameError("Не хватает sadcoin")
    col, inc = ("tap_power", 1) if kind == "tap" else ("passive", 100)
    db.execute(f"UPDATE users SET coins=coins-?, {col}={col}+? WHERE id=?", (cost, inc, uid))
    db.commit()


def open_case(uid, key):
    if key not in CASES:
        raise GameError("Нет такого кейса")
    _, price, drops = CASES[key]
    u = get_user(uid)
    if u["coins"] < price:
        raise GameError("Не хватает sadcoin")
    item = random.choices(list(drops), weights=list(drops.values()))[0]
    _coins(uid, -price)
    _inv_add(uid, item)
    db.execute("UPDATE users SET cases_opened=cases_opened+1 WHERE id=?", (uid,))
    db.commit()
    return item


def sell(uid, item):
    if item not in ITEMS:
        raise GameError("Нет такого предмета")
    _inv_take(uid, item)
    val = ITEMS[item][2]
    _coins(uid, val)
    db.commit()
    return val


def sell_all(uid):
    total = sum(ITEMS[r["item"]][2] * r["qty"] for r in inv_get(uid))
    db.execute("DELETE FROM inv WHERE uid=?", (uid,))
    _coins(uid, total)
    db.commit()
    return total


def register_referral(new_id, ref_id):
    if new_id == ref_id or not user_exists(ref_id):
        return False
    cur = db.execute("INSERT OR IGNORE INTO refs(new_id,ref_id) VALUES(?,?)", (new_id, ref_id))
    db.commit()
    return cur.rowcount > 0


def ref_counts(uid):
    r = db.execute("SELECT COUNT(*) t, COALESCE(SUM(paid),0) p FROM refs WHERE ref_id=?", (uid,)).fetchone()
    return r["t"], r["p"]


def done_tasks(uid):
    return {r["key"] for r in db.execute("SELECT key FROM tasks_done WHERE uid=?", (uid,))}


def task_progress(u, kind):
    return {"taps": u["taps"], "cases": u["cases_opened"], "refs": ref_counts(u["id"])[1]}[kind]


def give_task_reward(uid, key, reward):
    cur = db.execute("INSERT OR IGNORE INTO tasks_done(uid,key) VALUES(?,?)", (uid, key))
    if cur.rowcount:
        _coins(uid, reward)
    db.commit()
    return cur.rowcount > 0


def claim_task(uid, key):
    if key not in TASKS:
        raise GameError("Нет такого задания")
    _, kind, goal, reward = TASKS[key]
    if task_progress(get_user(uid), kind) < goal:
        raise GameError("Задание ещё не выполнено")
    if not give_task_reward(uid, key, reward):
        raise GameError("Награда уже получена")
    return reward


def daily_left(u):
    return max(0, u["daily_at"] + 86400 - time.time())


def claim_daily(uid):
    if daily_left(get_user(uid)) > 0:
        raise GameError("Бонус ещё не доступен")
    db.execute("UPDATE users SET daily_at=?, coins=coins+? WHERE id=?", (time.time(), DAILY_REWARD, uid))
    db.commit()
    return DAILY_REWARD


def top_users(n=10):
    return db.execute("SELECT name, coins FROM users ORDER BY coins DESC LIMIT ?", (n,)).fetchall()


def find_user(text):
    t = text.strip()
    if t.startswith("@"):
        r = db.execute("SELECT * FROM users WHERE LOWER(username)=?", (t[1:].lower(),)).fetchone()
    elif t.isdigit():
        r = db.execute("SELECT * FROM users WHERE id=?", (int(t),)).fetchone()
    else:
        r = None
    return dict(r) if r else None


def get_trade(tid):
    r = db.execute("SELECT * FROM trades WHERE id=?", (tid,)).fetchone()
    return dict(r) if r else None


def _expire():
    for t in db.execute("SELECT * FROM trades WHERE status='open' AND created<?", (time.time() - TRADE_TTL,)).fetchall():
        _inv_add(t["from_id"], t["give_item"])
        db.execute("UPDATE trades SET status='expired' WHERE id=?", (t["id"],))
    db.commit()


def create_trade(from_id, to_id, give, ask_item, ask_coins):
    _expire()
    if get_user(from_id)["taps"] < TRADE_MIN_TAPS:
        raise GameError(f"Обмен откроется после {TRADE_MIN_TAPS} тапов")
    n = db.execute("SELECT COUNT(*) c FROM trades WHERE from_id=? AND created>?", (from_id, time.time() - 86400)).fetchone()["c"]
    if n >= TRADE_DAILY_LIMIT:
        raise GameError("Лимит предложений на сегодня исчерпан")
    if not user_exists(to_id) or to_id == from_id:
        raise GameError("Игрок не найден")
    if give not in ITEMS or not (ask_item in ITEMS or ask_coins > 0):
        raise GameError("Некорректное предложение")
    _inv_take(from_id, give)
    cur = db.execute("INSERT INTO trades(from_id,to_id,give_item,ask_item,ask_coins,created) VALUES(?,?,?,?,?,?)",
                     (from_id, to_id, give, ask_item, ask_coins if not ask_item else 0, time.time()))
    db.commit()
    return cur.lastrowid


def incoming_trades(uid):
    _expire()
    return [dict(r) for r in db.execute("SELECT * FROM trades WHERE to_id=? AND status='open'", (uid,))]


def _open_trade(tid):
    _expire()
    t = get_trade(tid)
    if not t or t["status"] != "open":
        raise GameError("Предложение недоступно или истекло")
    return t


def accept_trade(tid, uid):
    t = _open_trade(tid)
    if t["to_id"] != uid:
        raise GameError("Это предложение не для тебя")
    if t["ask_item"]:
        _inv_take(uid, t["ask_item"])
        _inv_add(t["from_id"], t["ask_item"])
    else:
        if get_user(uid)["coins"] < t["ask_coins"]:
            raise GameError("Не хватает sadcoin")
        _coins(uid, -t["ask_coins"])
        _coins(t["from_id"], t["ask_coins"])
    _inv_add(uid, t["give_item"])
    db.execute("UPDATE trades SET status='done' WHERE id=?", (tid,))
    db.commit()
    return get_trade(tid)


def decline_trade(tid, uid):
    t = _open_trade(tid)
    if uid not in (t["to_id"], t["from_id"]):
        raise GameError("Это предложение не для тебя")
    _inv_add(t["from_id"], t["give_item"])
    db.execute("UPDATE trades SET status='declined' WHERE id=?", (tid,))
    db.commit()
    return t
                             
