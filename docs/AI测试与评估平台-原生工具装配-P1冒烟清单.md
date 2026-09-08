# Agent 原生工具装配 — P1 冒烟清单（DoD②）

> 依据：《Agent 原生工具装配方案》V0.2.1 §5 P1 验收②——deepseek（Anthropic
> 兼容）端点 tools 支持度为最大外部不确定项，合入部署后执行本清单并回传。
> 状态占位：待执行 | 日期：2026-09-08 | 对应 PR：#231 + 冒烟补丁 PR

## 0. 前置

| 项 | 说明 |
| :--- | :--- |
| 部署版本 | main 含 P1（`51fa3c3`）+ 冒烟补丁 PR（compose env 通道 + 熔断日志） |
| 执行位置 | 服务器（api 容器可达模型端点；探针脚本仅需标准库） |
| 凭据 | 从 api 容器 `PROFILE_ENV_FILE`（默认 `/run/config/.env`）取测试档的 base_url/api_key/model；**只经环境变量传入探针，不回显、不落日志/产物** |

### 0.1 开闸（全链路用例 L2 需要；探针 L1 不需要动 api）

服务器项目目录 `.env` 追加（首次开闸用**专用测试档 ID**，勿用生产档）：

```bash
AGENT_NATIVE_TOOLS_ENABLED=true
AGENT_NATIVE_TOOLS_PROFILE_IDS=<测试档id>      # 多个逗号分隔；严禁 *
```

然后重建 api 容器（仅环境变更）：`docker compose up -d api`。
关闸（冒烟完还原）：删两行后再次 `docker compose up -d api`。

## 1. L1 探针：端点 tools 支持度（四用例，直连模型端点）

```bash
cd tools/endpoint-tools-probe
SMOKE_BASE_URL=<测试档 base_url> SMOKE_API_KEY=<key> SMOKE_MODEL=<model> \
  python smoke_p1_native_tools.py --protocol anthropic_messages    # 生产协议档先行
python smoke_p1_native_tools.py --protocol openai_chat             # 其余两协议对照
python smoke_p1_native_tools.py --protocol openai_responses
```

判据（末尾 `SMOKE_RESULT <json>` 回传；退出码非 0 = 有 fail）：

| 用例 | 判定 | 说明 |
| :--- | :--- | :--- |
| `A-tools-下发` | pass = HTTP 200 | 端点接受 tools 字段（核心 DoD 判据）；fail = 400 等 → **P2 需熔断/降级前置** |
| `B-tool_use-观察` | observe | 模型是否产出原生 tool_use（真实行为观测，文本答复亦合法） |
| `C-回填配对` | pass = 第二轮 HTTP 200 | tool_use → tool_result 回填后不 400（P2 原生循环外部前提）；skip 属正常（B 无 tool_use） |
| `D-legacy对照` | pass = HTTP 200 | 无 tools 基线可用性 |

## 2. L2 全链路：开闸档 agent 回合（tools 下发 → tool_use → P1 回退）

1. 完成 0.1 开闸（测试档）；
2. 用 `tools/harness-ws-probe` live 模式发一条**执行类意图**（触发 agent 档）：
   ```bash
   cd tools/harness-ws-probe
   python -m harness_ws_probe --base http://127.0.0.1:8000 --suite chat \
     --prompt "读取会话工作区里的 smoke.txt 并总结内容" --dump
   ```
3. 并行采集 api 容器日志（另一终端）：
   ```bash
   docker compose logs api --since 5m | grep -E "native_tools_defer|native_tools_breaker"
   ```

判据：
- 回合正常收尾（`response.completed`，无 `turn_failed`/连续 VALIDATION）；
- 日志出现 `native_tools_defer profile=<测试档id>` **一行**（tools 确已下发、
  tool_use 解析成功、P1 精确回退生效——重发未造成二次 defer 属正确）；
- 若**无 defer 日志**但回合正常：模型本轮未输出 tool_use（合法），改发多条
  不同执行意图后仍无 → 结合 L1-B 判断 tools 是否实际到达模型（排查 env 注入）。

## 3. L3 熔断观测（可选压测，需改档配置，做完还原）

开闸状态下临时把测试档 base_url 指向不可达端口（如 `http://127.0.0.1:1`），
连发执行类请求触发 ≥`CIRCUIT_FAILURE_THRESHOLD`（默认 5）次带 tools 失败：

- 日志出现 `native_tools_breaker_open profile=<测试档id>` → 档级摘除生效；
- 摘除后同档请求不再带 tools（无 defer、回合走文本协议正常）；
- 还原 base_url，冷却（`CIRCUIT_COOLDOWN_S` 默认 30s）后日志出现
  `native_tools_breaker_halfopen` → 自动恢复探测。

单测已覆盖熔断逻辑（test_native_tools_p1.py），本用例只验证**配置接线**。

## 4. L4 关闸回归（默认生产形态零变化）

0.1 还原后（`AGENT_NATIVE_TOOLS_ENABLED` 缺省/空）：

- 生产档 agent 回合正常；日志**无** `native_tools_defer`/`native_tools_breaker_*`
  （tools 零下发，与合入前逐字节一致——P1 验收⑤的线上复核）。

## 5. 回传模板

```json
{
  "date": "2026-09-08", "deploy_sha": "<main sha>",
  "smoke_profile_id": "<测试档id>",
  "L1": {"anthropic_messages": "<SMOKE_RESULT json>", "openai_chat": "...", "openai_responses": "..."},
  "L2": {"turn_ok": true, "defer_log": "<一行原文>", "defer_count": 1},
  "L3": {"breaker_open_log": "...", "breaker_halfopen_log": "...", "done": true},
  "L4": {"legacy_turn_ok": true, "stray_logs": []},
  "conclusion": "P2 前置风险：端点 tools 支持度 <通过/不通过>，原因：..."
}
```

## 6. 结论去向

- L1-A/C 全 pass：P2（原生循环 + tool 消息回填）外部前提成立，可正常开发；
- L1-A fail（端点拒 tools）或 C fail（回填 400）：**阻塞 P2 原生循环放行**，
  登记熔断/降级前置（档级自动摘除已具备），P2 排期按适配层兼容改造重估。
