"""依赖注入根。

阶段 0 只提供包入口，禁止在 import 时装配 Redis、ExecutionFacade 或会话表。
请求级 TraceContext 禁止缓存在本模块；后续阶段再于此处装配无状态服务。
"""
