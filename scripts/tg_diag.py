# Диагностика конфликтов getUpdates: вебхук и активные потребители. Одноразовый скрипт.
import asyncio
import os
import sys

import aiohttp
from dotenv import load_dotenv

load_dotenv()


async def main() -> None:
    token = os.environ["BOT_TOKEN"]
    base = f"https://api.telegram.org/bot{token}"
    async with aiohttp.ClientSession() as s:
        async with s.get(f"{base}/getWebhookInfo") as r:
            res = (await r.json()).get("result", {})
        print("webhook_url:", repr(res.get("url")))
        print("pending_updates:", res.get("pending_update_count"))
        async with s.get(f"{base}/getUpdates?timeout=0") as r:
            data = await r.json()
        print("getUpdates ok:", data.get("ok"), "| error_code:", data.get("error_code"),
              "| description:", data.get("description"))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    asyncio.run(main())
