import asyncio
import time
from typing import Dict, List, Optional

from utils import server_state
from utils.database.database_manager import DatabaseManager
from utils.logger import setup_logger

logger = setup_logger(__name__)


class BacklogMessageWriter:
    def __init__(self, batch_size: int = 50, flush_interval: float = 1.0):
        self.batch_size = batch_size
        self.flush_interval = flush_interval
        self._queue: asyncio.Queue[Dict] = asyncio.Queue()
        self._task: Optional[asyncio.Task] = None

    async def enqueue(self, payload: Dict) -> None:
        self._ensure_started()
        await self._queue.put(payload)

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        finally:
            self._task = None

    def _ensure_started(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run(), name="backlog-message-writer")

    def _complete_catchup_if_idle(self) -> None:
        if not server_state.is_catching_up or not self._queue.empty():
            return

        last_activity = getattr(server_state, "last_backlog_message_at", 0.0) or 0.0
        if last_activity <= 0:
            return

        if time.monotonic() - last_activity < (self.flush_interval * 1.5):
            return

        logger.info(
            "Навёрстывание истории завершено. Обработано старых сообщений: %s",
            server_state.backlog_processed_count,
        )
        server_state.is_catching_up = False
        server_state.last_backlog_message_at = 0.0

    async def _run(self) -> None:
        batch: List[Dict] = []

        while True:
            if not server_state.server_active and self._queue.empty() and not batch:
                break

            timeout = self.flush_interval if batch or server_state.is_catching_up else None
            try:
                if timeout is None:
                    item = await self._queue.get()
                else:
                    item = await asyncio.wait_for(self._queue.get(), timeout=timeout)
                batch.append(item)

                while len(batch) < self.batch_size:
                    try:
                        batch.append(self._queue.get_nowait())
                    except asyncio.QueueEmpty:
                        break

                if len(batch) >= self.batch_size:
                    self._flush_batch(batch)
                    batch = []
            except asyncio.TimeoutError:
                if batch:
                    self._flush_batch(batch)
                    batch = []
                else:
                    self._complete_catchup_if_idle()
            except asyncio.CancelledError:
                if batch:
                    self._flush_batch(batch)
                self._complete_catchup_if_idle()
                raise
            except Exception as exc:
                logger.error(f"Ошибка в фоновом backlog writer: {exc}")
                if batch:
                    self._flush_batch(batch)
                    batch = []
                await asyncio.sleep(0.5)

        self._complete_catchup_if_idle()

    def _flush_batch(self, batch: List[Dict]) -> None:
        if not batch:
            return

        db = DatabaseManager()
        try:
            db.messages.add_messages_batch(batch)
        finally:
            db.close()

        self._complete_catchup_if_idle()


backlog_message_writer = BacklogMessageWriter()
