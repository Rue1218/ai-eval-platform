"""健康检查接口单测（M0 空跑，不依赖数据库）。"""

from fastapi.testclient import TestClient

from app.main import app


def test_health():
    # 不进入 with 上下文，避免触发 lifespan 里的数据库引导逻辑
    client = TestClient(app)
    resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["version"]
