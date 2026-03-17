"""
Админ-команды:
  /stats      — статистика пользователей
  /broadcast  — запуск режима рассылки
  /cancel     — отмена рассылки
  Отправка фото — получить file_id (только для админа)
"""

import asyncio
import logging
import os

from aiogram import Router, Bot, F
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from database import Database

logger = logging.getLogger(__name__)
router = Router(name="admin")

ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))


def _is_admin(user_id: int) -> bool:
    return ADMIN_ID != 0 and user_id == ADMIN_ID


class BroadcastStates(StatesGroup):
    waiting_for_content = State()


# ── /stats ────────────────────────────────────────────────────────────────────

@router.message(Command("stats"))
async def cmd_stats(message: Message, db: Database) -> None:
    if not _is_admin(message.from_user.id):
        await message.answer("⛔ Нет доступа.")
        return

    stats = db.get_stats()
    text = (
        "📊 <b>Статистика бота</b>\n\n"
        f"👥 Всего пользователей: <b>{stats['total']}</b>\n"
        f"📅 Активных сегодня (DAU): <b>{stats['dau']}</b>\n"
        f"📆 Активных за неделю (WAU): <b>{stats['wau']}</b>"
    )
    await message.answer(text, parse_mode="HTML")


# ── /broadcast ────────────────────────────────────────────────────────────────

@router.message(Command("broadcast"))
async def cmd_broadcast(message: Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id):
        await message.answer("⛔ Нет доступа.")
        return

    await state.set_state(BroadcastStates.waiting_for_content)
    await message.answer(
        "📢 <b>Режим рассылки</b>\n\n"
        "Отправь сообщение которое нужно разослать всем.\n"
        "Можно отправить: текст, фото, видео, документ.\n\n"
        "Для отмены напиши /cancel",
        parse_mode="HTML"
    )


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id):
        return
    await state.clear()
    await message.answer("❌ Рассылка отменена.")


@router.message(BroadcastStates.waiting_for_content)
async def process_broadcast_content(message: Message, state: FSMContext, db: Database, bot: Bot) -> None:
    await state.clear()

    user_ids = db.get_all_user_ids()
    if not user_ids:
        await message.answer("Нет пользователей для рассылки.")
        return

    status_msg = await message.answer(
        f"⏳ Начинаю рассылку {len(user_ids)} пользователям..."
    )

    success = 0
    failed = 0

    for user_id in user_ids:
        try:
            await message.copy_to(user_id)
            success += 1
        except Exception as exc:
            logger.warning("Не удалось отправить %d: %s", user_id, exc)
            failed += 1
        await asyncio.sleep(0.05)

    await status_msg.edit_text(
        f"✅ <b>Рассылка завершена</b>\n\n"
        f"Отправлено: {success}\n"
        f"Ошибок: {failed}",
        parse_mode="HTML"
    )
    logger.info("Рассылка завершена: успешно=%d, ошибок=%d", success, failed)


# ── Получение file_id фото ────────────────────────────────────────────────────

@router.message(F.photo)
async def get_photo_file_id(message: Message) -> None:
    """Отвечает file_id отправленного фото — только для админа."""
    if not _is_admin(message.from_user.id):
        return
    file_id = message.photo[-1].file_id
    await message.answer(
        "<b>file_id фото:</b>\n"
        f"<code>{file_id}</code>",
        parse_mode="HTML"
    )