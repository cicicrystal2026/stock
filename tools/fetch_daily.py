# -*- coding: utf-8 -*-
"""拉取池内全部标的的日线数据（前复权 330 根），缓存到本地。

数据源：腾讯 web.ifzq.gtimg.cn（前复权 qfq）
  https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=sh688012,day,,,330,qfq
  返回 qfqday: [[日期, 开, 收, 高, 低, 成交量], ...]  （成交量单位=股）

备注：东财 push2his 的 kline 接口目前 RemoteDisconnected（2026-10-14 实测），已弃用。
输出：data/cache/daily_330.json  {"names":{}, "bars":{code:[...]}, "source":"tencent", "fetched_at":...}
"""
import json, os, csv, time, threading, sys
from urllib.request import Request, urlopen
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pool_utils import current_pool_path, load_pool_list

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BASE, "data")
CACHE = os.path.join(DATA, "cache")
os.makedirs(CACHE, exist_ok=True)

POOL = current_pool_path()
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
LMT = 330
WORKERS = 6


def ts_symbol(code):
    if code[0] == "6":
        return "sh" + code
    if code[0] in "03":
        return "sz" + code
    return "bj" + code          # 920xxx 等北交所


def get_json(url, retries=3, timeout=20):
    last = None
    for i in range(retries):
        try:
            req = Request(url, headers={"User-Agent": UA})
            with urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except Exception as e:
            last = e
            time.sleep(0.8 + i)
    raise last


def fetch_kline(code):
    sym = ts_symbol(code)
    url = ("https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?"
           f"param={sym},day,,,{LMT},qfq")
    j = get_json(url)
    d = (j.get("data") or {}).get(sym) or {}
    kl = d.get("qfqday") or d.get("day") or []
    nm = ((d.get("qt") or {}).get(sym) or [None] * 2)[1] if d.get("qt") else None
    return nm, kl


codes = [s["code"] for s in load_pool_list()]
print(f"池内标的：{len(codes)} 只", flush=True)

lock = threading.Lock()
bars, names, fail = {}, {}, []
done = 0
t0 = time.time()


def worker(code):
    global done
    try:
        nm, kl = fetch_kline(code)
        with lock:
            if kl:
                bars[code] = kl
                if nm:
                    names[code] = nm
            else:
                fail.append(code)
    except Exception:
        with lock:
            fail.append(code)
    with lock:
        done += 1
        if done % 30 == 0 or done == len(codes):
            print(f"  进度 {done}/{len(codes)}  成功 {len(bars)}  "
                  f"用时 {time.time()-t0:.0f}s", flush=True)
    time.sleep(0.15)


with ThreadPoolExecutor(max_workers=WORKERS) as ex:
    list(ex.map(worker, codes))

print(f"[完成] 成功 {len(bars)}/{len(codes)}，失败 {len(fail)} 只：{fail[:20]}")
assert len(bars) >= len(codes) * 0.95, f"成功率过低：{len(bars)}/{len(codes)}"

with open(os.path.join(CACHE, "daily_330.json"), "w", encoding="utf-8") as f:
    json.dump({"source": "tencent.qfq", "lmt": LMT,
               "fetched_at": time.strftime("%Y-%m-%d %H:%M:%S"),
               "names": names, "bars": bars}, f, ensure_ascii=False)
print(f"耗时 {time.time()-t0:.0f}s  ->  data/cache/daily_330.json")
