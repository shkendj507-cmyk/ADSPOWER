import asyncio
import cv2
import numpy as np
import requests
import re
import random
import string
import time
import secrets
import os
import sys
import json
import base64
import uuid
import threading
import tempfile
import shutil
import urllib.request
import urllib.parse
from playwright.async_api import async_playwright
import proxy_vault

save_lock = threading.Lock()

def extract_auth_code(link_or_code: str) -> str:
    link_or_code = (link_or_code or "").strip()
    if "x_auth_code=" in link_or_code:
        match = re.search(r"x_auth_code=([a-zA-Z0-9_-]+)", link_or_code)
        if match:
            return match.group(1)
    return link_or_code



def generate_random_password(length: int = 14) -> str:
    upper = random.choice(string.ascii_uppercase)
    lower = random.choice(string.ascii_lowercase)
    digit = random.choice(string.digits)
    spec = random.choice("@#$!%")
    remaining = "".join(random.choices(string.ascii_letters + string.digits, k=max(length - 4, 6)))
    pwd_list = list(upper + lower + digit + spec + remaining)
    random.shuffle(pwd_list)
    return "".join(pwd_list)

def generate_desigroup_email() -> str:
    chars = string.ascii_lowercase + string.digits
    user = "ads" + "".join(random.choices(chars, k=7))
    return f"{user}@desigroup.buzz"

def poll_desigroup_otp(email: str, max_wait: int = 40, poll_interval: float = 0.8) -> str | None:
    url = f"https://desigroup.buzz/api/messages?email={email}"
    headers = {"User-Agent": "Mozilla/5.0"}
    start = time.time()
    print(f"[*] Polling OTP from {url}...")
    while time.time() - start < max_wait:
        try:
            r = requests.get(url, headers=headers, timeout=6)
            if r.status_code == 200:
                msgs = r.json()
                if isinstance(msgs, list) and msgs:
                    for m in msgs:
                        otp = str(m.get("otp") or "").strip()
                        if otp and re.match(r'^\d{4,8}$', otp):
                            return otp
                        subj = str(m.get("subject") or "").strip()
                        match = re.search(r'\b(\d{6})\b', subj)
                        if match:
                            return match.group(1)
        except Exception:
            pass
        time.sleep(poll_interval)
    return None

def find_slider_distance(bg_bytes: bytes, slice_bytes: bytes, rendered_width: float) -> float:
    bg_img = cv2.imdecode(np.frombuffer(bg_bytes, np.uint8), cv2.IMREAD_COLOR)
    slice_img = cv2.imdecode(np.frombuffer(slice_bytes, np.uint8), cv2.IMREAD_UNCHANGED)
    orig_h, orig_w = bg_img.shape[:2]
    
    if slice_img.shape[2] == 4:
        alpha = slice_img[:, :, 3]
        pts = cv2.findNonZero(alpha)
        if pts is not None:
            x, y, w, h = cv2.boundingRect(pts)
            slice_crop = slice_img[y:y+h, x:x+w, :3]
        else:
            slice_crop = slice_img
    else:
        slice_crop = slice_img

    bg_gray = cv2.cvtColor(bg_img, cv2.COLOR_BGR2GRAY)
    slice_gray = cv2.cvtColor(slice_crop, cv2.COLOR_BGR2GRAY)
    
    bg_edge = cv2.Canny(bg_gray, 100, 200)
    slice_edge = cv2.Canny(slice_gray, 100, 200)
    
    res = cv2.matchTemplate(bg_edge, slice_edge, cv2.TM_CCOEFF_NORMED)
    
    # Ignore the first 35px in rendered coordinates to prevent matching initial slot edge
    min_x_pixel = int(35 * orig_w / rendered_width)
    res[:, :min_x_pixel] = -1.0
    
    _, max_val, _, max_loc = cv2.minMaxLoc(res)
    
    target_x_orig = max_loc[0]
    return target_x_orig * (rendered_width / orig_w)

async def solve_geetest_slide(page) -> bool:
    btn = page.locator("[class*='geetest_btn']:visible").first
    try:
        await btn.wait_for(state="visible", timeout=8000)
    except Exception:
        btns = page.locator("[class*='geetest_btn']")
        count = await btns.count()
        found = False
        for i in range(count):
            if await btns.nth(i).is_visible():
                btn = btns.nth(i)
                found = True
                break
        if not found:
            print("[-] Visible slider button not found.")
            return False
    
    # Wait until background image and slice image are loaded
    info = None
    for _ in range(15):
        info = await page.evaluate('''() => {
            const getVisible = (sel) => {
                const els = Array.from(document.querySelectorAll(sel));
                for (const el of els) {
                    const rect = el.getBoundingClientRect();
                    if (rect.width > 0 && rect.height > 0 && window.getComputedStyle(el).visibility !== 'hidden') {
                        return el;
                    }
                }
                return els[0];
            };
            const bgEl = getVisible('[class*="geetest_bg"]');
            const sliceEl = getVisible('[class*="geetest_slice_bg"]');
            return {
                bg: bgEl ? window.getComputedStyle(bgEl).backgroundImage : '',
                slice: sliceEl ? window.getComputedStyle(sliceEl).backgroundImage : '',
                bgWidth: bgEl ? bgEl.offsetWidth : 300
            };
        }''')
        if info and "url(" in info.get("bg", "") and "url(" in info.get("slice", ""):
            break
        await asyncio.sleep(0.4)
        
    bg_match = re.search(r'url\("?([^"]+)"?\)', info.get('bg', ''))
    slice_match = re.search(r'url\("?([^"]+)"?\)', info.get('slice', ''))
    if not bg_match or not slice_match:
        print("[-] Captcha background or slice URL not found.")
        return False
        
    bg_url = bg_match.group(1)
    slice_url = slice_match.group(1)
    if bg_url.startswith("//"):
        bg_url = "https:" + bg_url
    if slice_url.startswith("//"):
        slice_url = "https:" + slice_url
        
    headers = {"User-Agent": "Mozilla/5.0"}
    bg_bytes = requests.get(bg_url, headers=headers, timeout=10).content
    slice_bytes = requests.get(slice_url, headers=headers, timeout=10).content
    distance = find_slider_distance(bg_bytes, slice_bytes, info.get('bgWidth', 300))
    print(f"[+] Calculated slider distance: {distance:.2f}px")
    
    box = await btn.bounding_box()
    if not box:
        box = await page.evaluate('''() => {
            const els = Array.from(document.querySelectorAll('[class*="geetest_btn"]'));
            for (const el of els) {
                const r = el.getBoundingClientRect();
                if (r.width > 0 && r.height > 0) {
                    return {x: r.left, y: r.top, width: r.width, height: r.height};
                }
            }
            return null;
        }''')
    if not box:
        print("[-] Slider button bounding box not found.")
        return False
        
    start_x = box['x'] + box['width'] / 2
    start_y = box['y'] + box['height'] / 2
    
    # 1. Approach button with natural cursor curve
    curr_x = start_x - random.randint(60, 140)
    curr_y = start_y + random.randint(30, 80)
    await page.mouse.move(curr_x, curr_y)
    for _ in range(4):
        curr_x += (start_x - curr_x) * 0.45
        curr_y += (start_y - curr_y) * 0.45
        await page.mouse.move(curr_x, curr_y)
        await asyncio.sleep(random.uniform(0.015, 0.03))
    await page.mouse.move(start_x, start_y)
    await page.wait_for_timeout(random.randint(180, 280))
    
    # 2. Press mouse down
    await page.mouse.down()
    await page.wait_for_timeout(random.randint(120, 200))
    
    # 3. Drag with human trajectory: fast acceleration -> deceleration -> micro-correction
    overshoot = random.uniform(2.0, 3.5)
    total_drag = distance + overshoot
    steps = 12
    for i in range(steps):
        t = (i + 1) / steps
        cur_dist = total_drag * (1 - (1 - t) ** 2.2)
        step_x = start_x + cur_dist
        step_y = start_y + random.uniform(-0.6, 0.6)
        await page.mouse.move(step_x, step_y)
        await asyncio.sleep(0.008)
        
    await asyncio.sleep(0.04)
    back_steps = 3
    for j in range(back_steps):
        back_t = (j + 1) / back_steps
        step_x = start_x + total_drag - (overshoot * back_t)
        step_y = start_y + random.uniform(-0.3, 0.3)
        await page.mouse.move(step_x, step_y)
        await asyncio.sleep(0.008)
        
    await asyncio.sleep(0.06)
    await page.mouse.up()
    print("[*] Slider drag completed.")
    await page.wait_for_timeout(600)
    return True

PROXY_USAGE_TRACKER = {}
PROXY_TRACK_LOCK = threading.Lock()

def get_worker_proxy(worker_id: int) -> dict | None:
    """
    Returns a proxy from proxy.txt with STRICT limit:
    Each proxy is used for at most 2 session changes (2 accounts).
    If someone runs 100 threads, 50 proxies will be allocated (each used 2 times).
    Prevents SX.org account suspension from excessive session changes.
    """
    proxy_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "proxy.txt")
    if not os.path.exists(proxy_file):
        return None
    try:
        with open(proxy_file, "r", encoding="utf-8") as f:
            lines = [l.strip() for l in f if l.strip() and not l.strip().startswith("#")]
        if not lines:
            return None

        with PROXY_TRACK_LOCK:
            # Filter proxies that have been used LESS than 2 times
            available = [l for l in lines if PROXY_USAGE_TRACKER.get(l, 0) < 2]
            if not available:
                # If all reached 2 sessions, pick the least used
                available = sorted(lines, key=lambda l: PROXY_USAGE_TRACKER.get(l, 0))

            selected = available[0]
            current_uses = PROXY_USAGE_TRACKER.get(selected, 0) + 1
            PROXY_USAGE_TRACKER[selected] = current_uses

        parts = selected.split(":")
        if len(parts) >= 4:
            ip, port, user, pwd = parts[0], parts[1], parts[2], parts[3]
            # Change session at most 2 times per proxy (s1 or s2)
            sess_id = f"s{current_uses}_{uuid.uuid4().hex[:6]}"
            if "-session-" in user:
                user = re.sub(r'-session-[a-zA-Z0-9_]+', f'-session-{sess_id}', user)
            else:
                user = f"{user}-session-{sess_id}"

            # Always inject clean Tier-1 country (US, GB, DE, CA, FR) to bypass AdsPower 1008
            tier1 = ["US", "GB", "DE", "CA", "FR", "NL", "AU"]
            target_country = tier1[(worker_id + current_uses) % len(tier1)]
            if "-country-" in user:
                user = re.sub(r'-country-[a-zA-Z]+', f'-country-{target_country}', user)
            else:
                user = f"{user}-country-{target_country}"

            idx = lines.index(selected) + 1
            print(f"[*] [Thread {worker_id}] Allocated Proxy #{idx}/{len(lines)} | Session: {current_uses}/2 max | Country: {target_country} | Host: {ip}:{port}")
            return {
                "server": f"http://{ip}:{port}",
                "username": user,
                "password": pwd,
                "raw": selected
            }
        elif len(parts) >= 2:
            return {
                "server": f"http://{parts[0]}:{parts[1]}",
                "raw": selected
            }
    except Exception as e:
        print(f"[*] [Thread {worker_id}] Proxy selection error: {e}")
    return None

async def register_account(headless: bool = False, worker_id: int = 1) -> dict | None:
    email = generate_desigroup_email()
    password = generate_random_password()
    print("\n" + "=" * 55)
    print(f"[*] [Thread {worker_id}] Target Email    : {email}")
    print(f"[*] [Thread {worker_id}] Generated Pass  : {password}")
    print("=" * 55)
    
    captured = {
        "cpl": None,
        "token": None,
        "email": email,
        "password": password,
        "cookies": {},
        "send_code_error": None,
        "code_sent_success": False,
        "rate_limited_1008": False,
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S")
    }
    
    ext_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "CAPCHA", "0.2.3800_0"))
    if not os.path.exists(ext_path):
        alt_path = r"C:\Users\MANIK\Videos\ADS\CAPCHA\0.2.3800_0"
        if os.path.exists(alt_path):
            ext_path = alt_path
    user_data_dir = os.path.join(tempfile.gettempdir(), f"ads_profile_{worker_id}_{int(time.time()*1000)}")
    os.makedirs(user_data_dir, exist_ok=True)
    
    launch_args = [
        f"--disable-extensions-except={ext_path}",
        f"--load-extension={ext_path}",
        "--disable-blink-features=AutomationControlled",
        "--no-sandbox",
        "--disable-infobars",
        "--disable-dev-shm-usage",
    ]
    if headless:
        launch_args.append("--headless=new")

    launch_kwargs = {
        "user_data_dir": user_data_dir,
        "headless": False,
        "args": launch_args,
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "viewport": {"width": 1280, "height": 800},
        "locale": "en-US",
    }

    # Automatically attach a rotating residential proxy IP from live pool if available
    worker_proxy = get_worker_proxy(worker_id)
    if worker_proxy:
        launch_kwargs["proxy"] = worker_proxy
        print(f"[*] [Thread {worker_id}] Using rotating residential proxy IP: {worker_proxy['server']}")

    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(**launch_kwargs)
        await context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            window.chrome = { runtime: {} };
            Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
        """)
        page = context.pages[0] if context.pages else await context.new_page()
        
        async def handle_response(resp):
            url = resp.url
            if "sys/user/passport/send-reg-code-v2" in url:
                try:
                    res_json = await resp.json()
                    print(f"\n[Thread {worker_id}] [SEND REG CODE RESP] {res_json}")
                    if res_json.get("code") == 0:
                        captured["code_sent_success"] = True
                        captured["send_code_error"] = None
                    elif res_json.get("code") == 1008:
                        captured["rate_limited_1008"] = True
                        print(f"[!] [Thread {worker_id}] AdsPower rate limit (1008) hit. Will cooldown 25s & auto-retry...")
                    else:
                        captured["send_code_error"] = res_json.get("msg", "Error")
                except Exception as ex:
                    print(f"[SEND REG CODE PARSE ERR]: {ex}")
            elif "sys/user/passport/register-v2" in url:
                try:
                    res_json = await resp.json()
                    print(f"\n[REGISTER RESP] {res_json}")
                    if res_json.get("code") == 0 and "data" in res_json:
                        captured["cpl"] = res_json["data"].get("cpl")
                        captured["token"] = captured["cpl"]
                except Exception as ex:
                    print(f"[REGISTER PARSE ERR]: {ex}")
                    
        page.on("response", handle_response)
        
        target_reg_url = "https://app.adspower.com/registration"
        print(f"[*] Navigating to {target_reg_url}...")
        try:
            await page.goto(target_reg_url, wait_until="domcontentloaded", timeout=40000)
        except Exception:
            pass
        await page.wait_for_timeout(3000)
        
        # 1. Fill email
        email_inp = page.locator("input[placeholder='Enter email']")
        await email_inp.wait_for(state="visible", timeout=25000)
        await email_inp.fill(email)
        await page.wait_for_timeout(200)
        
        # Check if "I'm not a robot" reCAPTCHA is on page before getting code
        recaptcha_iframe = page.locator("iframe[src*='recaptcha'], iframe[title*='reCAPTCHA'], iframe[title*='recaptcha']").first
        try:
            if await recaptcha_iframe.is_visible(timeout=3000):
                print(f"[*] [Thread {worker_id}] reCAPTCHA ('I\'m not a robot') detected! Triggering extension solver...")
                anchor = page.frame_locator("iframe[src*='recaptcha']").locator("#recaptcha-anchor")
                
                # Keep checking until reCAPTCHA is solved
                recaptcha_solved = False
                for attempt in range(1, 35):
                    try:
                        if await anchor.is_visible():
                            checked = await anchor.get_attribute("aria-checked")
                            if checked == "true":
                                recaptcha_solved = True
                                break
                            elif attempt == 1 or attempt % 8 == 0:
                                print(f"[*] [Thread {worker_id}] Clicking reCAPTCHA checkbox (attempt {attempt})...")
                                await anchor.click()
                    except Exception:
                        pass
                        
                    resp_val = await page.evaluate('''() => {
                        const el = document.querySelector('[name="g-recaptcha-response"], #g-recaptcha-response');
                        return el ? el.value : '';
                    }''')
                    if resp_val:
                        recaptcha_solved = True
                        break
                    await asyncio.sleep(1.5)
                    
                if recaptcha_solved:
                    print(f"[+] [Thread {worker_id}] reCAPTCHA verified successfully by extension!")
                    await page.wait_for_timeout(1000)
        except Exception as e:
            print(f"[*] [Thread {worker_id}] reCAPTCHA check: {e}")

        # 2. Click "Get verification code" and retry captcha until code is sent
        print(f"[*] [Thread {worker_id}] Requesting verification code...")
        captcha_cycles = 0
        while not captured.get("code_sent_success") and not captured.get("send_code_error") and captcha_cycles < 12:
            captcha_cycles += 1
            if captured.get("rate_limited_1008"):
                print(f"[*] [Thread {worker_id}] 1008 cooldown active: waiting 25s before retry...")
                await asyncio.sleep(25)
                captured["rate_limited_1008"] = False

            get_code_btn = page.locator("button:has-text('Get verification code')")
            try:
                btn_text = await get_code_btn.inner_text()
                if "Get verification code" in btn_text:
                    print(f"[*] [Thread {worker_id}] Clicking 'Get verification code' (Cycle {captcha_cycles})...")
                    await get_code_btn.click()
                    await page.wait_for_timeout(1500)
            except Exception:
                pass

            if captured.get("code_sent_success") or captured.get("send_code_error"):
                break

            # Handle Geetest if popup appears
            popup_loc = page.locator("[class*='geetest_window']:visible, [class*='geetest_popup']:visible, [class*='geetest_box']:visible, [class*='geetest_btn']:visible").first
            try:
                if await popup_loc.is_visible(timeout=4000):
                    print(f"[+] [Thread {worker_id}] Geetest captcha popup detected!")
                    await page.wait_for_timeout(1000)
                    for slide_attempt in range(1, 15):
                        visible_btns = await page.locator("[class*='geetest_btn']:visible").count()
                        if visible_btns == 0 or captured.get("code_sent_success"):
                            print(f"[+] [Thread {worker_id}] Geetest captcha solved/closed!")
                            break
                        print(f"[*] [Thread {worker_id}] Solving Geetest slide puzzle (Attempt {slide_attempt})...")
                        await solve_geetest_slide(page)
                        await page.wait_for_timeout(3000)
                        
                        # If still visible, try clicking refresh on Geetest
                        if await page.locator("[class*='geetest_btn']:visible").count() > 0:
                            refresh_btn = page.locator("[class*='geetest_refresh']:visible").first
                            if await refresh_btn.is_visible():
                                try:
                                    print(f"[*] [Thread {worker_id}] Refreshing Geetest slide...")
                                    await refresh_btn.click()
                                    await page.wait_for_timeout(1200)
                                except Exception:
                                    pass
            except Exception as e:
                print(f"[*] [Thread {worker_id}] Geetest handler: {e}")

            # Check if reCAPTCHA challenge modal appears
            bframe = page.locator("iframe[src*='bframe'], iframe[title*='recaptcha challenge']").first
            try:
                if await bframe.is_visible(timeout=3000):
                    print(f"[*] [Thread {worker_id}] reCAPTCHA challenge popup detected! Extension solving...")
                    for _ in range(40):
                        if not await bframe.is_visible() or captured.get("code_sent_success"):
                            print(f"[+] [Thread {worker_id}] reCAPTCHA challenge solved and closed!")
                            break
                        await asyncio.sleep(1)
            except Exception as e:
                print(f"[*] [Thread {worker_id}] reCAPTCHA challenge handler: {e}")

            if captured.get("code_sent_success"):
                break
            await page.wait_for_timeout(2000)

        # Check if server blocked this IP
        if captured.get("send_code_error"):
            print(f"\n[!] Send Code Rejected: {captured['send_code_error']}")
            print("[!] REASON FOR 'Unusual behavior, unable to register or login':")
            print("    -> AdsPower rate-limited this residential session. Rotating to next live proxy...")
            await context.close()
            try: shutil.rmtree(user_data_dir, ignore_errors=True)
            except Exception: pass
            return None
                
        # 4. Poll OTP from desigroup.buzz
        otp = poll_desigroup_otp(email, max_wait=45)
        if not otp:
            print("[-] Verification OTP not received on desigroup.buzz.")
            await context.close()
            try: shutil.rmtree(user_data_dir, ignore_errors=True)
            except Exception: pass
            return None
            
        print(f"[+] Successfully extracted OTP: {otp}")
        
        # 5. Fill OTP
        code_inp = page.locator("input[placeholder='Please enter the verification code']")
        await code_inp.fill(otp)
        
        # 6. Fill Password
        pwd_inp = page.locator("input[placeholder='Enter password']")
        await pwd_inp.fill(password)
        
        # 7. Select Terms Agreement checkbox
        svg = page.locator("#readProtocol svg")
        box = await svg.bounding_box()
        if box:
            print("[*] Checking Terms Agreement checkbox...")
            await page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
            await page.wait_for_timeout(150)
            
        # 8. Submit Sign Up
        signup_btn = page.locator("button:has-text('Sign up')")
        btn_box = await signup_btn.bounding_box()
        print("[*] Clicking 'Sign up'...")
        if btn_box:
            await page.mouse.click(btn_box["x"] + btn_box["width"] / 2, btn_box["y"] + btn_box["height"] / 2)
        else:
            await signup_btn.click()
        
        # 9. Wait for registration completion & token capture
        print("[*] Waiting for registration to complete & token capture...")
        for _ in range(40):
            if captured.get("cpl"):
                break
            await asyncio.sleep(0.2)
            
        await page.wait_for_timeout(300)
        
        # Extract cookies and localStorage token if needed
        cookies = await context.cookies()
        captured["cookies"] = {c["name"]: c["value"] for c in cookies}
        
        if not captured.get("cpl"):
            ls_token = await page.evaluate('''() => {
                return window.localStorage.getItem("CLT") || window.sessionStorage.getItem("CLT") || "";
            }''')
            if ls_token:
                captured["cpl"] = ls_token
                captured["token"] = ls_token
        else:
            captured["token"] = captured["cpl"]
            
        print(f"[+] Account Email  : {captured.get('email')}")
        print(f"[+] Account Pass   : {captured.get('password')}")
        print(f"[+] Captured Token : {captured.get('cpl')}")
        
        await context.close()
        try: shutil.rmtree(user_data_dir, ignore_errors=True)
        except Exception: pass
        
    return captured


CF_WORKER_URL = "https://sx.shkendj507.workers.dev"

def get_sx_jump_url(token: str, mix_auth_token: str = "") -> str | None:
    # 1. First attempt via Cloudflare Edge Worker (Clean IP, no ISP blocks or rate limits)
    if CF_WORKER_URL:
        try:
            cf_url = f"{CF_WORKER_URL}/api/jump"
            payload = json.dumps({"token": token, "mix_auth_token": mix_auth_token}).encode("utf-8")
            req = urllib.request.Request(cf_url, data=payload, headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"}, method="POST")
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                if data.get("success") and data.get("resolved_url"):
                    print("[+] [Cloudflare Edge] Successfully resolved SX Jump Link via Worker!")
                    return data.get("resolved_url")
        except Exception as e:
            print(f"[*] Cloudflare Worker jump notice: {e}. Using direct resolution...")

    # 2. Direct fallback
    s = requests.Session()
    if mix_auth_token:
        s.cookies.set("mix_auth_token", mix_auth_token)
        
    s.headers.update({
        "cpl": token,
        "accept": "application/json, text/plain, */*",
        "accept-language": "en-US,en;q=0.9",
        "origin": "https://app.adspower.com",
        "referer": "https://app.adspower.com/proxyManager?type=proxySource",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
    })
    
    jump_api = "https://api.adspower.com/sys/user/partner-share/get-jump-url?who=sxorgauto&can_see=0&lang=en-US"
    try:
        r = s.get(jump_api, timeout=12)
        if r.status_code == 200:
            res_json = r.json()
            if res_json.get("code") == 0:
                raw_url = res_json.get("data", {}).get("redirect_url", "")
                if raw_url:
                    # Follow redirect to saaslink landing URL
                    jump_res = s.get(raw_url, timeout=15, allow_redirects=True)
                    final_url = jump_res.url
                    # STOP IMMEDIATELY as requested: return the exact https://sx-org-proxy.saaslink.net/NyjLyk?x_auth_code=...&utm-source=Adspower&utm-keyword=Adspower
                    return final_url
    except Exception as e:
        print(f"[-] SX Jump URL resolution error: {e}")
    return None

def save_account_data(item: dict) -> str:
    with save_lock:
        token = item.get('cpl') or item.get('token', '')
        email = item.get('email', '')
        password = item.get('password', '')
        cookies = item.get('cookies', {})
        mix_auth_token = cookies.get('mix_auth_token', '')
        
        # 1. Resolve SX Jump Link
        print(f"\n[*] Extracting SX.org Jump Link for {email}...")
        sx_link = get_sx_jump_url(token, mix_auth_token) or ""
        
        if sx_link:
            code = extract_auth_code(sx_link)
            
            # 1. Auto-save link directly to links.txt in repo root
            links_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "links.txt")
            with open(links_file, "a", encoding="utf-8") as lf:
                lf.write(f"{sx_link}\n")
            print(f"[+] [SAVED] Link saved to links.txt: {sx_link}")

            # 2. Claim link and store proxies
            print(f"[*] Claiming SX.org proxy credentials for {email}...")
            ok, res = proxy_vault.claim_and_store_link(code, email=email)
            if ok:
                print(f"[+] [CLAIMED] Proxy account is READY in reserve! Email: {email}")
            
        print("\n" + "=" * 65)
        print(f"[SUCCESS] Account Created & SX Link Extracted!")
        print(f" -> Email   : {email}")
        print(f" -> Password: {password}")
        print(f" -> Token   : {token[:16]}...")
        if sx_link:
            print(f" -> SX LINK : {sx_link}")
        print("=" * 65)
        return sx_link


async def run_24h_creator_loop(target_buffer: int = 2, headless: bool = True, concurrency: int = 1):
    print("\n" + "=" * 75)
    print("      ADSPOWER 24/7 SX LINK CREATOR SERVICE (adspower_creator.py)")
    print("=" * 75)
    print(f" [+] Mode               : 24/7 Continuous Headless Generator")
    print(f" [+] Concurrent Threads : {concurrency} Browser(s) running simultaneously")
    print(f" [+] Headless State     : {headless} (Running invisible in background)")
    print(f" [+] Target Pool Buffer : {target_buffer} active pre-claimed proxies in reserve")
    print(f" [+] Output Destination : claimed_proxies.json and proxy.txt")
    print(f" [+] Press Ctrl+C anytime to stop.")
    print("=" * 75 + "\n")

    sem = asyncio.Semaphore(concurrency)

    async def single_worker(worker_id: int):
        async with sem:
            # Stagger startup by 7 seconds per thread to eliminate concurrent rate-limiting
            stagger = (worker_id - 1) * 7
            if stagger > 0:
                print(f"[*] [Thread #{worker_id}] Staggering start by {stagger}s to prevent IP rate-limiting (1008)...")
                await asyncio.sleep(stagger)

            now_str = time.strftime("%H:%M:%S")
            print(f"[{now_str}] [*] [Thread #{worker_id}] Starting browser to create and claim proxy...")
            data = await register_account(headless=headless, worker_id=worker_id)
            if data and (data.get("cpl") or data.get("token")):
                sx_link = await asyncio.to_thread(save_account_data, data)
                if sx_link:
                    print(f"[{time.strftime('%H:%M:%S')}] [+] [Thread #{worker_id}] SUCCESS! Claimed. Reserve: {proxy_vault.get_reserve_count()}")
                    return True
            print(f"[-] [Thread #{worker_id}] Registration attempt failed.")
            return False

    cycle = 0
    while True:
        try:
            cycle += 1
            now_str = time.strftime("%H:%M:%S")
            print(f"\n[{now_str}] [*] [Cycle #{cycle}] Spawning {concurrency} browser thread(s) for continuous account creation...")
            tasks = [single_worker(i + 1) for i in range(concurrency)]
            await asyncio.gather(*tasks, return_exceptions=True)

            # Brief pause between creation cycles
            await asyncio.sleep(3)
        except KeyboardInterrupt:
            print("\n[+] 24/7 Creator stopped by user.")
            break
        except Exception as e:
            now_str = time.strftime("%H:%M:%S")
            print(f"[{now_str}] [!] Error in creator loop: {e}. Retrying in 10s...")
            await asyncio.sleep(10)


async def worker_job(sem: asyncio.Semaphore, idx: int, total_count: int, headless: bool = False):
    async with sem:
        stagger = (idx - 1) * 7
        if stagger > 0:
            print(f"[*] [Thread #{idx}] Staggering start by {stagger}s to prevent IP rate-limiting (1008)...")
            await asyncio.sleep(stagger)
        print(f"\n>>> [Thread {idx}] Starting Account {idx} of {total_count} <<<")
        data = await register_account(headless=headless, worker_id=idx)
        if data and data.get("cpl"):
            await asyncio.to_thread(save_account_data, data)
        else:
            print(f"[-] [Thread {idx}] Registration failed for Account #{idx}")


async def run_concurrent(total_count: int, concurrency: int = 2, headless: bool = False):
    sem = asyncio.Semaphore(concurrency)
    tasks = [worker_job(sem, i + 1, total_count, headless=headless) for i in range(total_count)]
    await asyncio.gather(*tasks)


def main():
    args = sys.argv[1:]
    headless = True  # Default to headless as requested ("hideless mode")
    continuous = True
    target_buffer = 2
    total_count = None
    concurrency = 1

    if "--headful" in args or "--visible" in args or "-v" in args:
        headless = False
        args = [a for a in args if a not in ("--headful", "--visible", "-v")]

    if "--headless" in args or "-h" in args:
        headless = True
        args = [a for a in args if a not in ("--headless", "-h")]

    nums = []
    for a in args:
        if a.isdigit():
            nums.append(int(a))

    if nums:
        # If user explicitly passed numbers like: python adspower_creator.py 5 2
        continuous = False
        total_count = nums[0]
        if len(nums) >= 2:
            concurrency = nums[1]

    if continuous:
        asyncio.run(run_24h_creator_loop(target_buffer=target_buffer, headless=headless))
    else:
        print(f"[*] Starting AdsPower Creator: Total Accounts = {total_count}, Concurrent Threads = {concurrency}")
        print(f"[*] Output will be saved to: claimed_proxies.json & proxy.txt")
        print(f"[*] Headless Mode: {headless}")
        asyncio.run(run_concurrent(total_count, concurrency=concurrency, headless=headless))

if __name__ == "__main__":
    main()

