import asyncio
import datetime

from aiogram import Bot, Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, ChatJoinRequest
from aiogram.exceptions import TelegramAPIError

from .long_texts import NO_FLOOD_LINK_HTML, CHATS, SERVICES, COUNTRIES, BLOGS
from . import logs
from ..utils.db import get_link, get_user, update_last_ad_time
from ..utils.config import BOT_TOKEN


router = Router()
bot = Bot(BOT_TOKEN)



async def welcome(message: Message, link_text: str):
    await message.answer('Проверка прошла успешно!')

    if link_text is not None:
        monitored_link = get_link(link_text)
        link_html = logs.chat_link_html(monitored_link)
        await message.answer(
            'Теперь ты можешь вступить в чат ' + link_html,
            parse_mode='HTML',
        )
    else:
        await ad_after_auth(message)


chat_and_services_buttons = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text='Чаты', callback_data='chats')],
    [InlineKeyboardButton(text='Сервисы', callback_data='services')],
    [InlineKeyboardButton(text='По странам', callback_data='countries')],
    [InlineKeyboardButton(text='Блоги', callback_data='blogs')],
])


async def ad_after_auth(message: Message):
    await message.answer(
        'Посмотрите, какие у физтехов есть чаты, сервисы и блоги 🥳',
        reply_markup=chat_and_services_buttons
    )
    update_last_ad_time(message.from_user)


async def ad_after_join(request: ChatJoinRequest):
    await asyncio.sleep(60)
    bot_user = get_user(request.from_user)
    if (datetime.datetime.now(datetime.timezone.utc) - bot_user.last_ad_time) >= datetime.timedelta(days=1):
        await request.answer_pm(
            'Хотите посмотреть, какие есть чаты/сервисы/блоги у физтехов?',
            reply_markup=chat_and_services_buttons
        )
        update_last_ad_time(request.from_user)



@router.callback_query(F.data == 'chats')
@router.callback_query(F.data == 'services')
@router.callback_query(F.data == 'countries')
@router.callback_query(F.data == 'blogs')
async def switch_chats_and_services(query: CallbackQuery):
    match query.data:
        case 'chats':
            text = CHATS
        case 'services':
            text = SERVICES
        case 'countries':
            text = COUNTRIES
        case 'blogs':
            text = BLOGS

    try:
        await query.message.delete()
    except (TelegramAPIError, AttributeError):
        pass

    await query.message.answer(text, reply_markup=chat_and_services_buttons, parse_mode='HTML',
                               disable_web_page_preview=True)
    await query.answer()
    update_last_ad_time(query.from_user)
    logs.button_pressed(query.from_user, query.data)




# Legacy buttons for old users
@router.callback_query(F.data == 'no_flood')
@router.callback_query(F.data == 'agree')
async def invite_to_no_flood(query: CallbackQuery):
    await query.answer()
    await query.message.answer(
        f'Добро пожаловать в общефизтеховский чат {NO_FLOOD_LINK_HTML}',
        parse_mode='HTML',
    )
