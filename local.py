#!/usr/bin/env python3

import asyncio
import base64
import logging
import os
import re
import socket
import sys
import time
import uuid
from urllib.parse import urlparse
import proxy_vault

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] [Local-Proxy] %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger("LocalProxy")

BUFFER_SIZE = 65536
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROXY_TXT_FILE = os.path.join(BASE_DIR, "proxy.txt")

PRIMARY_PORTS = [1000, 8080]

ALL_COUNTRIES = {
    "AF": "Afghanistan", "AL": "Albania", "DZ": "Algeria", "AD": "Andorra", "AO": "Angola",
    "AG": "Antigua and Barbuda", "AR": "Argentina", "AM": "Armenia", "AU": "Australia", "AT": "Austria",
    "AZ": "Azerbaijan", "BS": "Bahamas", "BH": "Bahrain", "BD": "Bangladesh", "BB": "Barbados",
    "BY": "Belarus", "BE": "Belgium", "BZ": "Belize", "BJ": "Benin", "BT": "Bhutan",
    "BO": "Bolivia", "BA": "Bosnia and Herzegovina", "BW": "Botswana", "BR": "Brazil", "BN": "Brunei",
    "BG": "Bulgaria", "BF": "Burkina Faso", "BI": "Burundi", "CV": "Cabo Verde", "KH": "Cambodia",
    "CM": "Cameroon", "CA": "Canada", "CF": "Central African Republic", "TD": "Chad", "CL": "Chile",
    "CN": "China", "CO": "Colombia", "KM": "Comoros", "CG": "Congo", "CD": "Congo (DRC)",
    "CR": "Costa Rica", "CI": "Cote d'Ivoire", "HR": "Croatia", "CU": "Cuba", "CY": "Cyprus",
    "CZ": "Czech Republic", "DK": "Denmark", "DJ": "Djibouti", "DM": "Dominica", "DO": "Dominican Republic",
    "EC": "Ecuador", "EG": "Egypt", "SV": "El Salvador", "GQ": "Equatorial Guinea", "ER": "Eritrea",
    "EE": "Estonia", "SZ": "Eswatini", "ET": "Ethiopia", "FJ": "Fiji", "FI": "Finland",
    "FR": "France", "GA": "Gabon", "GM": "Gambia", "GE": "Georgia", "DE": "Germany",
    "GH": "Ghana", "GR": "Greece", "GD": "Grenada", "GT": "Guatemala", "GN": "Guinea",
    "GW": "Guinea-Bissau", "GY": "Guyana", "HT": "Haiti", "HN": "Honduras", "HK": "Hong Kong",
    "HU": "Hungary", "IS": "Iceland", "IN": "India", "ID": "Indonesia", "IR": "Iran",
    "IQ": "Iraq", "IE": "Ireland", "IL": "Israel", "IT": "Italy", "JM": "Jamaica",
    "JP": "Japan", "JO": "Jordan", "KZ": "Kazakhstan", "KE": "Kenya", "KI": "Kiribati",
    "KP": "North Korea", "KR": "South Korea", "KW": "Kuwait", "KG": "Kyrgyzstan", "LA": "Laos",
    "LV": "Latvia", "LB": "Lebanon", "LS": "Lesotho", "LR": "Liberia", "LY": "Libya",
    "LI": "Liechtenstein", "LT": "Lithuania", "LU": "Luxembourg", "MO": "Macao", "MG": "Madagascar",
    "MW": "Malawi", "MY": "Malaysia", "MV": "Maldives", "ML": "Mali", "MT": "Malta",
    "MH": "Marshall Islands", "MR": "Mauritania", "MU": "Mauritius", "MX": "Mexico", "FM": "Micronesia",
    "MD": "Moldova", "MC": "Monaco", "MN": "Mongolia", "ME": "Montenegro", "MA": "Morocco",
    "MZ": "Mozambique", "MM": "Myanmar", "NA": "Namibia", "NR": "Nauru", "NP": "Nepal",
    "NL": "Netherlands", "NZ": "New Zealand", "NI": "Nicaragua", "NE": "Niger", "NG": "Nigeria",
    "MK": "North Macedonia", "NO": "Norway", "OM": "Oman", "PK": "Pakistan", "PW": "Palau",
    "PS": "Palestine", "PA": "Panama", "PG": "Papua New Guinea", "PY": "Paraguay", "PE": "Peru",
    "PH": "Philippines", "PL": "Poland", "PT": "Portugal", "PR": "Puerto Rico", "QA": "Qatar",
    "RO": "Romania", "RU": "Russia", "RW": "Rwanda", "KN": "Saint Kitts and Nevis", "LC": "Saint Lucia",
    "VC": "Saint Vincent and the Grenadines", "WS": "Samoa", "SM": "San Marino", "ST": "Sao Tome and Principe",
    "SA": "Saudi Arabia", "SN": "Senegal", "RS": "Serbia", "SC": "Seychelles", "SL": "Sierra Leone",
    "SG": "Singapore", "SK": "Slovakia", "SI": "Slovenia", "SB": "Solomon Islands", "SO": "Somalia",
    "ZA": "South Africa", "SS": "South Sudan", "ES": "Spain", "LK": "Sri Lanka", "SD": "Sudan",
    "SR": "Suriname", "SE": "Sweden", "CH": "Switzerland", "SY": "Syria", "TW": "Taiwan",
    "TJ": "Tajikistan", "TZ": "Tanzania", "TH": "Thailand", "TL": "Timor-Leste", "TG": "Togo",
    "TO": "Tonga", "TT": "Trinidad and Tobago", "TN": "Tunisia", "TR": "Turkey", "TM": "Turkmenistan",
    "TV": "Tuvalu", "UG": "Uganda", "UA": "Ukraine", "AE": "United Arab Emirates", "GB": "United Kingdom",
    "US": "United States", "UY": "Uruguay", "UZ": "Uzbekistan", "VU": "Vanuatu", "VE": "Venezuela",
    "VN": "Vietnam", "YE": "Yemen", "ZM": "Zambia", "ZW": "Zimbabwe",
    "AW": "Aruba", "BM": "Bermuda", "KY": "Cayman Islands", "CW": "Curacao", "GL": "Greenland",
    "GU": "Guam", "FO": "Faroe Islands", "GI": "Gibraltar", "IM": "Isle of Man", "JE": "Jersey",
    "PF": "French Polynesia", "NC": "New Caledonia", "VI": "Virgin Islands (US)", "VG": "Virgin Islands (British)",
    "XK": "Kosovo", "RE": "Reunion", "GP": "Guadeloupe", "MQ": "Martinique", "GF": "French Guiana"
}

COUNTRY_PORTS = {
    9001: ("US", "United States"),
    9002: ("GB", "United Kingdom"),
    9003: ("DE", "Germany"),
    9004: ("CA", "Canada"),
    9006: ("AU", "Australia"),
    9007: ("IN", "India"),
    9008: ("SG", "Singapore"),
    9009: ("JP", "Japan"),
}

_DNS_CACHE = {}

def get_lan_ip() -> str:
    """Detects the real LAN IP address so devices on the same Wi-Fi / Network can connect."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        if ip and not ip.startswith("127."):
            return ip
    except Exception:
        pass

    try:
        hostname = socket.gethostname()
        all_ips = socket.gethostbyname_ex(hostname)[2]
        for ip in all_ips:
            if ip.startswith("192.168.") or ip.startswith("10.") or re.match(r"^172\.(1[6-9]|2[0-9]|3[0-1])\.", ip):
                return ip
    except Exception:
        pass

    return "127.0.0.1"

async def get_cached_ip(host: str) -> str:
    now = time.time()
    if host in _DNS_CACHE:
        ip, expires = _DNS_CACHE[host]
        if now < expires:
            return ip
    try:
        loop = asyncio.get_running_loop()
        addr_info = await loop.getaddrinfo(host, None, family=socket.AF_INET)
        if addr_info:
            ip = addr_info[0][4][0]
            _DNS_CACHE[host] = (ip, now + 1800)
            return ip
    except Exception:
        pass
    return host

def optimize_socket(writer):
    if not writer:
        return
    try:
        sock = writer.get_extra_info('socket')
        if sock:
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            try:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, BUFFER_SIZE * 4)
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, BUFFER_SIZE * 4)
            except Exception:
                pass
    except Exception:
        pass

class LocalProxyServer:
    def __init__(self, host="0.0.0.0", default_country="US"):
        self.host = host
        self.lan_ip = get_lan_ip()
        self.default_country = default_country.upper()
        self.proxies_cache = []
        self.last_mtime = 0
        self.active_file = PROXY_TXT_FILE
        self.rot_index = 0
        self.servers = []
        self.session_pool = [uuid.uuid4().hex[:10] for _ in range(15)]
        self.session_counter = 0
        self.last_pool_refresh = time.time()
        self._rotation_lock = asyncio.Lock()
        self._last_rotation_time = 0

    async def handle_407_rotation(self, dead_proxy: str = None) -> bool:
        async with self._rotation_lock:
            if dead_proxy:
                proxy_vault.remove_dead_proxy(dead_proxy)
            remaining = self.load_proxies(force=True)
            if remaining:
                logger.info(f'[+] [HOT SWAP] Dead 407 proxy removed! Remaining LIVE working proxies: {len(remaining)}')
                return True
            else:
                ok, acc = proxy_vault.pop_and_activate_next()
                if ok:
                    self.load_proxies(force=True)
                    return True
            return False

    def get_next_rotating_session(self) -> str:
        now = time.time()

        if now - self.last_pool_refresh > 90:
            self.session_pool = [uuid.uuid4().hex[:10] for _ in range(15)]
            self.last_pool_refresh = now
        self.session_counter += 1
        return self.session_pool[self.session_counter % len(self.session_pool)]

    def get_proxy_file_path(self):
        return PROXY_TXT_FILE

    def load_proxies(self, force=False):
        file_path = self.get_proxy_file_path()
        if not os.path.exists(file_path):
            self.proxies_cache = []
            return self.proxies_cache

        try:
            current_mtime = os.path.getmtime(file_path)
            if not force and current_mtime == self.last_mtime and file_path == self.active_file and self.proxies_cache:
                return self.proxies_cache

            parsed = []
            with open(file_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    parts = line.split(":")
                    if len(parts) >= 2:
                        ip = parts[0].strip()
                        port = int(parts[1].strip())
                        user = parts[2].strip() if len(parts) >= 3 else ""
                        pwd = parts[3].strip() if len(parts) >= 4 else ""
                        parsed.append({
                            "host": ip,
                            "port": port,
                            "user": user,
                            "pass": pwd,
                            "raw": line
                        })

            if len(parsed) != len(self.proxies_cache) or current_mtime != self.last_mtime or file_path != self.active_file:
                logger.info(f"Loaded {len(parsed)} upstream proxies from {os.path.basename(file_path)}")

            self.proxies_cache = parsed
            self.last_mtime = current_mtime
            self.active_file = file_path
        except Exception as e:
            logger.error(f"Error reading {file_path}: {e}")

        return self.proxies_cache

    def get_upstream_proxy(self, requested_country: str):
        proxies = self.load_proxies()
        if not proxies:
            return None

        req_c = (requested_country or self.default_country).lower()

        for p in proxies:
            u = p["user"].lower()
            if f"-country-{req_c}" in u or f"-cc-{req_c}" in u or f"_{req_c}" in u:
                return p

        idx = self.rot_index % len(proxies)
        self.rot_index += 1
        return proxies[idx]

    def parse_client_username(self, raw_user: str, fixed_country: str = None):
        if fixed_country and not raw_user:
            return fixed_country, None

        if not raw_user:
            return (fixed_country or self.default_country), None

        raw = raw_user.strip()
        req_session = None
        req_country = None

        m_hold = re.search(r'[-_](?:hold|sticky)', raw, re.IGNORECASE)
        if m_hold:
            req_session = "hold"
            raw = re.sub(r'[-_](?:hold|sticky)', '', raw, flags=re.IGNORECASE)
        else:
            m_sess = re.search(r'[-_](?:session|sess)[-_]([a-zA-Z0-9]+)$', raw, re.IGNORECASE)
            if m_sess:
                req_session = m_sess.group(1)
                raw = raw[:m_sess.start()]

        m = re.search(r'(?:^|[-_])(?:country|cc)[-_]([a-zA-Z]{2,3})(?:[-_]|$)', raw, re.IGNORECASE)
        if m:
            candidate = m.group(1).upper()
            req_country = candidate
        elif re.match(r'^[a-zA-Z]{2}$', raw):
            req_country = raw.upper()
        else:
            m_sfx = re.search(r'[-_](([a-zA-Z]{2}))(?![0-9])', raw)
            if m_sfx:
                candidate = m_sfx.group(1).upper()
                if candidate in ALL_COUNTRIES:
                    req_country = candidate

        final_country = req_country or fixed_country or self.default_country
        return final_country, req_session

    def format_upstream_user(self, base_user: str, country: str, custom_session: str = None) -> str:
        if not base_user:
            return base_user

        u = base_user
        c = (country or self.default_country).strip().upper()

        # Session rotation logic:
        # 1. If custom_session == "hold", preserve original upstream sticky session.
        # 2. If client passed specific session (e.g. session-myname), use that fixed session.
        # 3. Default (rotating mode): generate brand new random session for EVERY request so IP rotates!
        is_hold = custom_session in ("hold", "sticky")
        sess = custom_session if (custom_session and not is_hold) else (None if is_hold else self.get_next_rotating_session())

        if sess:
            if re.search(r'-session-[a-zA-Z0-9]+', u, re.IGNORECASE):
                u = re.sub(r'-session-[a-zA-Z0-9]+', f'-session-{sess}', u, flags=re.IGNORECASE)
            elif re.search(r'_session_[a-zA-Z0-9]+', u, re.IGNORECASE):
                u = re.sub(r'_session_[a-zA-Z0-9]+', f'_session_{sess}', u, flags=re.IGNORECASE)
            else:
                u = f"{u}-session-{sess}"

        # Adjust country only if requested country is known/supported, otherwise keep valid upstream country
        valid_countries = {"US", "GB", "DE", "FR", "CA", "AU", "BR", "RU", "VN", "UA", "AR", "CL", "MA", "IN", "SG", "JP", "NL", "IT", "ES", "PL", "TR", "ID"}
        if c and (c in valid_countries):
            if re.search(r'-country-[A-Za-z]+', u, re.IGNORECASE):
                u = re.sub(r'-country-[A-Za-z]+', f'-country-{c}', u, flags=re.IGNORECASE)
            elif re.search(r'-cc-[A-Za-z]+', u, re.IGNORECASE):
                u = re.sub(r'-cc-[A-Za-z]+', f'-cc-{c}', u, flags=re.IGNORECASE)
            elif re.search(r'_country_[A-Za-z]+', u, re.IGNORECASE):
                u = re.sub(r'_country_[A-Za-z]+', f'_country_{c}', u, flags=re.IGNORECASE)
            elif re.search(r'_cc_[A-Za-z]+', u, re.IGNORECASE):
                u = re.sub(r'_cc_[A-Za-z]+', f'_cc_{c}', u, flags=re.IGNORECASE)
            elif not re.search(rf'[-_](?:country|cc)[-_]{c}', u, re.IGNORECASE):
                u = f"{u}-country-{c}"

        return u

    async def pipe_streams(self, client_reader, client_writer, upstream_reader, upstream_writer, target_display, country):
        try:
            async def fwd_c2u():
                try:
                    while True:
                        data = await client_reader.read(BUFFER_SIZE)
                        if not data:
                            break
                        upstream_writer.write(data)
                        await upstream_writer.drain()
                except Exception:
                    pass

            async def fwd_u2c():
                try:
                    while True:
                        data = await upstream_reader.read(BUFFER_SIZE)
                        if not data:
                            break
                        client_writer.write(data)
                        await client_writer.drain()
                except Exception:
                    pass

            t1 = asyncio.create_task(fwd_c2u())
            t2 = asyncio.create_task(fwd_u2c())
            done, pending = await asyncio.wait([t1, t2], return_when=asyncio.FIRST_COMPLETED)
            for p in pending:
                p.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
        except Exception:
            pass

    async def dial_upstream_tunnel(self, upstream: dict, formatted_user: str, target_host: str, target_port: int):
        """Dials the upstream proxy with fallback to raw credentials if modified user is rejected."""
        upstream_ip = await get_cached_ip(upstream["host"])

        async def _attempt_connect(user_str):
            cred = base64.b64encode(f"{user_str}:{upstream['pass']}".encode("utf-8")).decode("utf-8")
            try:
                r, w = await asyncio.wait_for(asyncio.open_connection(upstream_ip, upstream["port"]), timeout=12.0)
                optimize_socket(w)
            except Exception as e:
                return None, None, f"connect_failed: {e}"

            up_req = (
                f"CONNECT {target_host}:{target_port} HTTP/1.1\r\n"
                f"Host: {target_host}:{target_port}\r\n"
                f"Proxy-Authorization: Basic {cred}\r\n"
                f"User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/128.0.0.0 Safari/537.36\r\n\r\n"
            ).encode("utf-8")
            w.write(up_req)
            await w.drain()

            try:
                resp = await asyncio.wait_for(r.readline(), timeout=12.0)
            except asyncio.TimeoutError:
                w.close()
                return None, None, "timeout"

            if resp.startswith(b"HTTP/1.1 200") or resp.startswith(b"HTTP/1.0 200"):
                while True:
                    hdr = await asyncio.wait_for(r.readline(), timeout=12.0)
                    if hdr == b"\r\n" or not hdr:
                        break
                return r, w, "ok"

            w.close()
            return None, None, resp.strip().decode('latin-1', errors='ignore')

        # 1. Attempt with formatted user (targeted country / session)
        r, w, res = await _attempt_connect(formatted_user)
        if res == "ok":
            return r, w, "ok"

        # If 429 Too Many Requests, upstream is rate-limiting! DO NOT flood fallback attempts!
        if "429" in str(res):
            logger.warning("Upstream rate limit (429 Too Many Requests). Backing off 0.5s...")
            await asyncio.sleep(0.5)
            return None, None, res

        # 2. Fallback to raw original credentials if formatted failed (only on 407 auth error)
        if formatted_user != upstream["user"] and "407" in str(res):
            logger.debug(f"Upstream rejected modified user ({res}). Falling back to original credentials...")
            r_fb, w_fb, res_fb = await _attempt_connect(upstream["user"])
            if res_fb == "ok":
                return r_fb, w_fb, "ok"
            return None, None, res_fb

        return None, None, res

    async def handle_socks5(self, client_reader, client_writer, client_addr, fixed_country=None):
        target_display = "unknown"
        upstream_writer = None
        upstream_reader = None

        try:
            nmethods_raw = await client_reader.read(1)
            if not nmethods_raw:
                return
            nmethods = nmethods_raw[0]
            methods = await client_reader.read(nmethods)

            raw_user = ""
            client_session = None

            if b"\x02" in methods:
                client_writer.write(b"\x05\x02")
                await client_writer.drain()

                auth_ver = await client_reader.read(1)
                if auth_ver != b"\x01":
                    return
                ulen_raw = await client_reader.read(1)
                if not ulen_raw:
                    return
                raw_user = (await client_reader.read(ulen_raw[0])).decode('utf-8', errors='ignore')
                plen_raw = await client_reader.read(1)
                if not plen_raw:
                    return
                _ = await client_reader.read(plen_raw[0])

                client_writer.write(b"\x01\x00")
                await client_writer.drain()
            elif b"\x00" in methods:
                client_writer.write(b"\x05\x00")
                await client_writer.drain()
            else:
                client_writer.write(b"\x05\xFF")
                await client_writer.drain()
                return

            req_country, client_session = self.parse_client_username(raw_user, fixed_country)

            req_hdr = await client_reader.read(4)
            if len(req_hdr) < 4 or req_hdr[0] != 5 or req_hdr[1] != 1:
                client_writer.write(b"\x05\x07\x00\x01\x00\x00\x00\x00\x00\x00")
                await client_writer.drain()
                return

            atyp = req_hdr[3]
            if atyp == 1:
                target_host = socket.inet_ntoa(await client_reader.read(4))
            elif atyp == 3:
                dlen = (await client_reader.read(1))[0]
                target_host = (await client_reader.read(dlen)).decode('utf-8', errors='ignore')
            elif atyp == 4:
                target_host = socket.inet_ntop(socket.AF_INET6, await client_reader.read(16))
            else:
                return

            port_raw = await client_reader.read(2)
            target_port = int.from_bytes(port_raw, 'big')
            target_display = f"{target_host}:{target_port}"

            upstream = self.get_upstream_proxy(req_country)
            if not upstream:
                logger.error("No upstream proxies available in proxy.txt!")
                client_writer.write(b"\x05\x04\x00\x01\x00\x00\x00\x00\x00\x00")
                await client_writer.drain()
                return

            formatted_user = self.format_upstream_user(upstream["user"], req_country, client_session)
            c_name = ALL_COUNTRIES.get(req_country, req_country)
            logger.info(f"SOCKS5 -> [{req_country} - {c_name}] {target_display} via upstream ({upstream['host']}:{upstream['port']})")

            r, w, res = await self.dial_upstream_tunnel(upstream, formatted_user, target_host, target_port)
            if res != "ok" or not w:
                if "407" in str(res) or "Authentication Required" in str(res):
                    logger.warning(f"SOCKS5 upstream tunnel failed with 407 ({res}). Auto-rotating session...")
                    rotated = await self.handle_407_rotation(upstream.get("raw") or upstream.get("user"))
                    if rotated:
                        upstream_new = self.get_upstream_proxy(req_country)
                        if upstream_new:
                            formatted_user_new = self.format_upstream_user(upstream_new["user"], req_country, client_session)
                            r, w, res = await self.dial_upstream_tunnel(upstream_new, formatted_user_new, target_host, target_port)

                if res != "ok" or not w:
                    logger.warning(f"SOCKS5 upstream tunnel failed: {res}")
                    client_writer.write(b"\x05\x04\x00\x01\x00\x00\x00\x00\x00\x00")
                    await client_writer.drain()
                    return

            upstream_reader = r
            upstream_writer = w

            client_writer.write(b"\x05\x00\x00\x01\x00\x00\x00\x00\x00\x00")
            await client_writer.drain()

            await self.pipe_streams(client_reader, client_writer, upstream_reader, upstream_writer, target_display, req_country)

        except Exception as e:
            logger.debug(f"SOCKS5 error ({target_display}): {e}")
        finally:
            try:
                client_writer.close()
                await client_writer.wait_closed()
            except Exception:
                pass
            try:
                if upstream_writer:
                    upstream_writer.close()
                    await upstream_writer.wait_closed()
            except Exception:
                pass

    async def handle_client(self, client_reader, client_writer, fixed_country=None):
        optimize_socket(client_writer)
        target_display = "unknown"
        upstream_writer = None
        upstream_reader = None

        try:
            first_byte = await client_reader.read(1)
            if not first_byte:
                client_writer.close()
                await client_writer.wait_closed()
                return

            if first_byte == b"\x05":
                client_addr = client_writer.get_extra_info('peername')
                await self.handle_socks5(client_reader, client_writer, client_addr, fixed_country)
                return

            req_data = first_byte
            while b"\r\n\r\n" not in req_data and len(req_data) < 16384:
                chunk = await client_reader.read(4096)
                if not chunk:
                    break
                req_data += chunk

            header_end = req_data.find(b"\r\n\r\n")
            if header_end == -1:
                client_writer.close()
                await client_writer.wait_closed()
                return

            extra_body = req_data[header_end + 4:]
            header_text = req_data[:header_end].decode("latin-1", errors="replace")
            lines = header_text.split("\r\n")
            req_line = lines[0] if lines else ""
            parts = req_line.split(" ")
            if len(parts) < 3:
                client_writer.close()
                return

            method, target_uri, http_ver = parts[0], parts[1], parts[2]

            headers = {}
            for line in lines[1:]:
                if ": " in line:
                    k, v = line.split(": ", 1)
                    headers[k.lower()] = v.strip()

            raw_user = ""
            auth_header = headers.get("proxy-authorization")
            if auth_header and auth_header.startswith("Basic "):
                try:
                    b64 = auth_header[6:].strip()
                    cred = base64.b64decode(b64).decode("utf-8", errors="replace")
                    raw_user = cred.split(":", 1)[0] if ":" in cred else cred
                except Exception:
                    raw_user = ""

            req_country, client_session = self.parse_client_username(raw_user, fixed_country)

            if method.upper() == "CONNECT":
                if ":" in target_uri:
                    target_host, target_port = target_uri.split(":", 1)
                    target_port = int(target_port)
                else:
                    target_host, target_port = target_uri, 443
                target_display = f"{target_host}:{target_port}"
            else:
                parsed = urlparse(target_uri)
                target_host = parsed.hostname or headers.get("host", "").split(":")[0]
                target_port = parsed.port or (443 if parsed.scheme == "https" else 80)
                target_display = f"{target_host}:{target_port}"

            upstream = self.get_upstream_proxy(req_country)
            if not upstream:
                logger.error("No upstream proxies available in proxy.txt!")
                client_writer.write(b"HTTP/1.1 502 Bad Gateway (proxy file is empty)\r\n\r\n")
                await client_writer.drain()
                client_writer.close()
                return

            formatted_user = self.format_upstream_user(upstream["user"], req_country, client_session)
            c_name = ALL_COUNTRIES.get(req_country, req_country)
            logger.info(f"HTTP {method} -> [{req_country} - {c_name}] {target_display} via upstream ({upstream['host']}:{upstream['port']})")

            if method.upper() == "CONNECT":
                r, w, res = await self.dial_upstream_tunnel(upstream, formatted_user, target_host, target_port)
                if res != "ok" or not w:
                    if "407" in str(res) or "Authentication Required" in str(res):
                        logger.warning(f"CONNECT tunnel failed with 407 ({res}). Auto-rotating session...")
                        rotated = await self.handle_407_rotation(upstream.get("raw") or upstream.get("user"))
                        if rotated:
                            upstream_new = self.get_upstream_proxy(req_country)
                            if upstream_new:
                                formatted_user_new = self.format_upstream_user(upstream_new["user"], req_country, client_session)
                                r, w, res = await self.dial_upstream_tunnel(upstream_new, formatted_user_new, target_host, target_port)

                    if res != "ok" or not w:
                        logger.warning(f"CONNECT tunnel failed: {res}")
                        client_writer.write(b"HTTP/1.1 502 Bad Gateway\r\n\r\n")
                        await client_writer.drain()
                        client_writer.close()
                        return

                client_writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
                await client_writer.drain()
                upstream_reader = r
                upstream_writer = w
            else:
                upstream_ip = await get_cached_ip(upstream["host"])
                cred = base64.b64encode(f"{formatted_user}:{upstream['pass']}".encode("utf-8")).decode("utf-8")
                try:
                    r, w = await asyncio.wait_for(asyncio.open_connection(upstream_ip, upstream["port"]), timeout=12.0)
                    optimize_socket(w)
                except Exception as e:
                    logger.error(f"Cannot dial upstream {upstream['host']}:{upstream['port']} - {e}")
                    client_writer.write(b"HTTP/1.1 504 Gateway Timeout\r\n\r\n")
                    await client_writer.drain()
                    client_writer.close()
                    return

                clean_headers = [l for l in lines[1:] if not l.lower().startswith("proxy-authorization:")]
                clean_headers.append(f"Proxy-Authorization: Basic {cred}")
                if target_uri.startswith("/"):
                    port_str = f":{target_port}" if target_port != 80 else ""
                    full_url = f"http://{target_host}{port_str}{target_uri}"
                else:
                    full_url = target_uri
                fwd_http = f"{method} {full_url} {http_ver}\r\n" + "\r\n".join(clean_headers) + "\r\n\r\n"
                w.write(fwd_http.encode("latin-1"))
                if extra_body:
                    w.write(extra_body)
                await w.drain()
                upstream_reader = r
                upstream_writer = w

            await self.pipe_streams(client_reader, client_writer, upstream_reader, upstream_writer, target_display, req_country)

        except Exception as e:
            logger.debug(f"HTTP error ({target_display}): {e}")
        finally:
            try:
                client_writer.close()
                await client_writer.wait_closed()
            except Exception:
                pass
            try:
                if upstream_writer:
                    upstream_writer.close()
                    await upstream_writer.wait_closed()
            except Exception:
                pass

    async def start(self):
        proxies = self.load_proxies(force=True)
        if not proxies:
            logger.warning("[*] Initial proxies empty or not found. Checking link pool for active session...")
            await self.handle_407_rotation()
            proxies = self.load_proxies(force=True)

        def create_handler(fixed_country=None):
            async def _handler(reader, writer):
                await self.handle_client(reader, writer, fixed_country=fixed_country)
            return _handler

        active_primary_ports = []
        for port in PRIMARY_PORTS:
            try:
                srv = await asyncio.start_server(create_handler(None), self.host, port)
                self.servers.append(srv)
                active_primary_ports.append(port)
            except Exception as e:
                logger.warning(f"Could not bind primary port {port}: {e}")

        active_country_ports = []
        for c_port, (c_code, c_name) in COUNTRY_PORTS.items():
            try:
                srv = await asyncio.start_server(create_handler(c_code), self.host, c_port)
                self.servers.append(srv)
                active_country_ports.append((c_port, c_code, c_name))
            except Exception:
                pass

        print("\n" + "=" * 75)
        print("          EASYADS LOCAL & NETWORK PROXY SERVER (local.py)")
        print("=" * 75)
        print(f" [+] Binding Address     : {self.host} (All Interfaces)")
        print(f" [+] Localhost Access    : 127.0.0.1:1000 (HTTP / HTTPS / SOCKS5)")
        print(f" [+] Network (LAN) Access: {self.lan_ip}:1000 (Phones, Tablets, other PCs)")
        print(f" [+] Country Targeting   : 127.0.0.1:1000:anyuser-country-US:easyads")
        print(f" [+] Dedicated Ports     : 9001 (US), 9002 (GB), 9003 (DE), 9004 (CA), 9007 (IN)...")
        print(f" [+] Upstream Source     : {os.path.basename(self.get_proxy_file_path())} ({len(proxies)} proxies loaded)")
        print(f" [+] Total Countries     : {len(ALL_COUNTRIES)} Countries & Territories Loaded")
        print(f" [+] 407 Auto-Rotation   : Instant (<0.1s) swap to pre-claimed proxy vault")
        print("=" * 75 + "\n")

        await asyncio.gather(*(s.serve_forever() for s in self.servers))

async def run_server():
    server = LocalProxyServer(host="0.0.0.0", default_country="US")
    while True:
        try:
            await server.start()
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Server error: {e}. Recovering in 1s...")
            await asyncio.sleep(1)

def main():
    try:
        asyncio.run(run_server())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Local proxy server stopped cleanly.")

if __name__ == "__main__":
    main()

