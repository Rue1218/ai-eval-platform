"""报告基线 Δ 对比纯函数单测（F-BM-07 / M2 出口「基线规则生效」）。

覆盖可比口径（同数据集版本 + 主指标）与退化判定（任一 profile 下降 ≥5pp）。
"""

from app.routers.reports import _baseline_matches, _degraded_vs_baseline


def test_baseline_matches_requires_same_dataset_version_metric():
    current = {"dataset_id": "ds-1", "dataset_version": 3, "metric": "contain"}
    assert _baseline_matches(current, {"dataset_id": "ds-1", "dataset_version": 3, "metric": "contain"})
    # 版本不同不可比
    assert not _baseline_matches(current, {"dataset_id": "ds-1", "dataset_version": 4, "metric": "contain"})
    # 主指标不同不可比
    assert not _baseline_matches(current, {"dataset_id": "ds-1", "dataset_version": 3, "metric": "rouge_l"})
    # 数据集不同不可比
    assert not _baseline_matches(current, {"dataset_id": "ds-2", "dataset_version": 3, "metric": "contain"})
    # 缺 dataset_id 的报告(旧数据)不参与对比
    assert not _baseline_matches({}, current)


def test_degraded_requires_5pp_drop_on_shared_profile():
    metrics = {"scores": [{"profile_id": "p-1", "score": 0.62}]}
    baseline = [{"profile_id": "p-1", "score": 0.70}]
    # 下降 8pp → 退化
    assert _degraded_vs_baseline(metrics, baseline) is True
    # 下降 5pp 恰好达到阈值 → 退化
    assert _degraded_vs_baseline({"scores": [{"profile_id": "p-1", "score": 0.65}]}, baseline) is True
    # 下降 3pp → 未退化
    assert _degraded_vs_baseline({"scores": [{"profile_id": "p-1", "score": 0.67}]}, baseline) is False
    # 提升不退化
    assert _degraded_vs_baseline({"scores": [{"profile_id": "p-1", "score": 0.90}]}, baseline) is False


def test_degraded_ignores_profiles_not_in_baseline():
    # 基准里不存在的 profile(新增被测档位)不参与退化判定
    metrics = {"scores": [{"profile_id": "p-new", "score": 0.10}]}
    baseline = [{"profile_id": "p-1", "score": 0.90}]
    assert _degraded_vs_baseline(metrics, baseline) is False


def test_degraded_without_baseline_is_false():
    # 无基准(未冻结或口径不可比)恒为 False
    assert _degraded_vs_baseline({"scores": [{"profile_id": "p-1", "score": 0.0}]}, []) is False
