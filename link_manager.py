import json
import os
import re
import time
from typing import Optional, Dict, List

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
POOL_FILE = os.path.join(BASE_DIR, "claimed_proxies.json")
LOCK_FILE = os.path.join(BASE_DIR, "vault.lock")

# Link validity duration (15 minutes strictly as requested)
LINK_MAX_AGE_SECONDS = 15 * 60  # 900 seconds
SAFE_USAGE_MAX_AGE = 14 * 60    # 840 seconds

def extract_auth_code(link_or_code: str) -> str:
    """Extracts auth code from SX link or raw code string."""
    link_or_code = (link_or_code or "").strip()
    if "x_auth_code=" in link_or_code:
        match = re.search(r"x_auth_code=([a-zA-Z0-9_-]+)", link_or_code)
        if match:
            return match.group(1)
    return link_or_code

class FileLock:
    """Simple cross-platform file-based lock with timeout."""
    def __init__(self, lock_file: str, timeout: float = 8.0, check_interval: float = 0.05):
        self.lock_file = lock_file
        self.timeout = timeout
        self.check_interval = check_interval
        self.acquired = False

    def __enter__(self):
        start = time.time()
        while time.time() - start < self.timeout:
            try:
                fd = os.open(self.lock_file, os.O_CREAT | os.O_EXCL | os.O_RDWR)
                os.write(fd, str(os.getpid()).encode())
                os.close(fd)
                self.acquired = True
                return self
            except FileExistsError:
                try:
                    mtime = os.path.getmtime(self.lock_file)
                    if time.time() - mtime > 30:
                        os.remove(self.lock_file)
                except Exception:
                    pass
                time.sleep(self.check_interval)
            except Exception:
                time.sleep(self.check_interval)
        self.acquired = False
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.acquired:
            try:
                if os.path.exists(self.lock_file):
                    os.remove(self.lock_file)
            except Exception:
                pass

def _load_pool_unlocked() -> List[Dict]:
    if not os.path.exists(POOL_FILE):
        return []
    try:
        with open(POOL_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                return data
            if isinstance(data, dict):
                return data.get("reserve", [])
    except Exception:
        pass
    return []

def _save_pool_unlocked(pool: List[Dict]):
    tmp_file = POOL_FILE + ".tmp"
    try:
        if os.path.exists(POOL_FILE):
            try:
                with open(POOL_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                data = {}
        else:
            data = {}

        if isinstance(data, dict):
            data["reserve"] = pool
            out_content = data
        else:
            out_content = pool

        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(out_content, f, indent=2)

        if os.path.exists(POOL_FILE):
            os.remove(POOL_FILE)
        os.rename(tmp_file, POOL_FILE)
    except Exception as e:
        print(f"[link_manager] Save pool error: {e}")

def add_link(link: str, email: str = "") -> Dict:
    code = extract_auth_code(link)
    entry = {
        "auth_code": code,
        "link": link,
        "email": email,
        "created_at": time.time()
    }
    with FileLock(LOCK_FILE):
        pool = _load_pool_unlocked()
        pool.append(entry)
        _save_pool_unlocked(pool)
    return entry

def pop_valid_link() -> Optional[Dict]:
    with FileLock(LOCK_FILE):
        pool = _load_pool_unlocked()
        now = time.time()
        for i, item in enumerate(pool):
            age = now - item.get("created_at", 0)
            if age <= SAFE_USAGE_MAX_AGE:
                return pool.pop(i)
        return None

def get_valid_count() -> int:
    with FileLock(LOCK_FILE):
        pool = _load_pool_unlocked()
        now = time.time()
        return sum(1 for item in pool if (now - item.get("created_at", 0)) <= SAFE_USAGE_MAX_AGE)

def purge_expired() -> int:
    with FileLock(LOCK_FILE):
        pool = _load_pool_unlocked()
        now = time.time()
        valid = [item for item in pool if (now - item.get("created_at", 0)) <= LINK_MAX_AGE_SECONDS]
        removed = len(pool) - len(valid)
        if removed > 0:
            _save_pool_unlocked(valid)
        return removed
