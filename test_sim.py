# -*- coding: utf-8 -*-
"""模拟买入核心逻辑单元测试（独立运行，不碰真实账户文件）"""
import os, sys, json, datetime, shutil, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "tools"))

import sim_utils

PASS, FAIL = 0, 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✓ {name}")
    else:
        FAIL += 1
        print(f"  ✗ {name}  {detail}")


def make_bars(closes, start="2026-10-01"):
    bars = []
    d = datetime.date.fromisoformat(start)
    for i, c in enumerate(closes):
        ds = (d + datetime.timedelta(days=i)).strftime("%Y-%m-%d")
        bars.append([ds, c, c, c, c, 1000.0])
    return bars


def fresh():
    acct = sim_utils._default_account()
    return acct


def test_shares():
    print("=== 股数计算 ===")
    check("20元→500股", sim_utils.compute_shares(20.0) == 500)
    check("68元→100股", sim_utils.compute_shares(68.0) == 100)
    check("125元→100股(不足1手按1手)", sim_utils.compute_shares(125.0) == 100)
    check("8元→1200股", sim_utils.compute_shares(8.0) == 1200)


def test_buy():
    print("=== 买入 ===")
    acct = fresh()
    stock = {"code": "600000", "name": "测试A", "industry": "测试", "close": 20.0, "stop": 19.0}
    ok, msg, pos = sim_utils.buy(acct, stock, 1, "2026-10-14")
    check("买入成功", ok, msg)
    check("股数500", pos["shares"] == 500, str(pos["shares"]))
    check("成本10000", pos["cost"] == 10000, str(pos["cost"]))
    check("现金减至40000", acct["cash"] == 40000, str(acct["cash"]))
    check("止盈线30%(策略一)", pos["take_profit_pct"] == 0.30)
    ok2, _, _ = sim_utils.buy(acct, stock, 1, "2026-10-14")
    check("重复买入被拒", not ok2)
    # 资金不足
    acct2 = fresh()
    acct2["cash"] = 1000
    stock_hi = {"code": "600001", "name": "高价", "industry": "测试", "close": 125.0, "stop": 118.0}
    ok3, msg3, _ = sim_utils.buy(acct2, stock_hi, 2, "2026-10-14")
    check("资金不足被拒", not ok3, msg3)


def test_stop_loss():
    print("=== 止损 ===")
    acct = fresh()
    stock = {"code": "600000", "name": "测试A", "industry": "测试", "close": 20.0, "stop": 19.0}
    sim_utils.buy(acct, stock, 1, "2026-10-14")
    # 最新收盘 18.5 < 19 → 止损
    bars = {"600000": make_bars([20, 19.5, 19.2, 18.8, 18.5])}
    events = sim_utils.settle(acct, bars, "2026-10-08")
    check("触发止损动作", any(e["action"] == "stop_loss" for e in events), str(events))
    check("持仓清零", all(p["shares"] == 0 or p["status"] == "closed" for p in acct["positions"]))
    check("平仓记录1条", len(acct["closed"]) == 1)
    check("卖出原因=stop_loss", acct["closed"][0]["reason"] == "stop_loss")
    check("亏损金额", acct["closed"][0]["pnl"] == round((18.5-20)*500, 2), str(acct["closed"][0]["pnl"]))
    check("现金回款", abs(acct["cash"] - (40000 + 18.5*500)) < 1, str(acct["cash"]))


def test_protect():
    print("=== 成本保护 ===")
    acct = fresh()
    stock = {"code": "600000", "name": "测试A", "industry": "测试", "close": 20.0, "stop": 19.0}
    sim_utils.buy(acct, stock, 1, "2026-10-14")
    bars = {"600000": make_bars([20, 21, 22, 22.5])}  # 浮盈12.5%
    events = sim_utils.settle(acct, bars, "2026-10-07")
    check("触发成本保护", any(e["action"] == "protect" for e in events), str(events))
    pos = acct["positions"][0]
    check("止损上移到成本价20", pos["stop"] == 20.0, str(pos["stop"]))
    check("protected标记", pos["protected"] is True)
    check("未触发止盈(12.5%<30%)", all(e["action"] != "take_profit_1_3" for e in events))


def test_take_profit():
    print("=== 止盈1/3 ===")
    acct = fresh()
    stock = {"code": "600000", "name": "测试A", "industry": "测试", "close": 20.0, "stop": 19.0}
    sim_utils.buy(acct, stock, 1, "2026-10-14")
    # 浮盈30%：closes 最后 26，ma20 需要 < 26 以免趋势止盈
    closes = [20]*15 + [22, 24, 26, 26, 26]
    bars = {"600000": make_bars(closes)}
    events = sim_utils.settle(acct, bars, "2026-10-20")
    check("触发止盈1/3", any(e["action"] == "take_profit_1_3" for e in events), str(events))
    pos = acct["positions"][0]
    check("partial_done标记", pos["partial_done"] is True)
    check("剩余股数334", pos["shares"] == 334, str(pos["shares"]))
    partials = [c for c in acct["closed"] if c["type"] == "partial"]
    check("有partial平仓记录", len(partials) == 1)
    check("partial卖166股", partials[0]["shares"] == 166, str(partials[0]["shares"]))


def test_trend_exit():
    print("=== 趋势止盈(跌破20日线) ===")
    acct = fresh()
    stock = {"code": "600000", "name": "测试A", "industry": "测试", "close": 20.0, "stop": 19.0}
    sim_utils.buy(acct, stock, 1, "2026-10-14")
    # 第一次结算：浮盈30%触发止盈1/3
    closes1 = [20]*15 + [22, 24, 26, 26, 26]
    sim_utils.settle(acct, {"600000": make_bars(closes1)}, "2026-10-20")
    pos = acct["positions"][0]
    check("已止盈1/3", pos["partial_done"] is True)
    # 第二次结算：收盘跌破20日线（构造 ma20 高于最新收盘）
    # 最新收盘 24，但前20日均值约 24.7 > 24 → 跌破
    closes2 = [26]*16 + [25, 24.8, 24.6, 24.4, 24.0]
    events2 = sim_utils.settle(acct, {"600000": make_bars(closes2)}, "2026-10-21")
    check("触发趋势离场", any(e["action"] == "trend_exit" for e in events2), str(events2))
    check("全部平仓", acct["positions"][0]["status"] == "closed")
    closes_all = [c for c in acct["closed"] if c["type"] == "close"]
    check("有close记录", any(c["reason"] == "trend_exit" for c in closes_all))


def main():
    test_shares()
    test_buy()
    test_stop_loss()
    test_protect()
    test_take_profit()
    test_trend_exit()
    print(f"\n{'='*40}\n结果：{PASS} 通过 / {FAIL} 失败")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
