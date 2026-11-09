"""命令行入口：初始化部门、角色、权限点、字典与登录账号（幂等）。

    py -3.12 scripts/seed.py                     # 默认密码 Pms@12345
    py -3.12 scripts/seed.py --password Xxx@123  # 指定初始密码
    py -3.12 scripts/seed.py --list              # 只列出内置账号，不写库
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pms.core.database import dispose_engine, get_session_factory  # noqa: E402
from pms.system.seed import (  # noqa: E402
    DEFAULT_PASSWORD,
    USERS,
    reset_password,
    seed_all,
)


def build_parser() -> argparse.ArgumentParser:
    """构造参数解析器。"""
    parser = argparse.ArgumentParser(description="PMS 初始化种子数据")
    parser.add_argument("--password", default=DEFAULT_PASSWORD, help="新建账号的初始密码")
    parser.add_argument("--list", action="store_true", help="仅列出内置账号清单")
    parser.add_argument("--reset-password", metavar="USERNAME", help="重置指定账号密码")
    return parser


def print_accounts() -> None:
    """打印内置账号清单。"""
    print("内置账号（部门 / 角色）：")
    for username, real_name, dept_code, role_codes in USERS:
        print(f"  {username:<12} {real_name:<10} {dept_code:<8} {','.join(role_codes)}")


async def run(password: str) -> int:
    """执行初始化并返回退出码。"""
    factory = get_session_factory()
    try:
        async with factory() as session:
            summary = await seed_all(session, password=password)
    finally:
        await dispose_engine()
    print(
        "新增：字典 {d}（项 {di}）/ 权限 {p} / 角色 {r}（授权 {rp}）/"
        " 部门 {dp} / 账号 {u}（授权 {ur}）/ 参数 {c}".format(
            d=summary.dicts,
            di=summary.dict_items,
            p=summary.permissions,
            r=summary.roles,
            rp=summary.role_permissions,
            dp=summary.depts,
            u=summary.users,
            ur=summary.user_roles,
            c=summary.configs,
        )
    )
    print(f"初始密码：{password}（首次登录后请修改）")
    print_accounts()
    return 0


async def reset(username: str, password: str) -> int:
    """重置单个账号密码并返回退出码。"""
    factory = get_session_factory()
    try:
        async with factory() as session:
            ok_reset = await reset_password(session, username, password)
    finally:
        await dispose_engine()
    if not ok_reset:
        print(f"账号不存在：{username}")
        return 1
    print(f"已重置 {username} 的密码为：{password}")
    return 0


def main() -> int:
    """入口。"""
    args = build_parser().parse_args()
    if args.list:
        print_accounts()
        return 0
    if not args.password:
        print("密码不能为空")
        return 2
    if args.reset_password:
        return asyncio.run(reset(args.reset_password, args.password))
    return asyncio.run(run(args.password))


if __name__ == "__main__":
    raise SystemExit(main())
