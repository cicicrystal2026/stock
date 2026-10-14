# -*- coding: utf-8 -*-
"""双策略回放对比：250日均线（上升初期）vs 均线多头（上升中期）。

窗口：最近 60 个交易日；末端不足 5/10 日的触发点记为「数据不足」不参与统计。
"""
import json, os, csv, datetime, sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pool_utils import load_pool

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BASE, "data")
T = 60

with open(os.path.join(DATA, "cache", "daily_330.json"), encoding="utf-8") as f:
    cache = json.load(f)
bars_all = cache["bars"]

pool = load_pool()  # {code: {"name":.., "industry":..}}


def ema_series(vals, n):
    k = 2.0 / (n + 1); out, e = [], None
    for v in vals:
        e = v if e is None else v * k + e * (1 - k); out.append(e)
    return out


def macd_series(closes):
    ef, es = ema_series(closes, 12), ema_series(closes, 26)
    dif = [a - b for a, b in zip(ef, es)]
    dea = ema_series(dif, 9)
    return dif, [2 * (d - s) for d, s in zip(dif, dea)]


def ma_series(vals, n):
    out = [None] * len(vals); s = 0.0
    for i, v in enumerate(vals):
        s += v
        if i >= n:
            s -= vals[i - n]
        if i >= n - 1:
            out[i] = s / n
    return out


strict1, loose1 = [], []      # 策略一
strict2, loose2 = [], []      # 策略二

for code, bars in bars_all.items():
    n = len(bars)
    if n < 275:
        continue
    closes = [float(b[2]) for b in bars]
    vols = [float(b[5]) for b in bars]
    dates = [b[0] for b in bars]

    ma20 = ma_series(closes, 20)
    ma30 = ma_series(closes, 30)
    ma60 = ma_series(closes, 60)
    ma120 = ma_series(closes, 120)
    ma250 = ma_series(closes, 250)
    vma50 = ma_series(vols, 50)
    _, hist = macd_series(closes)

    wk, wclose, bar2w = {}, [], [0] * n
    for i, b in enumerate(bars):
        key = datetime.date.fromisoformat(b[0]).isocalendar()[:2]
        if key not in wk:
            wk[key] = len(wclose); wclose.append(float(b[2]))
        else:
            wclose[wk[key]] = float(b[2])
        bar2w[i] = wk[key]
    wdif = macd_series(wclose)[0] if len(wclose) > 35 else None

    for i in range(max(250, n - T), n):
        if None in (ma250[i], ma250[i - 1], vma50[i], ma30[i], ma60[i],
                    ma30[i - 1], ma60[i - 1], ma20[i], ma20[i - 1],
                    ma120[i], ma120[i - 1]):
            continue
        chist = hist[i] > 0 and hist[i] > hist[i - 1]
        c6 = bool(wdif) and bar2w[i] >= 1 and wdif[bar2w[i]] > wdif[bar2w[i] - 1]
        vr = vols[i] / vma50[i]

        c1 = ma250[i] > ma250[i - 1]
        c2 = ma30[i] < ma250[i] and ma60[i] < ma250[i]
        c3 = ma30[i] > ma30[i - 1] and ma60[i] > ma60[i - 1]
        c4 = vr >= 2.0
        c7 = closes[i] > ma250[i]
        c8 = closes[i - 1] <= ma250[i - 1] and closes[i] > ma250[i]
        s1_all = sum([c1, c2, c3, c4, chist, c6, c7, c8])

        s1 = ma20[i] > ma20[i - 1] and ma120[i] > ma120[i - 1] and ma250[i] > ma250[i - 1]
        s2 = ma20[i] > ma120[i] > ma250[i]
        s3 = c4
        s4 = chist and c6
        s5 = closes[i] > max(closes[i - 20:i])
        s2_all = sum([s1, s2, s3, s4, s5])

        f5 = (closes[i + 5] / closes[i] - 1) * 100 if i + 5 <= n - 1 else None
        f10 = (closes[i + 10] / closes[i] - 1) * 100 if i + 10 <= n - 1 else None
        rec = (dates[i], code, (pool.get(code) or {}).get("name", ""), f5, f10)

        if s1_all == 8:
            strict1.append(rec)
        if c8 and c4:
            loose1.append(rec)
        if s2_all == 5:
            strict2.append(rec)
        if s2 and s3:
            loose2.append(rec)


def report(title, hits):
    stats = {"title": title, "triggers": len(hits),
             "stocks": len(set(h[1] for h in hits))}
    print(f"=== {title}：{len(hits)} 次 / 涉及 {stats['stocks']} 只 ===")
    byday = defaultdict(list)
    for d, c, n_, f5, f10 in hits:
        byday[d].append((c, n_, f5))
    for d in sorted(byday):
        parts = [f"{c} {n_}" + (f"(5日{f5:+.1f}%)" if f5 is not None else "(不足)")
                 for c, n_, f5 in byday[d]]
        print(f"  {d}  {len(parts)} 只： " + " | ".join(parts))
    s5 = [h[3] for h in hits if h[3] is not None]
    s10 = [h[4] for h in hits if h[4] is not None]
    if s5:
        avg5, med5 = sum(s5) / len(s5), sorted(s5)[len(s5) // 2]
        win5 = sum(1 for x in s5 if x > 0) / len(s5) * 100
        hi = max(s5)
        ex = (sum(s5) - hi) / (len(s5) - 1) if len(s5) > 1 else None
        stats["f5"] = {"n": len(s5), "avg": round(avg5, 2), "med": round(med5, 2),
                       "win": round(win5, 0), "hi": round(hi, 2)}
        if ex is not None:
            stats["f5"]["ex_hi"] = round(ex, 2)
        print(f"  → 次5日 n={len(s5)}  平均 {avg5:+.2f}%  中位 {med5:+.2f}%  胜率 {win5:.0f}%")
        if ex is not None:
            print(f"     最高 {hi:+.1f}%；剔除最高后平均 {ex:+.2f}%")
    if s10:
        avg10 = sum(s10) / len(s10)
        win10 = sum(1 for x in s10 if x > 0) / len(s10) * 100
        stats["f10"] = {"n": len(s10), "avg": round(avg10, 2), "win": round(win10, 0)}
        print(f"  → 次10日 n={len(s10)}  平均 {avg10:+.2f}%  胜率 {win10:.0f}%")
    print()
    return stats


_asof = max(b[-1][0] for b in bars_all.values())
print(f"回放窗口：最近 {T} 个交易日（截止 {_asof}）\n")
res = [
    report("策略一 · 严格（8项全中）", strict1),
    report("策略一 · 宽松（突破+量比≥2）", loose1),
    report("策略二 · 严格（5项全中）", strict2),
    report("策略二 · 宽松（多头+量比≥2）", loose2),
]
print("注：样本极小，仅用于判断触发频率，不作胜率结论。")

replay_json = {"window": T, "as_of": _asof, "strategies": res}
with open(os.path.join(DATA, "replay_latest.json"), "w", encoding="utf-8") as f:
    json.dump(replay_json, f, ensure_ascii=False)
print("JSON -> data/replay_latest.json")
