"""数据集导入的共享静态契约。

API 目录准入与 Worker 实际执行必须引用同一份解析器注册表，避免目录把无法
执行的 parser 标记为 supported。
"""

SUPPORTED_DATASET_IMPORT_PARSERS: dict[str, str] = {
    "jsonl-qa-v1": "jsonl",
    "csv-qa-v1": "csv",
}
