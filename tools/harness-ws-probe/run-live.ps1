# run-live.ps1 — 一键跑 Harness WS 探针 live 全套（连真实服务，落抓包证据）
# 用法：./run-live.ps1 [-Base http://127.0.0.1:8000] [-User admin] [-Password admin123]
# 说明：设置 HARNESS_PROBE_* 环境变量后调用 pytest live 套件；
#       任一契约断言失败即退出码非 0，抓包证据自动落盘 traces/live-<时间戳>.jsonl。
param(
    [string]$Base = "http://127.0.0.1:8000",
    [string]$User = "admin",
    [string]$Password = "admin123"
)

$ErrorActionPreference = "Stop"
$root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$env:HARNESS_PROBE_BASE = $Base
$env:HARNESS_PROBE_USER = $User
$env:HARNESS_PROBE_PASSWORD = $Password

Push-Location (Join-Path $root "backend\api")
try {
    python -m pytest tests/test_harness_probe_live.py -v
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
