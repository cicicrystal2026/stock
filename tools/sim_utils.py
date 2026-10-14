# -*- coding: utf-8 -*-
"""模拟买入账户 · 核心逻辑（纯函数，可独立测试）

账户模型：初始资金 50,000；每次买入固定预算 10,000（A 股 1 手 = 100 股，向下取整手数，
          若 1 手都买不起则按 1 手成交）。
卖出规则（每日收盘后由 settle 结算，严格按策略）：
  - 成本保护：浮盈 >= 10% 后，止损上移到成本价
  - 止损：现价 <= 止损价 → 全部平仓（reason=stop_loss）
  - 止盈 1/3：浮盈 >= 止盈线（策略一 +30% / 策略二 +20%）→ 卖 1/3，剩余继续持有
  - 趋势止盈：已卖 1/3 后，收盘跌破 20 日线 → 卖出剩余（reason=trend_exit）

数据文件：data/sim/account.json
"""
import os, json, datetime

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BASE, "data")
SIM_DIR = os.path.join(DATA, "sim")
SIM_FILE = os.path.join(SIM_DIR, "account.json")

INITIAL_CAPITAL = 50_000
BUY_BUDGET = 10_000
LOT = 100          # A 股一手 = 100 股
PROTECT_PCT = 10.0 # 成本保护阈值（浮盈百分比）
TAKE_PROFIT = {1: 0.30, 2: 0.20}  # 止盈线：策略一 +30% / 策略二 +20%


def _default_account():
    return {
        "initial_capital": INITIAL_CAPITAL,
        "cash": INITIAL_CAPITAL,
        "positions": [],
        "closed": [],
        "updated": None,
    }


def load_account():
    if os.path.exists(SIM_FILE):
        try:
            acct = json.load(open(SIM_FILE, encoding="utf-8"))
            # 兼容旧字段
            acct.setdefault("initial_capital", INITIAL_CAPITAL)
            acct.setdefault("cash", acct["initial_capital"])
            acct.setdefault("positions", [])
            acct.setdefault("closed", [])
            acct.setdefault("updated", None)
            return acct
        except Exception:
            pass
    return _default_account()


def save_account(acct):
    os.makedirs(SIM_DIR, exist_ok=True)
    with open(SIM_FILE, "w", encoding="utf-8") as f:
        json.dump(acct, f, ensure_ascii=False, indent=2)


def today():
    return datetime.date.today().strftime("%Y-%m-%d")


def compute_shares(price, budget=BUY_BUDGET, lot=LOT):
    """按预算买入的股数：向下取整到整手，至少 1 手。"""
    price = float(price)
    if price <= 0:
        return 0
    shares = int(budget // price // lot) * lot
    if shares < lot:
        shares = lot  # 1 手都买不起，按 1 手成交（允许小幅超预算）
    return shares


def get_a_signals():
    """从最新扫描结果读取 A 档信号（含买入价/止损价）。"""
    p = os.path.join(DATA, "screen_latest.json")
    if not os.path.exists(p):
        return []
    try:
        d = json.load(open(p, encoding="utf-8"))
    except Exception:
        return []
    out = []
    for strat, key in ((1, "s1"), (2, "s2")):
        for r in d.get("candidates", {}).get(key, {}).get("A", []):
            r = dict(r)
            r["strategy"] = strat
            out.append(r)
    return out


def buy(acct, stock, strategy, buy_date=None):
    """买入。stock 需含 code/name/industry/close/stop。返回 (ok, msg, pos)。"""
    code = stock["code"]
    if any(p["code"] == code and p["status"] == "holding"
           for p in acct["positions"]):
        return False, "已持有该标的，不能重复买入", None

    price = float(stock["close"])
    stop = float(stock.get("stop") or 0)
    shares = compute_shares(price)
    cost = shares * price
    if acct["cash"] < cost:
        return False, f"可用资金不足：需 {cost:.0f} 元，可用 {acct['cash']:.0f} 元", None

    acct["cash"] = round(acct["cash"] - cost, 2)
    pos = {
        "code": code,
        "name": stock.get("name", ""),
        "industry": stock.get("industry", ""),
        "strategy": strategy,
        "buy_date": buy_date or today(),
        "buy_price": round(price, 2),
        "shares": shares,
        "cost": round(cost, 2),
        "stop": round(stop, 2),
        "stop_original": round(stop, 2),
        "take_profit_pct": TAKE_PROFIT.get(strategy, 0.20),
        "partial_done": False,
        "protected": False,
        "status": "holding",
    }
    acct["positions"].append(pos)
    acct["updated"] = buy_date or today()
    return True, "买入成功", pos


def _pnl(buy_price, sell_price, shares):
    return round((sell_price - buy_price) * shares, 2)


def _close_position(acct, pos, sell_price, sell_date, reason):
    """全部平仓。"""
    shares = pos["shares"]
    pnl = _pnl(pos["buy_price"], sell_price, shares)
    pnl_pct = (sell_price / pos["buy_price"] - 1) * 100
    acct["cash"] = round(acct["cash"] + sell_price * shares, 2)
    acct["closed"].append({
        "code": pos["code"], "name": pos["name"], "strategy": pos["strategy"],
        "buy_date": pos["buy_date"], "buy_price": pos["buy_price"],
        "sell_date": sell_date, "sell_price": round(sell_price, 2),
        "shares": shares, "type": "close", "reason": reason,
        "pnl": pnl, "pnl_pct": round(pnl_pct, 2),
        "days": _days(pos["buy_date"], sell_date),
    })
    pos["status"] = "closed"
    pos["shares"] = 0


def _partial_sell(acct, pos, sell_price, sell_date, sell_shares):
    """卖 1/3 仓位（部分止盈），剩余继续持有。"""
    pnl = _pnl(pos["buy_price"], sell_price, sell_shares)
    pnl_pct = (sell_price / pos["buy_price"] - 1) * 100
    acct["cash"] = round(acct["cash"] + sell_price * sell_shares, 2)
    acct["closed"].append({
        "code": pos["code"], "name": pos["name"], "strategy": pos["strategy"],
        "buy_date": pos["buy_date"], "buy_price": pos["buy_price"],
        "sell_date": sell_date, "sell_price": round(sell_price, 2),
        "shares": sell_shares, "type": "partial", "reason": "take_profit",
        "pnl": pnl, "pnl_pct": round(pnl_pct, 2),
        "days": _days(pos["buy_date"], sell_date),
    })
    pos["shares"] -= sell_shares


def _days(buy_date, sell_date):
    try:
        a = datetime.date.fromisoformat(buy_date)
        b = datetime.date.fromisoformat(sell_date)
        return max(0, (b - a).days)
    except Exception:
        return 0


def settle(acct, bars_all, date):
    """每日结算：bars_all = {code: [[date, open, close, high, low, vol], ...]}。
    返回触发的动作列表（用于日志/展示）。"""
    events = []
    for pos in acct["positions"]:
        if pos["status"] != "holding":
            continue
        bars = bars_all.get(pos["code"])
        if not bars:
            continue
        closes = [float(b[2]) for b in bars]
        if len(closes) < 2:
            continue
        close = closes[-1]
        ma20 = sum(closes[-20:]) / 20 if len(closes) >= 20 else None
        pnl_pct = (close / pos["buy_price"] - 1) * 100

        # 1) 成本保护：浮盈 >= 10% → 止损上移到成本价
        if not pos["protected"] and pnl_pct >= PROTECT_PCT:
            pos["protected"] = True
            pos["stop"] = pos["buy_price"]
            events.append({"code": pos["code"], "name": pos["name"],
                           "action": "protect", "pnl_pct": round(pnl_pct, 2)})

        # 2) 止损：现价 <= 止损价 → 全平
        if close <= pos["stop"]:
            _close_position(acct, pos, close, date, "stop_loss")
            events.append({"code": pos["code"], "name": pos["name"],
                           "action": "stop_loss",
                           "price": round(close, 2),
                           "pnl_pct": round(pnl_pct, 2)})
            continue

        # 3) 止盈 1/3：浮盈 >= 止盈线，且未卖过 1/3
        if not pos["partial_done"] and pnl_pct >= pos["take_profit_pct"] * 100:
            sell_shares = pos["shares"] // 3
            if sell_shares >= LOT:
                _partial_sell(acct, pos, close, date, sell_shares)
                pos["partial_done"] = True
                events.append({"code": pos["code"], "name": pos["name"],
                               "action": "take_profit_1_3",
                               "shares": sell_shares,
                               "price": round(close, 2),
                               "pnl_pct": round(pnl_pct, 2)})

        # 4) 趋势止盈：已卖 1/3 后，收盘跌破 20 日线 → 卖剩余
        if pos["partial_done"] and ma20 is not None and close < ma20:
            _close_position(acct, pos, close, date, "trend_exit")
            events.append({"code": pos["code"], "name": pos["name"],
                           "action": "trend_exit",
                           "price": round(close, 2),
                           "pnl_pct": round(pnl_pct, 2)})

    acct["updated"] = date
    return events


def account_summary(acct, latest_price=None):
    """账户概览。latest_price = {code: price} 用于算持仓市值。"""
    latest_price = latest_price or {}
    pos_value = 0.0
    float_pnl = 0.0
    for p in acct["positions"]:
        if p["status"] != "holding":
            continue
        px = latest_price.get(p["code"], p["buy_price"])
        pos_value += px * p["shares"]
        float_pnl += (px - p["buy_price"]) * p["shares"]
    total = acct["cash"] + pos_value
    realized = sum(c["pnl"] for c in acct["closed"])
    return {
        "initial_capital": acct["initial_capital"],
        "cash": round(acct["cash"], 2),
        "pos_value": round(pos_value, 2),
        "total_assets": round(total, 2),
        "realized_pnl": round(realized, 2),
        "float_pnl": round(float_pnl, 2),
        "total_pnl": round(realized + float_pnl, 2),
        "total_return_pct": round((total / acct["initial_capital"] - 1) * 100, 2),
        "holding_count": sum(1 for p in acct["positions"] if p["status"] == "holding"),
        "closed_count": len(acct["closed"]),
        "win_count": sum(1 for c in acct["closed"] if c["pnl"] > 0),
        "loss_count": sum(1 for c in acct["closed"] if c["pnl"] <= 0),
    }


def reset_account():
    """重置账户（测试用）。"""
    acct = _default_account()
    save_account(acct)
    return acct
