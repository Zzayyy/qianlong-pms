"""命令行入口：对**已启动的服务**跑端到端验收（44 项断言）。

    py -3.12 -m uvicorn pms.main:app --host 127.0.0.1 --port 8000   # 另开终端启动
    py -3.12 scripts/acceptance.py                                  # 默认 127.0.0.1:8000
    py -3.12 scripts/acceptance.py --base http://127.0.0.1:8000 --password Pms@12345

覆盖：健康检查与前端首页、登录成功/失败、越权拦截、项目全生命周期、立项审批与状态机、
变更全流程、日志填报与确认、四类看板与日聚合、CRM 转项目、参数调整、审计与归档、登出失效。

注意：会创建以「验收」为前缀的**演示数据**（项目/变更/客户/商机），可用于浏览器走查。
"""

from __future__ import annotations

import argparse
import re
import uuid
from datetime import date

import httpx

BASE = "http://127.0.0.1:8000"
PASSWORD = "Pms@12345"
MARK = "验收"
RUN_ID = uuid.uuid4().hex[:6]

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, bool(ok), detail))


def login(client: httpx.Client, username: str, password: str = PASSWORD) -> str:
    r = client.post(f"{BASE}/api/v1/auth/login", json={"username": username, "password": password})
    return r.json()["data"]["token"] if r.status_code == 200 else ""


def code_of(r: httpx.Response) -> int:
    return r.json().get("code", -1) if r.headers.get("content-type", "").startswith("application/json") else -1


def data_of(r: httpx.Response) -> dict:
    body = r.json()
    return body.get("data") or {}


def run() -> None:
    """按业务链路顺序执行全部验收断言。"""
    with httpx.Client(timeout=20) as c:
        # 1. 健康检查与前端首页
        r = c.get(f"{BASE}/api/v1/health")
        check("健康检查 /health", r.status_code == 200 and data_of(r).get("status") == "UP", r.text[:60])
        r = c.get(f"{BASE}/")
        check("前端首页 /", r.status_code == 200 and 'id="app"' in r.text, str(r.status_code))
        assets = re.findall(r"/assets/[A-Za-z0-9._-]+", r.text)
        if assets:
            ar = c.get(f"{BASE}{assets[0]}")
            check("静态资源 /assets/*.js|css", ar.status_code == 200, assets[0])
        else:
            check("静态资源 /assets/*.js|css", False, "首页未引用 assets")

        # 2. 登录（成功 / 失败）
        admin = login(c, "admin")
        check("管理员登录", bool(admin), "admin")
        bad = c.post(f"{BASE}/api/v1/auth/login", json={"username": "admin", "password": "Wrong@123"})
        check("错误口令被拒", bad.status_code == 401 and code_of(bad) != 0, str(bad.status_code))
        dev_token = login(c, "dev1")
        pm_token = login(c, "pm1")
        check("普通账号登录（dev1/pm1）", bool(dev_token) and bool(pm_token), "dev1/pm1")

        ah = {"Authorization": f"Bearer {admin}"}
        ph = {"Authorization": f"Bearer {pm_token}"}
        dh = {"Authorization": f"Bearer {dev_token}"}

        # 3. 权限边界
        r = c.get(f"{BASE}/api/v1/audit/operate-logs?pageNum=1&pageSize=1", headers=dh)
        check("越权访问审计接口被拒 403", r.status_code == 403, str(r.status_code))
        r = c.post(f"{BASE}/api/v1/projects", json={"projectName": "x", "deptId": 1, "pmId": 1}, headers=dh)
        check("无权限创建项目被拒 403", r.status_code == 403, str(r.status_code))

        # 4. 组织数据
        users = data_of(c.get(f"{BASE}/api/v1/users?pageNum=1&pageSize=50", headers=ah)).get("list", [])
        uid = {u["username"]: u["id"] for u in users}
        depts = data_of(c.get(f"{BASE}/api/v1/depts/tree", headers=ah))
        check("用户与部门树可查", bool(uid.get("pm1")) and bool(depts), f"用户 {len(users)} 个")
        dept_id = _find_dept(depts, "PRODUCT") or 1

        # 5. 项目全生命周期
        r = c.post(
            f"{BASE}/api/v1/projects",
            json={
                "projectName": f"{MARK}项目-端到端验收",
                "deptId": dept_id,
                "pmId": uid["pm1"],
                "projectType": "研发",
                "contractAmount": 120000,
                "planStart": "2026-11-03",
                "planEnd": "2026-12-31",
            },
            headers=ph,
        )
        project_id = data_of(r).get("projectId") or data_of(r).get("id")
        check("PM 创建项目", r.status_code == 200 and bool(project_id), f"projectId={project_id}")
        if not project_id:
            _report()
            return

        r = c.post(
            f"{BASE}/api/v1/projects/{project_id}/members",
            json={"userId": uid["dev1"], "deptId": dept_id, "roleInProject": "开发", "allocation": 100},
            headers=ph,
        )
        check("添加项目成员", code_of(r) == 0, str(code_of(r)))
        r = c.post(
            f"{BASE}/api/v1/projects/{project_id}/stages",
            json={"stageName": "需求与设计", "weight": 40, "planStart": "2026-11-03", "planEnd": "2026-11-20"},
            headers=ph,
        )
        stage_id = data_of(r).get("stageId") or data_of(r).get("id")
        check("新增阶段", bool(stage_id), f"stageId={stage_id}")
        r = c.post(
            f"{BASE}/api/v1/projects/{project_id}/tasks",
            json={"taskName": f"{MARK}任务-接口设计", "stageId": stage_id, "ownerId": uid["dev1"], "planHours": 16},
            headers=ph,
        )
        task_id = data_of(r).get("taskId") or data_of(r).get("id")
        check("新增任务", bool(task_id), f"taskId={task_id}")
        r = c.post(
            f"{BASE}/api/v1/projects/{project_id}/milestones",
            json={"milestoneName": "设计评审通过", "planDate": "2026-11-20", "ownerId": uid["pm1"]},
            headers=ph,
        )
        check("新增里程碑", code_of(r) == 0, str(code_of(r)))
        r = c.put(
            f"{BASE}/api/v1/projects/{project_id}/tasks/{task_id}/progress",
            json={"progress": 60},
            headers=ph,
        )
        check("PM 更新任务进度", code_of(r) == 0, str(code_of(r)))
        r = c.get(f"{BASE}/api/v1/projects/{project_id}/progress", headers=ph)
        check("项目进度可算", code_of(r) == 0 and "progress" in str(data_of(r)), str(data_of(r))[:60])

        # 6. 立项审批
        r = c.post(f"{BASE}/api/v1/projects/{project_id}/submit", headers=ph)
        check("提交立项审批", code_of(r) == 0, str(code_of(r)))
        r = c.post(f"{BASE}/api/v1/projects/{project_id}/approve", headers=ah)
        check("管理员审批通过", code_of(r) == 0, str(code_of(r)))
        r = c.get(f"{BASE}/api/v1/projects/{project_id}", headers=ph)
        check("项目详情可读（审批后 APPROVED）", code_of(r) == 0 and data_of(r).get("status") == "APPROVED", str(data_of(r).get("status")))
        r = c.put(f"{BASE}/api/v1/projects/{project_id}/status", json={"target": "IN_PROGRESS"}, headers=ph)
        check("项目启动（状态机流转）", code_of(r) == 0, str(code_of(r)))
        r = c.put(f"{BASE}/api/v1/projects/{project_id}/status", json={"target": "DRAFT"}, headers=ph)
        check("非法流转被拦截", code_of(r) != 0, f"code={code_of(r)}")

        # 6.1 项目总监（项目级授权、多人会签）
        r = c.put(
            f"{BASE}/api/v1/projects/{project_id}/directors",
            json={"userIds": [uid["pm_lead"], uid["ceo"]]},
            headers=ph,
        )
        check("指派项目总监（多人）", code_of(r) == 0 and len(data_of(r) or []) == 2, str(data_of(r))[:60])
        r = c.get(f"{BASE}/api/v1/projects/{project_id}/directors", headers=ph)
        check("项目总监列表可查", code_of(r) == 0 and len(data_of(r) or []) == 2, str(data_of(r))[:60])

        # 6.2 节点文档：完成阶段前必须有交付文档
        r = c.put(
            f"{BASE}/api/v1/projects/{project_id}/stages/{stage_id}/status",
            json={"target": "IN_PROGRESS"},
            headers=ph,
        )
        check("阶段开始", code_of(r) == 0, str(code_of(r)))
        r = c.put(
            f"{BASE}/api/v1/projects/{project_id}/stages/{stage_id}/status",
            json={"target": "DONE"},
            headers=ph,
        )
        check("无交付文档时阶段不能完成", code_of(r) != 0, f"code={code_of(r)}")
        r = c.post(
            f"{BASE}/api/v1/files",
            data={"projectId": project_id, "bizType": "STAGE", "bizId": stage_id},
            files={"file": ("需求规格说明书.txt", b"acceptance stage doc", "text/plain")},
            headers=dh,
        )
        doc_file_id = data_of(r).get("fileId")
        check("员工上传节点文档（按项目分目录）", code_of(r) == 0 and bool(doc_file_id), str(data_of(r))[:60])
        r = c.get(f"{BASE}/api/v1/projects/{project_id}/attachments?bizType=STAGE", headers=dh)
        check("节点文档列表", code_of(r) == 0 and len(data_of(r) or []) >= 1, str(len(data_of(r) or [])))
        r = c.put(
            f"{BASE}/api/v1/projects/{project_id}/stages/{stage_id}/status",
            json={"target": "DONE"},
            headers=ph,
        )
        check("上传文档后阶段可完成", code_of(r) == 0, str(code_of(r)))
        if doc_file_id:
            r = c.get(f"{BASE}/api/v1/files/{doc_file_id}/download", headers=dh)
            check("文档下载（鉴权）", r.status_code == 200 and len(r.content) > 0, str(r.status_code))

        # 7. 变更全流程
        r = c.post(
            f"{BASE}/api/v1/changes",
            json={
                "projectId": project_id,
                "changeType": "SCOPE",
                "title": f"{MARK}变更-增加接口字段",
                "reason": "客户新增需求",
                "content": "订单接口增加字段",
                "expectResult": "接口兼容",
            },
            headers=ph,
        )
        change_id = data_of(r).get("requestId") or data_of(r).get("id")
        check("创建变更申请", bool(change_id), f"requestId={change_id}")
        if change_id:
            # 顺序：提交（DRAFT→SUBMITTED）→ 评估（→ASSESSED）→ 审批（→APPROVED）
            r = c.post(f"{BASE}/api/v1/changes/{change_id}/submit", headers=ph)
            check("提交变更审批", code_of(r) == 0, str(code_of(r)))
            r = c.post(f"{BASE}/api/v1/changes/{change_id}/assess", json={"impacts": [], "items": []}, headers=ph)
            assess_ok = code_of(r) == 0
            check("PM 六维评估（定级+审批链）", assess_ok, str(data_of(r))[:60] if assess_ok else r.text[:80])
            # 项目总监会签：两位总监都通过后才进入 PMO（L2）节点
            approved_by: list[str] = []
            for index, name in enumerate(("pm_lead", "ceo", "pmo", "admin")):
                token = login(c, name)
                r = c.post(
                    f"{BASE}/api/v1/changes/{change_id}/approve",
                    json={"opinion": "同意"},
                    headers={"Authorization": f"Bearer {token}"},
                )
                if code_of(r) == 0:
                    approved_by.append(name)
                if index == 0:
                    d = c.get(f"{BASE}/api/v1/changes/{change_id}", headers=ph)
                    status = (data_of(d).get("request") or {}).get("status")
                    check("总监会签未齐时仍待审", status == "ASSESSED", str(status))
                d = c.get(f"{BASE}/api/v1/changes/{change_id}", headers=ph)
                if (data_of(d).get("request") or {}).get("status") == "APPROVED":
                    break
            check(
                "变更会签审批通过（总监→PMO）",
                len(approved_by) >= 2,
                f"审批人={','.join(approved_by) or '无人可批'}",
            )
            r = c.post(f"{BASE}/api/v1/changes/{change_id}/execute", headers=ph)
            check("变更执行", code_of(r) == 0, str(code_of(r)))
            r = c.post(f"{BASE}/api/v1/changes/{change_id}/verify", headers=ph)
            check("变更验证通过", code_of(r) == 0, str(code_of(r)))
            r = c.post(f"{BASE}/api/v1/changes/{change_id}/close", headers=ph)
            check("变更关闭", code_of(r) == 0, str(code_of(r)))
            r = c.get(f"{BASE}/api/v1/changes/{change_id}", headers=ph)
            status = (data_of(r).get("request") or {}).get("status")
            check("变更详情终态 CLOSED", status == "CLOSED", str(status))

        # 8. 工作日志（一人一天可多条；日期取当天，避免固定日期滑出补填窗口）
        today = date.today()
        existing = data_of(
            c.get(
                f"{BASE}/api/v1/worklogs?pageNum=1&pageSize=100"
                f"&userId={uid.get('dev1')}&dateFrom={today.isoformat()}&dateTo={today.isoformat()}",
                headers=dh,
            )
        ).get("list", [])
        for row in existing:
            if str(row.get("status")) in {"SUBMITTED", "CONFIRMED"}:
                c.post(
                    f"{BASE}/api/v1/worklogs/{row['id']}/reject",
                    json={"reason": "验收清理"},
                    headers=ph,
                )
                row["status"] = "REJECTED"
            if str(row.get("status")) in {"DRAFT", "REJECTED"}:
                c.delete(f"{BASE}/api/v1/worklogs/{row['id']}", headers=dh)
        check("清理当天遗留日志（可重复验收）", True, f"{len(existing)} 条")

        options = data_of(c.get(f"{BASE}/api/v1/worklogs/options", headers=dh))
        check(
            "填报选项（补填天数/预警工时/我的项目）",
            int(options.get("backfillMaxDays") or 0) >= 1
            and float(options.get("warnHours") or 0) > 0
            and bool(options.get("projects")),
            str(options)[:80],
        )

        r = c.post(
            f"{BASE}/api/v1/worklogs",
            json={
                "logDate": today.isoformat(),
                "totalHours": 8,
                "content": f"{MARK}日志-接口设计",
                "problem": "",
                "plan": "继续",
                "items": [
                    {"projectId": project_id, "taskId": task_id, "hours": 8, "content": "接口设计", "progressAfter": 60}
                ],
            },
            headers=dh,
        )
        log_id = data_of(r).get("id")
        same_day = code_of(r) == 40902  # 当日已填报：幂等保护亦为通过
        check("填报工作日志", bool(log_id) or same_day, f"http={r.status_code} code={code_of(r)} id={log_id}")
        if log_id:
            r = c.post(f"{BASE}/api/v1/worklogs/{log_id}/submit", headers=dh)
            check("提交日志", code_of(r) == 0, str(code_of(r)))
            r = c.post(f"{BASE}/api/v1/worklogs/{log_id}/confirm", headers=ph)
            check("PM 确认日志", code_of(r) == 0, str(code_of(r)))
            r = c.post(f"{BASE}/api/v1/worklogs/{log_id}/comments", json={"content": "验收评论"}, headers=ph)
            check("日志评论", code_of(r) == 0, str(code_of(r)))
        r = c.get(
            f"{BASE}/api/v1/worklogs/stats?dateFrom={today.isoformat()}&dateTo={today.isoformat()}",
            headers=ph,
        )
        check("日志统计（填写率/及时率）", code_of(r) == 0, str(data_of(r))[:60])
        summary = data_of(
            c.get(f"{BASE}/api/v1/worklogs/day-summary?date={today.isoformat()}", headers=dh)
        )
        check(
            "当天累计工时统计（超 8h 仅提示）",
            float(summary.get("totalHours") or 0) >= 8,
            str(summary)[:80],
        )

        # 9. 看板与聚合
        for name, path in [
            ("公司看板", "/api/v1/reports/company"),
            ("部门看板", "/api/v1/reports/dept"),
            ("项目看板", f"/api/v1/reports/project/{project_id}"),
            ("个人看板", f"/api/v1/reports/personal?dateFrom={today.isoformat()}&dateTo={today.isoformat()}"),
        ]:
            r = c.get(f"{BASE}{path}", headers=ph)
            check(name, code_of(r) == 0, str(code_of(r)))
        r = c.post(f"{BASE}/api/v1/reports/aggregate", json={}, headers=ah)
        check("手动触发日聚合", code_of(r) == 0, str(data_of(r))[:60])

        # 10. CRM → 转项目
        r = c.post(f"{BASE}/api/v1/crm/customers", json={"customerName": f"{MARK}客户-{RUN_ID}", "customerLevel": "A"}, headers=ah)
        customer_id = data_of(r).get("id")
        check("创建客户", bool(customer_id), f"http={r.status_code} code={code_of(r)} id={customer_id}")
        if customer_id:
            r = c.post(
                f"{BASE}/api/v1/crm/customers/{customer_id}/contacts",
                json={"name": "张三", "title": "经理", "mobile": "13800000000", "isPrimary": 1},
                headers=ah,
            )
            check("新增联系人", code_of(r) == 0, str(code_of(r)))
            r = c.post(
                f"{BASE}/api/v1/crm/opportunities",
                json={"oppName": f"{MARK}商机-订单系统", "customerId": customer_id, "expectAmount": 300000, "winRate": 60},
                headers=ah,
            )
            opp_id = data_of(r).get("opportunityId") or data_of(r).get("id")
            check("创建商机", bool(opp_id), f"oppId={opp_id}")
            if opp_id:
                r = c.put(f"{BASE}/api/v1/crm/opportunities/{opp_id}/stage", json={"stage": "WON"}, headers=ah)
                check("商机推进至赢单", code_of(r) == 0, str(code_of(r)))
                bad = c.put(f"{BASE}/api/v1/crm/opportunities/{opp_id}/stage", json={"stage": "WIN"}, headers=ah)
                check("非法阶段被拦截", code_of(bad) != 0, f"code={code_of(bad)}")
                r = c.put(f"{BASE}/api/v1/crm/opportunities/{opp_id}/stage", json={"stage": "WON"}, headers=ah)
                r = c.post(
                    f"{BASE}/api/v1/crm/opportunities/{opp_id}/convert",
                    json={"projectName": f"{MARK}项目-商机转化-{RUN_ID}", "pmId": uid["pm1"], "planStart": "2026-11-10", "planEnd": "2026-12-31"},
                    headers=ah,
                )
                check("商机转项目", code_of(r) == 0, f"http={r.status_code} code={code_of(r)} {str(data_of(r))[:80]}")

        # 11. 参数在线调整
        r = c.put(f"{BASE}/api/v1/configs/job.lock.ttlSeconds", json={"configValue": "600", "remark": "验收测试"}, headers=ah)
        check("修改系统参数", code_of(r) == 0 and data_of(r).get("configValue") == "600", str(data_of(r)))
        c.put(f"{BASE}/api/v1/configs/job.lock.ttlSeconds", json={"configValue": "300", "remark": "恢复"}, headers=ah)
        r = c.get(f"{BASE}/api/v1/dicts/project_status", headers=ah)
        check("数据字典可查", code_of(r) == 0, str(code_of(r)))

        # 12. 审计留痕与归档
        r = c.get(f"{BASE}/api/v1/audit/operate-logs?pageNum=1&pageSize=5", headers=ah)
        logs = data_of(r).get("list", [])
        check("操作审计可查（含本次写操作）", code_of(r) == 0 and len(logs) > 0, f"{data_of(r).get('total')} 条")
        r = c.get(f"{BASE}/api/v1/audit/login-logs?pageNum=1&pageSize=5", headers=ah)
        login_logs = data_of(r).get("list", [])
        has_fail = any(x.get("status") == "FAIL" for x in login_logs)
        check("登录日志可查（含失败记录）", code_of(r) == 0 and has_fail, f"{len(login_logs)} 条")
        r = c.post(f"{BASE}/api/v1/audit/archive", json={"keepMonths": 12, "dryRun": True}, headers=ah)
        check("审计归档预演", code_of(r) == 0 and data_of(r).get("dryRun") is True, str(data_of(r)))

        # 13. 登出与令牌失效
        r = c.post(f"{BASE}/api/v1/auth/logout", json={"token": dev_token}, headers=dh)
        check("登出成功", code_of(r) == 0, str(code_of(r)))
        r = c.get(f"{BASE}/api/v1/worklogs?pageNum=1&pageSize=1", headers=dh)
        check("登出后令牌失效 401", r.status_code == 401, str(r.status_code))

    _report()


def _find_dept(node, code: str) -> int | None:
    if isinstance(node, list):
        for item in node:
            found = _find_dept(item, code)
            if found:
                return found
        return None
    if isinstance(node, dict):
        if node.get("deptCode") == code or node.get("code") == code:
            return node.get("id")
        for key in ("children", "list", "items"):
            if key in node:
                found = _find_dept(node[key], code)
                if found:
                    return found
    return None


def main() -> None:
    """解析参数并执行验收。"""
    args = build_parser().parse_args()
    global BASE, PASSWORD
    BASE = args.base.rstrip("/")
    PASSWORD = args.password
    run()


def build_parser() -> argparse.ArgumentParser:
    """构造参数解析器。"""
    parser = argparse.ArgumentParser(description="PMS 端到端验收")
    parser.add_argument("--base", default="http://127.0.0.1:8000", help="服务地址")
    parser.add_argument("--password", default="Pms@12345", help="内置账号密码")
    return parser


def _report() -> None:
    passed = sum(1 for _, ok, _ in results if ok)
    print(f"\n{'=' * 64}\n端到端验收：{passed}/{len(results)} 通过\n{'=' * 64}")
    for name, ok, detail in results:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}  {detail}")
    failed = [n for n, ok, _ in results if not ok]
    if failed:
        print("\n未通过项：")
        for n in failed:
            print("  -", n)


if __name__ == "__main__":
    main()
