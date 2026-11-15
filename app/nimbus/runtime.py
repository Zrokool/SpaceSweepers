"""Shared SI runtime helpers for every Nimbus agent: one model call at a time, and a fingerprint of what answers depend on."""

from __future__ import annotations

import asyncio
import weakref
from contextlib import asynccontextmanager

from app.config import Settings
from app.nimbus import spec
from app.si.ollama import SIError

_locks: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Lock]" = weakref.WeakKeyDictionary()


def model_lock() -> asyncio.Lock:
    """The one lock around calls to the local SI model, so a slow chat answer and an explanation never run at the same time."""
    loop = asyncio.get_running_loop()
    if loop not in _locks:
        _locks[loop] = asyncio.Lock()
    return _locks[loop]


_waiting = 0


@asynccontextmanager
async def model_slot(max_waiting: int = 4, wait_seconds: float = 90.0):
    """The model lock with a short queue and a wait limit, so a flood of questions cannot pile up behind one slow answer.

    Raises SIError (which the chat already turns into "evidence only") when too many are already waiting or the wait runs out."""
    global _waiting
    lock = model_lock()
    if lock.locked() and _waiting >= max_waiting:
        raise SIError("SI is busy with other questions. Try again in a minute.")
    _waiting += 1
    try:
        await asyncio.wait_for(lock.acquire(), wait_seconds)
    except TimeoutError:
        raise SIError("SI is busy with other questions. Try again in a minute.") from None
    finally:
        _waiting -= 1
    try:
        yield
    finally:
        lock.release()


def data_version(settings: Settings) -> tuple:
    """Changes whenever the labels, mappings, snapshot, the Nimbus specs or the model change, so a cached answer is never stale."""
    files = [settings.data_dir / "method_flags.json", settings.data_dir / "method_flags.yaml", settings.data_dir / "table_mappings.json",
             settings.data_dir / "snapshot" / "manifest.json"]
    return (tuple(f.stat().st_mtime_ns if f.exists() else 0 for f in files), spec.spec_hash(), settings.si_model)
