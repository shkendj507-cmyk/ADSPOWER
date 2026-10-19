import urllib.request
import urllib.parse
import json
import uuid
import sys
import re
import os
import time
import socket
import base64
import proxy_vault

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROXY_TXT = os.path.join(BASE_DIR, "proxy.txt")

def extract_auth_code(link_or_code: str) -> str:
    link_or_code = link_or_code.strip()
    if "x_auth_code=" in link_or_code:
        match = re.search(r"x_auth_code=([a-zA-Z0-9_-]+)", link_or_code)
        if match:
            return match.group(1)
    return link_or_code

def get_headers(session_id: str, token: str = None) -> dict:
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
        "Origin": "https://my.sx.org",
        "Referer": "https://my.sx.org/",
        "sec-ch-ua": '"Chromium";v="128", "Not;A=Brand";v="24", "Google Chrome";v="128"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "Sec-Fetch-Site": "same-site",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Dest": "empty",
        "Accept-Language": "en-US,en;q=0.9",
        "Locale": "en",
        "Content-Type": "application/json",
        "X-Ads-Session": session_id,
        "Accept": "application/json, text/plain, */*"
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers

def load_session() -> dict:
    return proxy_vault.get_active_session()

def save_session(data: dict):
    vdata = proxy_vault._load_vault_data()
    vdata["active"] = data
    proxy_vault._save_vault_data(vdata)

def signin(x_auth_code: str, session_id: str):
    signin_url = "https://auth.sx.org/signin/adspower"
    payload = json.dumps({
        "source": "adspower",
        "x_auth_code": x_auth_code
    }).encode("utf-8")
    
    headers = get_headers(session_id)
    req = urllib.request.Request(signin_url, data=payload, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            user_data = data.get("data", {})
            token = user_data.get("token")
            email = user_data.get("email")
            return email, token
    except urllib.error.HTTPError as e:
        err_msg = e.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"Signin Failed (HTTP {e.code}): {err_msg}")
    except Exception as e:
        raise RuntimeError(f"Signin Connection Error: {e}")

def refresh_auth_token_api(token: str, session_id: str) -> str:
    """Refreshes sx.org token to keep authentication alive permanently."""
    url = "https://api.sx.org/user/auth-token/refresh"
    headers = get_headers(session_id, token)
    req = urllib.request.Request(url, data=b"{}", headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("auth_token") or token
    except Exception:
        return token

def fetch_user_info_api(token: str, session_id: str) -> dict:
    """Checks user info and keeps user session active."""
    url = "https://api.sx.org/user/info"
    headers = get_headers(session_id, token)
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8")).get("data", {})
    except Exception:
        return {}

def fetch_proxies_api(token: str, session_id: str):
    proxy_url = "https://api.sx.org/proxy/short"
    headers = get_headers(session_id, token)
    req = urllib.request.Request(proxy_url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("data", [])
    except urllib.error.HTTPError as e:
        err_msg = e.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"Fetch Proxies Failed (HTTP {e.code}): {err_msg}")
    except Exception as e:
        raise RuntimeError(f"Fetch Proxies Connection Error: {e}")

def fetch_servers_api(token: str, session_id: str):
    url = "https://api.sx.org/servers"
    headers = get_headers(session_id, token)
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None

def fetch_tariff_promise(session_id: str, token: str = None):
    url = "https://api.sx.org/tariff/promise"
    headers = get_headers(session_id, token)
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None

def ping_proxy_tunnel(proxy_dict: dict) -> tuple[bool, str]:
    """Send a fast, lightweight TCP CONNECT ping to keep the sticky residential hold session active."""
    try:
        host = proxy_dict.get("ip") or proxy_dict.get("host")
        port = int(proxy_dict.get("port", 0))
        login = proxy_dict.get("login")
        password = proxy_dict.get("password")
        if not (host and port and login and password):
            return False, "missing_credentials"

        s = socket.create_connection((host, port), timeout=5)
        s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        auth = base64.b64encode(f"{login}:{password}".encode("utf-8")).decode("utf-8")
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

def format_proxy(proxy: dict) -> str:
    ip = str(proxy.get("ip", "")).strip()
    port = str(proxy.get("port", "")).strip()
    login = str(proxy.get("login", "")).strip()
    password = str(proxy.get("password", "")).strip()
    return f"{ip}:{port}:{login}:{password}"

def save_proxies_to_files(proxies: list) -> str:
    selected_proxy = None
    for p in proxies:
        name = (p.get("name") or "").upper()
        login = (p.get("login") or "").upper()
        if "-COUNTRY-US" in login or " US" in name or "-US" in name:
            selected_proxy = p
            break
    if not selected_proxy:
        selected_proxy = proxies[0]

    all_formatted = [format_proxy(p) for p in proxies]
    primary_result = format_proxy(selected_proxy)

    content = "\n".join(all_formatted) + "\n"
    with open(PROXY_TXT, "w", encoding="utf-8") as f:
        f.write(content)

    return primary_result

def renew_session_from_pool(wait_timeout: float = 30.0, manual_code: str = None) -> tuple[bool, dict]:
    """
    Pops the next pre-claimed account from proxy_vault, updates proxy.txt and active state.
    Returns (True, session_dict) on success, or (False, {"error": "..."}) on failure.
    """
    vault_ok, acc_info = proxy_vault.pop_and_activate_next()
    if vault_ok:
        return True, acc_info

    if not manual_code:
        return False, {"error": "Reserve queue empty (waiting for adspower_creator)"}

    auth_code = extract_auth_code(manual_code)
    session_id = uuid.uuid4().hex
    try:
        email, token = signin(auth_code, session_id)
        proxies = fetch_proxies_api(token, session_id)
        if not proxies:
            return False, {"error": "Signin succeeded but proxy list was empty"}

        primary_result = save_proxies_to_files(proxies)
        session_data = {
            "email": email,
            "token": token,
            "session_id": session_id,
            "x_auth_code": auth_code,
            "activated_at": time.strftime("%Y-%m-%d %H:%M:%S")
        }
        save_session(session_data)
        now_str = time.strftime("%H:%M:%S")
        print(f"\n[{now_str}] [AUTO-RENEW SUCCESS] Rotated to fresh SX session: {email}")
        print(f"[{now_str}] -> Loaded {len(proxies)} proxies | Primary: {primary_result}\n")
        return True, session_data
    except Exception as e:
        print(f"[-] [AUTO-RENEW FAILED]: {e}")
        return False, {"error": str(e)}

def keep_alive_cycle(token: str, session_id: str, proxies: list) -> tuple:
    """Performs one full heartbeat cycle across sx.org API and proxy tunnel."""
    fresh_proxies = None
    try:
        fetch_user_info_api(token, session_id)
        fetch_tariff_promise(session_id, token)
        fetch_servers_api(token, session_id)
        fresh_proxies = fetch_proxies_api(token, session_id)
    except Exception:
        pass

    # Proxy Tunnel Ping (maintains upstream residential sticky hold session)
    tunnel_ok = False
    tunnel_msg = ""
    if fresh_proxies:
        tunnel_ok, tunnel_msg = ping_proxy_tunnel(fresh_proxies[0])
    elif proxies:
        tunnel_ok, tunnel_msg = ping_proxy_tunnel(proxies[0])

    return fresh_proxies, tunnel_ok, tunnel_msg

def run_keep_alive_loop(token: str, session_id: str, email: str, proxies: list, session_data: dict, interval: int = 30):
    print(f"\n" + "=" * 75)
    print(f" [★] KEEP-ALIVE ACTIVE: SX.ORG & PROXY SESSION")
    print(f" [★] Current Account : {email}")
    print(f" [★] Heartbeat       : Every {interval}s (API + Proxy Tunnel Health Check)")
    print(f" [★] Auto-Rotation   : Instant 407/401 switch using adspower_creator link pool")
    print(f" [★] Press Ctrl+C anytime to stop.")
    print("=" * 75 + "\n")

    current_token = token
    current_session_id = session_id
    current_proxies = proxies
    current_email = email

    cycle_count = 0

    while True:
        try:
            time.sleep(interval)
            cycle_count += 1

            # Periodically refresh auth token every 10 cycles (~5 mins)
            if cycle_count % 10 == 0:
                new_tok = refresh_auth_token_api(current_token, current_session_id)
                if new_tok and new_tok != current_token:
                    current_token = new_tok
                    session_data["token"] = current_token

            fresh_proxies, tunnel_ok, tunnel_msg = keep_alive_cycle(current_token, current_session_id, current_proxies)

            # Check if upstream returned 407 Proxy Authentication Required or 401 Unauthorized
            is_auth_error = (
                not tunnel_ok and (
                    "407" in tunnel_msg
                    or "401" in tunnel_msg
                    or "Authentication Required" in tunnel_msg
                )
            )

            if is_auth_error or fresh_proxies is None:
                now_str = time.strftime("%H:%M:%S")
                print(f"[{now_str}] [!] Authentication failed / traffic finished ({tunnel_msg}). Auto-renewing session...")
                success, new_sess = renew_session_from_pool(wait_timeout=25.0)
                if success:
                    current_token = new_sess["token"]
                    current_session_id = new_sess["session_id"]
                    current_email = new_sess["email"]
                    session_data = new_sess
                    current_proxies = fetch_proxies_api(current_token, current_session_id)
                    print(f"[{now_str}] [+] Session seamlessly rotated to account: {current_email}!")
                    continue
                else:
                    print(f"[{now_str}] [!] Notice: {new_sess.get('error')}. Retrying next cycle...")

            if fresh_proxies:
                current_proxies = fresh_proxies
                save_proxies_to_files(current_proxies)

            session_data["last_active"] = time.strftime("%Y-%m-%d %H:%M:%S")
            save_session(session_data)

            tunnel_status = "[Tunnel: OK]" if tunnel_ok else f"[Tunnel: {tunnel_msg[:24]}]"
            now_str = time.strftime("%H:%M:%S")
            print(f"[{now_str}] Cycle #{cycle_count:03d} -> Session Alive | API OK | {tunnel_status} | {len(current_proxies)} Proxies ({current_email})")

        except KeyboardInterrupt:
            print("\n[+] Keep-alive loop stopped by user.")
            break
        except Exception as e:
            err_str = str(e)
            now_str = time.strftime("%H:%M:%S")
            print(f"[{now_str}] [!] Loop notice: {err_str}")

            if "HTTP 401" in err_str or "Unauthorized" in err_str or "407" in err_str:
                success, new_sess = renew_session_from_pool(wait_timeout=25.0)
                if success:
                    current_token = new_sess["token"]
                    current_session_id = new_sess["session_id"]
                    current_email = new_sess["email"]
                    session_data = new_sess
                    current_proxies = fetch_proxies_api(current_token, current_session_id)
                    continue

            time.sleep(10)

def main():
    args = sys.argv[1:]
    keep_alive_mode = True
    once_mode = False

    if "--once" in args or "-1" in args:
        once_mode = True
        keep_alive_mode = False
        args = [a for a in args if a not in ("--once", "-1")]

    if "--keep-alive" in args or "-k" in args:
        keep_alive_mode = True
        args = [a for a in args if a not in ("--keep-alive", "-k")]

    raw_input_val = args[0] if args else ""
    session_data = load_session()

    token = session_data.get("token")
    email = session_data.get("email")
    session_id = session_data.get("session_id") or uuid.uuid4().hex

    proxies = None

    # Step 1: Check existing saved active session if no manual input passed
    if not raw_input_val and token:
        try:
            test_proxies = fetch_proxies_api(token, session_id)
            if test_proxies:
                # Also verify tunnel health
                t_ok, t_msg = ping_proxy_tunnel(test_proxies[0])
                if t_ok or ("407" not in t_msg and "Authentication Required" not in t_msg):
                    proxies = test_proxies
                    print(f"[+] Active saved session verified for: {email} ({len(proxies)} proxies)")
                    session_data["last_active"] = time.strftime("%Y-%m-%d %H:%M:%S")
                    save_session(session_data)
                else:
                    print(f"[!] Saved session proxy tunnel rejected ({t_msg}). Rotating...")
                    token = None
        except Exception:
            token = None

    # Step 2: If manual input provided, use it
    if raw_input_val:
        auth_code = extract_auth_code(raw_input_val)
        session_id = uuid.uuid4().hex
        try:
            email, token = signin(auth_code, session_id)
            proxies = fetch_proxies_api(token, session_id)
            session_data = {
                "email": email,
                "token": token,
                "session_id": session_id,
                "x_auth_code": auth_code,
                "last_active": time.strftime("%Y-%m-%d %H:%M:%S")
            }
            save_session(session_data)
            print(f"[+] Authenticated successfully: {email} ({len(proxies)} proxies)")
        except Exception as e:
            print(f"[-] Authentication failed: {e}")
            return

    # Step 3: If still no active proxies, auto-activate from link pool
    if not proxies:
        print("[*] Checking link pool for active fresh link (<15 mins)...")
        success, new_sess = renew_session_from_pool(wait_timeout=5.0)
        if success:
            token = new_sess["token"]
            session_id = new_sess["session_id"]
            email = new_sess["email"]
            session_data = new_sess
            proxies = fetch_proxies_api(token, session_id)
        else:
            print("[-] No active link in pool. Please make sure adspower_creator is running,")
            print("    or enter a link manually below.")
            try:
                manual_in = input("Enter Link or x_auth_code: ").strip()
                if manual_in:
                    success, new_sess = renew_session_from_pool(manual_code=manual_in)
                    if success:
                        token = new_sess["token"]
                        session_id = new_sess["session_id"]
                        email = new_sess["email"]
                        session_data = new_sess
                        proxies = fetch_proxies_api(token, session_id)
            except (KeyboardInterrupt, EOFError):
                return

    if proxies:
        primary_result = save_proxies_to_files(proxies)
        print(f"\n[+] Primary Proxy: {primary_result}")
        print(f"[+] Saved {len(proxies)} proxies to proxy.txt")

    if once_mode:
        print("[+] Finished (--once). Exiting.")
        return

    if keep_alive_mode and token and proxies:
        run_keep_alive_loop(token, session_id, email, proxies, session_data, interval=30)

if __name__ == "__main__":
    main()

