from aiogram import Router, Bot
from aiogram.types import Message, ChatJoinRequest, ChatMemberUpdated
from aiogram.filters import Command
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError

from .ads import ad_after_join
from ..utils.config import BOT_TOKEN
from ..utils.db import UserStatus, MonitoredLink, save_link, get_link, save_user, get_user
from . import logs

router = Router()
bot = Bot(BOT_TOKEN)


async def notify_adder(update: Message | ChatMemberUpdated, text: str):
    """In channels the bot usually can't post, so DM the person who added it."""
    if update.chat.type == 'channel':
        try:
            await bot.send_message(update.from_user.id, text)
        except TelegramForbiddenError:
            logs.cant_talk_to_user(update.from_user)
        return
    await update.answer(text)


async def make_link(update: Message | ChatMemberUpdated):
    try:
        link = await bot.create_chat_invite_link(update.chat.id, creates_join_request=True)
    except TelegramBadRequest as error:
        await notify_adder(update, str(error))
        return

    save_link(link.invite_link, update.chat.title, update.chat.id, update.chat.type)
    title = update.chat.title or '?'
    if update.chat.type == 'channel':
        text = (
            f'Создана защищенная ссылка с подтверждением для канала «{title}»: '
            f'{link.invite_link}\n\n'
            'Бот будет автоматически принимать тех, кто подтвердил физтеховскую почту, '
            'и предлагать авторизоваться остальным.'
        )
    else:
        text = (
            f'Создана защищенная ссылка с подтверждением: {link.invite_link}\n\n'
            'Бот будет автоматически принимать тех, кто подтвердил физтеховскую почту, '
            'и предлагать авторизоваться остальным.'
        )
    await notify_adder(update, text)



@router.message(Command('make_link'))
async def process_make_link_command(message: Message):
    if message.chat.type == 'private':
        await message.answer('Эту команду нужно использовать непосредственно в чате')
        return

    async def is_sender_admin(message: Message):
        member = await bot.get_chat_member(message.chat.id, message.from_user.id)
        return member.status in ('administrator', 'creator')

    if not await is_sender_admin(message):
        await message.answer('Эту команду могут использовать только администраторы чата')
        return
    await make_link(message)


@router.my_chat_member()
async def process_my_chat_member(update: ChatMemberUpdated):
    if update.new_chat_member.status in ('kicked', 'left'):
        logs.bot_kicked(update.chat, update.from_user)
        return

    def check_status(member):
        return member.status == 'administrator' and member.can_invite_users

    was_ok = check_status(update.old_chat_member)
    is_ok = check_status(update.new_chat_member)

    kind = 'канал' if update.chat.type == 'channel' else 'чат'

    if is_ok and not was_ok:
        await make_link(update)

    elif not is_ok and not was_ok:
        await notify_adder(
            update,
            'Этот бот может создавать защищенные ссылки. '
            'Для этого нужно назначить его администратором и дать право приглашать пользователей.'
        )

    elif was_ok and not is_ok:
        await notify_adder(
            update,
            f'Бот больше не сможет принимать пользователей в этот {kind}. '
            'Ему не хватает прав'
        )


@router.chat_join_request()
async def accept_or_decline(request: ChatJoinRequest):
    if request.invite_link is not None:
        monitored_link = get_link(request.invite_link.invite_link)
        if monitored_link is None:
            return
    else:
        # public chat; Telegram will not say which link was used
        monitored_link = get_link(f'https://t.me/{request.chat.username}')
        if monitored_link is None:
            monitored_link = MonitoredLink(
                chat_name=request.chat.title,
                chat_id=request.chat.id,
                link=f'https://t.me/{request.chat.username}',
                chat_type=request.chat.type,
            )

    bot_user = get_user(request.from_user)
    if bot_user is None or bot_user.status != UserStatus.AUTHORIZED:
        save_user(request.from_user, monitored_link)
        await request.decline()
        try:
            await talk_to_user(request, monitored_link)
        except TelegramForbiddenError:
            logs.cant_talk_to_user(request.from_user)

    else:
        await request.approve()
        logs.chat_join(request.from_user, monitored_link)
        try:
            await congrats_user(request, monitored_link)
            await ad_after_join(request)
        except TelegramForbiddenError:
            logs.cant_talk_to_user(request.from_user)


async def talk_to_user(request: ChatJoinRequest, monitored_link: MonitoredLink):
    await request.answer_pm(
    f'Привет! Ты попытался вступить в {monitored_link.chat_name}.\n\n'
    f'Этот {monitored_link.kind_ru} доступен только для физтехов. '
    'Авторизуйся в этом боте и попробуй вступить снова.\n\n'
    'Используй команду /start'
)


async def congrats_user(request: ChatJoinRequest, monitored_link: MonitoredLink):
    await request.answer_pm(
        f'Твоя заявка на вступление в {logs.chat_link_html(monitored_link)} принята 🎉',
        parse_mode='HTML',
        disable_web_page_preview=True
    )



@router.message(Command('error'))
async def test_error(message: Message):
    raise ValueError('test error')
