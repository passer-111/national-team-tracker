# -*- coding: utf-8 -*-
"""全局配置：国家队口径、股票候选池、ETF 观察池、报告期。

数据源全部为免费公开接口（东方财富 / 上交所），无需 token。
"""
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
CACHE_DIR = BASE_DIR / "cache"
RAW_DIR = CACHE_DIR / "holders"

for _d in (DATA_DIR, CACHE_DIR, RAW_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# 国家队主体口径：中央汇金系
# ---------------------------------------------------------------------------
# 十大流通股东中，"股东名称" 命中任一关键词即计入国家队持仓
HOLDER_KEYWORDS = [
    "中央汇金",      # 中央汇金投资有限责任公司
    "汇金资管",      # 中央汇金资产管理有限责任公司
]

# 分组展示用的标签（按顺序匹配，命中即归组）
HOLDER_GROUPS = [
    ("中央汇金投资", ["中央汇金投资"]),
    ("中央汇金资管", ["中央汇金资产管理", "汇金资管"]),
]

# ---------------------------------------------------------------------------
# 股票候选池
# ---------------------------------------------------------------------------
# "all"    = 扫描全部 A 股（约 5000 只，最完整，首次约 10 分钟）
# "index"  = 仅扫描 INDEX_POOLS 成分股（约 800 只，速度快）
UNIVERSE_MODE = "all"
INDEX_POOLS = ["000300", "000905"]   # UNIVERSE_MODE="index" 时生效
PERIODS_BACK = 8                      # 回溯报告期数量（季报，8 期 ≈ 两年）
MAX_WORKERS = 16

# ---------------------------------------------------------------------------
# ETF 观察池：宽基 ETF 的成交额 / 份额变化
# state_owned=True 表示公开报道中中央汇金曾出现在其前十大持有人名单里；
# 该标记为人工维护口径，可在本文件直接增改。
# ---------------------------------------------------------------------------
ETF_WATCH = [
    {"code": "510300", "name": "沪深300ETF", "market": "sh", "state_owned": True},
    {"code": "510310", "name": "沪深300ETF易方达", "market": "sh", "state_owned": True},
    {"code": "510330", "name": "沪深300ETF华夏", "market": "sh", "state_owned": True},
    {"code": "510050", "name": "上证50ETF", "market": "sh", "state_owned": True},
    {"code": "510500", "name": "中证500ETF", "market": "sh", "state_owned": True},
    {"code": "512100", "name": "中证1000ETF", "market": "sh", "state_owned": True},
    {"code": "588000", "name": "科创50ETF", "market": "sh", "state_owned": True},
    {"code": "510180", "name": "上证180ETF", "market": "sh", "state_owned": False},
    {"code": "510880", "name": "红利ETF", "market": "sh", "state_owned": False},
    {"code": "159919", "name": "沪深300ETF嘉实", "market": "sz", "state_owned": True},
    {"code": "159915", "name": "创业板ETF", "market": "sz", "state_owned": True},
    {"code": "159901", "name": "深证100ETF", "market": "sz", "state_owned": False},
    {"code": "159338", "name": "中证A500ETF", "market": "sz", "state_owned": False},
]

ETF_HIST_DAYS = 120      # 行情回溯交易日
ETF_SHARE_DAYS = 60      # 份额回溯交易日（上交所口径，仅沪市）

# ---------------------------------------------------------------------------
# 说明文案（网页底部展示）
# ---------------------------------------------------------------------------
DISCLAIMER = (
    "国家队口径为“中央汇金投资 / 中央汇金资产管理”，识别自上市公司定期报告披露的"
    "十大流通股东名单；持股市值 = 持股数 × 报告期末（或最新）收盘价，为估算值。"
    "ETF 份额为上海证券交易所每日申赎清单口径（仅沪市），成交额与份额变化仅可作为"
    "资金托底力度的间接推断，不代表实际持仓。"
)
