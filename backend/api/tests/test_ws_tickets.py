"""WS 短票 Redis / 内存单次消费回归。"""

from app import ws_tickets


class _FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    def set(self, name, value, nx=False, ex=None):
        if nx and name in self.store:
            return False
        self.store[name] = value
        return True


def test_memory_ticket_single_use(monkeypatch) -> None:
    """无 Redis 时同一 jti 只能消费一次。"""
    monkeypatch.setattr(ws_tickets, "_redis_consume", lambda *_a, **_k: None)
    ws_tickets.reset_memory_tickets()
    assert ws_tickets.consume_ws_jti("jti-1", 60) is True
    assert ws_tickets.consume_ws_jti("jti-1", 60) is False
    assert ws_tickets.consume_ws_jti("", 60) is False


def test_redis_set_nx_rejects_second_use(monkeypatch) -> None:
    """Redis SET NX 成功后第二次消费失败。"""
    fake = _FakeRedis()

    def fake_redis(jti: str, ttl_seconds: int) -> bool | None:
        return bool(fake.set(f"ws:ticket:{jti}", "1", nx=True, ex=ttl_seconds))

    monkeypatch.setattr(ws_tickets, "_redis_consume", fake_redis)
    assert ws_tickets.consume_ws_jti("once", 30) is True
    assert ws_tickets.consume_ws_jti("once", 30) is False


def test_ttl_from_jwt_payload_uses_remaining_seconds(monkeypatch) -> None:
    """TTL 夹在 1 秒与短票有效期之间。"""
    monkeypatch.setattr(ws_tickets.settings, "ws_ticket_expire_minutes", 5)
    monkeypatch.setattr(ws_tickets.time, "time", lambda: 1_000_000.0)
    assert ws_tickets.ttl_from_jwt_payload({"exp": 1_000_000 + 12}) == 12
    assert ws_tickets.ttl_from_jwt_payload({"exp": 1_000_000 - 10}) == 1
    assert ws_tickets.ttl_from_jwt_payload({}) == 300
