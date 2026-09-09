from contextlib import contextmanager

import worker_health


class Cursor:
    def __init__(self, active):
        self.active = active

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None

    def execute(self, query):
        assert "worker_leases" in query

    def fetchone(self):
        return (self.active,)


class Connection:
    def __init__(self, active):
        self.active = active

    def cursor(self):
        return Cursor(self.active)


def fake_connection(active):
    @contextmanager
    def connect():
        yield Connection(active)

    return connect


def test_worker_health_requires_an_active_lease(monkeypatch):
    monkeypatch.setattr(worker_health, "connection", fake_connection(True))
    assert worker_health.main() == 0

    monkeypatch.setattr(worker_health, "connection", fake_connection(False))
    assert worker_health.main() == 1


def test_worker_health_fails_closed_on_database_error(monkeypatch):
    @contextmanager
    def broken_connection():
        raise RuntimeError("unavailable")
        yield

    monkeypatch.setattr(worker_health, "connection", broken_connection)
    assert worker_health.main() == 1
