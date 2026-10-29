# -*- coding: utf-8 -*-
"""抓取宽基 ETF 的日成交额与份额变化，用于观察国家队托底力度的高频代理指标。

行情：东方财富日线（沪深均可）
份额：上海证券交易所每日 ETF 申赎清单（仅沪市，单位万份）
输出：data/etf.json
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config  # noqa: E402
from http_utils import get_json, make_session, run_parallel  # noqa: E402

KLINE_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
SSE_URL = "https://query.sse.com.cn/commonQuery.do"
SHARE_CACHE = config.CACHE_DIR / "etf_share"
SHARE_CACHE.mkdir(parents=True, exist_ok=True)


def log(msg: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


def secid(code: str, market: str) -> str:
    return f"{1 if market == 'sh' else 0}.{code}"


def fetch_kline(session, code: str, market: str, days: int) -> list[dict]:
    params = {
        "secid": secid(code, market),
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f53,f57,f59",
        "klt": "101",
        "fqt": "1",
        "end": "20500101",
        "lmt": str(days),
        "ut": "7eea3edcaed734bea9cbfc24409ed989",
    }
    data = get_json(session, KLINE_URL, params=params, timeout=20)
    klines = (data or {}).get("data") or {}
    out = []
    for line in klines.get("klines", []):
        p = line.split(",")
        out.append({"d": p[0], "c": float(p[1]), "a": float(p[2]), "pct": float(p[3])})
    return out


def fetch_share_day(session, date: str) -> dict[str, float]:
    """返回 {etf_code: 份额(份)}，上交所口径。"""
    f = SHARE_CACHE / f"{date}.json"
    if f.exists():
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            pass
    params = {
        "isPagination": "true",
        "pageHelp.pageSize": "10000",
        "pageHelp.pageNo": "1",
        "pageHelp.beginPage": "1",
        "pageHelp.cacheSize": "1",
        "pageHelp.endPage": "1",
        "sqlId": "COMMON_SSE_ZQPZ_ETFZL_XXPL_ETFGM_SEARCH_L",
        "STAT_DATE": date,
    }
    data = get_json(session, SSE_URL, params=params,
                    headers={"Referer": "https://www.sse.com.cn/"}, timeout=25)
    out = {}
    for row in (data or {}).get("pageHelp", {}).get("data", []):
        try:
            out[str(row["SEC_CODE"])] = float(row["TOT_VOL"]) * 1e4  # 万份 -> 份
        except (KeyError, ValueError):
            continue
    f.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    return out


def pct_chg(new: float | None, old: float | None):
    if new is None or old in (None, 0):
        return None
    return round((new / old - 1) * 100, 3)


def main():
    session = make_session()
    log("抓取 ETF 日线行情")
    raw = {}
    res = run_parallel(
        lambda e: (e["code"], fetch_kline(session, e["code"], e["market"], config.ETF_HIST_DAYS)),
        config.ETF_WATCH, workers=8, desc="ETF 行情")
    for (item, result, err) in res:
        if result:
            raw[item["code"]] = result
        else:
            log(f"行情失败 {item['code']}: {err}")

    if not raw:
        raise RuntimeError("ETF 行情全部获取失败")

    # 交易日基准：以数据最全的一只为基准
    base_code = max(raw, key=lambda c: len(raw[c]))
    dates = [r["d"] for r in raw[base_code]]
    log(f"交易日基准 {base_code}，共 {len(dates)} 天")

    share_dates = dates[-config.ETF_SHARE_DAYS:]
    log(f"抓取上交所 ETF 份额（{len(share_dates)} 天）")
    sres = run_parallel(lambda d: (d, fetch_share_day(session, d)), share_dates,
                        workers=8, desc="ETF 份额")
    shares = {d: v for d, v, e in sres if v}

    etfs = []
    for item in config.ETF_WATCH:
        series = raw.get(item["code"])
        if not series:
            continue
        rec = {r["d"]: r for r in series}
        rows = []
        prev_share = None
        for d in dates:
            r = rec.get(d)
            share = shares.get(d, {}).get(item["code"])
            rows.append({
                "d": d,
                "c": r["c"] if r else None,
                "a": r["a"] if r else None,
                "s": share,
            })
            if share is not None:
                prev_share = share
        amounts = [r["a"] for r in rows if r["a"] is not None]
        ma20 = sum(amounts[-21:-1]) / 20 if len(amounts) >= 21 else None
        last = rows[-1]
        share_series = [r["s"] for r in rows if r["s"] is not None]
        etfs.append({
            "code": item["code"],
            "name": item["name"],
            "market": item["market"],
            "state_owned": item["state_owned"],
            "latest": {
                "date": last["d"],
                "close": last["c"],
                "amount": last["a"],
                "amount_ma20": round(ma20, 2) if ma20 else None,
                "amount_ratio": round(last["a"] / ma20, 3) if ma20 and last["a"] else None,
                "share": share_series[-1] if share_series else None,
                "share_chg_5d": pct_chg(share_series[-1], share_series[-6]) if len(share_series) >= 6 else None,
                "share_chg_20d": pct_chg(share_series[-1], share_series[-21]) if len(share_series) >= 21 else None,
            },
            "series": rows[-config.ETF_HIST_DAYS:],
        })

    # 重点 ETF（汇金公开持有）合计成交额：托底力度总览
    key_codes = {e["code"] for e in config.ETF_WATCH if e["state_owned"]}
    agg = []
    for d in dates:
        amt = 0.0
        hit = 0
        for e in etfs:
            if e["code"] not in key_codes:
                continue
            r = next((x for x in e["series"] if x["d"] == d), None)
            if r and r["a"]:
                amt += r["a"]
                hit += 1
        if hit:
            agg.append({"d": d, "amount": round(amt, 2)})
    for i, row in enumerate(agg):
        window = [x["amount"] for x in agg[max(0, i - 20):i]]
        row["amount_ma20"] = round(sum(window) / len(window), 2) if window else None
        row["ratio"] = round(row["amount"] / row["amount_ma20"], 3) if row.get("amount_ma20") else None

    payload = {
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "share_scope": "份额为上交所每日申赎清单口径，仅覆盖沪市 ETF；深市 ETF 无份额数据",
        "dates": dates,
        "etfs": etfs,
        "aggregate": agg,
    }
    out = config.DATA_DIR / "etf.json"
    out.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    log(f"已写入 {out}（{len(etfs)} 只 ETF / {len(dates)} 个交易日）")


if __name__ == "__main__":
    main()
