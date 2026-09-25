from datetime import datetime, timedelta, timezone

import predict
import watch_cycles


class Clock:
    elapsed = 0
    def monotonic(self): return self.elapsed
    def sleep(self, seconds): self.elapsed += seconds
    def now(self): return datetime(2026, 9, 25, tzinfo=timezone.utc) + timedelta(seconds=self.elapsed)


def test_watcher_waits_and_delivers_each_new_cycle_once(tmp_path, monkeypatch):
    monkeypatch.setattr(predict, "SUBMISSION_DIR", tmp_path)
    clock = Clock()
    sequence = iter([None, "cycle1", "cycle1", "cycle2", "cycle2"])
    class API:
        current = None
        def current_cycle(self):
            self.current = next(sequence)
            return {"cycle_id": self.current} if self.current else None
    api = API()
    delivered = []
    def send():
        delivered.append(api.current)
        predict.remember_acceptance(api.current, {"submission_id": "sub_" + api.current})
        return 0
    assert watch_cycles.watch(api, until=clock.now()+timedelta(days=1), seconds=300,
        send=send, monotonic=clock.monotonic, sleep=clock.sleep, now=clock.now)
    assert delivered == ["cycle1", "cycle2"]


def test_watcher_retries_failed_delivery_and_keeps_polling(tmp_path, monkeypatch):
    monkeypatch.setattr(predict, "SUBMISSION_DIR", tmp_path)
    clock = Clock()
    class API:
        calls = 0
        def current_cycle(self):
            self.calls += 1
            if self.calls == 1: raise TimeoutError()
            return {"cycle_id": "cycle1"}
    deliveries = []
    def send():
        deliveries.append(1)
        if len(deliveries) == 1: return 2
        predict.remember_acceptance("cycle1", {"submission_id": "sub_1"})
        return 0
    watch_cycles.watch(API(), until=clock.now()+timedelta(days=1), seconds=240,
        send=send, monotonic=clock.monotonic, sleep=clock.sleep, now=clock.now)
    assert len(deliveries) == 2


def test_expired_watcher_never_polls_or_renews():
    clock = Clock()
    assert not watch_cycles.watch(None, until=clock.now(), seconds=60,
        monotonic=clock.monotonic, sleep=clock.sleep, now=clock.now)
