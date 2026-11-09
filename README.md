# PMS 项目全周期管理与变更系统

按 `doc/` 下的设计稿实现：项目周期管理、变更管理、工作日志、统计看板、四维权限（功能 / 数据范围 / 项目 / 字段）。

## 技术栈

- 后端：**Python 3.12** + FastAPI + SQLAlchemy 2（async）+ Pydantic v2 + Alembic + Uvicorn（`backend/`）
- 存储：MySQL 8（`192.168.1.136` / 库 `qloffice`）+ Redis 7（缓存 / 会话黑名单 / 幂等）
- 附件：服务器本地磁盘 `backend/data/uploads`（预留对象存储适配）
- 前端：Vue 3 + TypeScript + Vite + Element Plus（`frontend/`），**响应式**，手机端可查看与填报；
  构建产物 `frontend/dist` 随仓库发布，**运行期由 Python 直接托管，不需要 Node.js**
- 启动方式：**纯 Python**（`backend/scripts/start.py` 或 `py -3.12 -m pms.main`），单进程 Uvicorn 同时提供
  `/api/v1` 接口与前端页面，无需 Node、无需 Nginx
- 容量定位：小企业规模（注册用户 ≤ 300、同时在线 ≤ 20），单进程 + 连接池默认参数即可承载
- 质量：`ruff` / `mypy --strict` / `pytest`

## 目录

```
backend/                后端（Python 3.12 + FastAPI）
  src/pms/              业务代码：common/ core/ org/ system/ crm/ project/ change/ worklog/ report/ file/ audit/ jobs/
  tests/                unit/ integration/
  migrations/           Alembic 迁移
  scripts/              init_layout / backup / version / docgen / seed / start（一键启动）
  data/uploads/         附件存储（按项目分目录）
  alembic.ini  pyproject.toml  requirements.txt  .env
frontend/               前端（Vue 3 + TS + Vite + Element Plus）
  src/                  api/ layout/ router/ stores/ views/
  dist/                 构建产物（随仓库发布，由后端托管）
  index.html  vite.config.ts  package.json  tsconfig*.json
doc/                    设计稿（00~14）+ incremental/ + full/ + templates/
backups/                修改前备份（只追加，运行时自动创建）
README.md  VERSION  .gitignore
```

## 快速开始

```bash
cd backend
py -3.12 -m venv .venv
.venv\Scripts\activate
py -3.12 -m pip install -r requirements.txt    # 或 pip install -e ".[dev]"
copy .env.example .env        # 填写 DB_PASSWORD 等
py -3.12 -m alembic upgrade head
py -3.12 backend/scripts/seed.py --password Pms@12345   # 初始化部门/角色/权限点/字典/账号（幂等）
cd ..
py -3.12 backend\scripts\start.py               # 一键启动：后端 + 前端，自动打开浏览器
```

> 全程 **不需要 Node.js**：前端构建产物 `frontend/dist` 已随仓库发布，由 Python 直接托管。
> `backend/scripts/start.py` 会自动把 `backend/src/` 加入模块搜索路径（未 `pip install -e .` 也能启动），
> 就绪后自动打开 `http://127.0.0.1:8000/`。

### 前端开发（需要 Node 20）

```bash
cd frontend
npm install          # 首次或依赖变更后
npm run dev          # http://localhost:5173，/api 由 Vite 代理到 127.0.0.1:8000
npm run build        # 产出 dist/，由后端单进程托管
```

### 内置账号（初始密码以执行 `seed.py` 时指定的为准）

| 账号 | 姓名 | 部门 | 角色 | 数据范围 |
| --- | --- | --- | --- | --- |
| `admin` | 系统管理员 | 总公司 | ADMIN | 全公司 |
| `ceo` | 公司领导 | 总公司 | EXEC | 全公司 |
| `pmo` | PMO 专员 | PMO 部 | PMO | 全公司 |
| `sales_lead` `pm_lead` `dev_lead` `test_lead` `ops_lead` | 各部门经理 | 对应部门 | DEPT_HEAD + 部门角色 | 本部门及下级 |
| `sale1` `pm1` `dev1` `dev2` `test1` `ops1` | 员工 | 对应部门 | SALES / PM / DEV / TEST / OPS | 参与项目 / 仅本人 |

```bash
py -3.12 backend/scripts/seed.py --list                                   # 只看账号清单
py -3.12 backend/scripts/seed.py --reset-password dev1 --password New@123  # 重置并解锁账号
```

### 启动方式（三选一，均为纯 Python）

```bash
py -3.12 backend/scripts/start.py                    # 推荐：自检 + 启动 + 自动打开浏览器
py -3.12 backend/scripts/start.py --host 0.0.0.0 --port 8080 --no-open   # 局域网访问 / 不开浏览器
py -3.12 -m pms.main --host 127.0.0.1 --port 8080 --reload       # 等价的内置入口
py -3.12 backend/scripts/start.py --check            # 只做环境自检，不启动
```

监听地址/端口取 `APP_HOST` / `APP_PORT`（默认 `0.0.0.0:8000`），命令行参数可覆盖；
安装后也可用 `pms` 命令启动。容量定位为小企业（并发 ≤ 20），**默认单进程**即可；
确需多进程时加 `--workers 2`（定时任务有 `t_sys_job_lock` 去重，不会重复执行）。

> 前提：`pms` 包需已装入当前解释器。`py -3.12 -m pms.main` 报 `No module named 'pms'` 时，
> 在 `backend/` 下执行 `py -3.12 -m pip install -e . --no-deps`（依赖已装可加 `--no-deps`，
> 离线再加 `--no-build-isolation`），或临时设置 `PYTHONPATH=backend/src`。
> `alembic` 命令需在 `backend/` 目录下执行（`alembic.ini` 位于该目录）。

- 前端页面：`http://localhost:8000/`（admin / `Pms@12345`）
- 接口文档：`http://localhost:8000/docs`

## 变更规范（必读）

修改任何文件前：

1. `py -3.12 backend/scripts/backup.py <待改文件...>`
2. 改代码（遵循 `doc/00` 设计稿与 Python 3.12 规范）
3. `py -3.12 backend/scripts/version.py bump`
4. `py -3.12 backend/scripts/docgen.py incremental --title "主题"` 并填写「修改前 → 修改后 → 理由 → 验证 → 回滚」
5. `py -3.12 backend/scripts/docgen.py full` 与 `py -3.12 backend/scripts/docgen.py index`

## 当前进度

- 设计稿 v1.1.2 已确认（Python 3.12 技术栈、客户与商机纳入一期、规则后台可调、响应式 Web）
- **I0 基础框架**：统一响应体 / 异常 / 错误码、配置、数据库会话、Redis、JWT、traceId 日志
- **I1 组织与权限**：部门 / 用户 / 角色 / 权限点模型，数据范围求解（需求 3 可见性规则），
  `ConfigService` 系统参数（**所有业务规则阈值后台可调**），登录/登出/用户/角色/授权/参数接口
- **I2 客户与商机 + 项目周期**：客户/联系人/商机/跟进、**商机转项目**；项目立项审批（层级按金额阈值）、
  状态机、阶段、里程碑、WBS 任务、成员、基线冻结、进度加权重算；数据库已建 28 张表
- **初始化种子数据**：字典 13 组（55 项）、权限点 31、角色 9、部门 7（含负责人与层级）、
  登录账号 14（默认密码 `Pms@12345`），`backend/scripts/seed.py` 幂等执行
- **I3 变更管理**：六维影响评估 → **自动定级 L1/L2/L3**（阈值后台可调）→
  **项目总监会签**（`t_prj_director`，可多人，全部通过才推进）→ PMO →（L3）公司领导 →
  批准后应用影响项（任务/里程碑/阶段/预算/成员）→ 冻结新基线 V(n+1)；**发起人限项目经理**
- **I4 工作日志**：**全员可填、一人一天可多条、按项目填报**（可选任务）、提交校验（合计一致/0 工时/当日累计超 24h）、
  当日累计工时超 8h 仅告警不禁止、可选日期为最近 5 天（后台参数可调）、T+3 以上补填审批、
  PM 确认回填工时与进度、撤销回滚、**同项目组互看 / 同部门非同项目默认不看**；
  未填仅 09:00 催办 + 页面提示（`worklog.remind.enabled` 可关），不阻断任何流程
- **I5 统计看板**：EV/SPI/CPI/健康度指标内核、日预聚合（`t_st_*`）、公司/部门/项目三级看板；
  个人工时统计并入「工作日志」页（今日/本周/本月切换），不再单独设个人看板
- **I6 前端（Vue3 响应式）**：`frontend/`（Vue3 + TS + Vite + Element Plus），覆盖登录、公司看板、部门看板、
  项目周期、变更管理、工作日志、客户商机、规则参数；**11 个菜单全部按权限点过滤**（无权限跳 `/403`），
  项目详情含成员/项目总监/阶段/任务/里程碑/文档页签；≤768px 侧栏转抽屉、窄屏隐藏次要列
- **定时任务**：`backend/src/pms/jobs/`（APScheduler）—— 日志催办 09:00、看板日聚合 01:00、变更审批 SLA 02:00
- **手册**：`doc/13-部署与运维手册.md`、`doc/14-用户手册.md`
- **审计留痕**：`backend/src/pms/audit/` —— 登录日志（成功/失败/登出）+ 中间件自动留痕（写操作全量、
  读操作仅失败与权限拒绝），口令令牌脱敏、**独立事务**、可按 `sys:log:view` 查询；前端「审计留痕」页
- **多实例定时任务去重**：`t_sys_job_lock` 分布式锁（抢占 / 续期 / 过期接管），任务由 `run_exclusive` 包装，
  开关 `job.enabled` 与 TTL `job.lock.ttlSeconds` 后台可调
- **审计表按月归档**：`backend/src/pms/audit/archive.py` + `backend/scripts/archive_audit.py` —— 按月把超出保留期的
  `t_sys_operate_log` / `t_sys_login_log` 搬入 `_YYYYMM` 月份表（同结构），支持预演；
  保留期 `audit.keepMonths` 默认 12 个月，每月 1 日 03:00 自动执行（多实例去重），也可接口/前端手动触发
- **运行体验验收（v1.1.11）**：真实服务端到端 44 项断言全通过；修复 6 项缺陷
  （立项审批 500、Redis 降级阻塞 2s/次、`/worklogs/stats` 路由被抢、登出令牌未失效、
  PM 无法评估变更、商机阶段脏值）。看板 6.17s → **0.06s**，全量测试 186s → **9.3s**
- **纯 Python 一键启动（v1.1.12）**：`backend/scripts/start.py`（自检 + 启动 + 就绪自动开浏览器）；
  `frontend/dist` 随仓库发布，运行与部署**零 Node**；新增前端路由回落，`api/` 前缀仍返回 JSON 404
- **静态资源 MIME 修复（v1.1.13）**：本机 Windows 把 `.js` 登记为 `text/plain`，导致
  `<script type="module">` 被浏览器拒绝、前端白屏；`main.py` 启动时显式登记产物 MIME
- **组织管理界面（v1.1.14）**：「人员管理」（新增/编辑/启停/重置密码/角色授权）与
  「部门架构」（树形新增/改名/换负责人/调整上级/删除校验），菜单按权限点过滤；
  **项目立项可同时选择项目组成员**（负责人自动入组为 PM），详情页支持变更负责人与增删成员
- **工作日志按项目多条填报（v1.1.15）**：新增 `project_id` / `task_id`（迁移 `f2c9a1b7d3e8`），
  一人一天可多条、按项目选择任务填报；`GET /worklogs/options`（我参与的项目、补填窗口、工时阈值）、
  `GET /worklogs/day-summary`（当日累计工时，超 8h 返回提示、不禁止）、`DELETE /worklogs/{id}`（删除草稿）；
  新增参数 `worklog.backfill.maxDays=5`，`worklog.hours.warnPerDay` 默认 12 → 8
- **权限菜单 + 项目总监 + 文档（v1.1.16）**：10 个菜单全部按权限点过滤并新增 403 页；
  新增 `t_prj_director`（项目总监=项目级授权、可多人）与变更**总监会签**（`DIRECTOR` 节点同序多行，全部通过才进入 PMO）；
  新增文档模块 `backend/src/pms/file/`（本地按项目分目录 `backend/data/uploads/project_<id>/年/月/`、类型白名单、20MB 上限、鉴权下载）；
  项目阶段/里程碑支持编辑/删除/状态推进，阶段完成校验节点文档（`project.stage.docRequired`）；
  新增权限点 `project:stage:edit` / `project:doc:upload` / `project:doc:manage`，日志 `worklog:create` 扩至全员；
  迁移 `a7d3e5c9b2f4`；真实服务端到端 **64/64** 断言通过，全量测试 **116 passed**
- **规则参数中文化（v1.1.17）**：`defaults.py` 新增 `CONFIG_REMARKS`（46 项参数逐条中文含义，含单位与取值影响），
  `GET /configs` 的 `remark` 统一返回中文说明（库值为空或旧占位「vX.Y.Z 新增参数」时自动回落），
  `seed_defaults` 自动回填历史数据；「规则参数」页新增分组列、说明列常显、支持按中文含义筛选
- 待建：性能压测、安全加固其余项（密钥轮换、接口限流）
