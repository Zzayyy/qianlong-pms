"""业务异常体系。

禁止在业务代码里抛裸 RuntimeError；所有可预期错误都用 BizError 子类。
"""

from __future__ import annotations

from typing import Any

from pms.common.codes import ErrorCode


class BizError(Exception):
    """业务异常基类。"""

    def __init__(
        self,
        code: ErrorCode = ErrorCode.SERVER_ERROR,
        message: str = "服务异常",
        detail: Any = None,
    ) -> None:
        super().__init__(message)
        self.code: ErrorCode = code
        self.message: str = message
        self.detail: Any = detail


class ParamError(BizError):
    """参数错误。"""

    def __init__(self, message: str = "参数错误", detail: Any = None) -> None:
        super().__init__(ErrorCode.PARAM_ERROR, message, detail)


class UnauthorizedError(BizError):
    """未认证或令牌失效。"""

    def __init__(self, message: str = "未认证或登录已失效") -> None:
        super().__init__(ErrorCode.UNAUTHORIZED, message)


class ForbiddenError(BizError):
    """无功能权限。"""

    def __init__(self, message: str = "无操作权限") -> None:
        super().__init__(ErrorCode.FORBIDDEN, message)


class DataForbiddenError(BizError):
    """无数据权限（越权访问）。"""

    def __init__(self, message: str = "无数据访问权限") -> None:
        super().__init__(ErrorCode.DATA_FORBIDDEN, message)


class NotFoundError(BizError):
    """资源不存在或不可见（对外统一表述，避免信息泄漏）。"""

    def __init__(self, message: str = "资源不存在") -> None:
        super().__init__(ErrorCode.NOT_FOUND, message)


class StateInvalidError(BizError):
    """状态流转非法（状态机拦截）。"""

    def __init__(self, message: str = "当前状态不允许该操作") -> None:
        super().__init__(ErrorCode.STATE_INVALID, message)


class ConflictError(BizError):
    """数据冲突：唯一约束、乐观锁、重复提交。"""

    def __init__(self, message: str = "数据冲突", detail: Any = None) -> None:
        super().__init__(ErrorCode.CONFLICT, message, detail)


class BizRuleError(BizError):
    """业务规则校验失败（如工时合计不符）。"""

    def __init__(self, message: str = "业务规则校验失败", detail: Any = None) -> None:
        super().__init__(ErrorCode.BIZ_RULE, message, detail)
