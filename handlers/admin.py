"""
Admin-only commands.
"""

import asyncio
import logging
import os

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message

from bot_config.schedule import SCHEDULE_2026
from database import Database
from utils import get_next_race
from utils.result_digest import (
    build_sample_qualifying_digest_text,
    build_sample_race_digest_text,
)

logger = logging.getLogger(__name__)
router = Router(name="admin")

ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
BROADCAST_CONCURRENCY = 12
BROADCAST_BATCH_SIZE = 60


def _is_admin(user_id: int) -> bool:
    return ADMIN_ID != 0 and user_id == ADMIN_ID


class BroadcastStates(StatesGroup):
    waiting_for_content = State()


@router.message(Command("stats"))
async def cmd_stats(message: Message, db: Database) -> None:
    if not _is_admin(message.from_user.id):
        await message.answer("⛔ Нет доступа.")
        return

    stats = db.get_stats()
    text = (
        "📊 <b>Статистика бота</b>\n\n"
        f"👥 Всего пользователей: <b>{stats['total']}</b>\n"
        f"📆 Активных сегодня (DAU): <b>{stats['dau']}</b>\n"
        f"📅 Активных за неделю (WAU): <b>{stats['wau']}</b>"
    )
    await message.answer(text, parse_mode="HTML")


@router.message(Command("broadcast"))
async def cmd_broadcast(message: Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id):
        await message.answer("⛔ Нет доступа.")
        return

    await state.set_state(BroadcastStates.waiting_for_content)
    await message.answer(
        "📢 <b>Режим рассылки</b>\n\n"
        "Отправь сообщение, которое нужно разослать всем.\n"
        "Поддерживаются: текст, фото, видео, документ.\n\n"
        "Для отмены напиши /cancel",
        parse_mode="HTML",
    )


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id):
        return
    await state.clear()
    await message.answer("❌ Рассылка отменена.")


@router.message(Command("test_digest"))
async def cmd_test_digest(message: Message) -> None:
    if not _is_admin(message.from_user.id):
        await message.answer("⛔ Нет доступа.")
        return

    race = get_next_race(SCHEDULE_2026) or SCHEDULE_2026[0]
    parts = (message.text or "").split(maxsplit=1)
    mode = parts[1].strip().lower() if len(parts) > 1 else ""

    if mode == "qual":
        await message.answer(build_sample_qualifying_digest_text(race), parse_mode="HTML")
        return

    if mode == "race":
        await message.answer(build_sample_race_digest_text(race), parse_mode="HTML")
        return

    await message.answer("<b>Пример квалификационного дайджеста</b>", parse_mode="HTML")
    await message.answer(build_sample_qualifying_digest_text(race), parse_mode="HTML")
    await message.answer("<b>Пример пост-гоночного дайджеста</b>", parse_mode="HTML")
    await message.answer(build_sample_race_digest_text(race), parse_mode="HTML")


@router.message(BroadcastStates.waiting_for_content)
async def process_broadcast_content(message: Message, state: FSMContext, db: Database) -> None:
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
    processed = 0
    semaphore = asyncio.Semaphore(BROADCAST_CONCURRENCY)

    for offset in range(0, len(user_ids), BROADCAST_BATCH_SIZE):
        batch = user_ids[offset : offset + BROADCAST_BATCH_SIZE]
        results = await asyncio.gather(
            *(_send_copy(message, user_id, semaphore) for user_id in batch)
        )

        batch_success = sum(1 for result in results if result)
        success += batch_success
        failed += len(batch) - batch_success
        processed += len(batch)

        if processed < len(user_ids):
            await status_msg.edit_text(
                f"⏳ Рассылка: {processed}/{len(user_ids)}\n"
                f"Успешно: {success}\n"
                f"Ошибок: {failed}"
            )

    await status_msg.edit_text(
        f"✅ <b>Рассылка завершена</b>\n\n"
        f"Отправлено: {success}\n"
        f"Ошибок: {failed}",
        parse_mode="HTML",
    )
    logger.info("Broadcast finished: success=%d, failed=%d", success, failed)


async def _send_copy(message: Message, user_id: int, semaphore: asyncio.Semaphore) -> bool:
    async with semaphore:
        try:
            await message.copy_to(user_id)
            return True
        except Exception as exc:
            retry_after = getattr(exc, "retry_after", None)
            if retry_after:
                try:
                    await asyncio.sleep(float(retry_after))
                    await message.copy_to(user_id)
                    return True
                except Exception as retry_exc:
                    logger.warning("Retry send failed for %d: %s", user_id, retry_exc)
                    return False

            logger.warning("Failed to send broadcast to %d: %s", user_id, exc)
            return False


@router.message(F.photo)
async def get_photo_file_id(message: Message) -> None:
    if not _is_admin(message.from_user.id):
        return

    file_id = message.photo[-1].file_id
    await message.answer(
        "<b>file_id фото:</b>\n"
        f"<code>{file_id}</code>",
        parse_mode="HTML",
    )
