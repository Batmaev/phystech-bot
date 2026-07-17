import asyncio
import random
import string

from aiogram import Router, Bot, F
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    InputChecklist,
    InputChecklistTask,
)
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramRetryAfter,
)

from ..utils import db
from ..utils.config import BOT_TOKEN, ADMIN_FILTER
from ..utils.telegram import client, ensure_client

router = Router()
bot = Bot(BOT_TOKEN)

CHECKLIST_CHUNK = 28
SEND_INTERVAL = 1 / 15  # half of Telegram's 30 msg/s limit


class BroadcastStates(StatesGroup):
    SELECTING = State()
    CONFIRMING = State()
    SENDING = State()


class BroadcastSession:
    def __init__(
        self,
        broadcast_id: str,
        admin_id: int,
        business_connection_id: str,
    ):
        self.broadcast_id = broadcast_id
        self.admin_id = admin_id
        self.business_connection_id = business_connection_id
        self.selected_chats: set[int] = set()
        self.participants: dict[int, list[int]] = {}
        self.participant_errors: dict[int, str] = {}
        self.load_tasks: dict[int, asyncio.Task] = {}
        self.chat_titles: dict[int, str] = {}
        self.task_chats: dict[int, int] = {}
        self.source_message: Message | None = None
        self.confirm_message: Message | None = None


_sessions: dict[str, BroadcastSession] = {}


async def _session_for_message(
    message: Message,
    state: FSMContext,
) -> BroadcastSession | None:
    broadcast_id = (await state.get_data()).get('broadcast_id')
    session = _sessions.get(broadcast_id)
    if session is not None:
        return session

    for candidate in _sessions.values():
        if candidate.admin_id != message.chat.id:
            continue
        if (
            message.business_connection_id is not None
            and candidate.business_connection_id != message.business_connection_id
        ):
            continue
        return candidate

    return None


def _generate_broadcast_id() -> str:
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=5))


def _task_text(title: str, chat_id: int) -> str:
    shift_id = str(chat_id).removeprefix('-100')
    suffix = f' | {shift_id}'
    max_title_len = 100 - len(suffix)
    return f'{title[:max_title_len]}{suffix}'


def _unique_recipients(session: BroadcastSession) -> set[int]:
    users: set[int] = set()
    for chat_id in session.selected_chats:
        users.update(session.participants.get(chat_id, []))
    return users


def _confirm_text(session: BroadcastSession) -> str:
    n_chats = len(session.selected_chats)
    recipients = _unique_recipients(session)
    failed = session.selected_chats & session.participant_errors.keys()
    loading = any(
        chat_id not in session.participants
        and chat_id not in session.participant_errors
        for chat_id in session.selected_chats
    )
    suffix = ' (ещё загружаем участников…)' if loading else ''
    if failed:
        suffix += f' (не удалось загрузить чатов: {len(failed)})'
    return (
        f'Разослать это сообщение {len(recipients)} пользователям '
        f'{n_chats} чатов? Его пока можно редактировать{suffix}'
    )


def _confirm_keyboard(broadcast_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text='тестировать на себе',
            callback_data=f'bc_test:{broadcast_id}',
        )],
        [InlineKeyboardButton(
            text='начать рассылку',
            callback_data=f'bc_start:{broadcast_id}',
        )],
        [InlineKeyboardButton(
            text='отменить',
            callback_data=f'bc_cancel:{broadcast_id}',
        )],
    ])


async def _send_checklist(
    session: BroadcastSession,
    title: str,
    items: list[tuple[int, str]],
):
    tasks = [
        InputChecklistTask(id=task_id, text=text)
        for task_id, text in items
    ]
    await bot.send_checklist(
        business_connection_id=session.business_connection_id,
        chat_id=session.admin_id,
        checklist=InputChecklist(
            title=title,
            tasks=tasks,
            others_can_mark_tasks_as_done=True,
        ),
    )


async def _load_participants(session: BroadcastSession, chat_id: int):
    session.participant_errors.pop(chat_id, None)
    try:
        await ensure_client()
        users = []
        async for member in client.iter_participants(chat_id):
            if member.bot:
                continue
            users.append(member.id)
        session.participants[chat_id] = users
    except Exception as error:
        session.participants.pop(chat_id, None)
        session.participant_errors[chat_id] = str(error)
        title = session.chat_titles.get(chat_id) or '?'
        await bot.send_message(
            session.admin_id,
            f'Не удалось загрузить участников чата '
            f'{title} - {chat_id}:\n{error}',
            business_connection_id=session.business_connection_id,
        )
    finally:
        await _refresh_confirm_message(session)


def _start_loading(session: BroadcastSession, chat_id: int):
    existing = session.load_tasks.get(chat_id)
    if existing and not existing.done():
        return
    if chat_id in session.participants:
        return
    session.load_tasks[chat_id] = asyncio.create_task(
        _load_participants(session, chat_id)
    )


async def _refresh_confirm_message(session: BroadcastSession):
    if session.confirm_message is None:
        return
    try:
        await session.confirm_message.edit_text(
            _confirm_text(session),
            reply_markup=_confirm_keyboard(session.broadcast_id),
        )
    except TelegramBadRequest:
        pass


async def _send_chat_lists(session: BroadcastSession):
    chats = db.get_all_monitored_chats()
    if not chats:
        raise ValueError('Нет отслеживаемых чатов')

    chats = sorted(chats, key=lambda c: (c.chat_name or '').lower())

    for chat in chats:
        session.chat_titles[chat.chat_id] = chat.chat_name

    task_id = 1
    for i in range(0, len(chats), CHECKLIST_CHUNK):
        chunk = chats[i:i + CHECKLIST_CHUNK]
        items = [
            (task_id + j, _task_text(chat.chat_name or '?', chat.chat_id))
            for j, chat in enumerate(chunk)
        ]
        session.task_chats.update(
            (item_id, chat.chat_id)
            for (item_id, _), chat in zip(items, chunk)
        )
        title = f'Чаты {i + 1}–{i + len(chunk)}'
        await _send_checklist(session, title, items)
        task_id += len(chunk)

    await bot.send_message(
        session.admin_id,
        f'Рассылка <code>{session.broadcast_id}</code>. '
        'Отметьте нужные чаты и пришлите сообщение для рассылки',
        parse_mode='HTML',
        business_connection_id=session.business_connection_id,
    )


async def _copy_to_user(source: Message, user_id: int):
    if source.text is not None:
        await bot.send_message(
            user_id,
            source.text,
            entities=source.entities,
            link_preview_options=source.link_preview_options,
        )
        return

    if source.photo:
        await bot.send_photo(
            user_id,
            source.photo[-1].file_id,
            caption=source.caption,
            caption_entities=source.caption_entities,
            show_caption_above_media=source.show_caption_above_media,
        )
        return

    raise ValueError('Для рассылки поддерживаются текст и одно фото с подписью')


def _is_supported_source(message: Message) -> bool:
    return message.text is not None or bool(message.photo)


def _classify_error(error: Exception) -> str:
    text = str(error).lower()
    if isinstance(error, TelegramForbiddenError):
        return 'blocked'
    if isinstance(error, TelegramBadRequest):
        if any(s in text for s in (
            'chat not found',
            'user not found',
            'peer_id_invalid',
            "can't initiate conversation",
            'have no access',
        )):
            return 'no_dialog'
        if 'blocked' in text or 'deactivated' in text:
            return 'blocked'
    return 'other'


@router.message(Command('broadcast'), ADMIN_FILTER)
async def require_business_chat(message: Message):
    await message.reply(
        'Команду /broadcast нужно отправить подключённому бизнес-аккаунту.'
    )


@router.business_message(Command('broadcast'), ADMIN_FILTER)
async def start_broadcast(message: Message, command: CommandObject, state: FSMContext):
    await state.clear()

    if message.business_connection_id is None:
        await message.reply('Не найдено подключение Telegram Business.')
        return

    if command.args:
        broadcast_id = command.args.strip().upper()
        if len(broadcast_id) != 5 or not broadcast_id.isalnum():
            await message.reply(
                'Некорректный id рассылки. Ожидается /broadcast или /broadcast ABC12'
            )
            return
    else:
        broadcast_id = _generate_broadcast_id()

    for bid, existing in list(_sessions.items()):
        if existing.admin_id == message.chat.id or bid == broadcast_id:
            for task in existing.load_tasks.values():
                task.cancel()
            _sessions.pop(bid, None)

    session = BroadcastSession(
        broadcast_id,
        message.chat.id,
        message.business_connection_id,
    )
    _sessions[broadcast_id] = session
    await state.set_state(BroadcastStates.SELECTING)
    await state.update_data(broadcast_id=broadcast_id)

    try:
        await _send_chat_lists(session)
    except Exception as error:
        if _sessions.get(broadcast_id) is session:
            _sessions.pop(broadcast_id, None)
        await state.clear()
        await message.reply(f'Не удалось создать списки чатов: {error}')


@router.message(F.checklist_tasks_done)
@router.business_message(F.checklist_tasks_done)
async def on_checklist_tasks_done(message: Message, state: FSMContext):
    session = await _session_for_message(message, state)
    if session is None:
        return

    event = message.checklist_tasks_done

    for task_id in event.marked_as_done_task_ids or []:
        chat_id = session.task_chats.get(task_id)
        if chat_id is None:
            continue
        session.selected_chats.add(chat_id)
        _start_loading(session, chat_id)

    for task_id in event.marked_as_not_done_task_ids or []:
        chat_id = session.task_chats.get(task_id)
        if chat_id is None:
            continue
        session.selected_chats.discard(chat_id)

    if session.confirm_message is not None:
        await _refresh_confirm_message(session)


@router.business_message(
    ADMIN_FILTER,
    BroadcastStates.SELECTING,
    ~F.text.startswith('/'),
    F.checklist_tasks_done.is_(None),
    F.checklist.is_(None),
)
async def receive_broadcast_message(message: Message, state: FSMContext):
    data = await state.get_data()
    broadcast_id = data.get('broadcast_id')
    session = _sessions.get(broadcast_id)
    if session is None:
        await message.reply('Сессия рассылки потеряна. Запустите /broadcast заново.')
        await state.clear()
        return

    if message.media_group_id:
        await message.reply('Альбомы пока не поддерживаются, пришлите одно сообщение.')
        return

    if not _is_supported_source(message):
        await message.reply('Для рассылки поддерживаются текст и одно фото с подписью.')
        return

    if not session.selected_chats:
        await message.reply('Сначала отметьте хотя бы один чат в списках задач.')
        return

    session.source_message = message
    confirm = await message.reply(
        _confirm_text(session),
        reply_markup=_confirm_keyboard(broadcast_id),
    )
    session.confirm_message = confirm
    await state.set_state(BroadcastStates.CONFIRMING)


@router.business_message(
    ADMIN_FILTER,
    BroadcastStates.CONFIRMING,
    ~F.text.startswith('/'),
)
async def update_source_message(message: Message, state: FSMContext):
    """Allow replacing the broadcast message while confirming."""
    if message.checklist_tasks_done or message.checklist:
        return

    data = await state.get_data()
    broadcast_id = data.get('broadcast_id')
    session = _sessions.get(broadcast_id)
    if session is None:
        return

    if message.media_group_id:
        await message.reply('Альбомы пока не поддерживаются, пришлите одно сообщение.')
        return

    if not _is_supported_source(message):
        await message.reply('Для рассылки поддерживаются текст и одно фото с подписью.')
        return

    session.source_message = message
    if session.confirm_message:
        try:
            await session.confirm_message.edit_reply_markup(reply_markup=None)
        except TelegramBadRequest:
            pass

    confirm = await message.reply(
        _confirm_text(session),
        reply_markup=_confirm_keyboard(broadcast_id),
    )
    session.confirm_message = confirm


@router.edited_business_message(ADMIN_FILTER)
async def update_edited_source(message: Message, state: FSMContext):
    if await state.get_state() != BroadcastStates.CONFIRMING.state:
        return

    data = await state.get_data()
    session = _sessions.get(data.get('broadcast_id'))
    if session is None or session.source_message is None:
        return

    source = session.source_message
    if source.chat.id != message.chat.id or source.message_id != message.message_id:
        return

    if _is_supported_source(message):
        session.source_message = message


@router.callback_query(F.data.startswith('bc_test:'), ADMIN_FILTER)
async def test_broadcast(update: CallbackQuery):
    broadcast_id = update.data.split(':', 1)[1]
    session = _sessions.get(broadcast_id)
    if session is None or session.source_message is None:
        await update.answer('Сессия рассылки не найдена', show_alert=True)
        return

    try:
        await _copy_to_user(session.source_message, update.from_user.id)
        await update.answer('Отправили вам копию')
    except Exception as error:
        await update.answer(f'Ошибка: {error}', show_alert=True)


@router.callback_query(F.data.startswith('bc_cancel:'), ADMIN_FILTER)
async def cancel_broadcast(update: CallbackQuery, state: FSMContext):
    broadcast_id = update.data.split(':', 1)[1]
    session = _sessions.pop(broadcast_id, None)
    if session:
        for task in session.load_tasks.values():
            task.cancel()

    await state.clear()
    try:
        await update.message.edit_reply_markup(reply_markup=None)
    except TelegramBadRequest:
        pass
    await update.message.answer('Рассылка отменена')
    await update.answer()


@router.callback_query(F.data.startswith('bc_start:'), ADMIN_FILTER)
async def start_sending(update: CallbackQuery, state: FSMContext):
    broadcast_id = update.data.split(':', 1)[1]
    session = _sessions.get(broadcast_id)
    if session is None or session.source_message is None:
        await update.answer('Сессия рассылки не найдена', show_alert=True)
        return

    current_state = await state.get_state()
    if current_state == BroadcastStates.SENDING.state:
        await update.answer('Рассылка уже идёт', show_alert=True)
        return

    await state.set_state(BroadcastStates.SENDING)
    try:
        await update.message.edit_reply_markup(reply_markup=None)
    except TelegramBadRequest:
        pass
    await update.answer()

    # wait for pending participant loads
    pending = [t for t in session.load_tasks.values() if not t.done()]
    if pending:
        await update.message.answer('Дожидаемся загрузки участников…')
        await asyncio.gather(*pending, return_exceptions=True)

    recipients = sorted(_unique_recipients(session))
    to_send = [
        uid for uid in recipients
        if not db.was_broadcast_delivered(broadcast_id, uid)
    ]

    if not to_send:
        await update.message.answer(
            'Некому рассылать: нет участников или всем уже отправлено.'
        )
        await state.clear()
        _sessions.pop(broadcast_id, None)
        return

    await update.message.answer(
        f'Начинаю рассылку <code>{broadcast_id}</code>: '
        f'{len(to_send)} пользователей…',
        parse_mode='HTML',
    )

    stats = {'success': 0, 'blocked': 0, 'no_dialog': 0, 'other': 0}
    total = len(to_send)

    for user_id in to_send:
        try:
            await _copy_to_user(session.source_message, user_id)
        except TelegramRetryAfter as error:
            await asyncio.sleep(error.retry_after)
            try:
                await _copy_to_user(session.source_message, user_id)
            except Exception as retry_error:
                stats[_classify_error(retry_error)] += 1
                await asyncio.sleep(SEND_INTERVAL)
                continue
        except Exception as error:
            stats[_classify_error(error)] += 1
            await asyncio.sleep(SEND_INTERVAL)
            continue

        try:
            db.mark_broadcast_delivered(broadcast_id, user_id)
        except Exception as error:
            await state.set_state(BroadcastStates.CONFIRMING)
            await _refresh_confirm_message(session)
            await update.message.answer(
                'Рассылка остановлена: сообщение пользователю '
                f'{user_id} отправлено, но результат не записался в БД:\n{error}\n\n'
                'При повторном запуске этот пользователь может получить дубликат.'
            )
            return

        stats['success'] += 1

        await asyncio.sleep(SEND_INTERVAL)

    already = db.count_broadcast_deliveries(broadcast_id)
    percent = 100 * stats['success'] / total if total else 0
    text = (
        f'Успешно отправлено: {stats["success"]} сообщений ({percent:.1f}%).\n'
        f'Пользователь заблокировал бота: {stats["blocked"]}\n'
        f'У пользователя нет диалога с ботом: {stats["no_dialog"]}\n'
        f'Другие исключения: {stats["other"]}'
    )
    if already > stats['success']:
        text += f'\nРанее доставлено в этой рассылке: {already - stats["success"]}.'
    await update.message.answer(text)

    await state.clear()
    _sessions.pop(broadcast_id, None)
    for task in session.load_tasks.values():
        task.cancel()
