"""周报提示词接口：模板的查看与维护（系统管理员 / PMO / 部门领导）。

权限口径：
- 查看：权限点 `weekly:prompt:manage`，部门范围受限（只看自己可见部门 + 全公司默认）；
- 维护：系统管理员 / PMO 可维护全公司默认模板，部门领导只能维护本部门及下级部门；
- 生成周报时会自动按「部门 → 上级部门 → 全公司默认 → 内置」匹配模板。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from pms.common.response import ok
from pms.core.context import AuthContext
from pms.core.deps import get_session, require_permissions
from pms.weekly import prompt_service

router = APIRouter(prefix="/api/v1/weekly-prompts", tags=["周报提示词"])

PROMPT_MANAGE_PERM: str = "weekly:prompt:manage"


class PromptIn(BaseModel):
    """新建提示词模板。"""

    scope: str = "PERSONAL"
    deptId: int = 0
    name: str = Field(min_length=1, max_length=100)
    systemPrompt: str = Field(default="", max_length=4000)
    userPrompt: str = Field(min_length=1, max_length=20000)
    enabled: int = 1
    remark: str = Field(default="", max_length=200)


class PromptUpdateIn(BaseModel):
    """编辑提示词模板（部门归属不可改）。"""

    name: str = Field(min_length=1, max_length=100)
    systemPrompt: str = Field(default="", max_length=4000)
    userPrompt: str = Field(min_length=1, max_length=20000)
    enabled: int = 1
    remark: str = Field(default="", max_length=200)


class PromptCopyIn(BaseModel):
    """复制模板到指定部门。"""

    deptId: int = 0
    name: str = Field(default="", max_length=100)


@router.get("/variables", summary="提示词可用变量")
async def variables(
    context: Annotated[
        AuthContext, Depends(require_permissions(PROMPT_MANAGE_PERM))
    ],
) -> object:
    """返回模板占位符清单（前端写提示词时的参考）。

    注：必须定义在 `/{prompt_id}` 之前，否则会被路径参数路由抢先匹配。
    """
    del context
    return ok([{"key": key, "remark": remark} for key, remark in prompt_service.VARIABLES])


@router.get("", summary="提示词模板列表")
async def list_prompts(
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[
        AuthContext, Depends(require_permissions(PROMPT_MANAGE_PERM))
    ],
    scope: Annotated[str, Query(pattern="^(PROJECT|PERSONAL|)$")] = "",
) -> object:
    """列出模板（含适用部门与当前生效标记），首次访问补齐默认模板。"""
    if await prompt_service.ensure_defaults(session, operator_id=context.user_id):
        await session.commit()
    items = await prompt_service.list_prompts(session, context, scope=scope)
    return ok(
        {
            "items": items,
            "canManageGlobal": prompt_service.can_manage_global(context),
            "deptId": context.dept_id,
            "deptPath": context.dept_path,
        }
    )


@router.post("", summary="新建提示词模板")
async def create_prompt(
    body: PromptIn,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[
        AuthContext, Depends(require_permissions(PROMPT_MANAGE_PERM))
    ],
) -> object:
    """为指定部门（0 表示全公司默认）新建一套提示词。"""
    row = await prompt_service.create_prompt(
        session,
        context,
        scope=body.scope,
        dept_id=body.deptId,
        name=body.name,
        system_prompt=body.systemPrompt,
        user_prompt=body.userPrompt,
        enabled=body.enabled,
        remark=body.remark,
    )
    await session.commit()
    return ok({"id": int(row.id)})


@router.put("/{prompt_id}", summary="编辑提示词模板")
async def update_prompt(
    prompt_id: int,
    body: PromptUpdateIn,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[
        AuthContext, Depends(require_permissions(PROMPT_MANAGE_PERM))
    ],
) -> object:
    """修改模板内容与启用状态，立即对后续生成生效。"""
    row = await prompt_service.update_prompt(
        session,
        context,
        prompt_id,
        name=body.name,
        system_prompt=body.systemPrompt,
        user_prompt=body.userPrompt,
        enabled=body.enabled,
        remark=body.remark,
    )
    await session.commit()
    return ok({"id": int(row.id), "enabled": int(row.enabled)})


@router.delete("/{prompt_id}", summary="删除提示词模板")
async def delete_prompt(
    prompt_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[
        AuthContext, Depends(require_permissions(PROMPT_MANAGE_PERM))
    ],
) -> object:
    """删除部门模板；系统内置默认模板不可删除。"""
    await prompt_service.delete_prompt(session, context, prompt_id)
    await session.commit()
    return ok({"deleted": 1})


@router.post("/{prompt_id}/copy", summary="复制提示词模板")
async def copy_prompt(
    prompt_id: int,
    body: PromptCopyIn,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[
        AuthContext, Depends(require_permissions(PROMPT_MANAGE_PERM))
    ],
) -> object:
    """以现有模板为蓝本复制到指定部门（从全公司默认拉一套部门版）。"""
    row = await prompt_service.copy_prompt(
        session, context, prompt_id, dept_id=body.deptId, name=body.name
    )
    await session.commit()
    return ok({"id": int(row.id)})
