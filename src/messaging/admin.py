import re
import asyncio

from aiogram import Router, Bot, F
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, FSInputFile
from aiogram.filters import Command
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramMigrateToChat
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State

import telethon
from telethon.tl.types import User
from telethon.errors.rpcerrorlist import UsernameInvalidError

import pandas as pd

from . import logs
from .logs import PrintableUser, UnaccessibleUser
from ..utils import db
from ..utils.config import BOT_TOKEN, ADMIN_FILTER, ADMIN_CHAT_ID, API_ID, API_HASH

router = Router()
bot = Bot(BOT_TOKEN)

client = telethon.TelegramClient('session', API_ID, API_HASH)

class NoUserSpecifiedError(Exception):
    pass

class NotUserError(Exception):
    pass


async def find_user(message: Message) -> PrintableUser | Exception:
    for entity in message.entities:
        if entity.type == 'mention':
            username = message.text[entity.offset + 1:entity.offset + entity.length]
            try:
                await client.start(bot_token=BOT_TOKEN)
                user = await client.get_entity(username)
                if not isinstance(user, User):
                    return NotUserError()
                return PrintableUser(user)
            except (UsernameInvalidError, ValueError) as error:
                return error

    ids = re.findall(r'\d{4,17}', message.text or message.caption)
    if ids:
        return UnaccessibleUser(int(ids[0]))

    if message.reply_to_message:
        if message.reply_to_message.forward_from:
            return PrintableUser(message.reply_to_message.forward_from)
        return PrintableUser(message.reply_to_message.from_user)

    return NoUserSpecifiedError()


async def chats_of_user_mentioned(user_id: int):
    for chat in db.get_all_monitored_chats():
        try:
            member = await bot.get_chat_member(chat.chat_id, user_id)
        except TelegramMigrateToChat as error:
            db.update_chat_id(chat, error.migrate_to_chat_id)
            member = await bot.get_chat_member(error.migrate_to_chat_id, user_id)
        except (TelegramBadRequest, TelegramForbiddenError):
            continue

        if member.status.value != 'left':
            yield chat, member



@router.message(Command('where'), ADMIN_FILTER | (F.chat.id == ADMIN_CHAT_ID))
async def list_user_chats(message: Message):
    user = await find_user(message)
    if isinstance(user, (UsernameInvalidError, ValueError)):
        await message.reply('Юзернейм никому не принадлежит')
        return
    if isinstance(user, NotUserError):
        await message.reply('Никнейм принадлежит не человеку')
        return
    if isinstance(user, NoUserSpecifiedError):
        await message.reply(
            'Использование:\n'
            '• /where @username\n'
            '• /where 1234567890\n'
            '• или ответом на сообщение пользователя'
        )
        return

    bot_user = db.get_user_by_id(user.id)
    if bot_user is not None:
        text = PrintableUser(bot_user).html()
        text += f'\nEmail: <code>{bot_user.email}</code>'
        text += f'\nРегистрация: {bot_user.created_at}'
        text += f'\nСтатус в боте: {bot_user.status.name}\n\n'
    else:
        text = f'Пользователь {user.html()} не контактировал с ботом\n\n'

    text += 'Статус в чатах:\n'
    async for chat, member in chats_of_user_mentioned(user.id):
        text += f'{chat.chat_name}: {member.status.value}\n'

    await message.answer(text, parse_mode='HTML')

@router.message(Command('ban'), ADMIN_FILTER)
async def ban(message: Message):
    user = await find_user(message)
    if isinstance(user, (UsernameInvalidError, ValueError)):
        await message.reply('Юзернейм никому не принадлежит')
        return
    if isinstance(user, NoUserSpecifiedError):
        await message.reply(
            'Использование:\n'
            '• /ban @username\n'
            '• /ban 1234567890\n'
            '• или ответом на сообщение пользователя'
        )
        return

    db.ban_user(user.id)

    text = ''
    async for chat, member in chats_of_user_mentioned(user.id):
        if member.status.value != 'kicked':
            try:
                await bot.ban_chat_member(chat.chat_id, member.user.id)
                text += f'{chat.chat_name}: забанили\n'
            except TelegramBadRequest:
                text += f'{chat.chat_name}: не хватает прав\n'
    if not text:
        text = 'Пользователя нет ни в одном чате'

    await message.answer(text)


@router.message(Command('unban'), ADMIN_FILTER)
async def unban(message: Message):
    user = await find_user(message)
    if isinstance(user, (UsernameInvalidError, ValueError)):
        await message.reply('Юзернейм никому не принадлежит')
        return
    if isinstance(user, NoUserSpecifiedError):
        await message.reply(
            'Использование:\n'
            '• /unban @username\n'
            '• /unban 1234567890\n'
            '• или ответом на сообщение пользователя'
        )
        return

    db.unban_user(user.id)

    text = ''
    async for chat, member in chats_of_user_mentioned(user.id):
        if member.status.value == 'kicked':
            try:
                await bot.unban_chat_member(chat.chat_id, member.user.id, only_if_banned=True)
                text += f'{chat.chat_name}: разбанили\n'
            except TelegramBadRequest:
                text += f'{chat.chat_name}: не хватает прав\n'
    if text:
        await message.answer(text)
    else:
        await message.answer('Пользователь не был забанен ни в одном чате')


@router.message(Command('is'))
async def check_status(message: Message):
    self_bot_user = db.get_user_by_id(message.from_user.id)
    if self_bot_user is None or self_bot_user.status != db.UserStatus.AUTHORIZED:
        await message.reply('Вы не авторизованы и не можете использовать эту команду')
        return

    user = await find_user(message)

    if isinstance(user, (UsernameInvalidError, ValueError)):
        await message.reply('Юзернейм никому не принадлежит')
        return

    if isinstance(user, NotUserError):
        await message.reply('Никнейм принадлежит не человеку')
        return

    if isinstance(user, NoUserSpecifiedError):
        instruction = await message.reply(
            'Использование:\n'
            '• /is @username\n'
            '• /is 1234567890\n'
            '• или ответом на сообщение пользователя'
        )
        if message.chat.type != 'private': # delete instruction to avoid spam
            await asyncio.sleep(300)
            try:
                await instruction.delete()
                await message.delete()
            except (TelegramBadRequest, AttributeError):
                pass
        return

    bot_user = db.get_user_by_id(user.id)

    if isinstance(user, UnaccessibleUser) and bot_user is not None:
        user_text = PrintableUser(bot_user).full_name
    else:
        user_text = user.full_name

    if bot_user is None:
        await message.reply(f'{user_text} не регистрировался в боте')
    else:
        match bot_user.status:
            case db.UserStatus.NOT_AUTHORIZED | db.UserStatus.AUTHORIZING:
                await message.reply(f'{user_text} начинал(a) регистрацию в боте, но не завершил(a) её')
            case db.UserStatus.AUTHORIZED:
                await message.reply(f'{user_text} подтвердил(a) свой статус физтеха')
            case db.UserStatus.BANNED:
                await message.reply(f'{user_text} забанен(a) админами бота')

    logs.status_checked(message.from_user, user, bot_user)


@router.message(Command('strangers'), F.chat.type == 'private')
async def list_strangers(message: Message):
    admin = await bot.get_chat_member(ADMIN_CHAT_ID, message.from_user.id)
    if admin.status in ('kicked', 'left'):
        await message.reply('Вам недоступна эта команда')
        return

    if len(message.text.split()) != 2:
        await message.reply('Использование: /strangers https://t.me/+chat_link')
        return

    chat_link = message.text.split()[1]
    monitored_link = db.get_link(chat_link)

    if monitored_link is None:
        await message.reply('Ссылка не отслеживается')
        return

    text = f'Неавторизованные в {monitored_link.chat_name}:\n'

    await client.start(bot_token=BOT_TOKEN)

    i = 1
    I_MAX = 100
    async for member in client.iter_participants(monitored_link.chat_id):
        if member.bot:
            continue

        if member.username:
            mention_str = f'@{member.username}'
        else:
            full_name = PrintableUser(member).full_name
            mention_str = f'<a href="tg://user?id={member.id}">{full_name}</a>'

        mention_str += f' <code>{member.id}</code>'

        bot_user = db.get_user_by_id(member.id)

        if bot_user is None:
            text += f'{i}. {mention_str} STRANGER\n'
        elif bot_user.status == db.UserStatus.AUTHORIZED:
            continue
        elif bot_user.status == db.UserStatus.NOT_AUTHORIZED:
            text += f'{i}. {mention_str} AUTHORIZING\n'
        else:
            text += f'{i}. {mention_str} {bot_user.status.name}\n'

        i += 1

        if i % I_MAX == 0:
            await message.answer(text, parse_mode='HTML', disable_web_page_preview=True)
            text = ''

    if text != '':
        await message.answer(text, parse_mode='HTML', disable_web_page_preview=True)

    logs.strangers_listed(message.from_user, monitored_link, i-1)



class ReviewStep(StatesGroup):
    SELECTING_CHAT = State()
    WAITING_FOR_FILE = State()
    WAITING_FOR_CONFIRMATION = State()



@router.message(Command('clean'), F.chat.type == 'private')
async def select_chat(message: Message, state: FSMContext):
    admin_id = message.from_user.id
    admin = await bot.get_chat_member(ADMIN_CHAT_ID, admin_id)
    if admin.status in ('kicked', 'left'):
        return

    chats = {}
    async for chat, member in chats_of_user_mentioned(admin_id):
        if member.status in ('creator', 'administrator'):
            chats[chat.chat_id] = chat

    if not chats:
        await message.reply('Нет чатов, где вы являетесь админом')
        return

    await message.answer(
        'Выберите чат, из которого вы хотели бы удалить неавторизованных пользователей. '
        'Бот пришлет файл со списком участников на проверку.',
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=chat.chat_name,
                        callback_data=f'clean {chat.chat_id} {chat.link}'
                    )
                ]
                for chat in chats.values()
            ]
        )
    )

    await state.set_state(ReviewStep.SELECTING_CHAT)



@router.callback_query(F.data.startswith('clean'), F.message.chat.type == 'private')
async def send_file_for_review(update: CallbackQuery, state: FSMContext):
    chat_id = int(update.data.split()[1])
    chat_link = update.data.split()[2]
    await state.update_data(chat_id=chat_id, chat_link=chat_link)

    me = await bot.get_me()
    my_rights = await bot.get_chat_member(chat_id, me.id)
    if not my_rights.status == 'administrator' and my_rights.can_restrict_members:
        await update.message.answer('Разрешите боту банить пользователей и нажмите на кнопку еще раз')
        return

    strangers = []
    await client.start(bot_token=BOT_TOKEN)
    async for member in client.iter_participants(chat_id):
        if member.bot:
            continue

        bot_user = db.get_user_by_id(member.id)
        if bot_user is not None and bot_user.status == db.UserStatus.AUTHORIZED:
            continue

        if bot_user is None:
            status = 'STRANGER'
        else:
            status = bot_user.status.name

        if status == 'NOT_AUTHORIZED':
            status = 'AUTHORIZING'

        strangers.append({
            'id': member.id,
            'ban?': '',
            'username': f'=HYPERLINK("https://t.me/{member.username}", "{member.username}")'
                        if member.username else '',
            'first_name': member.first_name,
            'last_name': member.last_name,
            'status': status
        })

    df = pd.DataFrame(strangers)
    df.to_excel(f'{chat_id}.xlsx', index=False)

    await update.message.answer_document(
        document=FSInputFile(f'{chat_id}.xlsx'),
        caption='Файл с неавторизованными участниками чата.\n\n'
                'Пожалуйста, отредактируйте его и отправьте обратно. '
                'Если пользователя нужно удалить из чата, то напишите TRUE в столбце "ban?".\n\n'
                'Если написать FALSE, оставить ячейку пустой или удалить строку целиком, '
                'то мы оставим пользователя в чате.'
    )
    await update.answer()

    await state.set_state(ReviewStep.WAITING_FOR_FILE)

    logs.clean_requested(update.from_user, db.get_link(chat_link), len(df))


@router.message(F.document, F.chat.type == 'private', ReviewStep.WAITING_FOR_FILE)
async def get_file(message: Message, state: FSMContext):
    file_id = message.document.file_id
    file = await bot.get_file(file_id)

    chat_id = (await state.get_data())['chat_id']
    fname = f'{chat_id}_rev.xlsx'

    await bot.download_file(file.file_path, fname)
    df = pd.read_excel(fname)
    df['ban?'] = df['ban?'].fillna(False).astype(bool)
    df = df[df['ban?']]
    await state.update_data(ids_to_ban = df['id'])

    chat = db.get_link((await state.get_data())['chat_link'])

    await message.answer(
        f'Исключить {len(df)} пользователей из {chat.chat_name}?',
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(
                    text='Да',
                    callback_data='confirm clean'
                )],
                [InlineKeyboardButton(
                    text='Нет, отправить другой файл',
                    callback_data='resend clean file'
                )],
                [InlineKeyboardButton(
                    text='Нет, остановить процесс',
                    callback_data='cancel clean'
                )],
            ]
        )
    )

    await state.set_state(ReviewStep.WAITING_FOR_CONFIRMATION)
    logs.file_received(message.from_user, chat, file, len(df))


@router.callback_query(F.data == 'cancel clean', F.message.chat.type == 'private',
                       ReviewStep.WAITING_FOR_CONFIRMATION)
async def cancel_clean(update: CallbackQuery, state: FSMContext):
    await update.message.edit_reply_markup()
    await state.clear()
    await update.message.answer('Процесс остановлен')
    await update.answer()
    logs.clean_cancelled(update.from_user)


@router.callback_query(F.data == 'resend clean file', F.message.chat.type == 'private',
                       ReviewStep.WAITING_FOR_CONFIRMATION)
async def suggest_resend_file(update: CallbackQuery, state: FSMContext):
    await update.message.edit_reply_markup()
    await update.message.answer('Отправьте новый файл')
    await update.answer()
    await state.set_state(ReviewStep.WAITING_FOR_FILE)


@router.callback_query(F.data == 'confirm clean', F.message.chat.type == 'private',
                       ReviewStep.WAITING_FOR_CONFIRMATION)
async def clean(update: CallbackQuery, state: FSMContext):

    chat_id = (await state.get_data())['chat_id']
    ids_to_ban = (await state.get_data())['ids_to_ban']

    admin = await bot.get_chat_member(chat_id, update.from_user.id)
    if admin.status not in ('creator', 'administrator'):
        await update.answer('Вы не администратор в этом чате')
        return

    banned = []
    not_banned = []
    for user_id in ids_to_ban:
        bot_user = db.get_user_by_id(user_id)
        if bot_user is not None and bot_user.status == db.UserStatus.AUTHORIZED:
            not_banned.append(bot_user)
            continue

        await bot.unban_chat_member(chat_id, user_id)
        banned.append(user_id)

    text = f'Исключили {len(banned)} пользователей.\n\n'
    if not_banned:
        text += 'Авторизовались в последний момент и не были исключены:\n'
        for user in not_banned:
            text += PrintableUser(user).html() + '\n'

    await update.message.answer(text, parse_mode='HTML', disable_web_page_preview=True)
    logs.clean_finished(
        update.from_user,
        db.get_link((await state.get_data())['chat_link']),
        banned,
        not_banned
    )
    await state.clear()
