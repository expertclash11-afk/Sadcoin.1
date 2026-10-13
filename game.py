import os, random, sqlite3, time

DB_PATH = os.getenv("DB_PATH", "game.db")
db = sqlite3.connect(DB_PATH, check_same_thread=False)
db.row_factory = sqlite3.Row

db.executescript("""
CREATE TABLE IF NOT EXISTS users(
    id INTEGER PRIMARY KEY, 
    name TEXT, 
    username TEXT,
    coins INTEGER DEFAULT 0, 
    energy REAL DEFAULT 500, 
    max_energy INTEGER DEFAULT 500,
    tap_power INTEGER DEFAULT 1, 
    passive INTEGER DEFAULT 0,
    taps INTEGER DEFAULT 0, 
    cases_opened INTEGER DEFAULT 0, 
    last_tap REAL DEFAULT 0, 
    updated REAL, 
    daily_at REAL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS inv(uid INTEGER, item TEXT, qty INTEGER, PRIMARY KEY(uid,item));
CREATE TABLE IF NOT EXISTS tasks_done(uid INTEGER, key TEXT, PRIMARY KEY(uid,key));
CREATE TABLE IF NOT EXISTS refs(new_id INTEGER PRIMARY KEY, ref_id INTEGER, paid INTEGER DEFAULT 0);
""")

START_ENERGY = 500
REGEN_PER_SEC = 1
REF_MIN_TAPS, REF_REWARD = 100, 5000
DAILY_REWARD = 2000

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
        db.execute("INSERT INTO users(id,name,username,energy,max_energy,updated) VALUES(?,?,?,?,?,?)",
                   (uid, name or str(uid), username or "", START_ENERGY, START_ENERGY, now))
        db.commit()
        r = db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    
    dt = now - r["updated"]
    energy = min(r["max_energy"], r["energy"] + dt * REGEN_PER_SEC)
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
        raise GameError("Предмет не найден в инвентаре")
    db.execute("UPDATE inv SET qty=qty-? WHERE uid=? AND item=?", (n, uid, item))
    db.execute("DELETE FROM inv WHERE qty<=0")

def inv_get(uid):
    return db.execute("SELECT item, qty FROM inv WHERE uid=? AND qty>0 ORDER BY item", (uid,)).fetchall()

def tap(uid, n=1):
    u = get_user(uid)
    now = time.time()
    dt = now - u["last_tap"]
    if dt < 0.05:
        return 0
    cnt = max(0, min(int(n), int(u["energy"])))
    if cnt == 0:
        return 0
    db.execute("UPDATE users SET coins=coins+?, energy=energy-?, taps=taps+?, last_tap=? WHERE id=?",
               (cnt * u["tap_power"], cnt, cnt, now, uid))
    if u["taps"] + cnt >= REF_MIN_TAPS:
        ref = db.execute("SELECT ref_id FROM refs WHERE new_id=? AND paid=0", (uid,)).fetchone()
        if ref:
            db.execute("UPDATE refs SET paid=1 WHERE new_id=?", (uid,))
            _coins(ref["ref_id"], REF_REWARD)
    db.commit()
    return cnt

def tap_upgrade_cost(u):
    return int(200 * 1.7 ** (u["tap_power"] - 1))

def passive_upgrade_cost(u):
    return int(1000 * 1.5 ** (u["passive"] // 100))

def buy_upgrade(uid, kind):
    u = get_user(uid)
    if kind == "tap":
        cost = tap_upgrade_cost(u)
        db.execute("UPDATE users SET coins=coins-?, tap_power=tap_power+? WHERE id=?", (cost, 1, uid))
    elif kind == "pass":
        cost = passive_upgrade_cost(u)
        db.execute("UPDATE users SET coins=coins-?, passive=passive+? WHERE id=?", (cost, 100, uid))
    else:
        raise GameError("Неизвестный тип улучшения")
    db.commit()

def open_case(uid, key):
    if key not in CASES:
        raise GameError("Кейс не существует")
    _, price, drops = CASES[key]
    u = get_user(uid)
    if u["coins"] < price:
        raise GameError("Недостаточно монет")
    item = random.choices(list(drops), weights=list(drops.values()))[0]
    _coins(uid, -price)
    _inv_add(uid, item)
    db.execute("UPDATE users SET cases_opened=cases_opened+1 WHERE id=?", (uid,))
    db.commit()
    return item

def sell(uid, item):
    if item not in ITEMS:
        raise GameError("Предмет не существует")
    _inv_take(uid, item)
    val = ITEMS[item][2]
    _coins(uid, val)
    db.commit()
    return val

def sell_all(uid):
    items = inv_get(uid)
    total = sum(ITEMS[r["item"]][2] * r["qty"] for r in items)
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

def claim_task(uid, key):
    if key not in TASKS:
        raise GameError("Задание не найдено")
    _, kind, goal, reward = TASKS[key]
    u = get_user(uid)
    if task_progress(u, kind) < goal:
        raise GameError("Условия задания еще не выполнены")
    cur = db.execute("INSERT OR IGNORE INTO tasks_done(uid,key) VALUES(?,?)", (uid, key))
    if not cur.rowcount:
        raise GameError("Награда уже получена")
    _coins(uid, reward)
    db.commit()
    return reward

def daily_left(u):
    return max(0, u["daily_at"] + 86400 - time.time())

def claim_daily(uid):
    u = get_user(uid)
    if daily_left(u) > 0:
        raise GameError("Бонус еще не доступен")
    db.execute("UPDATE users SET daily_at=?, coins=coins+? WHERE id=?", (time.time(), DAILY_REWARD, uid))
    db.commit()
    return DAILY_REWARD

def top_users(n=10):
    return db.execute("SELECT name, coins FROM users ORDER BY coins DESC LIMIT ?", (n,)).fetchall()
