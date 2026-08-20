"""api 与 worker 共享的数据库模型包（单一事实源）。

历史上 api 与 worker 各持一份手写模型副本，曾因 worker 副本漂移
（Task.created_by 悬空外键）在 flush 时抛 NoReferencedTableError。
现在两侧 Dockerfile 均将本包 COPY 进镜像，模型只此一份；
表结构演进流程：改本文件 -> alembic autogenerate -> 同 commit 部署。
"""
