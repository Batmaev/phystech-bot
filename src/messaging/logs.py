import asyncio
import traceback
import html

from aiogram import Bot
from aiogram.types import Chat, ErrorEvent

from ..utils.config import BOT_TOKEN, LOGS_CHAT_ID, SUPPORT_CALL

bot = Bot(BOT_TOKEN)


async def error_handler(event: ErrorEvent):
    text = '🚨 #UNCAUGHT_EXCEPTION\n\n'
    text += SUPPORT_CALL + '\n\n'
    text += f'<b>{event.exception}</b>\n\n'
    tb = html.escape(''.join(traceback.format_tb(event.exception.__traceback__)[-1]))
    text += f'<pre><code class="language-python">{tb}</code></pre>\n'
    update = html.escape(event.update.model_dump_json(exclude_defaults=True))[:3000]
    text += f'<pre><code class="language-json">{update}</code></pre>'

    asyncio.create_task(
        bot.send_message(LOGS_CHAT_ID, text, parse_mode='HTML', disable_web_page_preview=True)
    )
    if event.update.message:
        await event.update.message.reply('Бот сломался) Мы попробуем его починить.')
    if event.update.callback_query:
        await event.update.callback_query.answer('Бот сломался) Мы попробуем его починить.', show_alert=True)

    raise event.exception


def warn(msg: str, notify: bool = False):
    text = '⚠️ #WARNING\n\n'
    if notify:
        text += SUPPORT_CALL + '\n\n'
    text += msg

    asyncio.create_task(
        bot.send_message(LOGS_CHAT_ID, text, parse_mode='HTML', disable_web_page_preview=True)
    )

def chat_link_html(monitored_link):
    return f'<a href="{monitored_link.link}">{html.escape(monitored_link.chat_name)}</a>'


class PrintableUser:
    def __init__(self, user):
        self.id = user.id
        self.username = user.username
        self.first_name = user.first_name
        self.last_name = user.last_name

    @property
    def full_name(self):
        if self.last_name:
            return f'{self.first_name} {self.last_name}'
        return self.first_name

    def html(self):
        return f'@{self.username or ""} <a href="tg://user?id={self.id}">{html.escape(self.full_name)}</a> <code>{self.id}</code>'

class UnaccessibleUser(PrintableUser):
    def __init__(self, user_id: int):
        self.id = user_id
        self.username = None
        self.first_name = str(user_id)
        self.last_name = None


def new_user(user, utm_source):
    text = '👤 #new_user\n'
    text += PrintableUser(user).html()
    if utm_source:
        text += f'\nUTM Source: {chat_link_html(utm_source)}'

    asyncio.create_task(
        bot.send_message(LOGS_CHAT_ID, text, parse_mode='HTML', disable_web_page_preview=True)
    )

def new_link(monitored_link):
    text = '🔗 #new_link\n'
    text += chat_link_html(monitored_link)
    text += f'\n<code>{monitored_link.chat_id}</code>'
    asyncio.create_task(
        bot.send_message(LOGS_CHAT_ID, text, parse_mode='HTML', disable_web_page_preview=True)
    )

def chat_migrated(monitored_link, new_chat_id):
    text = '🔄 #chat_migrated\n'
    text += chat_link_html(monitored_link)
    text += f'\n<code>{new_chat_id}</code>'
    asyncio.create_task(
        bot.send_message(LOGS_CHAT_ID, text, parse_mode='HTML', disable_web_page_preview=True)
    )

def new_code(user, email: str, code: str):
    text = '💌 #new_code\n'
    text += PrintableUser(user).html()
    text += f'\nEmail: <code>{email}</code>'
    text += f'\nCode: <code>{code}</code>'
    asyncio.create_task(
        bot.send_message(LOGS_CHAT_ID, text, parse_mode='HTML', disable_web_page_preview=True)
    )

def finished_authorization(user, utm_source):
    text = '✨ #finished_authorization\n'
    text += PrintableUser(user).html()
    if utm_source:
        text += f'\nUTM Source: {chat_link_html(utm_source)}'
    asyncio.create_task(
        bot.send_message(LOGS_CHAT_ID, text, parse_mode='HTML', disable_web_page_preview=True)
    )

def chat_join(user, monitored_link):
    text = '👁️‍🗨️ #chat_join\n'
    text += PrintableUser(user).html()
    text += f'\n{chat_link_html(monitored_link)}'
    asyncio.create_task(
        bot.send_message(LOGS_CHAT_ID, text, parse_mode='HTML', disable_web_page_preview=True)
    )


def bot_kicked(chat: Chat, user):
    text = '👢 #bot_kicked\n'
    text += f'from {chat.title} <code>{chat.id}</code>\n'
    text += 'by ' + PrintableUser(user).html()
    asyncio.create_task(
        bot.send_message(LOGS_CHAT_ID, text, parse_mode='HTML', disable_web_page_preview=True)
    )

def cant_talk_to_user(user):
    text = '🤐 #bot_blocked\nby '
    text += PrintableUser(user).html()
    asyncio.create_task(
        bot.send_message(LOGS_CHAT_ID, text, parse_mode='HTML', disable_web_page_preview=True)
    )

def manual_authorization(user, email: str | None):
    text = '🔐 #manual_authorization\n'
    text += PrintableUser(user).html()
    if email:
        text += f'\n<code>{email}</code>'
    asyncio.create_task(
        bot.send_message(LOGS_CHAT_ID, text, parse_mode='HTML', disable_web_page_preview=True)
    )

def button_pressed(user, button: str):
    text = f'🔘 #button_pressed {button}\n'
    text += PrintableUser(user).html()
    asyncio.create_task(
        bot.send_message(LOGS_CHAT_ID, text, parse_mode='HTML', disable_web_page_preview=True)
    )

def malicious_user(user, email: str):
    text = '🚷 #malicious_user\n'
    text += PrintableUser(user).html()
    text += f'\n<code>{email}</code>'
    asyncio.create_task(
        bot.send_message(LOGS_CHAT_ID, text, parse_mode='HTML', disable_web_page_preview=True)
    )

def email_reuse(user, bot_users, email: str):
    text = '🤔 #email_reuse (prevented)\n'
    text += PrintableUser(user).html()
    text += f'\n<code>{email}</code>\n\n'
    text += 'User(s) with the same email:\n'
    for bot_user in bot_users:
        text += f'- {PrintableUser(bot_user).html()} ({bot_user.status.name})\n'

    asyncio.create_task(
        bot.send_message(LOGS_CHAT_ID, text, parse_mode='HTML', disable_web_page_preview=True)
    )

def ban_user(bot_user):
    text = '🚫 #ban_user\n'
    text += PrintableUser(bot_user).html()
    asyncio.create_task(
        bot.send_message(LOGS_CHAT_ID, text, parse_mode='HTML', disable_web_page_preview=True)
    )

def unban_user(bot_user):
    text = '🕊️ #unban_user\n'
    text += PrintableUser(bot_user).html()
    asyncio.create_task(
        bot.send_message(LOGS_CHAT_ID, text, parse_mode='HTML', disable_web_page_preview=True)
    )

def status_checked(checker_user, being_checked_user, user_from_db):
    text = '🔍 #status_checked\n'
    text += PrintableUser(checker_user).html()

    text += '\n\nhas checked status of\n'
    text += PrintableUser(being_checked_user).html()

    if user_from_db is not None:
        text += f'\n({user_from_db.status.name})'
    else:
        text += '\nUser not found in DB'

    asyncio.create_task(
        bot.send_message(LOGS_CHAT_ID, text, parse_mode='HTML', disable_web_page_preview=True)
    )


def strangers_listed(user, monitored_link, n):
    text = '🕵️‍♂️ #strangers_listed\n'
    text += PrintableUser(user).html()
    text += f'\n\nlisted strangers in {chat_link_html(monitored_link)}'
    text += f'\nresult: {n}'
    asyncio.create_task(
        bot.send_message(LOGS_CHAT_ID, text, parse_mode='HTML', disable_web_page_preview=True)
    )

def clean_requested(user, monitored_link, n):
    text = '💣 #clean_requested\n'
    text += 'by ' + PrintableUser(user).html()
    text += f'\nof {chat_link_html(monitored_link)} <code>{monitored_link.chat_id}</code>'
    text += f'\n(up to {n} unauthorized users)'
    asyncio.create_task(
        bot.send_message(LOGS_CHAT_ID, text, parse_mode='HTML', disable_web_page_preview=True)
    )


def file_received(user, monitored_link, file, n):
    text = '📁 #file_received\n'
    text += 'from ' + PrintableUser(user).html()
    text += f'\nwith {n} users to delete'
    text += f'\nin {chat_link_html(monitored_link)} <code>{monitored_link.chat_id}</code>'
    text += f'\n\n{file.file_size / 1024:.2f} KB'
    text += f'\n<code>{file.file_id}</code>'
    text += f'\n<code>{file.file_unique_id}</code>'
    asyncio.create_task(
        bot.send_message(LOGS_CHAT_ID, text, parse_mode='HTML', disable_web_page_preview=True)
    )


def clean_finished(user, monitored_link, banned, not_banned):
    text = '😵 #clean_finished\n'
    text += 'by ' + PrintableUser(user).html()
    text += f'\nin {chat_link_html(monitored_link)} <code>{monitored_link.chat_id}</code>'
    text += f'\nresult: {len(banned)} banned, {len(not_banned)} not banned'
    asyncio.create_task(
        bot.send_message(LOGS_CHAT_ID, text, parse_mode='HTML', disable_web_page_preview=True)
    )

def clean_cancelled(user):
    text = '🙄 #clean_cancelled\n'
    text += 'by ' + PrintableUser(user).html()
    asyncio.create_task(
        bot.send_message(LOGS_CHAT_ID, text, parse_mode='HTML', disable_web_page_preview=True)
    )
