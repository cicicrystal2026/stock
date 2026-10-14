# -*- coding: utf-8 -*-
"""本地冒烟测试：用 Flask test_client 验证所有路由。测试后清理副作用。"""
import os, sys, json, shutil

BASE = os.path.dirname(os.path.abspath(__file__))
os.environ["STOCK_APP_PASSWORD"] = "test123456"
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.join(BASE, "tools"))

# 备份池子，测完恢复
import pool_utils
CUR = os.path.join(BASE, "data", "pool_current.csv")
backup = open(CUR, encoding="utf-8-sig").read()
hist = pool_utils.HISTORY
snaps_before = set(os.listdir(hist)) if os.path.isdir(hist) else set()

import app as appmod
app = appmod.app
app.config["TESTING"] = True
c = app.test_client()

def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    return cond

ok = True
ok &= check("health", c.get("/api/health").status_code == 200)
r = c.get("/")
ok &= check("未登录看板->302", r.status_code == 302)
r = c.post("/login", data={"password": "wrong"})
ok &= check("错误密码提示", "密码错误" in r.get_data(as_text=True))
r = c.post("/login", data={"password": "test123456"})
ok &= check("登录成功->/", r.status_code == 302 and r.headers.get("Location").endswith("/"))
r = c.get("/")
html = r.get_data(as_text=True)
ok &= check("看板渲染", r.status_code == 200 and "优选决策台" in html and "2026-10-14" in html)
r = c.get("/pool")
ok &= check("池子页渲染", r.status_code == 200 and "池子管理" in r.get_data(as_text=True))
r = c.get("/api/pool")
j = r.get_json()
ok &= check("api/pool 列表", j["count"] == 299 and j["stocks"][0]["code"] == "688012")
r = c.post("/api/pool", json={"text": "688012 中微公司 半导体", "mode": "merge"})
ok &= check("api/pool 导入(带名称)", r.get_json().get("ok") is True)
r = c.get("/api/dashboard")
j = r.get_json()
ok &= check("api/dashboard 数据", j["screen"]["meta"]["date"] == "2026-10-14")

# 清理副作用
open(CUR, "w", encoding="utf-8-sig").write(backup)
if os.path.isdir(hist):
    for f in os.listdir(hist):
        if f not in snaps_before:
            os.remove(os.path.join(hist, f))
cfg = os.path.join(BASE, "data", "config.json")
if os.path.exists(cfg):
    os.remove(cfg)

print("\n结果:", "全部通过 ✓" if ok else "存在失败 ✗")
sys.exit(0 if ok else 1)
