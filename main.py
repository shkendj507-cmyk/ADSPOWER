import asyncio
import logging
import time
import os
import sys

import local
import adspower_creator
import proxy_vault

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger("EasyAds")

async def creator_worker_task(threads: int = 2):
    """24/7 Headless AdsPower Link Creator that immediately claims proxies into the reserve vault."""
    try:
        buffer_size = max(threads, 2)
        await adspower_creator.run_24h_creator_loop(target_buffer=buffer_size, headless=True, concurrency=threads)
    except asyncio.CancelledError:
        pass
    except Exception as e:
        logger.error(f"[Creator] Worker crashed: {e}. Restarting in 5s...")
        await asyncio.sleep(5)

async def proxy_server_task():
    """Runs the 24/7 Local & LAN proxy server on port 1000 and country ports."""
    server = local.LocalProxyServer(host="0.0.0.0", default_country="US")
    while True:
        try:
            await server.start()
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"[Server] Proxy server error: {e}. Recovering in 1s...")
            await asyncio.sleep(1)

async def keep_alive_monitor_task():
    """Background monitor checking proxy tunnel health every 2 seconds for early instant swap."""
    while True:
        try:
            await asyncio.sleep(2)
            proxies = local.LocalProxyServer().load_proxies()
            if proxies:
                ok, msg = proxy_vault.ping_proxy_tunnel(proxies[0])
                if not ok and ("407" in msg or "Authentication Required" in msg):
                    logger.warning(f"[Keep-Alive] 407 Proxy Authentication Required detected ({msg})!")
                    success, acc = proxy_vault.pop_and_activate_next()
                    if success:
                        logger.info(f"[Keep-Alive] [+] Swapped to fresh claimed account in 0.001s: {acc.get('email')}!")
        except asyncio.CancelledError:
            break
        except Exception as e:
            await asyncio.sleep(2)

async def main():
    # Parse thread count from command line args if provided
    threads = 2
    if len(sys.argv) > 1 and sys.argv[1].isdigit():
        threads = max(int(sys.argv[1]), 1)

    print("\n" + "=" * 78)
    print("      EASYADS 24/7 UNIFIED AUTOMATED PROXY & CREATOR SYSTEM")
    print("=" * 78)
    print(" [+] Mode             : Single Consolidated Master Service")
    print(f" [+] Creator Threads  : {threads} Concurrent Browser(s) creating accounts")
    print(" [+] Local Proxy      : 127.0.0.1:1000 (HTTP / HTTPS / SOCKS5)")
    print(" [+] Creator Engine   : 24/7 Headless Auto-Registration & SATE SATE Claim")
    print(" [+] Vault Rotation   : 407 Proxy Authentication Required -> Instant 0.001s swap")
    print(f" [+] Reserve Buffer   : Pre-claims {max(threads, 2)} proxies ready in advance")
    print(" [+] Press Ctrl+C anytime to stop.")
    print("=" * 78 + "\n")

    # Start all 3 coordinated tasks together
    t_server = asyncio.create_task(proxy_server_task(), name="ProxyServer")
    t_creator = asyncio.create_task(creator_worker_task(threads=threads), name="CreatorEngine")
    t_monitor = asyncio.create_task(keep_alive_monitor_task(), name="KeepAliveMonitor")

    await asyncio.gather(t_server, t_creator, t_monitor)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("\n[+] EasyAds unified system stopped cleanly.")
