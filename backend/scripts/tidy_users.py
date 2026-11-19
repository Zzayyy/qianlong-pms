"""命令行入口：整理测试账号（每个角色保留一个，统一密码）。

    py -3.12 scripts/tidy_users.py                        # 只预览，不写库
    py -3.12 scripts/tidy_users.py --apply                # 按预览结果执行（软删除）
    py -3.12 scripts/tidy_users.py --apply --password 123456
    py -3.12 scripts/tidy_users.py --apply --hard-delete  # 物理删除（不可回滚）

保留规则（自上而下，命中即保留）：
    1. 有业务数据的账号（项目/任务/工时/周报/变更/客户商机/部门领导等引用）一律保留；
    2. 其余账号按角色分组，每个 `role_code` 只保留一个代表账号（优先内置账号）；
    3. 剩下的账号软删除（`deleted = 1`）并清掉角色绑定。

执行后所有保留账号的密码重置为 `--password`（默认 123456），并解锁。
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections import defaultdict
from pathlib import Path
from typing import Final

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sqlalchemy import bindparam, text

from pms.core.database import dispose_engine, get_session_factory
from pms.core.security import hash_password
from pms.system.seed import USERS

DEFAULT_PASSWORD: Final[str] = "123456"

#: 内置账号优先级：同一角色有多个账号时，排前面的优先保留
_BUILTIN_ORDER: Final[dict[str, int]] = {
    username: index for index, (username, *_rest) in enumerate(USERS)
}

#: 引用用户的业务表列（判断“这个账号有没有在用”）
_REF_COLUMNS: Final[tuple[tuple[str, str], ...]] = (
    ("t_prj_project", "pm_id"),
    ("t_prj_project", "sponsor_id"),
    ("t_prj_project", "create_by"),
    ("t_prj_member", "user_id"),
    ("t_prj_director", "user_id"),
    ("t_prj_director", "assigned_by"),
    ("t_prj_stage", "owner_id"),
    ("t_prj_milestone", "owner_id"),
    ("t_prj_task", "owner_id"),
    ("t_prj_risk", "owner_id"),
    ("t_prj_baseline", "frozen_by"),
    ("t_prj_attachment", "create_by"),
    ("t_crm_customer", "owner_user_id"),
    ("t_crm_opportunity", "owner_user_id"),
    ("t_wl_worklog", "user_id"),
    ("t_wl_worklog", "confirm_by"),
    ("t_wl_comment", "user_id"),
    ("t_wk_weekly", "user_id"),
    ("t_wk_weekly", "confirm_by"),
    ("t_chg_request", "submitter_id"),
    ("t_chg_request", "pm_id"),
    ("t_chg_approval", "approver_id"),
    ("t_chg_schedule", "owner_id"),
    ("t_sys_dept", "leader_id"),
    ("t_sys_user", "manager_id"),
)


def build_parser() -> argparse.ArgumentParser:
    """构造参数解析器。"""
    parser = argparse.ArgumentParser(description="PMS 测试账号整理")
    parser.add_argument("--apply", action="store_true", help="真正写库；缺省只预览")
    parser.add_argument("--password", default=DEFAULT_PASSWORD, help="保留账号的统一密码")
    parser.add_argument("--hard-delete", action="store_true", help="物理删除多余账号（默认软删除）")
    return parser


def _ref_sql() -> str:
    """拼一条 UNION ALL：统计每个 user_id 在业务表里的引用次数。"""
    parts = [
        f"SELECT {column} AS uid, COUNT(*) AS cnt FROM {table}"
        f" WHERE deleted = 0 AND {column} > 0 GROUP BY {column}"
        for table, column in _REF_COLUMNS
    ]
    return "SELECT uid, SUM(cnt) AS cnt FROM (" + " UNION ALL ".join(parts) + ") t GROUP BY uid"


async def _load_users(session) -> list[dict[str, object]]:
    """读取未删除的用户及其角色。"""
    user_rows = (
        await session.execute(
            text(
                "SELECT id, username, real_name, dept_id FROM t_sys_user"
                " WHERE deleted = 0 ORDER BY id"
            )
        )
    ).mappings()
    role_map: dict[int, list[str]] = defaultdict(list)
    role_rows = (
        await session.execute(
            text(
                "SELECT ur.user_id, r.role_code FROM t_sys_user_role ur"
                " JOIN t_sys_role r ON r.id = ur.role_id"
                " WHERE ur.deleted = 0 AND r.deleted = 0 ORDER BY r.role_code"
            )
        )
    ).mappings()
    for row in role_rows:
        role_map[int(row["user_id"])].append(str(row["role_code"]))

    users: list[dict[str, object]] = []
    for row in user_rows:
        uid = int(row["id"])
        users.append(
            {
                "id": uid,
                "username": str(row["username"]),
                "real_name": str(row["real_name"]),
                "dept_id": int(row["dept_id"]),
                "roles": role_map.get(uid, []),
            }
        )
    return users


async def _load_refs(session) -> dict[int, int]:
    """统计每个用户被业务数据引用的次数。"""
    refs: dict[int, int] = {}
    try:
        rows = (await session.execute(text(_ref_sql()))).mappings()
    except Exception as exc:
        print(f"[warn] 业务引用统计失败，跳过该规则：{exc}")
        return refs
    for row in rows:
        refs[int(row["uid"])] = int(row["cnt"])
    return refs


def _priority(user: dict[str, object]) -> tuple[int, int]:
    """角色代表账号的排序键：内置账号优先，其次按 id。"""
    return (_BUILTIN_ORDER.get(str(user["username"]), 999), int(user["id"]))


def _decide(
    users: list[dict[str, object]], refs: dict[int, int]
) -> tuple[list[dict[str, object]], list[dict[str, object]], dict[int, str]]:
    """判定保留/删除，返回 (保留, 删除, {用户ID: 原因})。"""
    keep: dict[int, dict[str, object]] = {}
    reasons: dict[int, str] = {}

    # 规则 1：有业务数据的一律保留
    for user in users:
        count = refs.get(int(user["id"]), 0)
        if count > 0:
            keep[int(user["id"])] = user
            reasons[int(user["id"])] = f"有业务数据({count})"

    # 规则 2：每个角色保留一个代表账号
    by_role: dict[str, list[dict[str, object]]] = defaultdict(list)
    for user in users:
        for role_code in user["roles"]:  # type: ignore[union-attr]
            by_role[str(role_code)].append(user)
    for role_code, members in sorted(by_role.items()):
        if any(int(m["id"]) in keep for m in members):
            continue
        chosen = sorted(members, key=_priority)[0]
        keep[int(chosen["id"])] = chosen
        reasons[int(chosen["id"])] = f"角色代表({role_code})"

    kept = [u for u in users if int(u["id"]) in keep]
    removed = [u for u in users if int(u["id"]) not in keep]
    for user in removed:
        reasons[int(user["id"])] = "角色已有人"
    # 没有任何角色的账号也归入删除
    for user in removed:
        if not user["roles"]:
            reasons[int(user["id"])] = "无角色"
    return kept, removed, reasons


def _print_plan(
    users: list[dict[str, object]],
    refs: dict[int, int],
    removed: list[dict[str, object]],
    reasons: dict[int, str],
) -> None:
    """打印整理计划。"""
    removed_ids = {int(u["id"]) for u in removed}
    print(f"{'ID':<20}{'账号':<16}{'姓名':<12}{'角色':<28}{'引用':<6}结论")
    print("-" * 100)
    for user in users:
        uid = int(user["id"])
        verdict = "删除" if uid in removed_ids else f"保留({reasons.get(uid, '')})"
        print(
            f"{uid:<20}{user['username']:<16}{user['real_name']:<12}"
            f"{','.join(user['roles']) or '-':<28}{refs.get(uid, 0):<6}{verdict}"
        )
    print("-" * 100)
    print(f"合计 {len(users)} 个账号：保留 {len(users) - len(removed)}，删除 {len(removed)}")


async def run(password: str, apply: bool, hard_delete: bool) -> int:
    """执行整理并返回退出码。"""
    factory = get_session_factory()
    try:
        async with factory() as session:
            users = await _load_users(session)
            refs = await _load_refs(session)
            kept, removed, reasons = _decide(users, refs)
            _print_plan(users, refs, removed, reasons)
            if not apply:
                print("\n[dry-run] 未写库；确认无误后加 --apply 执行")
                return 0
            await _apply(session, kept, removed, password, hard_delete)
    finally:
        await dispose_engine()
    print(f"\n已完成：保留 {len(kept)} 个账号，密码统一为 {password}；清理 {len(removed)} 个账号")
    return 0


async def _apply(
    session,
    kept: list[dict[str, object]],
    removed: list[dict[str, object]],
    password: str,
    hard_delete: bool,
) -> None:
    """写库：重置密码、处理多余账号。"""
    password_hash = hash_password(password)
    keep_ids = [int(u["id"]) for u in kept]
    remove_ids = [int(u["id"]) for u in removed]

    def stmt(sql: str):
        """把 `IN :ids` 展开成占位符列表。"""
        return text(sql).bindparams(bindparam("ids", expanding=True))

    if keep_ids:
        await session.execute(
            stmt(
                "UPDATE t_sys_user SET password_hash = :pwd, login_fail_count = 0,"
                " locked_until = NULL, must_change_password = 0 WHERE id IN :ids"
            ),
            {"pwd": password_hash, "ids": keep_ids},
        )

    if remove_ids:
        # 断掉组织关系，避免部门领导 / 上级指向已删除账号
        await session.execute(
            stmt("UPDATE t_sys_dept SET leader_id = NULL WHERE leader_id IN :ids"),
            {"ids": remove_ids},
        )
        await session.execute(
            stmt("UPDATE t_sys_user SET manager_id = NULL WHERE manager_id IN :ids"),
            {"ids": remove_ids},
        )
        if hard_delete:
            await session.execute(
                stmt("DELETE FROM t_sys_user_role WHERE user_id IN :ids"), {"ids": remove_ids}
            )
            await session.execute(
                stmt("DELETE FROM t_sys_user WHERE id IN :ids"), {"ids": remove_ids}
            )
        else:
            await session.execute(
                stmt("UPDATE t_sys_user_role SET deleted = 1 WHERE user_id IN :ids"),
                {"ids": remove_ids},
            )
            await session.execute(
                stmt(
                    "UPDATE t_sys_user SET deleted = 1, status = 'DISABLED' WHERE id IN :ids"
                ),
                {"ids": remove_ids},
            )
    await session.commit()


def main() -> int:
    """入口。"""
    args = build_parser().parse_args()
    if not args.password:
        print("密码不能为空")
        return 2
    return asyncio.run(run(args.password, args.apply, args.hard_delete))


if __name__ == "__main__":
    raise SystemExit(main())
