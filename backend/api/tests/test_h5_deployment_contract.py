from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def test_compose_injects_h5_settings_and_isolates_runner_network() -> None:
    """检查 H5 开关注入及 runner 网络隔离契约。"""
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    api_block, runner_block = compose.split("\n  runner:", maxsplit=1)
    runner_block = runner_block.split("\n  worker:", maxsplit=1)[0]

    assert "AGENT_CHECKPOINTER: ${AGENT_CHECKPOINTER:-memory}" in api_block
    assert "AGENT_HITL_STRICT_PG: ${AGENT_HITL_STRICT_PG:-false}" in api_block
    assert "AGENT_INSTANCE_ID: ${AGENT_INSTANCE_ID:-}" in api_block
    assert "HYBRID_ENGINE_ENABLED: ${HYBRID_ENGINE_ENABLED:-false}" in api_block
    assert "AGENT_DRILL_SANDBOX_ENABLED: ${AGENT_DRILL_SANDBOX_ENABLED:-false}" in api_block
    assert "- default\n      - sandbox_net" in api_block
    assert "networks:\n      - sandbox_net" in runner_block
    assert "networks:\n      - default" not in runner_block
    assert "sandbox_net:\n    internal: true" in compose


def test_nginx_routes_websocket_by_session_id() -> None:
    """检查 WS 粘性路由和 Docker DNS 动态解析契约。"""
    nginx = (ROOT / "frontend/nginx.conf").read_text(encoding="utf-8")

    assert "map $arg_session_id $session_route_key" in nginx
    assert "hash $session_route_key consistent;" in nginx
    assert "server api:8000 resolve;" in nginx
    assert "proxy_pass http://api_ws;" in nginx
    assert "proxy_pass http://api_http;" in nginx
    assert "resolver 127.0.0.11 valid=10s ipv6=off;" in nginx
    assert "FROM nginx:1.27.3-alpine" in (ROOT / "frontend/Dockerfile").read_text(
        encoding="utf-8"
    )


def test_h5_multi_api_override_removes_host_port_collision() -> None:
    """检查多副本覆盖文件不会让 api 副本争抢宿主机端口。"""
    override = (ROOT / "deploy/docker-compose-h5-multi-api.yml").read_text(
        encoding="utf-8"
    )

    assert "services:" in override
    assert "  api:" in override
    assert "    ports: !reset []" in override
