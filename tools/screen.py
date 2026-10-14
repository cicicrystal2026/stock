# -*- coding: utf-8 -*-
"""每日扫描（双策略）：对顾问池逐只判定两个技术面策略，出 Markdown 日报 + CSV。

【策略一】250日均线巨量策略（上升初期）—— conditions c1..c8
  c1 250日线向上        c2 30/60日线在250线下方   c3 30/60日线向上
  c4 量比>=2            c5 日线MACD红柱发散        c6 周线MACD DIF向上
  c7 收盘站上250日线    c8 当日完成突破

【策略二】均线多头巨量策略（上升中期）—— conditions s1..s5
  s1 20/120/250日线均向上
  s2 多头排列（20>120>250）
  s3 量比>=2
  s4 MACD 双确认（=c5 and c6）
  s5 收盘创20日新高（突破的实现假设，待与顾问确认）

【通用风控参数】仓位<=3成；策略一止损=250日线-5%；策略二止损=巨量日最低点 或 -9%；
成本保护=浮盈10%上移成本价；止盈：策略一 30%卖1/3，策略二 20%卖1/3。

分档（每策略独立）：
  A  符合买点（全部条件）
  B  核心信号成立（策略一：c7+c8+c4；策略二：s1+s2+s3）但未全中
  C  观察（策略一：c8；策略二：s1+s2 多头但量不足）
  N  次新股，K线不足260根
"""
import json, os, csv, datetime, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BASE, "data")
REPORTS = os.path.join(BASE, "reports")
os.makedirs(REPORTS, exist_ok=True)

from pool_utils import load_pool

with open(os.path.join(DATA, "cache", "daily_330.json"), encoding="utf-8") as f:
    cache = json.load(f)
bars_all = cache["bars"]

# 当日资金流（最新一份 flow_*.json）
flow = {}
_flow_files = [x for x in os.listdir(os.path.join(DATA, "cache"))
               if x.startswith("flow_") and x.endswith(".json")]
if _flow_files:
    _flow_files.sort()
    with open(os.path.join(DATA, "cache", _flow_files[-1]), encoding="utf-8") as f:
        flow = json.load(f)

pool = load_pool()  # {code: {"name":.., "industry":..}}


def ema(vals, n):
    k = 2.0 / (n + 1); out, e = [], None
    for v in vals:
        e = v if e is None else v * k + e * (1 - k); out.append(e)
    return out


def macd(closes):
    ef, es = ema(closes, 12), ema(closes, 26)
    dif = [a - b for a, b in zip(ef, es)]
    dea = ema(dif, 9)
    return dif, dea, [2 * (d - s) for d, s in zip(dif, dea)]


def sma(vals, n):
    return None if len(vals) < n else sum(vals[-n:]) / n


def sma_prev(vals, n):
    return None if len(vals) < n + 1 else sum(vals[-n - 1:-1]) / n


def weekly_closes(bars):
    wk, order = {}, []
    for b in bars:
        d = datetime.date.fromisoformat(b[0]); k = d.isocalendar()[:2]
        if k not in wk:
            order.append(k)
        wk[k] = float(b[2])
    return [wk[k] for k in order]


rows, newstocks, last_date = [], [], None
for code, bars in bars_all.items():
    last_date = max(last_date or "", bars[-1][0])
    _p = pool.get(code) or {}
    nm, ind = _p.get("name", ""), _p.get("industry", "")
    if len(bars) < 260:
        newstocks.append({"code": code, "name": nm, "industry": ind,
                          "bars": len(bars), "first": bars[0][0]})
        continue

    closes = [float(b[2]) for b in bars]
    vols = [float(b[5]) for b in bars]
    lows = [float(b[4]) for b in bars]
    close, prev = closes[-1], closes[-2]

    ma5, ma10, ma20 = sma(closes, 5), sma(closes, 10), sma(closes, 20)
    ma30, ma60 = sma(closes, 30), sma(closes, 60)
    ma120 = sma(closes, 120)
    ma250, ma250p = sma(closes, 250), sma_prev(closes, 250)
    ma30p, ma60p = sma_prev(closes, 30), sma_prev(closes, 60)
    ma20p, ma120p = sma_prev(closes, 20), sma_prev(closes, 120)
    vma50 = sma(vols, 50)
    vratio = vols[-1] / vma50 if vma50 else 0

    _, _, hist = macd(closes)
    wcloses = weekly_closes(bars)
    wdif = macd(wcloses)[0] if len(wcloses) > 35 else None

    macd_ok = (hist[-1] > 0 and hist[-1] > hist[-2]) and \
              (wdif is not None and wdif[-1] > wdif[-2])

    # ---- 策略一：250日线（上升初期）----
    c1 = ma250 > ma250p
    c2 = (ma30 < ma250) and (ma60 < ma250)
    c3 = (ma30 > ma30p) and (ma60 > ma60p)
    c4 = vratio >= 2.0
    c5 = hist[-1] > 0 and hist[-1] > hist[-2]
    c6 = (wdif is not None) and (wdif[-1] > wdif[-2])
    c7 = close > ma250
    c8 = (prev <= ma250p) and (close > ma250)
    s1_score = sum([c1, c2, c3, c4, c5, c6, c7, c8])

    # ---- 策略二：均线多头（上升中期）----
    S1 = (ma20 > ma20p) and (ma120 > ma120p) and (ma250 > ma250p)
    S2 = (ma20 > ma120 > ma250)
    S3 = c4
    S4 = macd_ok
    S5 = close > max(closes[-21:-1]) if len(closes) >= 21 else False
    s2_score = sum([S1, S2, S3, S4, S5])

    rows.append({
        "code": code, "name": nm, "industry": ind,
        "close": close, "chg": (close / prev - 1) * 100,
        "low": lows[-1],
        "vratio": vratio, "s1_score": s1_score, "s2_score": s2_score,
        "f62e": (flow.get(code, {}).get("f62") or 0) / 1e8,
        "f184": flow.get(code, {}).get("f184"),
        "turnover": flow.get(code, {}).get("f8"),
        "c1": c1, "c2": c2, "c3": c3, "c4": c4, "c5": c5, "c6": c6,
        "c7": c7, "c8": c8,
        "ma250": ma250, "dist250": (close / ma250 - 1) * 100,
        "stop1": ma250 * 0.95,
        "S1": S1, "S2": S2, "S3": S3, "S4": S4, "S5": S5,
        "ma5": ma5, "ma10": ma10, "ma20": ma20,
        "stop2": min(lows[-1], close * 0.91),
        "high20": max(closes[-21:-1]) if len(closes) >= 21 else None,
    })

A1 = [r for r in rows if r["s1_score"] == 8]
B1 = [r for r in rows if r["c7"] and r["c8"] and r["c4"] and r["s1_score"] < 8]
C1 = [r for r in rows if r["c8"] and not r["c4"]]

A2 = [r for r in rows if r["s2_score"] == 5]
B2 = [r for r in rows if r["S1"] and r["S2"] and r["S3"] and r["s2_score"] < 5]
C2 = [r for r in rows if r["S1"] and r["S2"] and not r["S3"]]

rows.sort(key=lambda r: (-(r["s1_score"] + r["s2_score"]), -r["vratio"]))


def table(lst, cols, score_key):
    if not lst:
        return ["（无）"]
    head = ("| 代码 | 名称 | 行业 | 收盘 | 涨跌 | 量比 | 主力净流入(亿) | "
            + " | ".join(c[0] for c in cols) + " | 评分 |")
    sep = "|" + "---|" * (8 + len(cols))
    L = [head, sep]
    for r in lst:
        L.append(f"| {r['code']} | {r['name']} | {r['industry']} | {r['close']:.2f} | "
                 f"{r['chg']:+.2f}% | {r['vratio']:.2f} | {r['f62e']:+.2f} | "
                 + " | ".join(c[1](r) for c in cols) + f" | {r[score_key]} |")
    return L


COLS1 = [("买点(MA250)", lambda r: f"{r['ma250']:.2f}"),
         ("止损", lambda r: f"{r['stop1']:.2f}")]
COLS2 = [("MA5", lambda r: f"{r['ma5']:.2f}"),
         ("MA10", lambda r: f"{r['ma10']:.2f}"),
         ("MA20", lambda r: f"{r['ma20']:.2f}"),
         ("止损", lambda r: f"{r['stop2']:.2f}")]

L = []
L.append(f"# 池内扫描日报（双策略） · {last_date}")
L.append("")
L.append("> 池子：顾问核心池 2026-09（299 只）｜数据：腾讯前复权日线，截至 " + last_date)
L.append(">")
L.append("> 两策略均以「清风火种体系」前三步为前提（主线行业→顶尖公司→成长估值）。")
L.append("> 本报告只做第四步技术面判定，**不校验前提**——前提由顾问的池子承担。")
L.append("")
L.append("## 结论速览")
L.append("")
L.append("| 策略 | A 符合买点 | B 核心信号 | C 观察 |")
L.append("|---|---|---|---|")
L.append(f"| 一：250日均线巨量（上升初期） | **{len(A1)}** | {len(B1)} | {len(C1)} |")
L.append(f"| 二：均线多头巨量（上升中期） | **{len(A2)}** | {len(B2)} | {len(C2)} |")
L.append("")

# ---- 资金面警示 ----
_sig = [r for r in (A1 + B1 + A2 + B2) if r["f62e"] < 0]
L.append("## 资金面警示")
L.append("")
L.append("下列标的技术面信号成立，但当日**主力资金净流出**（大资金出货、散户接盘），需警惕：")
L.append("")
L.append("| 代码 | 名称 | 收盘 | 涨跌 | 主力净流入(亿) | 所属信号 |")
L.append("|---|---|---|---|---|---|")
if _sig:
    for r in _sig:
        tag = "策略一" if r in (A1 + B1) else "策略二"
        L.append(f"| {r['code']} | {r['name']} | {r['close']:.2f} | {r['chg']:+.2f}% | "
                 f"{r['f62e']:+.2f} | {tag} |")
else:
    L.append("| — | — | — | — | — | 今日无此情形 |")
L.append("")

L.append("## 策略一：250日均线巨量（上升初期）")
L.append("")
L.append("### A 档 · 符合买点（8 项全中）｜买点=250日线，止损=250日线-5%")
L.append("")
L += table(A1, COLS1, "s1_score")
L.append("")
L.append("### B 档 · 当日放量突破 250 日线（均线结构/MACD 未齐）")
L.append("")
L += table(B1, COLS1, "s1_score")
L.append("")
L.append("### C 档 · 当日突破但量能不足")
L.append("")
L += table(C1, COLS1, "s1_score")
L.append("")

L.append("## 策略二：均线多头巨量（上升中期）")
L.append("")
L.append("### A 档 · 符合买点（5 项全中）｜买点=5/10/20日线附近，止损=巨量日最低 或 -9%")
L.append("")
L += table(A2, COLS2, "s2_score")
L.append("")
L.append("### B 档 · 多头排列 + 放巨量（MACD/新高 未齐）")
L.append("")
L += table(B2, COLS2, "s2_score")
L.append("")
L.append("### C 档 · 多头排列但量能不足")
L.append("")
L += table(C2, COLS2, "s2_score")
L.append("")

L.append("## N 档：次新股（K线不足260根，两策略均不适用）")
L.append("")
L.append(f"共 {len(newstocks)} 只：" +
         "、".join(f"{r['code']} {r['name']}" for r in
                   sorted(newstocks, key=lambda x: x["bars"])))
L.append("")
L.append("---")
L.append("")
L.append("*由本地脚本自动生成，仅作技术面信号的机械判定，不校验基本面前提，不构成投资建议。*")

md = os.path.join(REPORTS, f"screen_{last_date}.md")
with open(md, "w", encoding="utf-8") as f:
    f.write("\n".join(L))

out = os.path.join(DATA, f"screen_{last_date}.csv")
cols = ["code", "name", "industry", "close", "chg", "low", "vratio",
        "f62e", "f184", "turnover",
        "s1_score", "c1", "c2", "c3", "c4", "c5", "c6", "c7", "c8",
        "ma250", "dist250", "stop1",
        "s2_score", "S1", "S2", "S3", "S4", "S5", "ma5", "ma10", "ma20",
        "stop2", "high20"]
with open(out, "w", encoding="utf-8-sig", newline="") as f:
    w = csv.DictWriter(f, fieldnames=cols)
    w.writeheader()
    w.writerows(rows)

# ---- 输出结构化 JSON，供 Web 看板渲染 ----
from collections import Counter

def _clean(r, score_key, strategy):
    d = {"code": r["code"], "name": r["name"], "industry": r["industry"],
         "close": round(r["close"], 2), "chg": round(r["chg"], 2),
         "vratio": round(r["vratio"], 2), "f62e": round(r["f62e"], 2),
         "f184": r["f184"], "turnover": r["turnover"],
         "score": r[score_key], "strategy": strategy}
    if strategy == 1:
        d["ma250"] = round(r["ma250"], 2)
        d["stop"] = round(r["stop1"], 2)
        d["dist250"] = round(r["dist250"], 2)
    else:
        d["ma5"] = round(r["ma5"], 2)
        d["ma10"] = round(r["ma10"], 2)
        d["ma20"] = round(r["ma20"], 2)
        d["stop"] = round(r["stop2"], 2)
    return d

_wd = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
_flow_pos = sum(1 for v in flow.values() if (v.get("f62") or 0) > 0)
_flow_neg = sum(1 for v in flow.values() if (v.get("f62") or 0) < 0)

screen_json = {
    "meta": {
        "date": last_date,
        "weekday": _wd[datetime.date.fromisoformat(last_date).weekday()],
        "pool_count": len(pool),
        "valid_count": len(rows),
        "newstock_count": len(newstocks),
        "flow_positive": _flow_pos,
        "flow_negative": _flow_neg,
        "flow_total": len(flow),
    },
    "kpi": {
        "s1": {"A": len(A1), "B": len(B1), "C": len(C1)},
        "s2": {"A": len(A2), "B": len(B2), "C": len(C2)},
        "flow_warn": len(_sig),
    },
    "candidates": {
        "s1": {"A": [_clean(r, "s1_score", 1) for r in A1],
               "B": [_clean(r, "s1_score", 1) for r in B1],
               "C": [_clean(r, "s1_score", 1) for r in C1]},
        "s2": {"A": [_clean(r, "s2_score", 2) for r in A2],
               "B": [_clean(r, "s2_score", 2) for r in B2],
               "C": [_clean(r, "s2_score", 2) for r in C2]},
    },
    "flow_warn": [{"code": r["code"], "name": r["name"], "close": round(r["close"], 2),
                   "chg": round(r["chg"], 2), "f62e": round(r["f62e"], 2),
                   "tag": "策略一" if r in (A1 + B1) else "策略二"} for r in _sig],
    "newstocks": [{"code": r["code"], "name": r["name"], "industry": r["industry"],
                   "bars": r["bars"], "first": r["first"]}
                  for r in sorted(newstocks, key=lambda x: x["bars"])],
    "industry_dist": [{"name": k, "count": v} for k, v in
                      Counter(v["industry"] for v in pool.values() if v["industry"]).most_common()],
}

with open(os.path.join(DATA, "screen_latest.json"), "w", encoding="utf-8") as f:
    json.dump(screen_json, f, ensure_ascii=False)

print(f"数据截止 {last_date}  有效 {len(rows)} 只  次新股 {len(newstocks)} 只")
print(f"策略一(250日线):  A={len(A1)}  B={len(B1)}  C={len(C1)}")
print(f"策略二(均线多头):  A={len(A2)}  B={len(B2)}  C={len(C2)}")
for r in (A1 + A2):
    print(f"  ★ {r['code']} {r['name']}  量比{r['vratio']:.2f}  "
          f"策略一={r['s1_score']}/8  策略二={r['s2_score']}/5")
print(f"报告 -> {md}")
print(f"JSON  -> data/screen_latest.json")
