"""在旧 API 容器内持有数据库屏障，直到宿主完成停机或放弃本次升级。"""

import signal
import sys


def hold_barrier(engine, release, output):
    """锁住主回合与专家运行表，输出计数后保持事务；不修改任何业务状态。"""
    from sqlalchemy import text

    with engine.connect() as connection, connection.begin():
        connection.execute(text("SET LOCAL lock_timeout = '5s'"))
        connection.execute(text("SET LOCAL statement_timeout = '10s'"))
        connection.execute(text("SET LOCAL idle_in_transaction_session_timeout = '90s'"))
        # 普通查询仍可读；新回合写入与 SELECT FOR UPDATE 均等待屏障释放。
        connection.execute(text("LOCK TABLE agent_runtime_state, agent_runs IN EXCLUSIVE MODE"))
        active = connection.execute(text(
            "SELECT (SELECT count(*) FROM agent_runtime_state WHERE active_turn IS NOT NULL)"
            " + (SELECT count(*) FROM agent_runs WHERE status IN ('queued', 'running'))"
        )).scalar_one()
        output.write(f"{active}\n")
        output.flush()
        release.readline()


if __name__ == "__main__":
    # 父部署进程失联时不永久持锁；总期限大于宿主读计数及停止容器的时间上限。
    signal.alarm(60)
    try:
        from app.db import engine

        hold_barrier(engine, sys.stdin, sys.stdout)
    except Exception:
        # 查询/连接失败只发固定提示，数据库 URL 和异常原文不得进入 Actions 日志。
        print("错误：旧 API 数据库屏障不可用，未允许停止服务", file=sys.stderr)
        sys.exit(1)
