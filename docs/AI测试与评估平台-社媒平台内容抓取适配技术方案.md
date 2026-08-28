# AI 测试与评估平台 — 抖音快手B站小红书内容抓取适配技术方案 (V1.0)

> **版本**：V1.0  
> **审查日期**：2026-08-28  
> **状态**：方案制定中（待评审后按 M1→M4 分期实施）  
> **关联契约**：API.md V1.53（`web_fetch` 三级降级链 / `web_search` Firecrawl 检索）；本文不改变既有契约，涉及新字段的部分均标注「需先回写 API.md」

---

## 1. 需求背景与目标

平台 Agent 在评测数据准备、竞品内容分析与素材调研场景中，需要抓取国内主流社媒平台的公开内容。当前 `web_fetch` 的通用网页链路（Firecrawl → trafilatura → `_TextExtractor`）对以下四类页面基本失效：

| 平台 | 内容形态 | 通用链路失效原因 |
| :--- | :--- | :--- |
| 哔哩哔哩（bilibili.com） | 视频（BV/AV）、专栏（read/cv）、评论、字幕 | 视频页正文为 JS 渲染，核心信息在内嵌 JSON 中 |
| 抖音（douyin.com） | 短视频、图集、评论 | `RENDER_DATA` 内嵌 JSON + 签名（`X-Bogus`/`a_bogus`）+ 强风控 |
| 快手（kuaishou.com） | 短视频、评论 | 页面内嵌 `__APOLLO_STATE__` + API 封闭 |
| 小红书（xiaohongshu.com） | 图文笔记、视频、评论 | 登录墙 + `x-s`/`x-s-common` 请求签名 + IP 风控 |

**目标**：

1. `web_fetch` 能抓取四平台**单条内容页**（视频/笔记详情），输出结构化 Markdown（标题、作者、正文描述、统计数据、标签）；
2. `web_search` 逐步支持**平台内关键词检索**（返回与现有搜索投影一致的 `title/url/description` 列表）；
3. 全程兼容既有安全边界（SSRF 校验、受控字节窗口、60,000 字符正文预算、卡片预览契约）与降级语义（失效诚实报 `UPSTREAM`，禁止静默脏数据）；
4. 借助 GitHub 开源项目二次开发，不自研签名逆向（除 M3 小红书按评审结论决策）。

**非目标**：

- 不做视频文件下载入库（无水印直链不下发到模型与浏览器，版权敏感）；
- 不做评论全量抓取与舆情分析（首期仅摘要级信息，范围扩充需先改 PRD）；
- 不做账号矩阵、批量采集等平台对抗性行为（仅公开数据、单次限频访问）。

---

## 2. 现状分析（v0a15000 时点）

### 2.1 web_fetch 现有链路（`backend/api/app/harness/execution/dispatch.py`）

```text
web_fetch(url, format)
  ├─ _validate_public_url        # SSRF 校验（入口 + 每次重定向，BLOCKED_NETWORKS fail-closed）
  ├─ _fetch_via_firecrawl        # 已配置 firecrawl_api_key 时优先（Markdown）
  └─ _fetch_direct               # 受控直抓：1MB 字节窗口 → 正文提取三级链
       ├─ _extract_article_with_trafilatura   # favor_recall，Markdown/txt
       └─ _TextExtractor         # 朴素全文本展开（最终降级）
```

- 正文预算 `WEB_FETCH_MAX_CHARS = 60_000`，结果投影 `web.{url,title,format,preview,preview_truncated,preview_limit_chars}`；
- `format` 诚实语义：只有提取器真实产出 Markdown 才声明 `format=markdown`。

### 2.2 web_search 现有链路

`web_search` 完全依赖 Firecrawl `search` 端点。Firecrawl 对国内社媒平台收录极差，且上述四平台的站内检索需登录态/签名，**现状对四平台检索能力为零**。

### 2.3 可复用的架构先例

| 先例 | 位置 | 对本方案的启示 |
| :--- | :--- | :--- |
| Firecrawl 服务端配置（Key 不入日志/事件） | `config.py` + `_request_firecrawl` | sidecar 服务地址同样走服务端配置、独立受控请求函数 |
| lightrag / stress sidecar 容器 | `docker-compose.yml` | 新增 `media-crawler` 服务沿用同一编排与健康检查模式 |
| 工具注册表（ToolDef + permission + recovery_policy） | `registry.py` | 平台检索参数扩展在注册表描述与 Schema 中同步 |
| 脱敏日志（`redact_for_log`，只记类型/错误码） | `dispatch.py` + §5.2.1 | cookie/签名头为敏感凭据，全程不落日志与 WS 事件 |

---

## 3. 开源项目调研结论（2026-08-28）

### 3.1 多平台项目

| 项目 | 覆盖 | 技术形态 | 许可 | 结论 |
| :--- | :--- | :--- | :--- | :--- |
| [NanmiCoder/MediaCrawler](https://github.com/NanmiCoder/MediaCrawler)（63.8k★） | 小红书/抖音/快手/B站/微博/知乎/贴吧 | Playwright + 登录态，关键词搜索 + 详情 + 评论，无需 JS 逆向 | **仅供学习研究，禁止商用** | ⚠️ 能力最全但**许可与本平台商用性质冲突**，不直接引入代码；借鉴其站点解析思路与数据模型 |
| [Evil0ctal/Douyin_TikTok_Download_API](https://github.com/Evil0ctal/Douyin_TikTok_Download_API) | 抖音/TikTok/**快手**/B站 | FastAPI 自托管 REST 服务，官方 Docker 镜像，异步 httpx | 宽松（附版权声明，需保留署名） | ✅ 作为 M2 sidecar 首选：`media-crawler` 容器 + REST 调用 |

### 3.2 单平台项目

| 平台 | 项目 | 结论 |
| :--- | :--- | :--- |
| B站 | [SocialSisterYi/bilibili-API-collect](https://github.com/SocialSisterYi/bilibili-API-collect)、[bilibili-api-python](https://pypi.org/project/bilibili-api-python/) | API 文档最全；视频详情公开接口免登录；部分接口需 WBI 签名与 `buvid3` cookie。M1 依据其文档**自研轻量适配器**，不引入整库 |
| 小红书 | [JoeanAmier/XHS-Downloader](https://github.com/JoeanAmier/XHS-Downloader)（12.5k★，活跃）、[ReaJason/xhs](https://github.com/ReaJason/xhs)、[Cloxl/xhshow](https://github.com/Cloxl/xhshow) | xhs 浏览器签名 2025 年后频繁失效；xhshow 纯算签名较新待观察。M3 方向：自托管 XHS-Downloader/签名服务 + 管理员供给登录 cookie，**需合规评审后实施** |

### 3.3 许可合规结论

MediaCrawler 的「禁止商用」条款决定了本平台**不能以其代码为基础二次开发**，只允许：①参考其公开文档理解站点结构；②对 Evill0ctal（Docker 自托管、边界清晰）这类可隔离部署的服务做进程外调用。小红书方案涉及登录态与签名，必须在实施前完成一次合规评审（§7.4）。

---

## 4. 总体架构

三层递进，上层失效自动降级到下层；对模型与前端完全无感知（工具名、参数、投影字段不变）：

```text
                     web_fetch(url, format)
                            │
                    _validate_public_url（SSRF，不变）
                            │
              ┌─── ①站点适配器层（in-process，新） ───┐
              │  sites/registry：按 hostname 路由     │
              │  bilibili / douyin / kuaishou / xhs   │
              │  解析内嵌 JSON → 结构化 Markdown       │
              └──────────────┬───────────────────────┘
                             │ 失败/未命中
              ┌─── ②sidecar 服务层（M2 新增容器）───┐
              │  media-crawler（Evil0ctal API）      │
              │  深度数据：评论/合集/搜索热词          │
              └──────────────┬───────────────────────┘
                             │ 失败/未配置
              ┌─── 既有通用层（不变） ───────────────┐
              │  Firecrawl → trafilatura → _Text     │
              └─────────────────────────────────────┘

                     web_search(query, platform?)
                            │
              platform 缺省 → Firecrawl（现状不变）
              platform 命中 → ③平台检索适配器（M4，B站公开接口起步，
                              抖音/快手/小红书经 sidecar/登录态）
```

**分层原则**：

1. 站点适配器**只解析已抓取的 HTML 字符串**，不发起任何新网络请求——SSRF 攻击面零增加；
2. sidecar 是容器内网固定配置地址，走与 `_request_firecrawl` 同级的**独立受控请求函数**（固定服务端配置、模型不可传参），属 SSRF 内网禁令的受控豁免，豁免理由与边界写入 API.md；
3. 任何一层失效降级到下一层，全部失败报 `UPSTREAM`，`truncated`/错误码诚实上抛。

---

## 5. 详细设计

### 5.1 站点适配器框架（M1 基建）

新增包 `backend/api/app/harness/execution/sites/`：

```text
sites/
├── __init__.py      # detect_site(url) -> SiteAdapter | None（对外唯一入口）
├── base.py          # SiteAdapter 协议与 SiteContent 数据类
├── bilibili.py      # M1
├── douyin.py        # M2
├── kuaishou.py      # M2
└── xiaohongshu.py   # M3
```

**协议契约**（`base.py`）：

```python
@dataclass(frozen=True, slots=True)
class SiteContent:
    """站点适配器提取结果：统一映射为 WebFetchResult 的 Markdown 正文。"""
    title: str                  # ≤300 字符，与 WebFetchResult.title 对齐
    markdown: str               # 结构化正文（未截断，由调用方裁剪预算）
    source_meta: dict[str, str] # 平台/类型/作者等脱敏元数据（可并入正文）

class SiteAdapter(Protocol):
    """站点适配器：match 判定 URL 归属；extract 仅解析 HTML 字符串。"""
    def match(self, url: str) -> bool: ...
    def extract(self, html: str, url: str) -> SiteContent | None: ...  # 失败返回 None
```

**路由接入点**（`dispatch.py::_fetch_direct`，仅新增一个分支）：

```python
if content_type == "text/html":
    adapter = detect_site(url)
    if adapter is not None:
        site = adapter.extract(decoded, url)     # 只解析字符串，零新增请求
        if site is not None:
            return WebFetchResult(url=final_url, title=site.title,
                                  content=site.markdown[:WEB_FETCH_MAX_CHARS],
                                  format=format, truncated=...)   # format=markdown 诚实声明
    # 未命中/失败 → 既有 trafilatura → _TextExtractor 降级链（不变）
```

设计约束：

1. **特性开关**：`config.py` 新增 `site_adapters_enabled: bool = True`，出问题时可一键回退通用链路；
2. **特征集中**：各适配器的 JSON 路径/正则特征集中在各自模块头部常量区，平台改版时可独立热修；
3. **失败静默降级**：适配器内部 `except Exception` 只 `agent_trace("site适配器失败 type=...")` 后返回 `None`，不中断抓取（§5.2.1 冻结写法）。

### 5.2 B站适配器（M1，无登录、无签名）

**数据源优先级**：

1. 页面内嵌 `window.__INITIAL_STATE__` JSON（随 1MB 字节窗口必然返回）：`videoData.{title,desc,owner.name,pubdate,stat.{view,danmaku,reply,favorite,coin,share,like}}`、`tags[]`；
2. 公开 REST 兜底：`GET api.bilibili.com/x/web-interface/view?bvid=<BV>`（免登录；带常规 UA + `Referer: https://www.bilibili.com`；进程内令牌桶限频 ≥2s/次）；
3. 专栏页（`read/cv`）：SSR 正文文本，直接命中既有 trafilatura 即可，**适配器不拦截**。

**URL 匹配**：`www.bilibili.com/video/BV*`、`b23.tv` 短链（跟随既有重定向后落到最终 URL 再判定）。

**输出 Markdown 模板**（示例）：

```markdown
# 【标题】

- 作者：xxx ｜ 发布时间：2026-08-01 ｜ 类型：视频
- 数据：播放 12.3w ｜ 弹幕 456 ｜ 评论 789 ｜ 点赞 1.2w ｜ 投币 300

## 简介

（desc 全文）

## 标签

`标签1` `标签2`
```

### 5.3 抖音 / 快手适配器（M2）

| 项 | 抖音 | 快手 |
| :--- | :--- | :--- |
| 单条页 | `www.douyin.com/video/{id}`、`v.douyin.com` 短链 | `www.kuaishou.com/short-video/{id}` |
| 进程内解析 | 内嵌 `RENDER_DATA`（URL-encoded JSON）：`desc`、`author.nickname`、`statistics.*`；解析失败即降级 | 内嵌 `__APOLLO_STATE__` 同理；**该路径脆弱，仅作快路径** |
| sidecar 深路径 | `GET {media_crawler_api_url}/hybrid_parse?url=...`（Evil0ctal 官方端点，返回统一 JSON：`data.title/desc/author/statistics`） | 同一 sidecar（官方声明支持快手） |

**sidecar 接入**（参照 stress 容器模式）：

- `docker-compose.yml` 新增服务 `media-crawler`：镜像 `evil0ctal/douyin_tiktok_download_api`，仅加入内部网络、**不映射宿主机端口**，`healthcheck` 探活 `/docs`；
- `config.py` 新增 `media_crawler_api_url: str = ""`（空 = 未启用 sidecar，纯进程内路径）；
- `dispatch.py` 新增 `_request_media_crawler(path, params)`：独立受控函数（固定配置地址 + `ProxyHandler({})` + 受控字节窗口），与 `_request_firecrawl` 同级；**不经过 `_reject_internal_target`**（内网豁免，理由见 §4 分层原则 2，需在 API.md V1.54 写明）。

### 5.4 小红书适配器（M3，依赖合规评审与凭据供给）

1. **凭据管理**：`config.py` 新增 `xiaohongshu_cookie: str = ""`，由管理员经 `.env` 注入**自有账号**的登录 cookie；存储与日志全链路复用 API Key 纪律（不回显、不进 `agent_trace`、不进 WS 事件，`redact_for_log` 覆盖）；
2. **签名方案**：优先自托管 [XHS-Downloader](https://github.com/JoeanAmier/XHS-Downloader)（活跃维护）以服务形态隔离；[xhshow](https://github.com/Cloxl/xhshow) 纯算签名作为轻量备选（实施前再次验证可用性）；不采用已频繁失效的浏览器签名服务；
3. **降级语义**：cookie 过期/签名失效统一报 `UPSTREAM`（`repair_hint` 提示"小红书登录态失效，请管理员更新配置"），禁止静默返回验证页脏文本；
4. **前置条件**：§7.4 合规评审通过。

### 5.5 web_search 平台内检索（M4，契约变更，需先回写 API.md）

**契约草案（API.md V1.54）**：`web_search` 输入 Schema 新增可选参数（`additionalProperties=false` 同步注册表）：

```json
"platform": {
  "type": "string",
  "enum": ["bilibili", "douyin", "kuaishou", "xiaohongshu"],
  "description": "指定站内检索；缺省走通用网络搜索"
}
```

**实现路径**：

| platform | 检索通道 | 依赖 |
| :--- | :--- | :--- |
| bilibili | 公开搜索接口（需 `buvid3` 匿名 cookie，进程内注入） | 无新增服务 |
| douyin / kuaishou | sidecar 检索端点 | M2 服务 |
| xiaohongshu | 登录态 + 签名服务 | M3 评审 |

**结果投影**：复用现有 `search.{query, results[]}` 形状（`title/url/description`，各字段截断长度不变），模型与 ToolCard 零改动；`platform` 未配置通道可用时按 `VALIDATION`（能力未启用 400）处理，与 §5.2 错误码纪律一致。

---

## 6. 安全、合规与可靠性

### 6.1 安全边界（不变项 + 受控豁免项）

| 项 | 设计 |
| :--- | :--- |
| SSRF | 站点适配器零新增请求面；sidecar 调用为固定配置地址的受控豁免（模型不可传 host/URL）；`_validate_public_url` 对用户 URL 与重定向的校验不变 |
| 敏感凭据 | cookie/签名头按 API Key 纪律：只写不回显，`redact_for_log` 覆盖，禁止进日志/WS 事件/ToolCard |
| 输出边界 | 无水印视频直链**不输出**（`source_meta` 中剔除）；仅元数据与文本进模型上下文 |
| 限频 | 进程内令牌桶：每适配器 ≥2s/次；sidecar 并发 ≤2；触发限频按 `UPSTREAM` 提示稍后重试 |

### 6.2 合规红线

1. 仅抓取**公开可见**内容，不破解付费/隐私数据；小红书使用管理员自有账号 cookie，仅限内部评测调研用途；
2. 单次限频访问、无批量采集，尊重目标平台负载；
3. MediaCrawler 代码不引入（商用许可冲突），仅文档级参考；
4. 抓取文本注入会话上下文即用即弃，不落库形成二次分发数据集（若未来需要，走 PRD 扩充流程）。

### 6.3 可靠性与可观测性

- 每层独立超时：进程内适配器 0 额外成本；sidecar 调用 `timeout_s=20` 与 `web_fetch` 对齐；
- 降级链每级失败均 `logger.info("... type=%s")`（只记类型与错误码，§5.2.1）；
- 特征失效快修：适配器 JSON 路径常量集中管理，配合 §5.1 特性开关可秒级回退；
- Docker `healthcheck` + 部署 SOP 补充 `media-crawler` 容器的排查命令（复用 §4.2 模板）。

---

## 7. 测试策略

| 层 | 用例 | 手段 |
| :--- | :--- | :--- |
| 适配器单元 | 真实页面裁剪脱敏的 fixture HTML（每平台 ≥2 例：标准页/改版容错页）→ 断言 Markdown 结构字段 | pytest 固定样例，不触网 |
| 路由与降级 | 命中适配器成功 / 适配器返回 None 降级 trafilatura / 适配器抛异常降级 / 特性开关关闭 | `monkeypatch` 桩 |
| sidecar 合同 | `_request_media_crawler` 的成功/超时/5xx/无效 JSON → 归一 `UPSTREAM`/`TIMEOUT` | urlopen 桩（沿用既有 `_FakeOpener` 模式） |
| SSRF 回归 | 适配器路径不得绕过 `_validate_public_url`；内网 URL 仍被拒 | 复用 `test_web_fetch_rejects_internal_targets` |
| web_search 契约 | `platform` 参数 Schema 校验、未配置通道报 `VALIDATION`、结果投影形状 | 注册表 + 分派层测试 |

全部用例离线可跑（HTML fixture 与桩），不依赖真实平台，CI 稳定。

---

## 8. 分期实施计划

| 里程碑 | 内容 | 预估 | 前置条件 |
| :--- | :--- | :--- | :--- |
| **M1** | 站点适配器框架 + B站适配器 + 测试 + API.md V1.54 备注 | 1 天 | 无 |
| **M2** | 抖音/快手适配器 + `media-crawler` sidecar（docker-compose/config/受控请求函数） | 2–3 天 | 服务器可拉取 Docker 镜像 |
| **M3** | 小红书适配器（cookie 管理 + 签名服务） | 2–3 天 | **合规评审通过 + 管理员供给 cookie** |
| **M4** | `web_search` `platform` 参数 + B站/抖音/快手站内检索 | 2–3 天 | API.md 契约回写；M2 sidecar 在线 |

每里程碑独立分支（`feat/site-adapter-bilibili` 等）、独立 PR、独立回滚点。

---

## 9. 风险与开放问题

| # | 风险/问题 | 等级 | 应对 |
| :--- | :--- | :--- | :--- |
| 1 | 平台风控升级导致适配器特征失效（历史：小红书 x-s 一年内多次变更） | 高 | 特征集中 + 特性开关 + 诚实 `UPSTREAM`；把四平台适配可用性纳入 M8 运维看板 |
| 2 | MediaCrawler 商用许可冲突 | 高 | 不引入代码；仅文档参考；如必须用其能力需先取得作者授权或替换实现 |
| 3 | 登录 cookie 属个人信息凭据，泄露即事故 | 高 | Fernet/.env 注入 + 全链路脱敏 + 不落库；cookie 仅管理员可配 |
| 4 | 抓取行为与平台 ToS 冲突的合规争议 | 中 | 仅公开数据、限频、内部用途；M3 前置合规评审留痕 |
| 5 | sidecar 镜像体积/资源（含 Playwright 的方案约 1GB） | 中 | M2 选 Evil0ctal 纯 httpx 镜像（轻量）；Playwright 方案仅在 M3 评审时评估 |
| 6 | 视频内容是否需要 ASR 转写进上下文 | 开放 | 平台已有 `audio.speech_recognition`；如需要作为独立里程碑再立项（涉 PRD） |
| 7 | Firecrawl 与适配器的重复抓取成本 | 低 | 命中站点适配器时跳过 Firecrawl 路径（平台域名不走外部配额） |

---

## 10. 修改代码文件与作用清单（V1.0 预期实施清单）

> 本节为方案实施后的预期变更清单，随各里程碑合入在本文档追加实际落地记录。

| 文件 | 作用 |
| :--- | :--- |
| `docs/AI测试与评估平台-社媒平台内容抓取适配技术方案.md` | 本方案（V1.0） |
| `docs/AI测试与评估平台-API.md` | V1.54：`web_search.platform` 参数、sidecar 内网豁免说明、适配器降级链表述 |
| `backend/api/app/harness/execution/sites/`（新包） | `base.py` 协议与 `SiteContent`；`registry.py` hostname 路由；四平台适配器 |
| `backend/api/app/harness/execution/dispatch.py` | `_fetch_direct` 接入适配器分支；`_request_media_crawler` 受控 sidecar 请求 |
| `backend/api/app/config.py` | `site_adapters_enabled` / `media_crawler_api_url` / `xiaohongshu_cookie` 配置 |
| `backend/api/app/harness/execution/registry.py` | `web_search` Schema 增补 `platform`（M4） |
| `docker-compose.yml` / `deploy/deploy.sh` | `media-crawler` 服务编排与健康检查（M2） |
| `backend/api/tests/test_harness_execution.py`、`tests/test_site_adapters.py`（新） | §7 测试策略全部用例 |
