# -*- coding: utf-8 -*-
"""抓取中央汇金系在十大流通股东中的持仓（季报口径）。

两阶段扫描，控制请求量：
  阶段一：最新报告期扫描全候选池，筛出出现国家队身影的股票集合 S；
  阶段二：仅对 S 回溯历史报告期。
结果写入 data/holdings.json，原始响应缓存于 cache/holders/。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import akshare as ak
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config  # noqa: E402
from http_utils import get_json, make_session, run_parallel, to_symbol  # noqa: E402


def log(msg: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


# ---------------------------------------------------------------------------
# 报告期
# ---------------------------------------------------------------------------
def build_periods(n: int) -> list[str]:
    """生成截止当前的 n 个季度报告期（YYYYMMDD）。"""
    today = datetime.today()
    y, m = today.year, today.month
    # 季度末月份 3/6/9/12，披露有滞后，故最后一个未完成季不纳入
    q_end_month = ((m - 1) // 3) * 3 + 3
    if m <= q_end_month:
        q_end_month -= 3
        if q_end_month == 0:
            q_end_month = 12
            y -= 1
    periods = []
    yy, mm = y, q_end_month
    daymap = {3: "0331", 6: "0630", 9: "0930", 12: "1231"}
    for _ in range(n):
        periods.append(f"{yy}{daymap[mm]}")
        mm -= 3
        if mm == 0:
            mm = 12
            yy -= 1
    return sorted(periods)


def fmt_period(p: str) -> str:
    return f"{p[:4]}-{p[4:6]}-{p[6:]}"


# ---------------------------------------------------------------------------
# 候选池
# ---------------------------------------------------------------------------
def get_universe() -> pd.DataFrame:
    if config.UNIVERSE_MODE == "all":
        for attempt in range(3):
            try:
                df = ak.stock_info_a_code_name()  # 新浪：全部 A 股代码/名称
                df = df.rename(columns={"code": "code", "name": "name"})
                df = df[df["code"].astype(str).str.match(r"^(0|3|6)")]
                df = df[~df["name"].astype(str).str.contains("ST|退", na=False)]
                df = df[["code", "name"]].copy()
                df["index"] = "全A"
                uni = df.drop_duplicates("code").reset_index(drop=True)
                uni["market"] = uni["code"].map(
                    lambda c: "sh" if c.startswith("6") else "sz")
                log(f"全 A 候选池 {len(uni)} 只")
                return uni
            except Exception as exc:  # noqa: BLE001
                log(f"全 A 快照第 {attempt + 1} 次失败：{str(exc)[:80]}")
                time.sleep(2 * (attempt + 1))
        log("全 A 快照不可用，回退到指数成分股池")

    frames = []
    for idx in config.INDEX_POOLS:
        try:
            df = ak.index_stock_cons(symbol=idx)
            df = df.rename(columns={"品种代码": "code", "品种名称": "name"})
            df["index"] = idx
            frames.append(df[["code", "name", "index"]])
            log(f"指数 {idx} 成分股 {len(df)} 只")
        except Exception as exc:  # noqa: BLE001
            log(f"指数 {idx} 获取失败: {exc}")
    if not frames:
        raise RuntimeError("候选池为空，检查网络或 INDEX_POOLS 配置")
    uni = pd.concat(frames).drop_duplicates("code").reset_index(drop=True)
    uni["market"] = uni["code"].map(lambda c: "sh" if c.startswith("6") else ("sz" if c[:1] in ("0", "3") else "bj"))
    return uni


# ---------------------------------------------------------------------------
# 十大流通股东
# ---------------------------------------------------------------------------
def _col(df: pd.DataFrame, *keys: str):
    for c in df.columns:
        if all(k in str(c) for k in keys):
            return c
    return None


def _to_num(v):
    if v is None:
        return None
    s = str(v).strip().replace(",", "")
    if s in ("", "-", "nan", "None"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _is_nan(v) -> bool:
    try:
        return bool(pd.isna(v))
    except Exception:  # noqa: BLE001
        return False


def fetch_top10(code: str, period: str, refresh: bool = False) -> list[dict]:
    """返回该股票在该报告期的十大流通股东记录（带本地缓存）。"""
    cache_file = config.RAW_DIR / f"{code}_{period}.json"
    if cache_file.exists() and not refresh:
        try:
            return json.loads(cache_file.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            pass
    rows: list[dict] = []
    last_err = None
    for attempt in range(3):
        try:
            df = ak.stock_gdfx_top_10_em(symbol=to_symbol(code), date=period)
            c_name = _col(df, "名称")
            c_shares = _col(df, "持股") or _col(df, "持股数")
            c_ratio = _col(df, "比例")
            c_change = _col(df, "变化") or _col(df, "变动")
            for _, r in df.iterrows():
                rows.append({
                    "name": str(r.get(c_name, "")).strip(),
                    "shares": _to_num(r.get(c_shares)),
                    "ratio": _to_num(r.get(c_ratio)),
                    "change": r.get(c_change),
                })
            break
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            time.sleep(0.8 * (attempt + 1))
    if last_err is not None and not rows:
        raise RuntimeError(str(last_err))
    cache_file.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    return rows


def is_state_holder(name: str) -> bool:
    return any(k in name for k in config.HOLDER_KEYWORDS)


def group_of(name: str) -> str:
    for label, kws in config.HOLDER_GROUPS:
        if any(k in name for k in kws):
            return label
    return "其他汇金系"


def pick_state_rows(rows: list[dict]) -> list[dict]:
    out = []
    for r in rows:
        if is_state_holder(r["name"]):
            out.append({
                "holder": r["name"],
                "group": group_of(r["name"]),
                "shares": r["shares"],
                "ratio": r["ratio"],
                "change": _to_num(r["change"]),
                "change_raw": None if _is_nan(r["change"]) else str(r["change"]).strip(),
            })
    return out


def scan(args_tuple):
    """返回 (该期十大股东记录条数, 命中的国家队记录列表)。"""
    code, period, refresh = args_tuple
    rows = fetch_top10(code, period, refresh)
    return len(rows), pick_state_rows(rows)


# ---------------------------------------------------------------------------
# 价格
# ---------------------------------------------------------------------------
KLINE_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"


def _save(f: Path, series: dict[str, float]) -> None:
    pd.DataFrame({"date": list(series), "close": list(series.values())}).to_csv(
        f, index=False, encoding="utf-8-sig")


def fetch_prices(codes: list[str], markets: dict[str, str]) -> dict[str, dict[str, float]]:
    """返回 {code: {date_str: close}}（不复权收盘价）。

    主用新浪全历史日线（覆盖 2015 年以来的入场时点），东财作为兜底。
    """
    out: dict[str, dict[str, float]] = {}
    cache_dir = config.CACHE_DIR / "price"
    cache_dir.mkdir(exist_ok=True)
    session = make_session()

    def one(code):
        f = cache_dir / f"{code}.csv"
        if f.exists():
            try:
                df = pd.read_csv(f, dtype={"date": str})
                series = {d: float(c) for d, c in zip(df["date"], df["close"])}
                if series:
                    return code, series
            except Exception:  # noqa: BLE001
                pass
        market = markets.get(code) or ("sh" if code.startswith("6") else "sz")

        # 1) 新浪：一次拿到全部历史日线
        for attempt in range(3):
            try:
                df = ak.stock_zh_a_daily(symbol=market + code, adjust="")
                df["date"] = df["date"].astype(str).str.slice(0, 10)
                series = {d: float(c) for d, c in zip(df["date"], df["close"])}
                if series:
                    _save(f, series)
                    return code, series
            except Exception:  # noqa: BLE001
                time.sleep(0.8 * (attempt + 1))

        # 2) 东财兜底
        params = {
            "secid": f"{1 if market == 'sh' else 0}.{code}",
            "fields1": "f1,f2,f3,f4,f5,f6",
            "fields2": "f51,f53",
            "klt": "101",
            "fqt": "0",
            "beg": "20150101",
            "end": "20500101",
            "lmt": "4000",
            "ut": "7eea3edcaed734bea9cbfc24409ed989",
        }
        for attempt in range(3):
            try:
                data = get_json(session, KLINE_URL, params=params, timeout=20)
                klines = ((data or {}).get("data") or {}).get("klines", [])
                series = {}
                for line in klines:
                    d, c = line.split(",")[:2]
                    series[d] = float(c)
                if series:
                    _save(f, series)
                    return code, series
            except Exception:  # noqa: BLE001
                time.sleep(0.8 * (attempt + 1))
        return code, {}

    res = run_parallel(one, codes, workers=6, desc="拉取行情")
    for item, result, err in res:
        if result and result[1]:
            code, series = result
            out[code] = series
        elif err:
            log(f"行情失败 {item}: {err}")
    return out


def close_on_or_before(series: dict[str, float], period: str) -> float | None:
    """取报告期末当日（或之前最近交易日）收盘价。"""
    if not series:
        return None
    target = fmt_period(period)
    keys = [d for d in series if d <= target]
    if not keys:
        return None
    return series[max(keys)]


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--periods", type=int, default=config.PERIODS_BACK)
    ap.add_argument("--refresh", action="store_true", help="忽略本地缓存重新抓取")
    args = ap.parse_args()

    periods = build_periods(args.periods)
    log(f"报告期: {periods}")

    uni = get_universe()
    log(f"候选池合计 {len(uni)} 只")

    # ---- 阶段一：最近两期全池扫描（规避最新期披露不全）----
    scan_periods = periods[-2:] if len(periods) >= 2 else periods
    latest_hits: dict[str, dict[str, list[dict]]] = {}
    scanned: list[str] = []
    coverage: dict[str, float] = {}
    for p in scan_periods:
        log(f"阶段一：扫描报告期 {p}（全池 {len(uni)} 只）")
        res = run_parallel(scan, [(c, p, args.refresh) for c in uni["code"]],
                           workers=config.MAX_WORKERS, desc=f"{p} 扫描")
        hits = 0
        non_empty = 0
        for (code, _, _), result, err in res:
            if err is not None or result is None:
                continue
            n_rows, rows = result
            if n_rows:
                non_empty += 1
            if rows:
                latest_hits.setdefault(code, {})[p] = rows
                hits += 1
        coverage[p] = round(non_empty / max(1, len(uni)), 4)
        log(f"  {p} 命中 {hits} 只，披露覆盖 {coverage[p]:.1%}")
        if hits:
            scanned.append(p)
    if not latest_hits:
        raise RuntimeError("最近两期均未命中任何国家队持仓，检查报告期是否已披露")
    latest = max(scanned)

    # ---- 阶段二：命中股票回溯历史期 ----
    tasks = []
    for code, recs in latest_hits.items():
        for p in periods:
            if p not in recs:
                tasks.append((code, p, args.refresh))
    log(f"阶段二：回溯 {len(tasks)} 个（股票 × 报告期）")
    history: dict[str, dict[str, list[dict]]] = {c: dict(v) for c, v in latest_hits.items()}
    if tasks:
        res = run_parallel(scan, tasks, workers=config.MAX_WORKERS, desc="历史期扫描")
        for (code, period, _), result, err in res:
            if result and result[1]:
                history.setdefault(code, {})[period] = result[1]

    codes = sorted(history)
    log(f"国家队持仓股票合计 {len(codes)} 只")

    # ---- 价格 ----
    market_map = dict(zip(uni["code"], uni["market"]))
    prices = fetch_prices(codes, market_map)
    log(f"行情覆盖 {len(prices)} 只")

    # ---- 组装 ----
    name_map = dict(zip(uni["code"], uni["name"]))
    stocks = []
    for code in codes:
        recs = history[code]
        hist = {}
        for p in periods:
            rows = recs.get(p)
            if not rows:
                continue
            shares = sum(r["shares"] or 0 for r in rows)
            ratio = sum(r["ratio"] or 0 for r in rows)
            change = None
            flag = None
            for r in rows:
                if r["change"] is not None:
                    change = (change or 0) + r["change"]
                elif r["change_raw"]:
                    flag = r["change_raw"]
            series = prices.get(code, {})
            by_group: dict[str, float] = {}
            for r in rows:
                by_group[r["group"]] = by_group.get(r["group"], 0.0) + (r["shares"] or 0)
            hist[p] = {
                "shares": shares,
                "ratio": round(ratio, 4),
                "change": change,
                "flag": flag,
                "holders": [r["holder"] for r in rows],
                "groups": sorted({r["group"] for r in rows}),
                "by_group": {g: round(v, 2) for g, v in by_group.items()},
                "close": close_on_or_before(series, p),
                "value": round(shares * close_on_or_before(series, p), 2) if close_on_or_before(series, p) else None,
            }
        if not hist:
            continue
        plist = sorted(hist)
        for i, p in enumerate(plist):
            rec = hist[p]
            chg = rec.get("change") or 0
            rec["event"] = "entry" if i == 0 else ("add" if chg > 0 else ("cut" if chg < 0 else "flat"))
        series = prices.get(code, {})
        last_close = max(series) if series else None
        prev = hist[plist[-2]] if len(plist) >= 2 else None
        entry_close = hist[plist[0]].get("close")
        stocks.append({
            "code": code,
            "name": name_map.get(code, code),
            "market": market_map.get(code, ""),
            "first_period": plist[0],
            "last_period": plist[-1],
            "periods_held": len(plist),
            # 入场时点：首次现身于十大流通股东的报告期
            # entry_truncated=True 表示追踪起点已有持仓，真实入场早于该期、不可知
            "entry_period": plist[0],
            "entry_close": entry_close,
            "entry_truncated": plist[0] == periods[0],
            "pnl_since_entry": ((series[last_close] / entry_close - 1) * 100)
            if (series and entry_close) else None,
            "history": hist,
            "latest": hist[plist[-1]],
            "prev": prev,
            "latest_close": series.get(last_close) if series else None,
            "latest_value": round(hist[plist[-1]]["shares"] * series[last_close], 2)
            if series and hist[plist[-1]].get("shares") else None,
        })
    stocks.sort(key=lambda s: (s["latest"].get("value") or 0), reverse=True)

    # ---- 汇总 ----
    summary = []
    flows = {}
    prev_codes: set[str] = set()
    prev_cur: dict[str, dict] = {}
    for p in periods:
        cur = {s["code"]: s["history"][p] for s in stocks if p in s["history"]}
        new = sorted(set(cur) - prev_codes)
        exit_ = sorted(prev_codes - set(cur))
        add = [c for c in cur if cur[c]["change"] and cur[c]["change"] > 0]
        cut = [c for c in cur if cur[c]["change"] and cur[c]["change"] < 0]
        flat = [c for c in cur if not cur[c]["change"]]
        total_value = sum(v["value"] for v in cur.values() if v.get("value"))
        by_group: dict[str, dict] = {}
        for v in cur.values():
            px = v.get("close")
            for g, sh in (v.get("by_group") or {}).items():
                item = by_group.setdefault(g, {"stock_count": 0, "shares": 0.0, "value": 0.0})
                item["stock_count"] += 1
                item["shares"] += sh
                if px:
                    item["value"] += sh * px
        for g, item in by_group.items():
            item["shares"] = round(item["shares"], 2)
            item["value"] = round(item["value"], 2)
        summary.append({
            "period": p,
            "stock_count": len(cur),
            "total_shares": round(sum(v["shares"] for v in cur.values()), 2),
            "total_value": round(total_value, 2),
            "new": len(new), "exit": len(exit_),
            "add": len(add), "cut": len(cut), "flat": len(flat),
            "by_group": by_group,
        })
        def brief(cs, key, src=None):
            src = src or cur
            rows = []
            for c in cs:
                v = src.get(c) or {}
                rows.append({"code": c, "name": next((s["name"] for s in stocks if s["code"] == c), c),
                             "value": v.get("value"), "shares": v.get("shares"), "change": v.get("change")})
            rows.sort(key=lambda r: abs(r.get(key) or 0), reverse=True)
            return rows[:10]
        flows[p] = {
            "new": brief(new, "value"),
            "exit": brief(exit_, "value", prev_cur),   # 退出个股展示退出前的市值
            "add": brief(add, "change"),
            "cut": brief(cut, "change"),
        }
        prev_codes = set(cur)
        prev_cur = cur

    payload = {
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "scope": "中央汇金投资 / 中央汇金资产管理",
        "periods": periods,
        "universe_size": len(uni),
        "universe_mode": config.UNIVERSE_MODE,
        "index_pools": config.INDEX_POOLS,
        "coverage": coverage,
        "summary": summary,
        "flows": flows,
        "stocks": stocks,
    }
    out = config.DATA_DIR / "holdings.json"
    out.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    log(f"已写入 {out}（{len(stocks)} 只股票 / {len(periods)} 个报告期）")


if __name__ == "__main__":
    main()
