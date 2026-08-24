# Изоляция конфликта getUpdates: поллинг без нашего бота. Одноразовый скрипт.
import asyncio
import os
import sys
import time

import aiohttp
from dotenv import load_dotenv

load_dotenv()


async def main() -> None:
    token = os.environ["BOT_TOKEN"]
    base = f"https://api.telegram.org/bot{token}"
    conflicts = 0
    ok = 0
    async with aiohttp.ClientSession() as s:
        for i in range(10):
            try:
                async with s.get(f"{base}/getUpdates?timeout=3", timeout=aiohttp.ClientTimeout(total=15)) as r:
                    data = await r.json()
            except Exception as e:
                print(f"[{i}] network error: {type(e).__name__}: {e}")
                await asyncio.sleep(2)
                continue
            if data.get("ok"):
                ok += 1
                print(f"[{i}] ok, updates={len(data.get('result', []))}")
            else:
                desc = data.get("description", "")
                if "Conflict" in desc:
                    conflicts += 1
                print(f"[{i}] ERROR {data.get('error_code')}: {desc}")
            await asyncio.sleep(1)
    print(f"--- итог: ok={ok}, conflicts={conflicts} ---")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    t0 = time.time()
    asyncio.run(main())
    print(f"elapsed: {time.time() - t0:.0f}s")
