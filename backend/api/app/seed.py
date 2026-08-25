"""预览种子数据：全新部署时为各工作台页面提供可浏览的演示内容。

幂等原则：每个业务域仅在其主表为空时播种，绝不覆盖用户真实数据；
播种数据均标记 created_by 为引导成员，可随时在页面上删除或改造。
"""

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from .models import (
    CaseFolder,
    CaseItem,
    CaseSet,
    Dataset,
    DatasetFolder,
    DatasetRow,
    DispatchEvent,
    DispatchWorker,
    GoldQa,
    GoldQaItem,
    KnowledgeBase,
    ProtocolProfile,
    Report,
    Setting,
    Task,
    TaskEvent,
    User,
)

logger = logging.getLogger("ai-eval")


def _hours_ago(h: float) -> datetime:
    """生成相对当前时间的过去时间戳，让预览数据的时间线更真实。"""
    return datetime.now(UTC) - timedelta(hours=h)


def _seed_profiles(db: Session, admin: User) -> list[ProtocolProfile]:
    """三协议档各一：覆盖 benchmark / agent / judge 用途，凭据留空待页面配置。"""
    if db.query(ProtocolProfile).count():
        return []
    profiles = [
        ProtocolProfile(
            name="GPT-4o（OpenAI Chat）",
            protocol="openai_chat",
            base_url="https://api.openai.com/v1",
            model="gpt-4o",
            usages=["benchmark", "agent"],
            created_by=admin.id,
        ),
        ProtocolProfile(
            name="GPT-4.1（OpenAI Responses）",
            protocol="openai_responses",
            base_url="https://api.openai.com/v1",
            model="gpt-4.1",
            usages=["benchmark"],
            created_by=admin.id,
        ),
        ProtocolProfile(
            name="Claude Sonnet（Anthropic Messages）",
            protocol="anthropic_messages",
            base_url="https://api.anthropic.com",
            model="claude-sonnet-4-20250514",
            usages=["benchmark", "judge"],
            anthropic_version="2023-06-01",
            created_by=admin.id,
        ),
    ]
    db.add_all(profiles)
    db.flush()
    # Agent 运行时默认引用第一个协议档
    if not db.query(Setting).filter(Setting.key == "agent_profile_id").first():
        db.add(Setting(key="agent_profile_id", value=profiles[0].id, updated_by=admin.id))
    logger.info("已播种 %d 个协议档预览数据", len(profiles))
    return profiles


def _seed_datasets(db: Session, admin: User) -> Dataset | None:
    """目录树 + 一个带扩展列的冒烟数据集（含 1 条待补全行演示红字检查）。"""
    if db.query(Dataset).count():
        return None
    folder = DatasetFolder(name="基准评测", sort_order=0)
    folder2 = DatasetFolder(name="RAG 回归", sort_order=1)
    db.add_all([folder, folder2])
    db.flush()
    dataset = Dataset(
        name="smoke-20 冒烟数据集",
        version=3,
        metric="contain",
        folder_id=folder.id,
        column_schema=[
            {"key": "tags", "name": "标签", "type": "string", "required": False, "sort_order": 1},
            {"key": "difficulty", "name": "难度", "type": "string", "required": False, "sort_order": 2},
        ],
        created_by=admin.id,
    )
    db.add(dataset)
    db.flush()
    rows = [
        ("如何修改登录密码？", "在右上角点击个人头像，选择「修改密码」，按提示完成短信验证后设置新密码。", "账户安全", "账户,密码", "简单"),
        ("平台支持哪些模型协议？", "支持 OpenAI Chat、OpenAI Responses 与 Anthropic Messages 三种协议档。", "协议配置", "协议", "简单"),
        ("评测任务如何取消？", "在任务中心选择进行中的任务，点击「取消」；评测类任务在当前样本结束后停止，压测任务立即停发。", "任务管理", "任务,取消", "中等"),
        ("什么是先评后压？", "质量评测成功且勾选压测后，系统自动派生共享压测子任务，用于定位 SLA 拐点。", "压测", "压测,流程", "中等"),
        ("数据集支持什么格式上传？", "支持 UTF-8 编码的 JSONL 或 CSV 文件，列需包含 question、reference，context 可选；单文件不超过 50MB、2 万行。", "数据集", "数据集,上传", "简单"),
        ("RAG 评测有哪几种检索模式？", "支持 naive、local、global、hybrid 四种检索模式的对比评测。", "RAG", "rag,检索", "中等"),
        ("如何查看压测实时曲线？", "压测报告页提供 QPS、响应时延与错误率的多轴时序曲线，数据来自 stress-series 接口。", "压测", "压测,曲线", "中等"),
        # 待补全行：reference 缺失，演示待补全计数与红字提示
        ("如何配置企业微信通知？", "", "通知设置", "通知", "简单"),
    ]
    for idx, (q, r, c, tags, difficulty) in enumerate(rows, start=1):
        db.add(
            DatasetRow(
                dataset_id=dataset.id,
                row_no=idx,
                question=q,
                reference=r,
                context=c,
                extras={"tags": tags, "difficulty": difficulty},
                pending_complete=not r.strip(),
            )
        )
    dataset.row_count = len(rows)
    dataset.pending_complete_count = 1
    logger.info("已播种数据集 %s（%d 行）", dataset.name, len(rows))
    return dataset


def _seed_cases(db: Session, admin: User) -> CaseSet | None:
    """用例目录 + 一个已确认用例集：6 大策略配比各一条，演示确认态与映射入口。"""
    if db.query(CaseSet).count():
        return None
    folder = CaseFolder(name="支付链路", sort_order=0)
    db.add(folder)
    db.flush()
    case_set = CaseSet(
        name="PRD-支付链路用例集",
        status="confirmed",
        folder_id=folder.id,
        created_by=admin.id,
    )
    db.add(case_set)
    db.flush()
    items = [
        ("正向", "HX", "收银台", "余额支付", "正常支付", "余额充足场景下完成支付", "用户已登录且账户余额 ≥ 订单金额", "1. 提交订单\n2. 选择余额支付\n3. 确认支付", "支付成功，生成支付流水号，订单状态变更为「已支付」", "功能"),
        ("边界", "BJ", "收银台", "余额支付", "金额边界", "支付金额等于账户余额", "账户余额恰好等于订单金额", "1. 提交订单\n2. 余额支付", "支付成功，账户余额扣减为 0", "功能"),
        ("反向", "YC", "收银台", "网关调用", "异常重试", "支付网关超时重试", "Mock 网关首次响应超时", "1. 发起支付\n2. 网关超时\n3. 系统自动重试", "重试成功后支付完成，不产生重复扣款", "异常"),
        ("场景", "FHX", "收银台", "性能保障", "高峰压测", "高峰期支付接口响应", "并发 100 QPS 持续 5 分钟", "1. 压测引擎发压\n2. 观察 P99 延迟", "P99 ≤ 800ms，错误率 ≤ 0.5%", "性能"),
        ("反向", "ZD", "收银台", "安全风控", "密码锁定", "支付密码连续错误锁定", "同一账户连续输错密码", "1. 连续 5 次输入错误支付密码", "账户支付功能锁定 30 分钟并触发风控告警", "安全"),
        ("场景", "BL", "收银台", "兼容适配", "浏览器遍历", "主流浏览器支付流程", "覆盖 Chrome / Edge / Safari 最新版", "1. 分别在各浏览器完成一笔支付", "各浏览器支付流程一致且无样式错乱", "兼容"),
    ]
    for idx, (strategy, priority, module, submodule, feature_point, name, precondition, steps, expected, test_type) in enumerate(items):
        db.add(
            CaseItem(
                case_set_id=case_set.id,
                strategy=strategy,
                priority=priority,
                module=module,
                submodule=submodule,
                feature_point=feature_point,
                name=name,
                precondition=precondition,
                steps=steps,
                expected=expected,
                test_type=test_type,
                sort_order=idx,
            )
        )
    case_set.generated_count = len(items)
    case_set.confirmed_count = len(items)
    logger.info("已播种用例集 %s（%d 条用例）", case_set.name, len(items))
    return case_set


def _seed_workers(db: Session) -> list[DispatchWorker]:
    """调度星图 Worker 节点：覆盖四大业务域，含离线节点演示状态分层；已有节点时返回现状供事件引用。"""
    existing = db.query(DispatchWorker).order_by(DispatchWorker.id.asc()).all()
    if existing:
        return list(existing)
    now = datetime.now(UTC)
    workers = [
        DispatchWorker(id="worker-01", name="GPU-Node-A1", caps=["benchmark", "judge"], state="idle", load_percent=18, weight=100, last_heartbeat_at=now),
        DispatchWorker(id="worker-02", name="Vec-Node-V1", caps=["rag", "vector"], state="idle", load_percent=8, weight=100, last_heartbeat_at=now),
        DispatchWorker(id="worker-03", name="Gen-Node-G1", caps=["testcase", "prd"], state="idle", load_percent=12, weight=80, last_heartbeat_at=now),
        DispatchWorker(id="worker-04", name="Stress-Node-S1", caps=["stress", "load"], state="idle", load_percent=5, weight=120, last_heartbeat_at=now),
        DispatchWorker(id="worker-05", name="Judge-Node-J1", caps=["benchmark", "prompt"], state="offline", load_percent=0, weight=100, last_heartbeat_at=_hours_ago(3)),
        DispatchWorker(id="worker-06", name="Chunk-Node-C1", caps=["rag", "chunking"], state="idle", load_percent=6, weight=80, last_heartbeat_at=now),
    ]
    db.add_all(workers)
    db.flush()
    logger.info("已播种 %d 个 Worker 节点", len(workers))
    return workers


def _seed_tasks_and_reports(
    db: Session,
    admin: User,
    dataset: Dataset | None,
    workers: list[DispatchWorker],
    profiles: list[ProtocolProfile],
) -> None:
    """先评后压演示链路：benchmark 父任务 + stress 子任务 + RAG 任务，各配报告与事件。"""
    if db.query(Task).count():
        return
    dataset_id = dataset.id if dataset else None
    # 报告 scores 的 profile 字段引用真实协议档 ID，保证详情页可回溯
    profile_ids = [p.id for p in profiles[:2]] or ["seed-profile-1", "seed-profile-2"]
    started = _hours_ago(5)
    finished = started + timedelta(minutes=12)

    # 1) Benchmark 父任务（已成功）
    bm = Task(
        kind="benchmark",
        status="succeeded",
        config={
            "dataset_id": dataset_id,
            "dataset_version": 3,
            "metric": "contain",
            "profile_ids": profile_ids,
            "with_stress": True,
        },
        progress={"done": 20, "total": 20, "percent": 100, "message": "评测完成"},
        created_by=admin.id,
        created_at=started,
        started_at=started,
        finished_at=finished,
    )
    db.add(bm)
    db.flush()
    db.add(
        Report(
            task_id=bm.id,
            kind="benchmark",
            created_at=finished,
            metrics={
                "scores": [
                    {"profile": profile_ids[0], "profile_name": "GPT-4o", "contain": 0.87, "exact": 0.62, "rouge_l": 0.74, "fail_rate": 0.0, "latency": "1.2s", "judge": 4.3},
                    {"profile": profile_ids[-1], "profile_name": "Claude Sonnet", "contain": 0.84, "exact": 0.58, "rouge_l": 0.71, "fail_rate": 0.02, "latency": "1.6s", "judge": 4.1},
                ],
                "judge_info": {"model": "claude-sonnet-4-20250514", "note": "裁判打分基于 5 分制 rubric"},
                "sample_items": [],
            },
        )
    )

    # 2) 派生压测子任务（已成功，含时序曲线）
    st_started = finished + timedelta(minutes=2)
    st_finished = st_started + timedelta(minutes=8)
    stress = Task(
        kind="stress",
        status="succeeded",
        parent_task_id=bm.id,
        config={"parent_task_id": bm.id, "stress": {"env": "test", "qps": 120, "duration_s": 480}},
        progress={"done": 1, "total": 1, "percent": 100, "message": "压测完成"},
        created_by=admin.id,
        created_at=st_started,
        started_at=st_started,
        finished_at=st_finished,
    )
    db.add(stress)
    db.flush()
    series = [
        {"ts": (st_started + timedelta(minutes=i)).isoformat(), "qps": qps, "rt_ms": rt, "error_rate": er}
        for i, (qps, rt, er) in enumerate(
            [(20, 280, 0.0), (55, 320, 0.0), (90, 450, 0.001), (118, 780, 0.002), (115, 1100, 0.004), (60, 520, 0.001)]
        )
    ]
    db.add(
        Report(
            task_id=stress.id,
            kind="stress",
            created_at=st_finished,
            metrics={
                "qps_peak": 118,
                "rt_avg_ms": 575,
                "error_rate": 0.002,
                "sla_p99_ms": 1100,
                "est_cost_usd": 0.42,
                "knee": {"qps": 118, "note": "P99 在 118 QPS 后出现拐点"},
                "time_series": series,
                "series": series,
            },
        )
    )

    # 3) RAG 评测任务（已成功，四模式对比）
    rag_started = _hours_ago(2)
    rag_finished = rag_started + timedelta(minutes=6)
    rag = Task(
        kind="rag",
        status="succeeded",
        config={"kb_id": "kb-default", "gold_qa_id": "qa-v1", "rag_mode": ["naive", "local", "global", "hybrid"]},
        progress={"done": 50, "total": 50, "percent": 100, "message": "评测完成"},
        created_by=admin.id,
        created_at=rag_started,
        started_at=rag_started,
        finished_at=rag_finished,
    )
    db.add(rag)
    db.flush()
    db.add(
        Report(
            task_id=rag.id,
            kind="rag",
            created_at=rag_finished,
            metrics={
                "k": 5,
                "hit_rate_at_k": 0.86,
                "mrr": 0.78,
                "recall_at_k": 0.90,
                "answer_contain": 0.83,
                "modes": ["naive", "local", "global", "hybrid"],
                "rag_scores": {
                    "naive": {"hit": 0.72, "mrr": 0.61, "recall": 0.78, "contain": 0.70},
                    "local": {"hit": 0.84, "mrr": 0.76, "recall": 0.88, "contain": 0.81},
                    "global": {"hit": 0.80, "mrr": 0.72, "recall": 0.85, "contain": 0.77},
                    "hybrid": {"hit": 0.86, "mrr": 0.78, "recall": 0.90, "contain": 0.83},
                },
                "hit_denominator_note": "无 expected_doc_ids 的样本不计入 Hit Rate 分母",
            },
        )
    )

    # 4) 任务时间线事件
    for task, label in [(bm, "Benchmark 评测"), (stress, "派生压测"), (rag, "RAG 评测")]:
        db.add_all(
            [
                TaskEvent(task_id=task.id, event="queued", message=f"{label}任务已入队", payload={"status": "queued"}, ts=task.created_at),
                TaskEvent(task_id=task.id, event="running", message=f"{label}任务开始执行", payload={"status": "running"}, ts=task.started_at),
                TaskEvent(task_id=task.id, event="succeeded", message=f"{label}任务执行成功", payload={"status": "succeeded"}, ts=task.finished_at),
            ]
        )

    # 5) 调度事件流：供调度中心日志与星图回放
    w1 = workers[0].id if workers else "worker-01"
    w4 = workers[3].id if len(workers) > 3 else "worker-04"
    w2 = workers[1].id if len(workers) > 1 else "worker-02"
    db.add_all(
        [
            DispatchEvent(task_id=bm.id, worker_id=w1, event="assigned", message=f"任务 {bm.id[:8]} 分配至 {w1} · 策略=负载均衡 · 耗时 82ms", ts=started),
            DispatchEvent(task_id=bm.id, worker_id=w1, event="succeeded", message=f"{w1} 执行完成 {bm.id[:8]}，释放并发槽位", ts=finished),
            DispatchEvent(task_id=stress.id, worker_id=w4, event="assigned", message=f"派生压测 {stress.id[:8]} 分配至 {w4} · env=test", ts=st_started),
            DispatchEvent(task_id=stress.id, worker_id=w4, event="succeeded", message=f"{w4} 执行完成 {stress.id[:8]} · 峰值 118 QPS", ts=st_finished),
            DispatchEvent(task_id=rag.id, worker_id=w2, event="assigned", message=f"RAG 评测 {rag.id[:8]} 分配至 {w2}", ts=rag_started),
            DispatchEvent(task_id=rag.id, worker_id=w2, event="succeeded", message=f"{w2} 执行完成 {rag.id[:8]} · Hit@5=0.86", ts=rag_finished),
        ]
    )
    logger.info("已播种先评后压演示任务链与 3 份报告")


def _seed_kb(db: Session, admin: User) -> KnowledgeBase | None:
    """种子默认知识库与黄金 QA（不种子文档文件），保证黄金 QA 树首屏有数据。"""
    if db.query(KnowledgeBase).count():
        return None
    kb = KnowledgeBase(
        name="默认知识库",
        kind="lightrag",
        is_core=True,
        created_by=admin.id,
    )
    db.add(kb)
    db.flush()
    qa = GoldQa(kb_id=kb.id, name="smoke-qa", version=1, created_by=admin.id)
    db.add(qa)
    db.flush()
    rows = [
        ("退款多久到账？", "退款一般在 1-3 个工作日内原路退回。", []),
        ("如何修改绑定的手机号？", "在安全中心验证身份后即可更换绑定手机号。", []),
        ("会员过期后权益如何处理？", "会员过期后当月权益保留至月底，续费后恢复全部权益。", []),
    ]
    for row_no, (question, reference, expected) in enumerate(rows, start=1):
        db.add(
            GoldQaItem(
                gold_qa_id=qa.id,
                row_no=row_no,
                question=question,
                reference=reference,
                expected_doc_ids=expected,
            )
        )
    qa.row_count = len(rows)
    logger.info("已播种知识库与黄金 QA 预览数据")
    return kb


def bootstrap_preview_data(db: Session, admin: User) -> None:
    """按域幂等播种预览数据；任一域已有数据即跳过该域。"""
    profiles = _seed_profiles(db, admin)
    if not profiles:
        profiles = list(db.query(ProtocolProfile).order_by(ProtocolProfile.created_at.asc()).all())
    dataset = _seed_datasets(db, admin)
    _seed_cases(db, admin)
    _seed_kb(db, admin)
    workers = _seed_workers(db)
    _seed_tasks_and_reports(db, admin, dataset, workers, profiles)
    db.commit()
