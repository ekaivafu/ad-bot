"""
proxy_manager.py — Free Indian Proxy Auto-Fetcher & Rotator
Fetches free Indian HTTP proxies, tests them against UIDAI, and provides working ones.
"""

import requests
import random
import os
import time
import json

UIDAI_TEST_URL = "https://myaadhaar.uidai.gov.in/genricDownloadAadhaar"
PROXY_CACHE_FILE = "working_proxies.json"
PROXY_CACHE_TTL = 1800  # 30 min

_working_proxies = []
_last_fetch_time = 0

FREE_PROXY_SOURCES = [
    # GeoNode free Indian proxies
    "https://proxylist.geonode.com/api/proxy-list?limit=100&page=1&country=IN&protocols=http%2Chttps&filterUpTime=50&speed=fast",
    # ProxyScrape Indian proxies
    "https://api.proxyscrape.com/v3/free-proxy-list/get?request=displayproxies&country=in&protocol=http&anonymity=elite,anonymous&timeout=5000",
]

def _fetch_proxy_list():
    """Fetch raw proxy list from free sources."""
    proxies = []

    # Source 1: GeoNode (JSON format)
    try:
        r = requests.get(FREE_PROXY_SOURCES[0], timeout=10)
        if r.status_code == 200:
            data = r.json()
            for p in data.get("data", []):
                ip = p.get("ip")
                port = p.get("port")
                if ip and port:
                    proxies.append(f"{ip}:{port}")
            print(f"[PROXY] GeoNode: {len(proxies)} Indian proxies fetched")
    except Exception as e:
        print(f"[PROXY] GeoNode fetch failed: {e}")

    # Source 2: ProxyScrape (plain text ip:port)
    try:
        r = requests.get(FREE_PROXY_SOURCES[1], timeout=10)
        if r.status_code == 200:
            lines = r.text.strip().splitlines()
            new = [l.strip() for l in lines if ":" in l.strip()]
            proxies.extend(new)
            print(f"[PROXY] ProxyScrape: {len(new)} Indian proxies fetched")
    except Exception as e:
        print(f"[PROXY] ProxyScrape fetch failed: {e}")

    return list(set(proxies))  # deduplicate

def _test_proxy(proxy_str, timeout=6):
    """Test if proxy can reach UIDAI. Returns True/False."""
    proxies = {
        "http":  f"http://{proxy_str}",
        "https": f"http://{proxy_str}",
    }
    try:
        r = requests.get(
            "https://myaadhaar.uidai.gov.in",
            proxies=proxies,
            timeout=timeout,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        )
        return r.status_code < 500
    except Exception:
        return False

def refresh_proxies(max_workers=10, max_good=5):
    """Fetch and test proxies in parallel. Returns list of working proxy strings."""
    global _working_proxies, _last_fetch_time

    print("[PROXY] Fetching fresh Indian proxy list...")
    all_proxies = _fetch_proxy_list()

    if not all_proxies:
        print("[PROXY] ⚠️ No proxies fetched from sources")
        return []

    print(f"[PROXY] Testing {min(40, len(all_proxies))} proxies (parallel)...")
    random.shuffle(all_proxies)
    candidates = all_proxies[:40]  # test top 40

    from concurrent.futures import ThreadPoolExecutor, as_completed
    good = []
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(_test_proxy, p): p for p in candidates}
        for fut in as_completed(futures):
            proxy = futures[fut]
            try:
                if fut.result():
                    good.append(proxy)
                    print(f"[PROXY] ✅ Working: {proxy}")
                    if len(good) >= max_good:
                        break
            except Exception:
                pass

    print(f"[PROXY] Found {len(good)} working Indian proxies")
    _working_proxies = good
    _last_fetch_time = time.time()

    # Cache to file
    try:
        with open(PROXY_CACHE_FILE, "w") as f:
            json.dump({"proxies": good, "ts": _last_fetch_time}, f)
    except Exception:
        pass

    return good

def get_proxy_dict():
    """
    Returns a requests-compatible proxy dict using a working proxy,
    or None if no proxy is configured / available.

    Priority:
      1. PROXY_URL env var (single manual proxy)
      2. PROXY_LIST env var (comma-separated list — rotates randomly)
      3. Cached auto-fetched proxies
      4. None (direct connection fallback)
    """
    global _working_proxies, _last_fetch_time

    # 1. Single manual proxy from env var
    manual = os.environ.get("PROXY_URL", "").strip()
    if manual:
        return {"http": manual, "https": manual}

    # 2. PROXY_LIST env var — pre-configured list (highest priority after manual)
    proxy_list_env = os.environ.get("PROXY_LIST", "").strip()
    if proxy_list_env:
        candidates = [p.strip() for p in proxy_list_env.split(",") if p.strip()]
        if candidates:
            chosen = random.choice(candidates)
            return {
                "http":  f"http://{chosen}",
                "https": f"http://{chosen}",
            }

    # 3. Use cached auto-fetched working proxies (refresh if stale)
    now = time.time()
    if not _working_proxies or (now - _last_fetch_time) > PROXY_CACHE_TTL:
        # Try loading from file cache first
        try:
            with open(PROXY_CACHE_FILE) as f:
                data = json.load(f)
                if (now - data.get("ts", 0)) < PROXY_CACHE_TTL and data.get("proxies"):
                    _working_proxies = data["proxies"]
                    _last_fetch_time = data["ts"]
                    print(f"[PROXY] Loaded {len(_working_proxies)} proxies from cache file")
        except Exception:
            pass

        if not _working_proxies or (now - _last_fetch_time) > PROXY_CACHE_TTL:
            refresh_proxies()

    if _working_proxies:
        chosen = random.choice(_working_proxies)
        return {
            "http":  f"http://{chosen}",
            "https": f"http://{chosen}",
        }

    return None  # direct connection fallback

def remove_bad_proxy(proxy_dict):
    """Remove a proxy that just failed (call this on connection errors)."""
    global _working_proxies
    if not proxy_dict:
        return
    for val in proxy_dict.values():
        addr = val.replace("http://", "").replace("https://", "")
        if addr in _working_proxies:
            _working_proxies.remove(addr)
            print(f"[PROXY] ❌ Removed bad proxy: {addr} ({len(_working_proxies)} left)")
