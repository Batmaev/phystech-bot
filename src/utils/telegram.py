import asyncio

import telethon

from .config import API_HASH, API_ID, BOT_TOKEN


client = telethon.TelegramClient('session', API_ID, API_HASH)
_start_lock = asyncio.Lock()
_started = False


async def ensure_client():
    global _started

    if _started and client.is_connected():
        return

    async with _start_lock:
        if not _started or not client.is_connected():
            await client.start(bot_token=BOT_TOKEN)
            _started = True
