# -*- coding: utf-8 -*-
"""每日结算脚本：读最新日线 + 模拟账户，按策略执行止损/止盈/成本保护。
由 update.sh 在 screen.py 之后调用（收盘后自动结算），也可手动执行。
"""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import sim_utils

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BASE, "data")
DAILY = os.path.join(DATA, "cache", "daily_330.json")


def main():
    if not os.path.exists(DAILY):
        print("[结算] 无日线缓存，跳过")
        return

    with open(DAILY, encoding="utf-8") as f:
        cache = json.load(f)
    bars_all = cache.get("bars", {})
    if not bars_all:
        print("[结算] 日线缓存为空，跳过")
        return

    last_date = max(b[-1][0] for b in bars_all.values() if b)

    acct = sim_utils.load_account()
    holding = [p for p in acct["positions"] if p["status"] == "holding"]
    if not holding:
        print(f"[结算] {last_date} 无持仓，跳过")
        return

    events = sim_utils.settle(acct, bars_all, last_date)
    sim_utils.save_account(acct)

    if events:
        for e in events:
            a = e["action"]
            if a == "protect":
                print(f"[结算] {e['code']} {e['name']} 浮盈{e['pnl_pct']}% 触发成本保护，止损上移到成本价")
            elif a == "stop_loss":
                print(f"[结算] {e['code']} {e['name']} 现价{e['price']} 触发止损({e['pnl_pct']}%)，全部平仓")
            elif a == "take_profit_1_3":
                print(f"[结算] {e['code']} {e['name']} 浮盈{e['pnl_pct']}% 触发止盈，卖出 1/3（{e['shares']}股）")
            elif a == "trend_exit":
                print(f"[结算] {e['code']} {e['name']} 收盘跌破20日线({e['price']})，剩余仓位离场")
    else:
        print(f"[结算] {last_date} 持仓无触发动作")

    s = sim_utils.account_summary(acct)
    print(f"[结算] 总资产 {s['total_assets']:.0f} 元 · 总盈亏 {s['total_pnl']:+.0f} 元 "
          f"({s['total_return_pct']:+.2f}%) · 持仓 {s['holding_count']} 只")


if __name__ == "__main__":
    main()
