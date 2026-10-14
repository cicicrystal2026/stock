# -*- coding: utf-8 -*-
"""解析顾问 2026-09 核心池 -> 落盘 + 补齐名称/行业。

输入：WPS云盘里的 2026-9核心公司导入文档.txt（纯代码，每行一个）
输出：
  data/pool_2026-09.txt    规范化代码列表
  data/pool_2026-09.csv    代码,名称,行业
  data/pool_2026-09.json   结构化（含元数据）

数据源：东方财富 ulist 批量接口
  https://push2.eastmoney.com/api/qt/ulist.np/get?secids=1.688012,0.300604&fields=f12,f13,f14,f100
  f12=代码 f13=市场(1沪/0深) f14=名称 f100=行业
坑：fs 参数不能 URL 编码；clist 接口目前 502，ulist 正常。
"""
import json, re, os, csv, time
from urllib.request import Request, urlopen
from collections import Counter

SRC = r"C:\Users\admin\WPSDrive\460887772\WPS云盘\07-我要进步\26年有钱君\2026-9核心公司导入文档.txt"
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BASE, "data")
POOL_DATE = "2026-09"
BATCH = 50

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")


def get_json(url, retries=4):
    last = None
    for i in range(retries):
        try:
            req = Request(url, headers={"User-Agent": UA,
                                        "Referer": "https://quote.eastmoney.com/"})
            with urlopen(req, timeout=25) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except Exception as e:
            last = e
            time.sleep(1.5 + i)
    raise last


def secid(code):
    return ("1." if code[0] == "6" else "0.") + code


# ---------- 1. 解析原始文件 ----------
codes = []
with open(SRC, "r", encoding="utf-8", errors="replace") as f:
    for line in f:
        s = line.strip()
        if not s:
            continue
        m = re.search(r"\d{6}", s)
        if m:
            codes.append(m.group(0))

seen, uniq = set(), []
for c in codes:
    if c not in seen:
        seen.add(c)
        uniq.append(c)
codes = uniq

assert len(codes) >= 200, f"解析到的代码太少：{len(codes)}"
assert all(re.fullmatch(r"\d{6}", c) for c in codes), "存在非 6 位代码"
print(f"[1] 解析完成：{len(codes)} 只（去重后）")

with open(os.path.join(DATA, "pool_2026-09.txt"), "w", encoding="utf-8") as f:
    f.write("\n".join(codes) + "\n")

# ---------- 2. 批量补齐名称 / 行业 ----------
mkt = {}
for i in range(0, len(codes), BATCH):
    chunk = codes[i:i + BATCH]
    secids = ",".join(secid(c) for c in chunk)
    url = ("https://push2.eastmoney.com/api/qt/ulist.np/get?"
           "fltt=2&invt=2&fields=f12,f13,f14,f100&secids=" + secids)
    try:
        j = get_json(url)
    except Exception as e:
        print(f"     批次 {i//BATCH+1} 失败：{e}")
        continue
    diff = (j.get("data") or {}).get("diff") or []
    if isinstance(diff, dict):
        diff = list(diff.values())
    for it in diff:
        mkt[str(it.get("f12"))] = (it.get("f14"), it.get("f100"))
    print(f"     批次 {i//BATCH+1}/{(len(codes)+BATCH-1)//BATCH}："
          f"请求 {len(chunk)} 返回 {len(diff)}")
    time.sleep(1.0)

print(f"[2] 匹配到 {len(mkt)}/{len(codes)}")

# 缺失补拉（单只）
missing = [c for c in codes if c not in mkt]
if missing:
    print(f"[2b] 补拉 {len(missing)} 只：{','.join(missing)}")
    for c in missing:
        try:
            j = get_json("https://push2.eastmoney.com/api/qt/stock/get?"
                         f"secid={secid(c)}&fields=f57,f58,f127")
            d = j.get("data") or {}
            if d.get("f58"):
                mkt[c] = (d.get("f58"), d.get("f127"))
        except Exception:
            pass
        time.sleep(0.4)

# ---------- 3. 输出 ----------
rows = []
for c in codes:
    n, ind = mkt.get(c) or ("", "")
    rows.append([c, n or "", ind or ""])

with open(os.path.join(DATA, "pool_2026-09.csv"), "w",
          encoding="utf-8-sig", newline="") as f:
    w = csv.writer(f)
    w.writerow(["代码", "名称", "所属行业"])
    w.writerows(rows)

matched = sum(1 for r in rows if r[1])
print(f"[3] CSV 落地：{len(rows)} 行，匹配到名称 {matched} 只")

ind = Counter(r[2] for r in rows if r[2])
print("[4] 行业分布 Top25：")
for k, v in ind.most_common(25):
    print(f"     {v:>3}  {k}")

payload = {
    "pool_name": "顾问核心池",
    "pool_date": POOL_DATE,
    "source": SRC,
    "count": len(rows),
    "matched": matched,
    "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    "stocks": [{"code": r[0], "name": r[1], "industry": r[2]} for r in rows],
}
with open(os.path.join(DATA, "pool_2026-09.json"), "w", encoding="utf-8") as f:
    json.dump(payload, f, ensure_ascii=False, indent=2)

if matched < len(rows):
    miss = [r[0] for r in rows if not r[1]]
    print(f"[!] 仍缺名称 {len(miss)} 只：{','.join(miss)}")
else:
    print("[OK] 全部代码均匹配到名称")
