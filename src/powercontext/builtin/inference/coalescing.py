# Copyright (c) 2026 OceanBase.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Cross-call Embedding request coalescing with a bounded successful-vector cache.

One wrapper is shared by every caller in an event loop. Each distinct text is
awaited once: callers arriving inside the merge window, and callers arriving
while an accepted request is still running, attach to the same work instead of
starting another provider call.

Work runs in its own Task, so cancelling one waiter never cancels a request that
other callers still need, and one failing batch never blocks an independent one.
The cache only ever holds successful vectors, and each caller aggregates usage
for the distinct provider requests it actually waited on.
"""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from collections.abc import Iterable
from typing import Any

from powercontext.builtin.inference.models import EmbeddingResult, EmbeddingVector, InferenceUsage
from powercontext.builtin.inference.protocols import EmbeddingModel

Waiter = tuple["asyncio.Future[EmbeddingVector]", "_Call"]


class _VectorCache:
    """A bounded LRU of successful vectors; a zero capacity disables reuse."""

    __slots__ = ("_entries", "_maxsize")

    def __init__(self, maxsize: int) -> None:
        self._maxsize = maxsize
        self._entries: OrderedDict[str, EmbeddingVector] = OrderedDict()

    def get(self, text: str) -> EmbeddingVector | None:
        if not self._maxsize:
            return None
        vector = self._entries.get(text)
        if vector is None:
            return None
        self._entries.move_to_end(text)
        return vector

    def put(self, text: str, vector: EmbeddingVector) -> None:
        if not self._maxsize:
            return
        self._entries[text] = vector
        self._entries.move_to_end(text)
        while len(self._entries) > self._maxsize:
            self._entries.popitem(last=False)


class _Call:
    """One caller's accounting of the distinct provider requests it waited on."""

    __slots__ = ("batches",)

    def __init__(self) -> None:
        self.batches: dict[int, _Batch] = {}


class _Slot:
    """One distinct text and every caller currently waiting for its vector."""

    __slots__ = ("batch", "waiters")

    def __init__(self) -> None:
        self.waiters: list[Waiter] = []
        # Set once the text is owned by a dispatched request, so a caller that
        # arrives later still attributes usage to the batch it waited on.
        self.batch: _Batch | None = None


class _Batch:
    """One accepted provider request covering a bounded group of distinct texts."""

    __slots__ = ("slots", "texts", "usage")

    def __init__(self, texts: tuple[str, ...], slots: tuple[_Slot, ...]) -> None:
        self.texts = texts
        self.slots = slots
        self.usage = InferenceUsage(requests=0)


class CoalescingEmbeddingModel:
    """Share in-flight Embedding work across callers and reuse successful vectors."""

    def __init__(
        self,
        model: EmbeddingModel,
        *,
        max_batch_size: int = 64,
        coalesce_ms: float = 5.0,
        cache_size: int = 1024,
    ) -> None:
        self._require_positive_integer("max_batch_size", max_batch_size)
        self._require_non_negative_number("coalesce_ms", coalesce_ms)
        self._require_non_negative_integer("cache_size", cache_size)
        self._model = model
        self.profile = model.profile
        self._max_batch_size = max_batch_size
        self._window_seconds = float(coalesce_ms) / 1000.0
        self._cache = _VectorCache(cache_size)
        # Texts accepted but not yet dispatched, in first-arrival order.
        self._pending: dict[str, _Slot] = {}
        self._queue: list[str] = []
        # Texts owned by a request that is still running; late callers join it.
        self._active: dict[str, _Slot] = {}
        self._flush_handle: asyncio.Handle | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    async def embed(self, texts: tuple[str, ...], /) -> EmbeddingResult:
        """Return one ordered vector per input text, reusing cached and shared work."""

        items = tuple(texts)
        if not items:
            return EmbeddingResult(vectors=(), usage=InferenceUsage(requests=0))
        loop = asyncio.get_running_loop()
        self._bind_loop(loop)
        call = _Call()
        futures: dict[str, asyncio.Future[EmbeddingVector]] = {}
        scheduled = False
        for text in items:
            if text in futures:
                continue
            cached = self._cache.get(text)
            if cached is not None:
                resolved: asyncio.Future[EmbeddingVector] = loop.create_future()
                resolved.set_result(cached)
                futures[text] = resolved
                continue
            slot = self._active.get(text)
            if slot is None:
                slot = self._pending.get(text)
                if slot is None:
                    slot = _Slot()
                    self._pending[text] = slot
                    self._queue.append(text)
                    scheduled = True
            elif slot.batch is not None:
                # Joining a request that is already running: this caller waited
                # on that batch, so charge it once, exactly like the callers
                # that were present when it was dispatched.
                call.batches[id(slot.batch)] = slot.batch
            waiter: asyncio.Future[EmbeddingVector] = loop.create_future()
            slot.waiters.append((waiter, call))
            futures[text] = waiter
        if scheduled:
            self._schedule_flush(loop)
        await self._settle(tuple(futures.values()))
        return EmbeddingResult(
            vectors=tuple(futures[text].result() for text in items),
            usage=_aggregate_usage(call),
        )

    def _bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Drop transient state that belonged to a different, already closed loop.

        A merge handle is bound to the loop that created it: if a scenario ends
        while a window is still open the handle can never fire, and keeping it
        would make every later call wait for a flush that cannot happen. The
        vector cache holds no loop state, so it survives the switch.
        """

        if self._loop is loop:
            return
        self._loop = loop
        self._pending.clear()
        self._queue.clear()
        self._active.clear()
        self._flush_handle = None

    def _schedule_flush(self, loop: asyncio.AbstractEventLoop) -> None:
        if self._flush_handle is not None:
            return
        # A zero window still merges every caller that is already runnable, then
        # dispatches once instead of opening a request per awaiting caller.
        self._flush_handle = (
            loop.call_soon(self._flush)
            if self._window_seconds <= 0
            else loop.call_later(self._window_seconds, self._flush)
        )

    def _flush(self) -> None:
        self._flush_handle = None
        texts = tuple(self._queue)
        self._queue.clear()
        if not texts:
            return
        for start in range(0, len(texts), self._max_batch_size):
            chunk: list[str] = []
            slots: list[_Slot] = []
            for text in texts[start : start + self._max_batch_size]:
                slot = self._pending.pop(text, None)
                if slot is None:
                    continue
                self._active[text] = slot
                chunk.append(text)
                slots.append(slot)
            if not slots:
                continue
            batch = _Batch(tuple(chunk), tuple(slots))
            for slot in slots:
                slot.batch = batch
                for _, call in slot.waiters:
                    call.batches[id(batch)] = batch
            asyncio.ensure_future(self._run_batch(batch))

    async def _run_batch(self, batch: _Batch) -> None:
        try:
            result = await self._model.embed(batch.texts)
        except BaseException as error:  # noqa: BLE001 - every waiter must observe the same failure
            self._release(batch)
            self._fail(batch, error)
            if isinstance(error, asyncio.CancelledError):
                raise
            return
        vectors = tuple(result.vectors)
        if len(vectors) != len(batch.texts):
            self._release(batch)
            self._fail(batch, ValueError("embedding vector count does not match the submitted texts"))
            return
        batch.usage = result.usage
        for text, vector in zip(batch.texts, vectors, strict=True):
            self._cache.put(text, vector)
        self._release(batch)
        for slot, vector in zip(batch.slots, vectors, strict=True):
            for waiter, _ in slot.waiters:
                if not waiter.done():
                    waiter.set_result(vector)

    def _release(self, batch: _Batch) -> None:
        for text in batch.texts:
            self._active.pop(text, None)

    @staticmethod
    def _fail(batch: _Batch, error: BaseException) -> None:
        for slot in batch.slots:
            for waiter, _ in slot.waiters:
                if not waiter.done():
                    waiter.set_exception(error)

    async def _settle(self, waiters: tuple[asyncio.Future[EmbeddingVector], ...]) -> None:
        outstanding = [waiter for waiter in waiters if not waiter.done()]
        if outstanding:
            await asyncio.gather(*outstanding, return_exceptions=True)
        failure: BaseException | None = None
        cancelled = False
        for waiter in waiters:
            if waiter.cancelled():
                cancelled = True
                continue
            if waiter.done() and failure is None:
                failure = waiter.exception()
        if failure is not None:
            raise failure
        if cancelled:
            raise asyncio.CancelledError

    @staticmethod
    def _require_positive_integer(name: str, value: Any) -> None:
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ValueError(f"{name} must be a positive integer")  # noqa: TRY003

    @staticmethod
    def _require_non_negative_integer(name: str, value: Any) -> None:
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"{name} must be a non-negative integer")  # noqa: TRY003

    @staticmethod
    def _require_non_negative_number(name: str, value: Any) -> None:
        if isinstance(value, bool) or not isinstance(value, int | float) or value < 0:
            raise ValueError(f"{name} must be a non-negative number")  # noqa: TRY003


def _aggregate_usage(call: _Call) -> InferenceUsage:
    """Sum one provider report per distinct request this caller waited on."""

    if not call.batches:
        return InferenceUsage(requests=0)
    requests = 0
    inputs: list[int | None] = []
    outputs: list[int | None] = []
    for batch in call.batches.values():
        requests += batch.usage.requests
        inputs.append(batch.usage.input_tokens)
        outputs.append(batch.usage.output_tokens)
    return InferenceUsage(
        requests=requests,
        input_tokens=_total_or_none(inputs),
        output_tokens=_total_or_none(outputs),
    )


def _total_or_none(values: Iterable[int | None]) -> int | None:
    reported = [value for value in values if value is not None]
    return sum(reported) if reported else None


__all__ = ["CoalescingEmbeddingModel"]
