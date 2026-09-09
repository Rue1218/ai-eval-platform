"""错误码枚举与统一错误响应。

对应 PRD 5.5 / API V1.0 §1.3：十个错误码 + 统一错误体
``{"code", "message", "fields"?}``。所有业务错误抛出 ``AppError``，
由 ``register_error_handlers`` 统一渲染为 JSON；同时把 FastAPI 自动的
422 校验错误归一为 ``VALIDATION``（400），保证前后端共享同一套错误名单。
"""

import logging
from enum import StrEnum
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class ErrorCode(StrEnum):
    UNAUTHORIZED = "UNAUTHORIZED"
    VALIDATION = "VALIDATION"
    NOT_FOUND = "NOT_FOUND"
    BUDGET_EXCEEDED = "BUDGET_EXCEEDED"
    CONCURRENCY = "CONCURRENCY"
    WHITELIST = "WHITELIST"
    NEED_APPROVAL = "NEED_APPROVAL"
    UPSTREAM = "UPSTREAM"
    TIMEOUT = "TIMEOUT"
    INTERNAL = "INTERNAL"
    DENIED = "DENIED"  # F5/G6：bash 只读档拒写（升档审批触发源，§6.4）


# code -> 默认 HTTP 状态码（API V1.0 §1.3）
_CODE_STATUS: dict[ErrorCode, int] = {
    ErrorCode.UNAUTHORIZED: 403,
    ErrorCode.VALIDATION: 400,
    ErrorCode.NOT_FOUND: 404,
    ErrorCode.BUDGET_EXCEEDED: 409,
    ErrorCode.CONCURRENCY: 409,
    ErrorCode.WHITELIST: 403,
    ErrorCode.NEED_APPROVAL: 403,
    ErrorCode.UPSTREAM: 502,
    ErrorCode.TIMEOUT: 504,
    ErrorCode.INTERNAL: 500,
    ErrorCode.DENIED: 403,  # F5/G6：只读拒写（HTTP 403 授权语义）
}


class AppError(Exception):
    """业务错误。``status_code`` 缺省取 ``_CODE_STATUS`` 默认值，
    但 ``UNAUTHORIZED`` 用于未登录时需显式传 ``status_code=401``。"""

    def __init__(
        self,
        code: ErrorCode,
        message: str = "",
        *,
        status_code: int | None = None,
        fields: dict[str, Any] | None = None,
    ) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code if status_code is not None else _CODE_STATUS[code]
        self.fields = fields
        super().__init__(message or code.value)


def register_error_handlers(app: FastAPI) -> None:
    """注册业务、校验和未处理异常的统一 JSON 错误响应。"""
    logger = logging.getLogger("ai-eval.errors")

    @app.exception_handler(AppError)
    async def _app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        body: dict[str, Any] = {"code": exc.code.value, "message": exc.message}
        if exc.fields:
            body["fields"] = exc.fields
        return JSONResponse(status_code=exc.status_code, content=body)

    @app.exception_handler(RequestValidationError)
    async def _validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        # FastAPI 自动校验默认 422，按 API V1.0 归一为 400 + VALIDATION
        return JSONResponse(
            status_code=400,
            content={"code": ErrorCode.VALIDATION.value, "message": "请检查标红字段"},
        )

    @app.exception_handler(Exception)
    async def _internal_error_handler(request: Request, exc: Exception) -> JSONResponse:
        """记录内部堆栈但不把 SQL、密钥或实现细节返回给浏览器。"""
        logger.exception("未处理的服务端异常: %s", request.url.path, exc_info=exc)
        return JSONResponse(
            status_code=500,
            content={"code": ErrorCode.INTERNAL.value, "message": "内部错误，请重试或联系平台维护者"},
        )
