"""路由顺序守卫（设计稿 09 §2）：**静态子路径必须先于路径参数路由注册**。

否则 `/worklogs/stats` 会被 `/worklogs/{worklog_id}` 抢先匹配而 422。
"""

from __future__ import annotations

from fastapi import FastAPI

from pms.main import create_app

# (方法, 路径, 期望处理函数名)
GUARD_CASES: tuple[tuple[str, str, str], ...] = (
    ("GET", "/api/v1/worklogs/stats", "stats"),
    ("GET", "/api/v1/worklogs/summary", "summary"),
    ("GET", "/api/v1/worklogs/reminders", "reminders"),
    ("GET", "/api/v1/worklogs/reminder-targets", "reminder_targets"),
    ("GET", "/api/v1/worklogs/options", "options"),
    ("GET", "/api/v1/worklogs/day-summary", "day_summary"),
    ("POST", "/api/v1/configs/seed", "seed_configs"),
    ("GET", "/api/v1/audit/operate-logs", "list_operate_logs"),
    ("GET", "/api/v1/audit/login-logs", "list_login_logs"),
    ("POST", "/api/v1/audit/archive", "archive_logs"),
)


def _flatten_routes(app: FastAPI) -> list[object]:
    """展开全部路由。

    实现说明：新版 FastAPI 用 `_IncludedRouter` 包装 `include_router` 的结果，
    不再把子路由平铺进 `app.routes`，故需递归其 `original_router.routes`。
    """

    def walk(routes: object) -> list[object]:
        flat: list[object] = []
        for route in routes:  # type: ignore[union-attr]
            nested = getattr(route, "original_router", None)
            if nested is not None:
                flat.extend(walk(nested.routes))
            else:
                flat.append(route)
        return flat

    return walk(app.routes)


def _endpoint_name(app: FastAPI, method: str, path: str) -> str:
    """按「方法 + 路径」找到实际命中的处理函数名。"""
    for route in _flatten_routes(app):
        if getattr(route, "path", "") == path and method in getattr(route, "methods", set()):
            return getattr(route.endpoint, "__name__", "?")
    return "?"


def test_static_subpaths_not_shadowed() -> None:
    """关键静态子路径必须命中自身处理器，不被 `{id}` 路由抢走。"""
    app = create_app()
    for method, path, expected in GUARD_CASES:
        actual = _endpoint_name(app, method, path)
        assert actual == expected, f"{method} {path} 命中 {actual}，期望 {expected}"


# 管理与协作类接口（v1.1.14 起：人员 / 部门 / 项目负责人）
MANAGE_ROUTES: tuple[tuple[str, str, str], ...] = (
    ("POST", "/api/v1/depts", "dept_create"),
    ("PUT", "/api/v1/depts/{dept_id}", "dept_update"),
    ("DELETE", "/api/v1/depts/{dept_id}", "dept_delete"),
    ("PUT", "/api/v1/users/{user_id}", "user_update"),
    ("PUT", "/api/v1/users/{user_id}/status", "user_status"),
    ("PUT", "/api/v1/users/{user_id}/password", "user_password"),
    ("GET", "/api/v1/users/{user_id}/roles", "user_roles"),
    ("PUT", "/api/v1/projects/{project_id}/pm", "change_pm"),
    ("DELETE", "/api/v1/projects/{project_id}/members/{member_id}", "delete_member"),
)


def test_manage_routes_registered() -> None:
    """组织管理与项目负责人相关接口必须已注册且未被其他路由遮蔽。"""
    app = create_app()
    for method, path, expected in MANAGE_ROUTES:
        actual = _endpoint_name(app, method, path)
        assert actual == expected, f"{method} {path} 命中 {actual}，期望 {expected}"


def test_param_route_still_works() -> None:
    """参数化路由仍然可用（`/worklogs/{worklog_id}` 存在）。"""
    app = create_app()
    paths = {getattr(r, "path", "") for r in _flatten_routes(app)}
    assert "/api/v1/worklogs/{worklog_id}" in paths
    assert "/api/v1/configs/{config_key}" in paths
