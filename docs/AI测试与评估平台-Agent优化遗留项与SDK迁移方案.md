# AI 测试与评估平台 — Agent 优化遗留项与 SDK 迁移方案

> 状态:方案待实施 | 创建:2026-08-27 | 前置:eeffd77 + 3264a00 两批优化已上线
>
> 背景:2026-08-26~27 完成 Agent 读文件链路专项优化(read 预算/流式适配器 bug/
> 元数据头/缓存回放/native 默认化/turn_stats 观测),本文档记录**尚未完成**的
> 后续工作,核心是 LLM 调用层迁移官方 SDK。

---

## 一、遗留项总览(按优先级)

| # | 事项 | 级别 | 预估 |
|---|---|---|---|
| 1 | LLM 调用迁移官方 SDK(本文档主体) | P2 | 天级,分两期 |
| 2 | turn_stats 前端可视化 | P3 | 半天(web 端) |
| 3 | GitHub Actions 首推未触发原因排查 | 运维 | 半小时 |
| 4 | 本地兜底镜像清理 | 运维 | 分钟 |
| 5 | 超长上下文精度衰减的缓解策略 | 可选 | — |

---

## 二、核心项:LLM 调用迁移官方 SDK

### 2.1 现状与动机

`backend/api/app/adapters.py` 手搓实现了三协议(openai_chat / openai_responses /
anthropic_messages)的 HTTP 层:`urllib.request.urlopen` + 手写 SSE 解析
(`_iter_stream_lines` / `_arm_read_timeout`)。历史上已因此付出代价:

- **2026-08-26 流式 bug**:「2s 切片读超时 → continue 重试同一 socket」在 CPython
  下必然失败(socket 一次超时即进入 timed-out 状态,后续 read 直接抛
  `OSError('cannot read from timed out object')`),任何首帧延迟 >2s 的流式
  响应(大上下文 prefill 静默)都被误报「上游连接中断」。已修(3b77a8a),
  但手搓 HTTP 的结构性风险仍在。
- 无重试、无连接池、无 HTTP/2、超时语义靠人肉维护;每个新网关的兼容怪癖
  都要在手写解析器里打补丁。

参照实现(cweaty/Agent)使用官方 SDK(AsyncOpenAI / AsyncAnthropic,底层
httpx),同规模请求零调优即稳定。

### 2.2 目标

1. `call_protocol` / `stream_protocol` 的**对外契约不变**:
   `AdapterStreamEvent`、`AdapterToolCall`、错误归一(`AppError` + ErrorCode
   语义:TIMEOUT / UPSTREAM / 参数错误)、`_norm_usage` 的 usage 归一结构。
2. 传输层整体替换:
   - openai_chat / openai_responses → `openai` SDK `AsyncOpenAI`
   - anthropic_messages → `anthropic` SDK `AsyncAnthropic`
   - 手写 `Request/urlopen`、`_post_json`、`_iter_stream_lines`、
     `_arm_read_timeout`、`_is_wait_timeout`、`_is_poisoned_socket` 删除。
3. 现有行为保持:超时(`timeout_s` 透传 SDK timeout)、取消
   (`should_abort` → asyncio cancel)、`_service_base_url` 后缀剥离逻辑
   (放 SDK `base_url` 参数前)。

### 2.3 分期计划

**第一期:非流式(invoke 路径)**
- `call_protocol` 三协议分支改用 SDK 的 `client.chat.completions.create` /
  `client.responses.create` / `client.messages.create`(非流式)。
- 保留 `_post_json` 为模块私有**过渡 seam**:全部调用点切换后删除。
- 测试夹具:现有大量单测 monkeypatch `adapters._post_json` 注入 payload——
  第一期把这些夹具改为 patch SDK client 工厂(`_openai_client()` /
  `_anthropic_client()` 返回 FakeClient),响应对象用 SDK 的 pydantic 模型
  或鸭子类型。

**第二期:流式(stream 路径)**
- `stream_protocol` 改用 SDK 的 stream 迭代器(`client.messages.stream` /
  `client.chat.completions.create(stream=True)`),SSE 解析、分块重组成
  SDK 完成;平台只消费事件回调(thinking_delta/text_delta/tool_calls 增量)。
- `AdapterStreamEvent` 的产出时机与语义对照现有 `_stream_anthropic` /
  `_stream_openai` 逐事件核对(含 anthropic 的 tool_use 增量拼装
  `content_block_start/input_json_delta/content_block_stop`)。
- 取消语义:SDK 流支持 async with + cancel,`should_abort` 轮询退化为
  cancel 检查点(每事件间),行为不弱于现状。

### 2.4 依赖与配置

- `backend/api/requirements.txt` 增加 `openai>=1.40`、`anthropic>=0.34`
  (纯 Python,镜像体积影响 <30MB;pip 走 USTC 源)。
- 客户端按请求构造(与现状一致,不引长生命周期连接池到 api 进程;
  若压测显示握手开销显著,再评估模块级复用 + httpx 连接池)。

### 2.5 风险与回滚

| 风险 | 缓解 |
|---|---|
| 三协议响应字段映射差异(尤其 openai_responses) | 契约层(`_norm_usage`/`_full_text`)不动,只换传输;每协议保留黄金样本单测 |
| 上游网关与 SDK 的兼容差异(如 MaaS 剥 /v1 后缀) | `_service_base_url` 逻辑前移,上线前用三协议档直连探针复测 |
| 流式事件语义漂移 | 第二期单独 PR,灰度一个协议档(DeepSeek 官方)观察 turn_stats 与 stream_metrics |

回滚:两期各自独立提交,revert 单个 PR 即回到手搓实现。

### 2.6 验收标准

1. 全量 pytest 通过(含改造后的适配器夹具);
2. 三协议档直连探针(参照 /root/endpoint_probe.py 思路,最小化为
   非流式/流式/带 tools 三形态)延迟与正确率不低于现状;
3. 生产 E2E:72KB/1000 行文件 1 次 read、耗时 ≤10s、随机内容逐字正确;
   483KB 极端文件全链路完成;
4. `adapters.py` 行数下降 ≥40%,无手写 socket 超时管理代码。

---

## 三、其他遗留项

### 3.1 turn_stats 前端可视化(P3,web 端)

- 数据已就绪:`assistant_message` 事件与 REST 历史回放 payload 均含
  `turn_stats`(`model_calls / tool_calls / tool_failures /
  prompt_tokens / completion_tokens / total_tokens`)。
- 建议:assistant 气泡 hover/展开显示「耗时 x 秒 · N 轮 · N 次工具 ·
  xxx tokens」;管理端可加会话维度的聚合视图(直接查
  `messages.turn_stats`,无需后端改动)。

### 3.2 GitHub Actions 首推未触发排查(运维)

2026-08-26 推送 eeffd77 后 Actions 无任何运行记录(ref 已确认更新),
空提交重推后恢复正常。当时怀疑 workflow 被禁用或账号 Actions 分钟数
耗尽,未最终定位。**建议**:若复发,按顺序检查 Actions 页禁用横幅 →
Settings → Billing → workflow_dispatch 手动触发;必要时给 deploy.yml
加 `workflow_run` 兜底或告警。

### 3.3 本地兜底镜像清理(运维)

服务器残留 `ai-eval-platform-api:opt-5b2271a`(本地构建兜底,已被 CI
镜像取代),确认无引用后 `docker rmi` 释放 258MB。

### 3.4 超长上下文精度衰减(可选,模型能力边界)

实测 483KB(~12 万 token)上下文下,各模型抽查行的逐字召回均出现
衰减(如把第 500 行内容抄成末行)。属模型能力边界而非链路缺陷。
若业务需要高精度,可选:
- read 元数据头已声明总行数/读完状态,模型多数场景可直接引用元数据作答;
- 评估类场景建议由出题方控制上下文体量,或拆分多轮读取+逐段核对。

---

## 四、已完成项索引(供追溯,不属本文档范围)

- eeffd77:read 600k 预算 / 流式 2s 切片修复 / 元数据头 / 重复调用缓存回放 / bash 报错
- 3264a00:协议档配置缓存 / tool_call_mode 默认 native(迁移 a9c41b7e2d10)/
  turn_stats 落库(迁移 c52e8fa1b340)
- 协议档:DeepSeek 官方档已建(anthropic_messages,native,未激活);
  MaaS 端点 legacy 长 system 挂死已在 qwen3.6-flash 与 deepseek-v4-flash
  双实锤,native 模式规避。
