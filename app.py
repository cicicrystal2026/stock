# -*- coding: utf-8 -*-
"""优选决策台 · Flask 后端

路由：
  GET  /login            登录页        POST /login  登录
  GET  /logout           登出
  GET  /                 看板（需登录）
  GET  /pool             池子管理页（需登录）
  ---- API（需登录，返回 JSON）----
  GET  /api/dashboard    看板数据（screen_latest + replay_latest）
  GET  /api/pool         当前池子 + 快照列表
  POST /api/pool         批量导入 / 单个添加 / 全量替换
  DELETE /api/pool/<code> 删除单个
  POST /api/pool/snapshot 版本快照
  POST /api/run          手动触发「抓数+扫描」后台任务
  GET  /api/run/status   查询后台任务状态
  GET  /api/health       健康检查（免登录）

密码：优先读环境变量 STOCK_APP_PASSWORD（部署时注入），
      首次启动会哈希后持久化到 data/config.json；无环境变量则用默认值。
"""
import os, sys, json, re, hashlib, secrets, threading, subprocess, datetime
from functools import wraps

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(BASE, "tools"))

from flask import (Flask, render_template, request, jsonify,
                   session, redirect, url_for)

import pool_utils
from pool_utils import load_pool_list, save_pool, snapshot_pool, get_meta, list_snapshots
import sim_utils

DATA = os.path.join(BASE, "data")
CONFIG = os.path.join(DATA, "config.json")
TEMPLATES = os.path.join(BASE, "web", "templates")
DEFAULT_PASSWORD = "stock123456"

app = Flask(__name__, template_folder=TEMPLATES)


# ---------------- 配置 / 密码 ----------------
def _hash(pw):
    return hashlib.pbkdf2_hmac("sha256", pw.encode("utf-8"),
                               b"stock-screener-salt", 100_000).hex()


def load_config():
    cfg = {}
    if os.path.exists(CONFIG):
        try:
            cfg = json.load(open(CONFIG, encoding="utf-8"))
        except Exception:
            cfg = {}
    changed = False
    if not cfg.get("secret_key"):
        cfg["secret_key"] = secrets.token_hex(32)
        changed = True
    env = os.environ.get("STOCK_APP_PASSWORD")
    # 环境变量注入的密码优先生效（部署时覆盖默认值）
    if env and _hash(env) != cfg.get("password_hash"):
        cfg["password_hash"] = _hash(env)
        changed = True
    if not cfg.get("password_hash"):
        cfg["password_hash"] = _hash(DEFAULT_PASSWORD)
        changed = True
    if changed:
        os.makedirs(DATA, exist_ok=True)
        json.dump(cfg, open(CONFIG, "w", encoding="utf-8"), ensure_ascii=False)
    return cfg


CFG = load_config()
app.secret_key = CFG["secret_key"]


def check_pw(pw):
    return _hash(pw or "") == CFG.get("password_hash")


def login_required(f):
    @wraps(f)
    def wrapper(*a, **kw):
        if not session.get("ok"):
            if request.path.startswith("/api/"):
                return jsonify({"ok": False, "error": "未登录"}), 401
            return redirect(url_for("login", next=request.path))
        return f(*a, **kw)
    return wrapper


def read_json(name):
    p = os.path.join(DATA, name)
    if os.path.exists(p):
        try:
            return json.load(open(p, encoding="utf-8"))
        except Exception:
            return None
    return None


# ---------------- 后台任务 ----------------
RUN = {"running": False, "log": [], "started": None, "finished": None, "error": None}


def _run_update():
    RUN["running"] = True
    RUN["log"] = []
    RUN["started"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    RUN["finished"] = None
    RUN["error"] = None
    scripts = ["fetch_daily.py", "fetch_flow.py", "screen.py", "replay.py"]
    py = sys.executable
    try:
        for s in scripts:
            p = os.path.join(BASE, "tools", s)
            RUN["log"].append(f">>> {s}")
            r = subprocess.run([py, p], cwd=BASE, capture_output=True,
                               text=True, timeout=1800)
            tail = (r.stdout or "").strip().splitlines()[-6:]
            RUN["log"].extend(tail)
            if r.returncode != 0:
                RUN["log"].append(f"[失败] {s} exit={r.returncode}")
                RUN["log"].extend((r.stderr or "").strip().splitlines()[-10:])
                RUN["error"] = s
                break
    except Exception as e:
        RUN["error"] = str(e)
        RUN["log"].append(f"[异常] {e}")
    RUN["finished"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    RUN["running"] = False


# ---------------- 页面路由 ----------------
@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("ok"):
        return redirect(url_for("dashboard"))
    error = None
    if request.method == "POST":
        if check_pw(request.form.get("password", "")):
            session["ok"] = True
            return redirect(request.args.get("next") or url_for("dashboard"))
        error = "密码错误，请重试"
    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
@login_required
def dashboard():
    screen = read_json("screen_latest.json")
    replay = read_json("replay_latest.json")
    return render_template("dashboard.html", screen=screen, replay=replay)


@app.route("/pool")
@login_required
def pool_page():
    return render_template("pool.html")


# ---------------- API ----------------
@app.route("/api/health")
def api_health():
    return jsonify({"ok": True, "time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")})


@app.route("/api/dashboard")
@login_required
def api_dashboard():
    return jsonify({"screen": read_json("screen_latest.json"),
                    "replay": read_json("replay_latest.json")})


@app.route("/api/pool", methods=["GET"])
@login_required
def api_pool_list():
    stocks = load_pool_list()
    return jsonify({"count": len(stocks), "stocks": stocks,
                    "meta": get_meta(), "snapshots": list_snapshots()})


def _parse_import_text(text):
    """解析粘贴文本 -> [{code,name,industry}]。支持：
       '688012' / '688012 中微公司' / '688012,中微公司,半导体' / '688012 中微公司 半导体'
    """
    out, seen = [], set()
    for line in (text or "").splitlines():
        s = line.strip()
        if not s:
            continue
        code_m = re.search(r"\d{6}", s)
        if not code_m:
            continue
        code = code_m.group(0)
        if code in seen:
            continue
        seen.add(code)
        rest = re.sub(r"\d{6}", " ", s)
        parts = [p.strip() for p in re.split(r"[,，\s]+", rest) if p.strip()]
        name = parts[0] if parts else ""
        industry = parts[1] if len(parts) > 1 else ""
        out.append({"code": code, "name": name, "industry": industry})
    return out


@app.route("/api/pool", methods=["POST"])
@login_required
def api_pool_add():
    body = request.get_json(silent=True) or {}
    mode = body.get("mode", "merge")  # merge | replace
    incoming = []

    if body.get("text"):
        incoming = _parse_import_text(body["text"])
    elif body.get("stocks"):
        incoming = body["stocks"]

    if not incoming:
        return jsonify({"ok": False, "error": "未解析到有效代码（需 6 位数字）"}), 400

    # 纯代码（缺名称）-> 东财补全
    need = [s["code"] for s in incoming if not s["name"]]
    if need:
        from market_utils import enrich
        mkt = enrich(need)
        for s in incoming:
            if not s["name"] and s["code"] in mkt:
                s["name"] = mkt[s["code"]]["name"]
                s["industry"] = s["industry"] or mkt[s["code"]]["industry"]

    # 合并
    if mode == "replace":
        merged = incoming
    else:
        cur = {s["code"]: s for s in load_pool_list()}
        for s in incoming:
            cur[s["code"]] = s
        merged = list(cur.values())

    save_pool(merged)
    unnamed = [s["code"] for s in merged if not s["name"]]
    return jsonify({"ok": True, "count": len(merged), "added": len(incoming),
                    "unnamed": unnamed})


@app.route("/api/pool/<code>", methods=["DELETE"])
@login_required
def api_pool_delete(code):
    cur = load_pool_list()
    nxt = [s for s in cur if s["code"] != code]
    if len(nxt) == len(cur):
        return jsonify({"ok": False, "error": "代码不存在"}), 404
    save_pool(nxt)
    return jsonify({"ok": True, "count": len(nxt)})


@app.route("/api/pool/snapshot", methods=["POST"])
@login_required
def api_pool_snapshot():
    dst = snapshot_pool()
    if not dst:
        return jsonify({"ok": False, "error": "无当前池子可快照"}), 400
    return jsonify({"ok": True, "path": dst, "snapshots": list_snapshots()})


@app.route("/api/run", methods=["POST"])
@login_required
def api_run():
    if RUN["running"]:
        return jsonify({"ok": False, "error": "已有任务在运行"}), 409
    t = threading.Thread(target=_run_update, daemon=True)
    t.start()
    return jsonify({"ok": True, "message": "已启动更新任务"})


@app.route("/api/run/status")
@login_required
def api_run_status():
    return jsonify(RUN)


# ---------------- 模拟买入 ----------------
def _latest_prices():
    """从日线缓存读每只股票最新收盘价。"""
    p = os.path.join(DATA, "cache", "daily_330.json")
    if not os.path.exists(p):
        return {}
    try:
        cache = json.load(open(p, encoding="utf-8"))
    except Exception:
        return {}
    return {code: float(bars[-1][2])
            for code, bars in cache.get("bars", {}).items() if bars}


def _days_between(a, b):
    try:
        return max(0, (datetime.date.fromisoformat(b) - datetime.date.fromisoformat(a)).days)
    except Exception:
        return 0


@app.route("/sim")
@login_required
def sim_page():
    return render_template("sim.html")


@app.route("/api/sim")
@login_required
def api_sim():
    acct = sim_utils.load_account()
    prices = _latest_prices()
    summary = sim_utils.account_summary(acct, prices)
    today_s = datetime.date.today().strftime("%Y-%m-%d")

    positions = []
    for p in acct["positions"]:
        if p["status"] != "holding":
            continue
        px = prices.get(p["code"], p["buy_price"])
        pnl_pct = (px / p["buy_price"] - 1) * 100
        positions.append({
            "code": p["code"], "name": p["name"], "industry": p["industry"],
            "strategy": p["strategy"], "buy_date": p["buy_date"],
            "buy_price": p["buy_price"], "shares": p["shares"],
            "cost": p["cost"], "price": round(px, 2),
            "pnl": round((px - p["buy_price"]) * p["shares"], 2),
            "pnl_pct": round(pnl_pct, 2),
            "stop": p["stop"], "stop_original": p["stop_original"],
            "protected": p["protected"], "partial_done": p["partial_done"],
            "take_profit_pct": p["take_profit_pct"],
            "take_profit_price": round(p["buy_price"] * (1 + p["take_profit_pct"]), 2),
            "days": _days_between(p["buy_date"], today_s),
        })

    signal_date = None
    sp = os.path.join(DATA, "screen_latest.json")
    if os.path.exists(sp):
        try:
            signal_date = json.load(open(sp, encoding="utf-8"))["meta"]["date"]
        except Exception:
            pass

    return jsonify({
        "summary": summary,
        "positions": positions,
        "closed": acct["closed"],
        "signals": sim_utils.get_a_signals(),
        "signal_date": signal_date,
    })


@app.route("/api/sim/buy", methods=["POST"])
@login_required
def api_sim_buy():
    body = request.get_json(silent=True) or {}
    code = body.get("code")
    try:
        strategy = int(body.get("strategy") or 0)
    except (TypeError, ValueError):
        strategy = 0
    if not code or strategy not in (1, 2):
        return jsonify({"ok": False, "error": "参数错误"}), 400
    sig = next((s for s in sim_utils.get_a_signals()
                if s["code"] == code and s["strategy"] == strategy), None)
    if not sig:
        return jsonify({"ok": False, "error": "该标的不在今日 A 档信号中"}), 400
    acct = sim_utils.load_account()
    ok, msg, pos = sim_utils.buy(acct, sig, strategy)
    if not ok:
        return jsonify({"ok": False, "error": msg}), 400
    sim_utils.save_account(acct)
    return jsonify({"ok": True, "message": msg, "position": pos})


@app.route("/api/sim/settle", methods=["POST"])
@login_required
def api_sim_settle():
    """手动触发一次结算（收盘后）。"""
    p = os.path.join(DATA, "cache", "daily_330.json")
    if not os.path.exists(p):
        return jsonify({"ok": False, "error": "无日线缓存"}), 400
    try:
        cache = json.load(open(p, encoding="utf-8"))
    except Exception:
        return jsonify({"ok": False, "error": "日线缓存读取失败"}), 400
    bars_all = cache.get("bars", {})
    last_date = max((b[-1][0] for b in bars_all.values() if b), default="")
    acct = sim_utils.load_account()
    events = sim_utils.settle(acct, bars_all, last_date)
    sim_utils.save_account(acct)
    return jsonify({"ok": True, "date": last_date, "events": events})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    app.run(host="127.0.0.1", port=port, debug=False)
