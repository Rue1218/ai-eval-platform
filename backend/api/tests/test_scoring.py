"""规则评分器单测（M2 W7）：五种主指标的命中 / 未命中 / 边界口径。

评分器正本位于 worker 包（纯函数零依赖），此处按文件路径加载，
保证 CI 覆盖 Worker 评分口径而无需数据库或额外依赖。
"""

import importlib.util
from pathlib import Path

# worker 侧评分器路径：backend/worker/app/scoring.py
_SCORING_PATH = Path(__file__).resolve().parents[2] / "worker" / "app" / "scoring.py"
_spec = importlib.util.spec_from_file_location("worker_scoring", _SCORING_PATH)
scoring = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(scoring)


def test_exact_hit_and_miss():
    # 归一空白后完全一致才得分
    assert scoring.score_exact("巴黎", "巴黎") == 1.0
    assert scoring.score_exact("  巴黎 \n", "巴黎") == 1.0
    assert scoring.score_exact("巴黎是法国首都", "巴黎") == 0.0
    assert scoring.score_exact("", "") == 1.0


def test_contain_requires_reference():
    # 空参考答案记 0 分；子串命中得 1
    assert scoring.score_contain("法国的首都是巴黎", "巴黎") == 1.0
    assert scoring.score_contain("法国的首都", "巴黎") == 0.0
    assert scoring.score_contain("任意输出", "") == 0.0
    assert scoring.score_contain("答案  A  B", "A B") == 1.0


def test_regex_tolerates_invalid_pattern():
    # 合法正则命中得 1；非法正则与空模式记 0，不抛异常
    assert scoring.score_regex("订单号: A12345", r"A\d{5}") == 1.0
    assert scoring.score_regex("订单号: A12345", r"^\d+$") == 0.0
    assert scoring.score_regex("任意", r"([unclosed") == 0.0
    assert scoring.score_regex("任意", "") == 0.0


def test_rouge_l_bounds():
    # 完全一致为 1；无公共词为 0；部分重叠介于两者之间
    assert scoring.score_rouge_l("a b c d", "a b c d") == 1.0
    assert scoring.score_rouge_l("a b c d", "x y z") == 0.0
    partial = scoring.score_rouge_l("a b c d", "a b x y")
    assert 0.0 < partial < 1.0
    assert scoring.score_rouge_l("", "a b") == 0.0


def test_bleu_bounds():
    # 词数充足且完全一致为 1；空输入记 0
    assert scoring.score_bleu("the cat sat on the mat", "the cat sat on the mat") == 1.0
    # 加一平滑下完全无关文本存在非零地板分，但显著低于任何真实重叠
    unrelated = scoring.score_bleu("alpha beta gamma delta", "one two three four")
    assert 0.0 < unrelated < 0.5
    assert scoring.score_bleu("", "a b c d e") == 0.0
    assert scoring.score_bleu("a b c d e", "") == 0.0
    # 输出不足 4 词（无 4-gram）按 0 处理（口径见 scoring.py 注释）
    assert scoring.score_bleu("a b c", "a b c") == 0.0


def test_bleu_partial_overlap_scores_between_bounds():
    partial = scoring.score_bleu("the cat sat on the mat", "the cat sat there quietly")
    assert 0.0 < partial < 1.0


def test_score_answer_dispatch_and_fallback():
    # 按指标分发；未知指标回退 contain，保证执行器不因脏数据中断
    assert scoring.score_answer("exact", "甲", "甲") == 1.0
    assert scoring.score_answer("contain", "包含甲字", "甲") == 1.0
    assert scoring.score_answer("contain", "没有", "甲") == 0.0
    assert scoring.score_answer("not_a_metric", "包含甲字", "甲") == 1.0
    assert scoring.score_answer(None, "包含甲字", "甲") == 1.0


def test_supported_metrics_contract():
    # 五种主指标与默认值对齐 PRD 5.2.2
    assert scoring.SUPPORTED_METRICS == ("exact", "contain", "regex", "rouge_l", "bleu")
    assert scoring.DEFAULT_METRIC == "contain"
