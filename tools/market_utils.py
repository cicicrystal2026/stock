# -*- coding: utf-8 -*-
"""东方财富 ulist 批量补全名称/行业（供池子管理批量导入用）。

输入：6 位代码列表 -> 返回 {code: {"name":.., "industry":..}}
接口：https://push2.eastmoney.com/api/qt/ulist.np/get  f12=代码 f14=名称 f100=行业
"""
import json, time
from urllib.request import Request, urlopen

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
BATCH = 50


def secid(code):
    return ("1." if code[0] == "6" else "0.") + code


def get_json(url, retries=3):
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


def enrich(codes):
    """批量补齐 {code: {name, industry}}；失败/缺失的代码不返回。"""
    mkt = {}
    for i in range(0, len(codes), BATCH):
        chunk = codes[i:i + BATCH]
        secids = ",".join(secid(c) for c in chunk)
        url = ("https://push2.eastmoney.com/api/qt/ulist.np/get?"
               "fltt=2&invt=2&fields=f12,f13,f14,f100&secids=" + secids)
        try:
            j = get_json(url)
        except Exception:
            continue
        diff = (j.get("data") or {}).get("diff") or []
        if isinstance(diff, dict):
            diff = list(diff.values())
        for it in diff:
            mkt[str(it.get("f12"))] = {
                "name": it.get("f14") or "",
                "industry": it.get("f100") or ""}
        time.sleep(0.4)
    return mkt
