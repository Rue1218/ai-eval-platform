"""探针运行时错误（连接失败、超时、未授权入队）。"""


class ProbeError(RuntimeError):
    """探针未能按场景完成：超时、关闭码不符、缺少 --allow-enqueue。"""
