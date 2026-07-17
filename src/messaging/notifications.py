import asyncio

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError

from . import logs
from ..utils import db, db_addons
from ..utils.config import BOT_TOKEN, SUPPORT_IDS
from ..utils.telegram import client, ensure_client

bot = Bot(BOT_TOKEN)

async def notify_users_of(chat_id: int, text: str, limit: int = 100):
    await ensure_client()

    i = 0
    async for member in client.iter_participants(chat_id):
        if i >= limit:
            break

        if member.bot:
            continue

        bot_user = db.get_user_by_id(member.id)
        if bot_user is None:
            continue

        if bot_user.status == db.UserStatus.AUTHORIZED or bot_user.status == db.UserStatus.BANNED:
            continue

        notified_user = db_addons.get_notified_user(bot_user.id)
        if notified_user is not None:
            continue

        if db_addons.was_error_with(bot_user):
            continue

        try:
            await bot.send_message(bot_user.id, text, parse_mode='HTML')
            db_addons.save_notification(bot_user)
            logs.sent_notification(bot_user, text)
            i += 1

        except (TelegramBadRequest, TelegramForbiddenError) as error:
            db_addons.save_notification_error(bot_user, str(error))
            logs.error_notification(bot_user, error)

        await asyncio.sleep(3.1)

async def make_threatening_post_at(chat_id: int, text: str, starter = '', joiner = '\u200B', ender = ''):
    await ensure_client()
    members = await client.get_participants(chat_id)

    not_authorized = [member for member in members if should_notify(member)]
    print(len(not_authorized))

    mentions = [f'<a href="tg://user?id={user.id}">{joiner}</a>' for user in not_authorized]

    text = text + starter + ''.join(mentions) + ender

    msg = await bot.send_message(chat_id, text, parse_mode='HTML')

    return msg, mentions


def should_notify(member):
    if member.bot:
        return False

    if member.id in SUPPORT_IDS:
        return True

    bot_user = db.get_user_by_id(member.id)
    if bot_user is None:
        return True

    if bot_user.status in (db.UserStatus.AUTHORIZED, db.UserStatus.BANNED):
        return False
    else:
        return True
