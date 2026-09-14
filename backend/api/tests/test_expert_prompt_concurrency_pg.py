"""显式独立测试库验证首次并发写入、行锁与专家映射防丢失，不读取业务凭据。"""

import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app import expert_prompt_settings as prompts
from app.agent.experts import get_expert
from app.errors import AppError, ErrorCode
from app.models import Base, Setting, User


@pytest.fixture
def pg_prompt_factory():
    """只在显式测试库创建随机 schema；生命周期内仅删除本例创建的对象。"""
    url = os.getenv("LOOP_TOOLS_TEST_DATABASE_URL")
    if not url:
        pytest.skip("需要显式 LOOP_TOOLS_TEST_DATABASE_URL 验证 PostgreSQL 行锁")
    schema = "expert_prompts_" + uuid4().hex
    control = create_engine(url)
    with control.begin() as db:
        db.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(url, connect_args={"options": f"-csearch_path={schema} -clock_timeout=5000 -cstatement_timeout=10000"})
    factory = sessionmaker(engine, autoflush=False)
    try:
        Base.metadata.create_all(engine, tables=[User.__table__, Setting.__table__])
        with factory.begin() as db:
            db.add(User(id="test-user", username="prompt-concurrency", password_hash="not-a-login"))
        yield factory
    finally:
        engine.dispose()
        with control.begin() as db:
            db.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        control.dispose()


@pytest.mark.parametrize("existing", [False, True])
@pytest.mark.parametrize("same_expert", [False, True])
def test_concurrent_expert_updates(pg_prompt_factory, monkeypatch, existing, same_expert):
    """同专家同修订只能一方成功；不同专家更新必须保留双方内容，包括首次插入。"""
    expert = get_expert("testcase-agent")
    alternate = replace(expert, expert_id="second-test-expert")
    monkeypatch.setattr(prompts, "get_expert", lambda id: alternate if id == alternate.expert_id else get_expert(id))
    if existing:
        with pg_prompt_factory.begin() as db:
            db.add(Setting(key=prompts.EXPERT_PROMPT_OVERRIDES_KEY, value={}))
    barrier = Barrier(2)

    def write(id, content):
        """两个独立会话先持有相同旧快照，再同时提交以覆盖真实竞态。"""
        with pg_prompt_factory() as db:
            cached_row = db.get(Setting, prompts.EXPERT_PROMPT_OVERRIDES_KEY)
            before = prompts.read_expert_prompt_document(db, id)
            barrier.wait(timeout=10)
            try:
                result = prompts.update_expert_prompt_document(db, id, content, before.revision, updated_by="test-user")
                db.commit()
                return result
            except AppError as exc:
                db.rollback()
                assert exc.code == ErrorCode.CONCURRENCY
                return None
            finally:
                # 显式保留 ORM 旧行至事务结束，验证 populate_existing 真正刷新锁后状态。
                del cached_row

    ids = [expert.expert_id, expert.expert_id if same_expert else alternate.expert_id]
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(write, id, f"团队约定 {index}") for index, id in enumerate(ids)]
        results = [future.result(timeout=20) for future in futures]
    successful = [result for result in results if result is not None]
    assert len(successful) == (1 if same_expert else 2)
    with pg_prompt_factory() as db:
        values = db.get(Setting, prompts.EXPERT_PROMPT_OVERRIDES_KEY).value
        assert values == {result.expert.expert_id: result.content for result in successful}
