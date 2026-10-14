# -*- coding: utf-8 -*-
"""池子统一读写工具：当前生效池子 + 版本快照。

约定：
- 当前生效池子：data/pool_current.csv（表头 代码,名称,所属行业）
- 历史快照：    data/pool_history/pool_<日期>.csv
- 所有脚本（fetch/screen/replay）只读 pool_current.csv；
  若不存在，回退到最新的 pool_*.csv 作为首次初始化。
"""
import os, csv, datetime, json, shutil

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BASE, "data")
HISTORY = os.path.join(DATA, "pool_history")
CURRENT = os.path.join(DATA, "pool_current.csv")
META = os.path.join(DATA, "pool_meta.json")


def _list_pool_csv():
    out = []
    for fn in os.listdir(DATA):
        if fn.startswith("pool_") and fn.endswith(".csv") and fn != "pool_current.csv":
            out.append(os.path.join(DATA, fn))
    out.sort()
    return out


def current_pool_path():
    if os.path.exists(CURRENT):
        return CURRENT
    pools = _list_pool_csv()
    if pools:
        return pools[-1]
    return None


def load_pool():
    """返回 {code: {"name":.., "industry":..}}，按 csv 顺序（Python dict 保序）。"""
    path = current_pool_path()
    pool = {}
    if not path:
        return pool
    with open(path, encoding="utf-8-sig", newline="") as f:
        for row in csv.reader(f):
            if row and row[0].strip().isdigit():
                pool[row[0].strip()] = {"name": row[1].strip(), "industry": row[2].strip() if len(row) > 2 else ""}
    return pool


def load_pool_list():
    """返回有序列表 [{code,name,industry}]。"""
    return [{"code": c, "name": v["name"], "industry": v["industry"]}
            for c, v in load_pool().items()]


def save_pool(stocks):
    """stocks: [{code,name,industry}]，全量覆盖写入 pool_current.csv。"""
    os.makedirs(DATA, exist_ok=True)
    with open(CURRENT, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["代码", "名称", "所属行业"])
        for s in stocks:
            w.writerow([s["code"], s["name"], s["industry"]])
    _write_meta(len(stocks))


def _write_meta(count):
    meta = {"count": count,
            "updated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
    with open(META, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False)


def snapshot_pool(label=""):
    """把当前池子复制一份到 pool_history/，返回快照路径。"""
    if not os.path.exists(CURRENT):
        return None
    os.makedirs(HISTORY, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y-%m-%d")
    dst = os.path.join(HISTORY, f"pool_{ts}{label}.csv")
    shutil.copyfile(CURRENT, dst)
    return dst


def get_meta():
    if os.path.exists(META):
        with open(META, encoding="utf-8") as f:
            return json.load(f)
    return {"count": len(load_pool()), "updated_at": None}


def list_snapshots():
    if not os.path.isdir(HISTORY):
        return []
    out = [f for f in os.listdir(HISTORY) if f.endswith(".csv")]
    out.sort(reverse=True)
    return out
