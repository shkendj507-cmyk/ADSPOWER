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
    """24/7 Headless AdsPower Link Creator that continuously creates and claims proxies."""
    buffer_size = max(threads, 2)
    while True:
        try:
            await adspower_creator.run_24h_creator_loop(target_buffer=buffer_size, headless=True, concurrency=threads)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"[Creator] Worker notice: {e}. Retrying in 5s...")
            await asyncio.sleep(5)

async def proxy_server_task():
    """Runs the 24/7 Local & LAN proxy server on port 1000, 8080 and country ports."""
    server = local.LocalProxyServer(host="0.0.0.0", default_country="US")
    while True:
        try:
            await server.start()
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"[Server] Proxy server notice: {e}. Recovering in 2s...")
            await asyncio.sleep(2)

async def keep_alive_monitor_task():
    """Background monitor checking proxy tunnel health in parallel and keeping sessions active 24/7."""
    last_session_refresh = 0
    last_full_scan = 0
    while True:
        try:
            await asyncio.sleep(5)
            now = time.time()
            if now - last_session_refresh > 45:
                refreshed = proxy_vault.keep_all_sessions_alive()
                last_session_refresh = now

            # Rapid background scan of all proxies in parallel every 90 seconds
            if now - last_full_scan > 90:
                await proxy_vault.scan_and_clean_dead_proxies(concurrency=25)
                local.LocalProxyServer().load_proxies(force=True)
                last_full_scan = now

        except asyncio.CancelledError:
            break
        except Exception as e:
            await asyncio.sleep(5)

async def main():
    # Parse thread count from command line args if provided
    threads = 2
    if len(sys.argv) > 1 and sys.argv[1].isdigit():
        threads = max(int(sys.argv[1]), 1)

    print("\n" + "=" * 78)
    print("      EASYADS 24/7 UNIFIED AUTOMATED PROXY & CREATOR SYSTEM")
    print("=" * 78)
    print(" [+] Mode             : Single Consolidated Master Service (24/7 Continuous)")
    print(f" [+] Creator Threads  : {threads} Concurrent Browser(s) creating accounts")
    print(" [+] Local Proxy      : 127.0.0.1:1000 (HTTP / HTTPS / SOCKS5)")
    print(" [+] Creator Engine   : 24/7 Headless Auto-Registration & SATE SATE Claim")
    print(" [+] Vault Rotation   : 407 Proxy Authentication Required -> Instant 0.001s swap")
    print(f" [+] Reserve Buffer   : Pre-claims {max(threads, 2)} proxies ready in advance")
    print(" [+] Press Ctrl+C anytime to stop.")
    print("=" * 78 + "\n")

    # 1. Instant parallel health check on startup
    print("[*] Performing instant parallel health-check of all upstream proxies...")
    await proxy_vault.scan_and_clean_dead_proxies(concurrency=25)

    # 2. Start all 3 coordinated tasks together
    asyncio.create_task(proxy_server_task(), name="ProxyServer")
    asyncio.create_task(creator_worker_task(threads=threads), name="CreatorEngine")
    asyncio.create_task(keep_alive_monitor_task(), name="KeepAliveMonitor")

    # Run continuously 24/7 without terminating the VPS or disconnecting SSH/RDP
    while True:
        await asyncio.sleep(60)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("\n[+] EasyAds unified system stopped cleanly.")
