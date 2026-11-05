"""One aiogram polling process, with a leased transactional notification queue."""
import asyncio
import logging
import time
from contextlib import suppress
from datetime import timedelta
from aiogram import Bot, Dispatcher, F
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from aiogram.types import BotCommand, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import select
from app.bot_dialog import respond, STATUSES
from app.config import settings
from app.database import SessionLocal
from app.models import Notification, Staff, SystemState, Ticket, now

log = logging.getLogger('app.bot')
dispatcher = Dispatcher()


def process(user_id, name, text='', callback='', username=None):
    with SessionLocal.begin() as db:
        return respond(db, user_id, name, text, callback, username)


def keyboard(rows):
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=label, callback_data=value)] for label, value in rows]) if rows else None


async def reply(message, user, text='', callback=''):
    try:
        answer, rows = await asyncio.to_thread(process, user.id, user.full_name, text, callback, user.username)
    except Exception as error:
        log.error('Dialog failed: %s', type(error).__name__)
        answer, rows = 'Не удалось сохранить данные. Повторите действие через несколько секунд.', []
    await message.answer(answer, reply_markup=keyboard(rows), parse_mode=None)


@dispatcher.message(F.chat.type == 'private')
async def message_handler(message: Message):
    if not message.from_user:
        return
    await reply(message, message.from_user, message.text or '')


@dispatcher.callback_query(F.message.chat.type == 'private')
async def callback_handler(callback: CallbackQuery):
    await callback.answer()
    await reply(callback.message, callback.from_user, callback=callback.data or '')


def claim():
    with SessionLocal.begin() as db:
        while True:
            row = db.scalar(select(Notification).where(Notification.next_attempt_at <= now(),
                Notification.state.in_(('pending', 'sending'))).order_by(Notification.id).with_for_update(skip_locked=True).limit(1))
            if not row:
                return None
            payload = row.payload
            if 'staff_id' in payload:
                employee = db.get(Staff, payload['staff_id'])
                ticket = db.get(Ticket, row.ticket_id)
                valid = employee and employee.active and employee.telegram_id == row.recipient
                admin_event = payload['kind'] == 'create' or payload['kind'].startswith('admin_')
                valid = valid and (employee.role == 'admin' if admin_event else ticket.assignee_id == employee.id)
                if not valid:
                    if payload.get('applicant_copy'):
                        payload = {key: payload[key] for key in ('number', 'status', 'result')}
                        row.payload = payload
                    else:
                        row.state = 'cancelled'
                        db.flush()
                        continue
            row.state, row.attempts = 'sending', row.attempts + 1
            row.next_attempt_at = now() + timedelta(minutes=2)
            return row.id, row.recipient, payload


def finish(notification_id, state, error=None, delay=0):
    with SessionLocal.begin() as db:
        row = db.get(Notification, notification_id)
        row.state = 'failed' if state == 'pending' and row.attempts >= settings.notifications_max_attempts else state
        row.last_error = error
        row.next_attempt_at = now() + timedelta(seconds=delay)
        if state == 'sent':
            row.sent_at = now()


def notification_text(payload):
    kind = payload.get('kind', '')
    heading = {'create': 'Новая заявка', 'assign': 'Вам назначена заявка', 'take': 'Вы взяли заявку в работу',
               'admin_take': 'Принята в работу заявка', 'admin_complete': 'Выполнена заявка',
               'admin_reject': 'Отклонена заявка'}.get(kind)
    if heading:
        text = f"{heading} {payload['number']}\n{payload['category']}\n{payload['description']}"
        if kind.startswith('admin_'):
            text += f"\nИсполнитель: {payload['assignee_name']}"
            if payload.get('result'):
                label = 'Причина' if kind == 'admin_reject' else 'Результат'
                text += f"\n{label}: {payload['result'][:2000]}"
        if payload.get('telegram_user_id'):
            username = '@' + payload['telegram_username'] if payload.get('telegram_username') else 'не указан'
            text += f"\nЗаявитель: {payload['applicant_name']}\nTelegram ID: {payload['telegram_user_id']}\nUsername: {username}"
        return text
    status = 'принята в работу' if payload['status'] == 'in_progress' else STATUSES[payload['status']].lower()
    text = f"Заявка №{payload['number']} {status}."
    return text + (f"\nРезультат: {payload['result'][:3000]}" if payload.get('result') else '')


async def send_one(bot):
    job = await asyncio.to_thread(claim)
    if not job:
        return False
    notification_id, recipient, payload = job
    state, error, delay = 'sent', None, 0
    try:
        await bot.send_message(recipient, notification_text(payload), parse_mode=None)
    except (TelegramForbiddenError, TelegramBadRequest) as exc:
        state, error = 'failed', type(exc).__name__
    except TelegramRetryAfter as exc:
        state, error, delay = 'pending', type(exc).__name__, max(3, exc.retry_after)
    except Exception as exc:
        state, error, delay = 'pending', type(exc).__name__, 15
    await asyncio.to_thread(finish, notification_id, state, error, delay)
    return True


def heartbeat():
    with SessionLocal.begin() as db:
        row = db.get(SystemState, 'telegram_heartbeat')
        if not row:
            row = SystemState(key='telegram_heartbeat')
            db.add(row)
        row.value = int(time.time())


async def notifications(bot):
    while True:
        try:
            await asyncio.to_thread(heartbeat)
            if settings.notifications_enabled:
                for _ in range(20):
                    if not await send_one(bot):
                        break
        except Exception as exc:
            log.error('Notification worker failed: %s', type(exc).__name__)
        await asyncio.sleep(settings.notifications_poll_seconds)


async def main():
    if not settings.telegram_configured:
        raise SystemExit('Set TELEGRAM_BOT_TOKEN in backend/.env')
    # aiogram polling errors can include URLs; redact credentials from every log.
    class SafeFormatter(logging.Formatter):
        def format(self, record):
            return super().format(record).replace(settings.telegram_bot_token, '[redacted]')
    handler = logging.StreamHandler()
    handler.setFormatter(SafeFormatter('%(asctime)s %(levelname)s %(message)s'))
    logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)
    async with Bot(settings.telegram_bot_token) as bot:
        me = await bot.get_me()
        log.info('Bot ready: @%s', me.username)
        await bot.set_my_commands([BotCommand(command=command, description=description) for command, description in
            [('start','Меню'),('new','Создать заявку'),('mine','Мои заявки'),('status','Статус заявки'),('assigned','Мои задания'),('cancel','Отменить диалог'),('id','Мой Telegram ID')]])
        worker = asyncio.create_task(notifications(bot))
        try:
            # Sequential updates keep each persisted conversation ordered, including confirmations.
            await dispatcher.start_polling(bot, handle_as_tasks=False, close_bot_session=False)
        finally:
            worker.cancel()
            with suppress(asyncio.CancelledError):
                await worker


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
    except Exception as error:
        log.error('Bot stopped: %s', type(error).__name__)
        raise SystemExit(1)
