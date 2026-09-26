"""Serialising the read-modify-write window.

Targeted cell writes stop taps on *different* plants from clobbering each
other, but two taps on the same plant still contend for its Status cell: each
reads the same snapshot, clears a different action, and the last write wins.

Capping the function at one instance fixes that, but a concurrency of 1 makes
Cloud Run reject bursts with 429. So the instance accepts concurrent requests
and serialises them here instead.
"""
import threading
import time

from src import recorder, storage


def test_exclusive_serialises_overlapping_writers():
    order = []

    def worker(n):
        with storage.exclusive():
            order.append(("enter", n))
            time.sleep(0.05)
            order.append(("exit", n))

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Every enter is immediately followed by its own exit -- no interleaving.
    for i in range(0, len(order), 2):
        assert order[i][0] == "enter"
        assert order[i + 1] == ("exit", order[i][1])


def test_exclusive_releases_when_the_body_raises():
    """A failed tap must not wedge every later one."""
    try:
        with storage.exclusive():
            raise RuntimeError("boom")
    except RuntimeError:
        pass

    acquired = []

    def worker():
        with storage.exclusive():
            acquired.append(True)

    t = threading.Thread(target=worker)
    t.start()
    t.join(timeout=2)

    assert acquired == [True], "lock was not released"


def test_the_webhook_holds_the_lock_for_the_whole_request(monkeypatch):
    """The snapshot is taken when PlantDB is constructed, so the lock has to
    span construction through save -- not just the write itself."""
    held = []

    class TrackingLock:
        def __init__(self):
            self._real = threading.RLock()

        def __enter__(self):
            held.append("acquired")
            return self._real.__enter__()

        def __exit__(self, *a):
            held.append("released")
            return self._real.__exit__(*a)

    monkeypatch.setattr(storage, "_write_lock", TrackingLock())

    class FakeDB:
        def log_task_action(self, plant_name, action, date=None, notes=""):
            held.append("sheet-work")
            return True

    monkeypatch.setattr(recorder, "TELEGRAM_WEBHOOK_SECRET", "s")
    monkeypatch.setattr(recorder, "TELEGRAM_CHAT_ID", "1")
    monkeypatch.setattr(recorder, "PlantDB", FakeDB)
    monkeypatch.setattr(recorder, "edit_message_reply_markup", lambda *a, **k: None)
    monkeypatch.setattr(recorder, "answer_callback_query", lambda *a, **k: None)

    class Req:
        headers = {"X-Telegram-Bot-Api-Secret-Token": "s"}

        def get_json(self, silent=True):
            return {"callback_query": {"id": "c", "data": "t:WATER:Monstera",
                                       "message": {"chat": {"id": 1}, "message_id": 1,
                                                   "reply_markup": {"inline_keyboard": []}}}}

    recorder.telegram_webhook(Req())

    assert held == ["acquired", "sheet-work", "released"]
