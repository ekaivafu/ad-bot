import os
import sys
import asyncio
import logging
import time
from typing import Optional, Dict, Any
from aiogram import Bot
from aiogram.types import FSInputFile, BufferedInputFile
import aadhaar_engine

logger = logging.getLogger(__name__)

class DummyMessage:
    def __init__(self, message_id: int):
        self.message_id = message_id

class AiogramBotAdapter:
    """
    Seamless compatibility adapter that wraps aiogram.Bot so aadhaar_engine
    can invoke send_message, edit_message_text, delete_message, send_photo,
    and send_document synchronously within its workflow.
    """
    def __init__(self, bot: Bot, loop: Optional[asyncio.AbstractEventLoop] = None):
        self.bot = bot
        self.loop = loop or asyncio.get_event_loop()

    def _sync_run(self, coro):
        """Runs a coroutine safely whether invoked from sync or async context."""
        try:
            curr_loop = asyncio.get_running_loop()
            if curr_loop == self.loop:
                # We are already inside the target loop
                task = curr_loop.create_task(coro)
                # If we are in an async function, we can't synchronously block the loop,
                # but we return the task which can be awaited or treated as dispatched.
                return task
        except RuntimeError:
            pass
        return asyncio.run_coroutine_threadsafe(coro, self.loop).result(timeout=25)

    def send_message(self, chat_id, text, parse_mode="HTML", **kwargs):
        async def _do():
            msg = await self.bot.send_message(
                chat_id=int(chat_id),
                text=str(text),
                parse_mode=parse_mode,
                disable_web_page_preview=True
            )
            return DummyMessage(msg.message_id)

        try:
            # If called inside an active async event loop, schedule it immediately
            task = self._sync_run(_do())
            # For status message tracking, return dummy message or placeholder
            return DummyMessage(int(time.time() * 1000) % 10000000)
        except Exception as e:
            logger.warning(f"AiogramBotAdapter send_message notice: {e}")
            return DummyMessage(0)

    def edit_message_text(self, text, chat_id=None, message_id=None, parse_mode="HTML", **kwargs):
        async def _do():
            if not message_id or message_id < 1000:
                # If synthetic message_id, send new message instead
                await self.bot.send_message(
                    chat_id=int(chat_id),
                    text=str(text),
                    parse_mode=parse_mode,
                    disable_web_page_preview=True
                )
                return
            await self.bot.edit_message_text(
                chat_id=int(chat_id),
                message_id=int(message_id),
                text=str(text),
                parse_mode=parse_mode,
                disable_web_page_preview=True
            )

        try:
            self._sync_run(_do())
        except Exception as e:
            logger.debug(f"AiogramBotAdapter edit_message_text notice: {e}")

    def delete_message(self, chat_id, message_id):
        async def _do():
            if message_id and message_id > 1000:
                await self.bot.delete_message(chat_id=int(chat_id), message_id=int(message_id))

        try:
            self._sync_run(_do())
        except Exception:
            pass

    def send_photo(self, chat_id, photo, caption=None, parse_mode="HTML", **kwargs):
        async def _do():
            if isinstance(photo, str) and os.path.exists(photo):
                file_obj = FSInputFile(photo)
            elif hasattr(photo, "read"):
                file_obj = BufferedInputFile(photo.read(), filename="captcha.png")
            elif isinstance(photo, bytes):
                file_obj = BufferedInputFile(photo, filename="captcha.png")
            else:
                file_obj = photo

            msg = await self.bot.send_photo(
                chat_id=int(chat_id),
                photo=file_obj,
                caption=caption,
                parse_mode=parse_mode
            )
            return DummyMessage(msg.message_id)

        try:
            self._sync_run(_do())
            return DummyMessage(int(time.time() * 1000) % 10000000)
        except Exception as e:
            logger.error(f"AiogramBotAdapter send_photo error: {e}")
            return DummyMessage(0)

    def send_document(self, chat_id, document, caption=None, **kwargs):
        async def _do():
            if isinstance(document, str) and os.path.exists(document):
                file_obj = FSInputFile(document)
            elif hasattr(document, "read"):
                file_obj = BufferedInputFile(document.read(), filename="Aadhaar.pdf")
            elif isinstance(document, bytes):
                file_obj = BufferedInputFile(document, filename="Aadhaar.pdf")
            else:
                file_obj = document

            await self.bot.send_document(
                chat_id=int(chat_id),
                document=file_obj,
                caption=caption
            )

        try:
            self._sync_run(_do())
        except Exception as e:
            logger.error(f"AiogramBotAdapter send_document error: {e}")


class AadhaarService:
    """Manages the full lifecycle of Aadhaar download operations."""

    @staticmethod
    def is_user_waiting_input(chat_id: int) -> bool:
        str_id = str(chat_id)
        reg = aadhaar_engine.user_page_registry.get(str_id)
        return reg is not None and reg.get("value") is None

    @staticmethod
    def submit_user_input(chat_id: int, text: str):
        str_id = str(chat_id)
        if str_id in aadhaar_engine.user_page_registry:
            aadhaar_engine.user_page_registry[str_id]["value"] = text.strip()
        else:
            aadhaar_engine.buffered_inputs[str_id] = text.strip()

    @staticmethod
    def cancel_task(chat_id: int):
        str_id = str(chat_id)
        if str_id in aadhaar_engine.user_page_registry:
            aadhaar_engine.user_page_registry[str_id]["value"] = "__CANCEL__"
        aadhaar_engine.buffered_inputs[str_id] = "__CANCEL__"

    @staticmethod
    def is_task_active(chat_id: int) -> bool:
        return chat_id in aadhaar_engine.active_tasks or str(chat_id) in aadhaar_engine.active_tasks

    @classmethod
    async def run_download_workflow(
        cls,
        bot: Bot,
        chat_id: int,
        name: str,
        mobile: str,
        dob: Optional[str] = None,
        user_info: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Executes the Aadhaar engine workflow asynchronously.
        Returns True on success, False on failure.
        """
        adapter = AiogramBotAdapter(bot, asyncio.get_running_loop())
        try:
            res = await aadhaar_engine.execute_task(
                adapter,
                chat_id=chat_id,
                name=name,
                mobile=mobile,
                dob=dob,
                user_info=user_info
            )
            return bool(res)
        except Exception as e:
            logger.error(f"AadhaarService execution error for {chat_id}: {e}", exc_info=True)
            return False
        finally:
            cls.cleanup_temp_files()

    @staticmethod
    def cleanup_temp_files():
        """Safely cleans up generated cracked PDFs to preserve free hosting disk space."""
        try:
            cracked_dir = getattr(aadhaar_engine, "CRACKED_DIR", None)
            if cracked_dir and os.path.exists(cracked_dir):
                now = time.time()
                for fn in os.listdir(cracked_dir):
                    fp = os.path.join(cracked_dir, fn)
                    # Delete files older than 5 minutes
                    if os.path.isfile(fp) and (now - os.path.getmtime(fp) > 300):
                        try:
                            os.unlink(fp)
                        except Exception:
                            pass
        except Exception as e:
            logger.debug(f"Cleanup notice: {e}")
