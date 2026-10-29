# -*- coding: utf-8 -*-
"""一键更新全部数据：持仓（季报）+ ETF（日频），并生成 data/meta.json。

用法：
    python scripts/run_all.py                 # 全量更新
    python scripts/run_all.py --skip-holders  # 只更新 ETF
    python scripts/run_all.py --skip-etf      # 只更新持仓
    python scripts/run_all.py --refresh       # 忽略缓存重新抓取
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config  # noqa: E402

HERE = Path(__file__).resolve().parent


def run(script: str, extra: list[str]) -> None:
    cmd = [sys.executable, "-X", "utf8", str(HERE / script), *extra]
    print(f"\n>>> {' '.join(cmd)}", flush=True)
    ret = subprocess.run(cmd, cwd=str(config.BASE_DIR))
    if ret.returncode != 0:
        raise SystemExit(f"{script} 执行失败（code={ret.returncode}）")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-holders", action="store_true")
    ap.add_argument("--skip-etf", action="store_true")
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--periods", type=int, default=config.PERIODS_BACK)
    args = ap.parse_args()

    extra = ["--refresh"] if args.refresh else []
    if not args.skip_holders:
        run("fetch_holders.py", [*extra, "--periods", str(args.periods)])
    if not args.skip_etf:
        run("fetch_etf.py", extra)

    meta = {
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "keyword": config.HOLDER_KEYWORDS,
        "index_pools": config.INDEX_POOLS,
        "etf_watch": [f"{e['code']} {e['name']}" for e in config.ETF_WATCH],
        "disclaimer": config.DISCLAIMER,
        "sources": [
            "东方财富 - 十大流通股东（上市公司定期报告）",
            "东方财富 - 个股/ETF 日线行情",
            "上海证券交易所 - ETF 每日申赎清单（份额）",
        ],
    }
    out = config.DATA_DIR / "meta.json"
    out.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n已写入 {out}")


if __name__ == "__main__":
    main()
