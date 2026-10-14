# -*- coding: utf-8 -*-
"""批量拉取池内标的的当日资金流，缓存到本地。

数据源：东财 ulist（f62 主力净流入/元、f184 主力占比%、f66 超大单、f72 大单、
        f78 中单、f84 小单、f8 换手率、f10 东财量比、f6 成交额）
输出：data/cache/flow_YYYY-MM-DD.json  {code: {...}}
"""
import json, os, csv, time, sys
from urllib.request import Request, urlopen

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pool_utils import load_pool_list

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BASE, "data")
CACHE = os.path.join(DATA, "cache")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
BATCH = 50


def secid(code):
    return ("1." if code[0] == "6" else "0.") + code


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
            time.sleep(1.0 + i)
    raise last


codes = [s["code"] for s in load_pool_list()]

result = {}
for i in range(0, len(codes), BATCH):
    chunk = codes[i:i + BATCH]
    secids = ",".join(secid(c) for c in chunk)
    url = ("https://push2.eastmoney.com/api/qt/ulist.np/get?fltt=2&invt=2"
           "&fields=f12,f14,f62,f184,f66,f72,f78,f84,f8,f10,f6&secids=" + secids)
    try:
        j = get_json(url)
    except Exception as e:
        print(f"  批次 {i//BATCH+1} 失败：{e}")
        continue
    diff = (j.get("data") or {}).get("diff") or []
    if isinstance(diff, dict):
        diff = list(diff.values())
    for it in diff:
        result[str(it.get("f12"))] = it
    print(f"  批次 {i//BATCH+1}/{(len(codes)+BATCH-1)//BATCH} 返回 {len(diff)}")
    time.sleep(1.0)

date = time.strftime("%Y-%m-%d")
with open(os.path.join(CACHE, f"flow_{date}.json"), "w", encoding="utf-8") as f:
    json.dump(result, f, ensure_ascii=False)

pos = sum(1 for c in codes if (result.get(c) or {}).get("f62", 0) > 0)
print(f"[完成] 拉取 {len(result)}/{len(codes)} 只，其中主力净流入为正 {pos} 只")
