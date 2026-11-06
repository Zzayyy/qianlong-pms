"""审计留痕与多实例任务锁（设计稿 03 §7、11 §4）。

- `audit.service`：登录日志 `t_sys_login_log`、操作审计 `t_sys_operate_log`
- `audit.middleware`：写操作与拒绝访问的全量留痕
- `audit.lock`：定时任务分布式锁 `t_sys_job_lock`（多实例部署只执行一次）
"""

from __future__ import annotations
