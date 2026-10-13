import hashlib, hmac, json, os, time
from urllib.parse import parse_qsl

from aiohttp import web

import game
from game import CASES, ITEMS, START_ENERGY, TASKS, GameError

INDEX = os.path.join(os.path.dirname(__file__), "webapp", "index.html")


def check_init_data(init_data: str, token: str):
    """Проверка подписи Telegram WebApp initData. Возвращает dict пользователя или None."""
    try:
        data = dict(parse_qsl(init_data, strict_parsing=True))
        got = data.pop("hash")
        check = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
        secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
        if not hmac.compare_digest(hmac.new(secret, check.encode(), hashlib.sha256).hexdigest(), got):
            return None
        if time.time() - int(data["auth_date"]) > 86400:
            return None
        return json.loads(data["user"])
    except Exception:
        return None


def state(u, bot_username):
    done = game.done_tasks(u["id"])
    tasks = [{"key": k, "title": t, "progress": min(game.task_progress(u, kind), goal), "goal": goal,
              "reward": rew, "done": k in done} for k, (t, kind, goal, rew) in TASKS.items()]
    return {
        "me": {"id": u["id"], "coins": u["coins"], "energy": int(u["energy"]), "max_energy": START_ENERGY,
               "tap_power": u["tap_power"], "passive": u["passive"]},
        "costs": {"tap": game.tap_upgrade_cost(u), "pass": game.passive_upgrade_cost(u)},
        "items": {k: {"name": v[0], "rarity": v[1], "value": v[2]} for k, v in ITEMS.items()},
        "cases": {k: {"name": n, "price": p, "drops": {i: round(w * 100 / sum(d.values()), 1) for i, w in d.items()}}
                  for k, (n, p, d) in CASES.items()},
        "inv": {r["item"]: r["qty"] for r in game.inv_get(u["id"])},
        "tasks": tasks,
        "daily": {"left": int(game.daily_left(u)), "reward": game.DAILY_REWARD},
        "top": [{"name": r["name"], "coins": r["coins"]} for r in game.top_users(10)],
        "link": f"https://t.me/{bot_username}?start=ref_{u['id']}",
    }


def create_app(token: str, bot_username: str) -> web.Application:
    async def index(_):
        return web.FileResponse(INDEX)

    async def healthz(_):
        return web.Response(text="ok")

    async def api(request: web.Request):
        tg = check_init_data(request.headers.get("X-Init-Data", ""), token)
        if not tg:
            return web.json_response({"error": "Открой игру из Telegram"}, status=401)
        uid = tg["id"]
        name = " ".join(filter(None, [tg.get("first_name"), tg.get("last_name")])) or str(uid)
        game.get_user(uid, name, tg.get("username") or "")
        body = await request.json() if request.can_read_body else {}
        act, res = request.match_info["action"], {}
        try:
            if act == "tap":
                res["counted"] = game.tap(uid, int(body.get("n", 1)))
            elif act == "open":
                res["drop"] = game.open_case(uid, str(body.get("case")))
            elif act == "sell":
                it = str(body.get("item"))
                res["got"] = game.sell_all(uid) if it == "all" else game.sell(uid, it)
            elif act == "buy":
                game.buy_upgrade(uid, str(body.get("kind")))
            elif act == "claim":
                res["got"] = game.claim_task(uid, str(body.get("key")))
            elif act == "daily":
                res["got"] = game.claim_daily(uid)
            elif act != "state":
                return web.json_response({"error": "Неизвестное действие"}, status=404)
        except GameError as e:
            res["error"] = str(e)
        res["state"] = state(game.get_user(uid), bot_username)
        return web.json_response(res)

    app = web.Application()
    app.router.add_get("/", index)
    app.router.add_get("/healthz", healthz)
    app.router.add_post("/api/{action}", api)
    return app
  
