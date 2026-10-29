# -*- coding: utf-8 -*-
"""带重试的 HTTP 会话与并发工具。

东方财富/上交所接口偶发连接中断，统一在此处做退避重试，
避免个别请求失败导致整条管线中断。
"""
import random
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")


def make_session(pool_size: int = 32) -> requests.Session:
    session = requests.Session()
    session.headers.update({
        "User-Agent": UA,
        "Accept": "*/*",
        "Accept-Language": "zh-CN,zh;q=0.9",
    })
    retry = Retry(
        total=4,
        backoff_factor=0.8,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET"]),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=pool_size, pool_maxsize=pool_size)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


def get_json(session: requests.Session, url: str, params=None, headers=None,
             timeout: int = 20, tries: int = 3):
    """GET + json 解析，失败自动退避重试。"""
    last_err = None
    for i in range(tries):
        try:
            resp = session.get(url, params=params, headers=headers, timeout=timeout)
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            time.sleep(0.6 * (i + 1) + random.random() * 0.4)
    raise RuntimeError(f"请求失败: {url} -> {last_err}")


def get_text(session: requests.Session, url: str, params=None, headers=None,
             timeout: int = 20, tries: int = 3) -> str:
    last_err = None
    for i in range(tries):
        try:
            resp = session.get(url, params=params, headers=headers, timeout=timeout)
            resp.raise_for_status()
            return resp.text
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            time.sleep(0.6 * (i + 1) + random.random() * 0.4)
    raise RuntimeError(f"请求失败: {url} -> {last_err}")


def run_parallel(func, items, workers: int = 16, desc: str = ""):
    """线程池并发执行，返回 [(item, result_or_exception), ...]。"""
    results = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(func, item): item for item in items}
        done = 0
        total = len(futures)
        for future in as_completed(futures):
            item = futures[future]
            try:
                results.append((item, future.result(), None))
            except Exception as exc:  # noqa: BLE001
                results.append((item, None, exc))
            done += 1
            if desc and (done % 100 == 0 or done == total):
                print(f"  {desc}: {done}/{total}")
    return results


def to_symbol(code: str) -> str:
    """600519 -> sh600519，供 akshare/东财使用。"""
    code = code.strip()
    if code.lower().startswith(("sh", "sz", "bj")):
        return code.lower()
    if code.startswith("6"):
        return "sh" + code
    if code.startswith(("0", "3")):
        return "sz" + code
    return "bj" + code
