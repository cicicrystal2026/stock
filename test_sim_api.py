# -*- coding: utf-8 -*-
"""模拟买入 Flask 集成测试"""
import os, sys, json

BASE = os.path.dirname(os.path.abspath(__file__))
os.environ["STOCK_APP_PASSWORD"] = "test123"
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.join(BASE, "tools"))

import app as appmod
import sim_utils

c = appmod.app.test_client()
PASS, FAIL = 0, 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✓ {name}")
    else:
        FAIL += 1
        print(f"  ✗ {name}  {detail}")


def main():
    print("=== 未登录拦截 ===")
    r = c.get("/sim")
    check("未登录 /sim → 302", r.status_code == 302, str(r.status_code))
    r = c.get("/api/sim")
    check("未登录 /api/sim → 401", r.status_code == 401, str(r.status_code))

    print("=== 登录 ===")
    r = c.post("/login", data={"password": "test123"})
    check("登录成功", r.status_code == 302, str(r.status_code))

    print("=== 页面与账户 ===")
    r = c.get("/sim")
    check("sim 页面 200", r.status_code == 200, str(r.status_code))
    check("页面含「模拟买入」", "模拟买入" in r.get_data(as_text=True))
    check("页面含「交易规则」", "交易规则" in r.get_data(as_text=True))

    r = c.get("/api/sim")
    d = r.get_json()
    check("初始资金 5 万", d["summary"]["initial_capital"] == 50000,
          str(d["summary"]["initial_capital"]))
    check("初始现金 5 万", d["summary"]["cash"] == 50000)
    check("无持仓", len(d["positions"]) == 0)
    check("无平仓", len(d["closed"]) == 0)

    print("=== 买入（无 A 档信号）===")
    r = c.post("/api/sim/buy", json={"code": "600000", "strategy": 1})
    check("无信号买入被拒 400", r.status_code == 400, str(r.status_code))
    check("错误信息", "不在今日 A 档" in r.get_json()["error"], str(r.get_json()))

    print("=== 注入持仓，测渲染 ===")
    acct = sim_utils.load_account()
    acct["positions"].append({
        "code": "688012", "name": "中微公司", "industry": "半导体", "strategy": 1,
        "buy_date": "2026-10-14", "buy_price": 125.40, "shares": 100, "cost": 12540.0,
        "stop": 110.20, "stop_original": 110.20, "take_profit_pct": 0.30,
        "partial_done": False, "protected": False, "status": "holding",
    })
    sim_utils.save_account(acct)

    r = c.get("/api/sim")
    d = r.get_json()
    check("持仓 1 只", len(d["positions"]) == 1)
    pos = d["positions"][0]
    check("持仓含止损价", pos["stop"] == 110.20, str(pos["stop"]))
    check("持仓含止盈价", abs(pos["take_profit_price"] - 125.40*1.3) < 0.01,
          str(pos["take_profit_price"]))

    r = c.get("/sim")
    html = r.get_data(as_text=True)
    check("页面含持仓渲染逻辑(JS)", "renderPositions" in html)
    check("页面含买入逻辑(JS)", "api/sim/buy" in html)

    print("=== 手动结算接口 ===")
    r = c.post("/api/sim/settle")
    check("结算接口 200", r.status_code == 200, str(r.status_code))
    check("结算返回 date", bool(r.get_json().get("date")))

    # 清理
    sim_utils.reset_account()
    print(f"\n{'='*40}\n结果：{PASS} 通过 / {FAIL} 失败")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
