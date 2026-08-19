"""规则评分器(PRD 5.2.2 / 后端开发计划 M2 W7)。

Benchmark 主指标五种:``exact`` / ``contain`` / ``regex`` / ``rouge_l`` / ``bleu``,
默认 ``contain``。本模块为纯函数且零 import:api 侧测试按文件路径直接加载
(见 ``backend/api/tests/test_scoring.py``),worker 执行器运行时同源引用,
两端评分口径永远一致;修改时必须保持零 import 约束。
"""

from __future__ import annotations

import math
import re

# 契约支持的五种规则评分主指标(与数据集 metric 字段取值一致,默认 contain)
SUPPORTED_METRICS = ("exact", "contain", "regex", "rouge_l", "bleu")
DEFAULT_METRIC = "contain"


def _normalize(text: str) -> str:
    """归一空白:折叠连续空白并去首尾空格,降低无关格式差异干扰。"""
    return " ".join((text or "").split())


def score_exact(output: str, reference: str) -> float:
    """精确匹配:归一空白后完全一致得 1,否则 0。"""
    return 1.0 if _normalize(output) == _normalize(reference) else 0.0


def score_contain(output: str, reference: str) -> float:
    """包含匹配:归一后的参考答案作为子串出现在输出中得 1;空参考记 0。"""
    needle = _normalize(reference)
    if not needle:
        return 0.0
    return 1.0 if needle in _normalize(output) else 0.0


def score_regex(output: str, reference: str) -> float:
    """正则匹配:参考答案作为正则模式在输出中命中得 1;非法正则记 0 不抛错。"""
    pattern = (reference or "").strip()
    if not pattern:
        return 0.0
    try:
        return 1.0 if re.search(pattern, output or "") else 0.0
    except re.error:
        return 0.0


def _tokenize(text: str) -> list[str]:
    """按空白切词,供 rouge_l / bleu 的词级 n-gram 计算。"""
    return (text or "").split()


def _lcs_length(a: list[str], b: list[str]) -> int:
    """最长公共子序列长度(滚动数组动态规划,O(len(a)×len(b)))。"""
    if not a or not b:
        return 0
    prev = [0] * (len(b) + 1)
    for token in a:
        curr = [0] * (len(b) + 1)
        for j, other in enumerate(b, start=1):
            if token == other:
                curr[j] = prev[j - 1] + 1
            else:
                curr[j] = max(curr[j - 1], prev[j])
        prev = curr
    return prev[len(b)]


def score_rouge_l(output: str, reference: str) -> float:
    """ROUGE-L F1:词级最长公共子序列的精确率/召回率调和均值,取值 0–1。"""
    out_tokens = _tokenize(output)
    ref_tokens = _tokenize(reference)
    if not out_tokens or not ref_tokens:
        return 0.0
    lcs = _lcs_length(out_tokens, ref_tokens)
    if lcs == 0:
        return 0.0
    precision = lcs / len(out_tokens)
    recall = lcs / len(ref_tokens)
    return 2 * precision * recall / (precision + recall)


def _ngram_counts(tokens: list[str], n: int) -> dict[tuple[str, ...], int]:
    """统计 n-gram 频次;不足 n 个词时为空字典。"""
    counts: dict[tuple[str, ...], int] = {}
    for i in range(len(tokens) - n + 1):
        gram = tuple(tokens[i : i + n])
        counts[gram] = counts.get(gram, 0) + 1
    return counts


def score_bleu(output: str, reference: str) -> float:
    """平滑 BLEU-4:4-gram 修正精确率几何均值 × 简短惩罚,取值 0–1。

    逐阶加一平滑 ``(命中数+1)/(总数+1)`` 缓解短文本零分(完全无关的句对
    因此存在非零地板分,属平滑口径的已知特性,排序不失真);输出或参考
    为空、或输出不足 4 个词(任一阶 n-gram 总数为 0)时按 0 处理。
    """
    out_tokens = _tokenize(output)
    ref_tokens = _tokenize(reference)
    if not out_tokens or not ref_tokens:
        return 0.0

    log_sum = 0.0
    for n in range(1, 5):
        out_grams = _ngram_counts(out_tokens, n)
        if not out_grams:
            return 0.0
        ref_grams = _ngram_counts(ref_tokens, n)
        # 修正精确率:每个 n-gram 命中次数不超过参考侧出现次数(clipping)
        matches = sum(min(count, ref_grams.get(gram, 0)) for gram, count in out_grams.items())
        p_n = (matches + 1) / (sum(out_grams.values()) + 1)
        log_sum += 0.25 * math.log(p_n)

    # 简短惩罚:输出不短于参考时为 1,否则按长度比衰减
    if len(out_tokens) >= len(ref_tokens):
        brevity = 1.0
    else:
        brevity = math.exp(1 - len(ref_tokens) / len(out_tokens))
    return brevity * math.exp(log_sum)


def score_answer(metric: str, output: str, reference: str) -> float:
    """按主指标评分的统一入口;未知指标回退 contain,单样本异常不中断整次评测。"""
    scorers = {
        "exact": score_exact,
        "contain": score_contain,
        "regex": score_regex,
        "rouge_l": score_rouge_l,
        "bleu": score_bleu,
    }
    scorer = scorers.get(metric or DEFAULT_METRIC, score_contain)
    try:
        return float(scorer(output, reference))
    except Exception:  # noqa: BLE001 评分器全防御:脏数据按 0 分处理并继续
        return 0.0
