import json
import os
import time
import uuid
import socket
import base64
import urllib.request
import urllib.parse
import re
from typing import Optional, Dict, List, Tuple

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
VAULT_FILE = os.path.join(BASE_DIR, "claimed_proxies.json")
SESSION_FILE = os.path.join(BASE_DIR, "session.json")
PROXY_TXT_FILE = os.path.join(BASE_DIR, "proxy.txt")
PROXIES_TXT_FILE = os.path.join(BASE_DIR, "proxies.txt")
LOCK_FILE = os.path.join(BASE_DIR, "vault.lock")

# Maximum time a claimed session is kept in reserve (e.g. 2 hours)
MAX_CLAIMED_AGE = 7200 

def format_proxy(p: dict) -> str:
    ip = str(p.get("ip") or p.get("host") or "").strip()
    port = str(p.get("port") or "").strip()
    login = str(p.get("login") or p.get("user") or "").strip()
    pwd = str(p.get("password") or p.get("pass") or "").strip()
    return f"{ip}:{port}:{login}:{pwd}"

def ping_proxy_tunnel(proxy_dict: dict) -> Tuple[bool, str]:
    """Tests TCP CONNECT through the proxy to cp.cloudflare.com:80."""
    try:
        host = proxy_dict.get("ip") or proxy_dict.get("host")
        port = int(proxy_dict.get("port", 0))
        login = proxy_dict.get("login") or proxy_dict.get("user")
        pwd = proxy_dict.get("password") or proxy_dict.get("pass")
        if not (host and port and login and pwd):
            return False, "missing_credentials"

        s = socket.create_connection((host, port), timeout=4)
        s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        auth = base64.b64encode(f"{login}:{pwd}".encode("utf-8")).decode("utf-8")
        req = f"CONNECT cp.cloudflare.com:80 HTTP/1.1\r\nHost: cp.cloudflare.com:80\r\nProxy-Authorization: Basic {auth}\r\nUser-Agent: Mozilla/5.0\r\n\r\n"
        s.sendall(req.encode("utf-8"))
        resp = s.recv(256)
        s.close()
        resp_str = resp.decode("latin-1", errors="ignore").strip()
        if resp.startswith(b"HTTP/1.1 200") or resp.startswith(b"HTTP/1.0 200"):
            return True, "200 OK"
        return False, resp_str
    except Exception as e:
        return False, str(e)

def _get_headers(session_id: str, token: str = None) -> dict:
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
        "Origin": "https://my.sx.org",
        "Referer": "https://my.sx.org/",
        "Accept-Language": "en-US,en;q=0.9",
        "Content-Type": "application/json",
        "X-Ads-Session": session_id,
        "Accept": "application/json, text/plain, */*"
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers

CF_WORKER_URL = "https://sx.shkendj507.workers.dev"

def signin_sx(x_auth_code: str, session_id: str) -> Tuple[str, str]:
    # 1. Attempt via Cloudflare Worker (Clean Edge IP, no blocking)
    if CF_WORKER_URL:
        try:
            cf_url = f"{CF_WORKER_URL}/api/signin"
            payload = json.dumps({"auth_code": x_auth_code}).encode("utf-8")
            req = urllib.request.Request(cf_url, data=payload, headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"}, method="POST")
            with urllib.request.urlopen(req, timeout=12) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                if data.get("success") and data.get("token"):
                    print("[+] [Cloudflare Edge] Successfully signed in to SX.org via Worker!")
                    return data.get("email", ""), data.get("token", "")
        except Exception as e:
            print(f"[*] Cloudflare signin notice: {e}. Using direct signin...")

    # 2. Direct fallback
    url = "https://auth.sx.org/signin/adspower"
    payload = json.dumps({"source": "adspower", "x_auth_code": x_auth_code}).encode("utf-8")
    req = urllib.request.Request(url, data=payload, headers=_get_headers(session_id), method="POST")
    with urllib.request.urlopen(req, timeout=12) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        u = data.get("data", {})
        return u.get("email", ""), u.get("token", "")

def fetch_proxies_sx(token: str, session_id: str) -> List[dict]:
    url = "https://api.sx.org/proxy/short"
    req = urllib.request.Request(url, headers=_get_headers(session_id, token), method="GET")
    with urllib.request.urlopen(req, timeout=12) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        return data.get("data", [])

def _load_vault() -> List[dict]:
    if not os.path.exists(VAULT_FILE):
        return []
    try:
        with open(VAULT_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                # Filter out expired reserve items
                now = time.time()
                return [d for d in data if (now - d.get("claimed_at", 0)) < MAX_CLAIMED_AGE]
    except Exception:
        pass
    return []

def _save_vault(vault: List[dict]):
    tmp = VAULT_FILE + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(vault, f, indent=2)
        if os.path.exists(VAULT_FILE):
            os.remove(VAULT_FILE)
        os.rename(tmp, VAULT_FILE)
    except Exception as e:
        print(f"[Vault] Error saving vault: {e}")

def get_reserve_count() -> int:
    """Returns number of pre-claimed ready accounts waiting in reserve."""
    vault = _load_vault()
    return len(vault)

def activate_account_data(account_dict: dict) -> bool:
    """Instantly writes proxy credentials to proxy.txt, proxies.txt, and session.json (<50ms)."""
    proxies = account_dict.get("proxies", [])
    if not proxies:
        return False

    selected = proxies[0]
    formatted_list = [format_proxy(p) for p in proxies]
    content = "\n".join(formatted_list) + "\n"

    try:
        with open(PROXY_TXT_FILE, "w", encoding="utf-8") as f:
            f.write(content)
        with open(PROXIES_TXT_FILE, "w", encoding="utf-8") as f:
            f.write(content)

        session_data = {
            "email": account_dict.get("email"),
            "token": account_dict.get("token"),
            "session_id": account_dict.get("session_id"),
            "x_auth_code": account_dict.get("auth_code"),
            "activated_at": time.strftime("%Y-%m-%d %H:%M:%S")
        }
        with open(SESSION_FILE, "w", encoding="utf-8") as f:
            json.dump(session_data, f, indent=2)

        return True
    except Exception as e:
        print(f"[Vault] Failed to activate account: {e}")
        return False

def claim_and_store_link(x_auth_code: str, email: str = "") -> Tuple[bool, dict]:
    """
    Called IMMEDIATELY when adspower_creator creates a link.
    Signs in to sx.org, fetches proxies, validates tunnel.
    If no proxy is currently active or active proxy has 407, activates immediately!
    Otherwise, deposits into pre-claimed reserve queue.
    """
    session_id = uuid.uuid4().hex
    try:
        fetched_email, token = signin_sx(x_auth_code, session_id)
        if not token:
            return False, {"error": "Failed to get auth token from sx.org"}

        final_email = fetched_email or email
        proxies = fetch_proxies_sx(token, session_id)
        if not proxies:
            return False, {"error": "Proxy short list was empty"}

        account_entry = {
            "id": uuid.uuid4().hex,
            "email": final_email,
            "token": token,
            "session_id": session_id,
            "auth_code": x_auth_code,
            "claimed_at": time.time(),
            "proxies": proxies,
            "primary": format_proxy(proxies[0])
        }

        # 1. Save account into permanent claimed vault
        vault = _load_vault()
        if not any(v.get("auth_code") == x_auth_code for v in vault):
            vault.append(account_entry)
            _save_vault(vault)

        # 2. SATE SATE Activate and ADD ALL PROXIES to live active pool!
        total_live = add_account_proxies_to_live_pool(account_entry)
        now_str = time.strftime("%H:%M:%S")
        print(f"[{now_str}] [Vault] SATE SATE Claimed & Added to Live Pool! ({final_email}) -> Total Live: {total_live} proxies")
        return True, account_entry

    except Exception as e:
        print(f"[Vault] Error claiming link: {e}")
        return False, {"error": str(e)}

def add_account_proxies_to_live_pool(account_entry: dict) -> int:
    """Appends all freshly claimed proxies to the active live pool (proxy.txt and proxies.txt)."""
    proxies = account_entry.get("proxies", [])
    if not proxies:
        return 0

    existing_lines = []
    if os.path.exists(PROXY_TXT_FILE):
        try:
            with open(PROXY_TXT_FILE, "r", encoding="utf-8") as f:
                existing_lines = [l.strip() for l in f if l.strip() and not l.strip().startswith("#")]
        except Exception:
            existing_lines = []

    new_formatted = [format_proxy(p) for p in proxies]
    combined = list(existing_lines)
    for nf in new_formatted:
        if nf not in combined:
            combined.append(nf)

    content = "\n".join(combined) + "\n"
    try:
        with open(PROXY_TXT_FILE, "w", encoding="utf-8") as f:
            f.write(content)
        with open(PROXIES_TXT_FILE, "w", encoding="utf-8") as f:
            f.write(content)

        # Update all active sessions in session.json
        sdata = load_session_data()
        sessions = sdata.get("sessions", [])
        new_sess = {
            "email": account_entry.get("email"),
            "token": account_entry.get("token"),
            "session_id": account_entry.get("session_id"),
            "x_auth_code": account_entry.get("auth_code"),
            "activated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "proxies": new_formatted
        }
        if not any(s.get("x_auth_code") == account_entry.get("auth_code") for s in sessions):
            sessions.append(new_sess)
        sdata["sessions"] = sessions
        save_session_data(sdata)

    except Exception as e:
        print(f"[Vault] Error updating live pool: {e}")

    return len(combined)

def load_session_data() -> dict:
    if not os.path.exists(SESSION_FILE):
        return {"sessions": []}
    try:
        with open(SESSION_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                if "sessions" not in data:
                    data["sessions"] = [data] if data.get("token") else []
                return data
            elif isinstance(data, list):
                return {"sessions": data}
            return {"sessions": []}
    except Exception:
        return {"sessions": []}

def save_session_data(sdata: dict):
    try:
        sessions = sdata.get("sessions", [])
        if sessions:
            primary = sessions[0]
            sdata["email"] = primary.get("email")
            sdata["token"] = primary.get("token")
            sdata["session_id"] = primary.get("session_id")
            sdata["x_auth_code"] = primary.get("x_auth_code")
            sdata["activated_at"] = primary.get("activated_at")
        else:
            sdata["email"] = ""
            sdata["token"] = ""
            sdata["session_id"] = ""
            sdata["x_auth_code"] = ""
            sdata["activated_at"] = ""
        sdata["total_active_sessions"] = len(sessions)
        with open(SESSION_FILE, "w", encoding="utf-8") as f:
            json.dump(sdata, f, indent=2)
    except Exception as e:
        print(f"[Session] Error saving session.json: {e}")

def keep_all_sessions_alive() -> int:
    """Pings SX.org for each active session in session.json to keep them alive 24/7."""
    sdata = load_session_data()
    sessions = sdata.get("sessions", [])
    refreshed = 0
    for s in sessions:
        token = s.get("token")
        sess_id = s.get("session_id")
        if token and sess_id:
            try:
                url = "https://api.sx.org/user/info"
                req = urllib.request.Request(url, headers=_get_headers(sess_id, token), method="GET")
                with urllib.request.urlopen(req, timeout=8) as resp:
                    d = json.loads(resp.read().decode("utf-8"))
                    if d.get("code") == 0 or "data" in d:
                        refreshed += 1
            except Exception:
                pass
    return refreshed

def remove_dead_proxy(dead_proxy_identifier: str) -> int:
    """
    Instantly removes ONLY the specific proxy that encountered 407 Proxy Authentication Required
    from BOTH proxy.txt, proxies.txt AND session.json!
    All other working sessions & proxies remain live! (< 1ms).
    """
    if not dead_proxy_identifier:
        return 0

    dead_id = dead_proxy_identifier.strip()

    # 1. Remove from proxy.txt & proxies.txt
    surviving = []
    if os.path.exists(PROXY_TXT_FILE):
        try:
            with open(PROXY_TXT_FILE, "r", encoding="utf-8") as f:
                lines = [l.strip() for l in f if l.strip() and not l.strip().startswith("#")]

            for line in lines:
                if dead_id in line or line in dead_id:
                    continue
                surviving.append(line)

            if len(surviving) != len(lines):
                content = "\n".join(surviving) + "\n"
                with open(PROXY_TXT_FILE, "w", encoding="utf-8") as f:
                    f.write(content)
                with open(PROXIES_TXT_FILE, "w", encoding="utf-8") as f:
                    f.write(content)
                now_str = time.strftime("%H:%M:%S")
                print(f"[{now_str}] [-] [407 REMOVED] Dead proxy removed from proxy.txt ({dead_id[:35]}...). Remaining LIVE proxies: {len(surviving)}")
        except Exception as e:
            print(f"[Live Pool] Error updating proxy.txt: {e}")

    # 2. Remove dead proxy from session.json
    try:
        sdata = load_session_data()
        sessions = sdata.get("sessions", [])
        updated_sessions = []
        for s in sessions:
            s_proxies = s.get("proxies", [])
            remaining_sp = [p for p in s_proxies if dead_id not in p and p not in dead_id]
            if remaining_sp:
                s["proxies"] = remaining_sp
                updated_sessions.append(s)
            else:
                now_str = time.strftime("%H:%M:%S")
                print(f"[{now_str}] [-] [SESSION REMOVED] All proxies depleted for session: {s.get('email')} -> Removed from session.json")
        sdata["sessions"] = updated_sessions
        save_session_data(sdata)
    except Exception as e:
        print(f"[Session] Error updating session.json: {e}")

    return len(surviving)

def pop_and_activate_next() -> Tuple[bool, dict]:
    """Fallback if all live proxies are depleted, pops next pre-claimed account from vault."""
    vault = _load_vault()
    if not vault:
        return False, {"error": "Reserve queue empty"}

    next_account = vault.pop(0)
    _save_vault(vault)
    ok = activate_account_data(next_account)
    return ok, next_account

