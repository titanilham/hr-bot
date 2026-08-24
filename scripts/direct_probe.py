# Прямой запрос к API Telegram с пином IP. Сравнение с обычным путем. Одноразовый скрипт.
import asyncio
import os
import socket
import sys

import aiohttp
from aiohttp.resolver import AbstractResolver
from dotenv import load_dotenv

load_dotenv()

TG_IP = "149.154.167.220"  # официальный API-адрес Telegram


class PinnedResolver(AbstractResolver):
    """Всегда возвращает один IP, независимо от системного DNS."""

    async def resolve(self, host, port=0, family=socket.AF_INET):
        return [{"hostname": host,
                 "host": TG_IP,
                 "port": port,
                 "family": socket.AF_INET,
                 "proto": 0,
                 "flags": socket.AI_NUMERICHOST}]

    async def close(self) -> None:
        return None


async def probe(label: str, connector: aiohttp.TCPConnector, base: str, n: int = 4) -> None:
    async with aiohttp.ClientSession(connector=connector) as s:
        for i in range(n):
            try:
                async with s.get(f"{base}/getUpdates?timeout=0",
                                 timeout=aiohttp.ClientTimeout(total=15)) as r:
                    d = await r.json()
            except Exception as e:
                print(f"{label} [{i}]: NETERR {type(e).__name__}: {str(e)[:80]}")
                await asyncio.sleep(1)
                continue
            if d.get("ok"):
                print(f"{label} [{i}]: OK updates={len(d.get('result', []))}")
            else:
                print(f"{label} [{i}]: ERR {d.get('error_code')}: {str(d.get('description'))[:70]}")
            await asyncio.sleep(1)


async def main() -> None:
    token = os.environ["BOT_TOKEN"]
    base = f"https://api.telegram.org/bot{token}"
    print("=== прямой путь (пин 149.154.167.220) ===")
    conn = aiohttp.TCPConnector(resolver=PinnedResolver(), ssl=True)
    await probe("прямой", conn, base)
    print("=== обычный путь (системный DNS) ===")
    conn2 = aiohttp.TCPConnector(ssl=True)
    await probe("обычный", conn2, base)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    asyncio.run(main())
