import { del, download, get, post, put, upload, type Page } from './http'

export type { Page }

/* ------------------------------ 认证 ------------------------------ */

export interface LoginResult {
  token: string
  expiresIn: number
  user: { id: string; username: string; realName: string; deptId: string; status: string }
  roles: string[]
  permissions: string[]
  mustChangePassword?: boolean
}

export interface Profile {
  id: string
  username: string
  realName: string
  deptId: string
  deptName?: string
  mobile?: string
  email?: string
  roles: string[]
  permissions: string[]
  allScope: boolean
  mustChangePassword?: boolean
}

export const login = (username: string, password: string) =>
  post<LoginResult>('/auth/login', { username, password })

export const logout = () => post<null>('/auth/logout', { token: localStorage.getItem('pms_token') })

export const profile = () => get<Profile>('/auth/profile')

/** 本人修改密码：成功后所有已签发令牌失效，需要重新登录。 */
export const changePassword = (oldPassword: string, newPassword: string) =>
  put<null>('/auth/password', { oldPassword, newPassword })

/* ------------------------------ 项目 ------------------------------ */

export const listProjects = (params: Record<string, unknown>) =>
  get<Page<Record<string, unknown>>>('/projects', params)

export const createProject = (data: Record<string, unknown>) =>
  post<{ id: string; projectCode: string; status: string }>('/projects', data)

export const projectDetail = (id: string) => get<Record<string, unknown>>(`/projects/${id}`)

export const submitProject = (id: string) => post<{ status: string }>(`/projects/${id}/submit`)

export const approveProject = (id: string) => post<{ status: string }>(`/projects/${id}/approve`)

export const rejectProject = (id: string, reason: string) =>
  post<{ status: string }>(`/projects/${id}/reject`, { reason })

/** 项目状态流转：后端字段为 `target`（非 status）；`reason` 仅终止时使用。 */
export const changeProjectStatus = (id: string, target: string, reason = '') =>
  put<{ status: string }>(`/projects/${id}/status`, reason ? { target, reason } : { target })

export const listStages = (id: string) => get<Record<string, unknown>[]>(`/projects/${id}/stages`)

export const createStage = (id: string, data: Record<string, unknown>) =>
  post<{ id: string }>(`/projects/${id}/stages`, data)

export const updateStage = (id: string, stageId: string, data: Record<string, unknown>) =>
  put<{ id: string }>(`/projects/${id}/stages/${stageId}`, data)

export const deleteStage = (id: string, stageId: string) =>
  del<unknown>(`/projects/${id}/stages/${stageId}`)

export const stageStatus = (id: string, stageId: string, target: string) =>
  put<{ id: string; status: string }>(`/projects/${id}/stages/${stageId}/status`, { target })

export const listTasks = (id: string) => get<Record<string, unknown>[]>(`/projects/${id}/tasks`)

export const createTask = (id: string, data: Record<string, unknown>) =>
  post<{ id: string }>(`/projects/${id}/tasks`, data)

export const updateTask = (id: string, taskId: string, data: Record<string, unknown>) =>
  put<{ id: string }>(`/projects/${id}/tasks/${taskId}`, data)

export const deleteTask = (id: string, taskId: string) =>
  del<unknown>(`/projects/${id}/tasks/${taskId}`)

export const updateTaskProgress = (id: string, taskId: string, progress: number) =>
  put<{ progress: number }>(`/projects/${id}/tasks/${taskId}/progress`, { progress })

export const recalcProgress = (id: string) => get<{ progress: number }>(`/projects/${id}/progress`)

export const listMilestones = (id: string) =>
  get<Record<string, unknown>[]>(`/projects/${id}/milestones`)

export const createMilestone = (id: string, data: Record<string, unknown>) =>
  post<{ id: string }>(`/projects/${id}/milestones`, data)

export const updateMilestone = (id: string, milestoneId: string, data: Record<string, unknown>) =>
  put<{ id: string }>(`/projects/${id}/milestones/${milestoneId}`, data)

export const deleteMilestone = (id: string, milestoneId: string) =>
  del<unknown>(`/projects/${id}/milestones/${milestoneId}`)

export const milestoneStatus = (id: string, milestoneId: string, target: string) =>
  put<{ id: string; status: string }>(`/projects/${id}/milestones/${milestoneId}/status`, {
    target,
  })

/** 项目总监（可多人，变更审批会签）。 */
export const projectDirectors = (id: string) =>
  get<Record<string, unknown>[]>(`/projects/${id}/directors`)

export const setProjectDirectors = (id: string, userIds: string[]) =>
  put<Record<string, unknown>[]>(`/projects/${id}/directors`, { userIds })

/** 项目/节点文档。 */
export const projectAttachments = (id: string, params: Record<string, unknown> = {}) =>
  get<Record<string, unknown>[]>(`/projects/${id}/attachments`, params)

export const uploadProjectFile = (form: FormData) =>
  upload<Record<string, unknown>>('/files', form)

export const deleteProjectFile = (fileId: string) => del<unknown>(`/files/${fileId}`)

export const downloadProjectFile = (fileId: string, fileName: string) =>
  download(`/files/${fileId}/download`, fileName)

/** 风险与问题（risk_type 区分 RISK / ISSUE）。 */
export const listRisks = (id: string, params: Record<string, unknown> = {}) =>
  get<Record<string, unknown>[]>(`/projects/${id}/risks`, params)

export const createRisk = (id: string, data: Record<string, unknown>) =>
  post<{ id: string }>(`/projects/${id}/risks`, data)

export const updateRisk = (id: string, riskId: string, data: Record<string, unknown>) =>
  put<{ id: string }>(`/projects/${id}/risks/${riskId}`, data)

export const changeRiskStatus = (id: string, riskId: string, status: string) =>
  put<{ id: string; status: string }>(`/projects/${id}/risks/${riskId}/status`, { status })

export const deleteRisk = (id: string, riskId: string) =>
  del<unknown>(`/projects/${id}/risks/${riskId}`)

/** 项目基线（立项基线 + 每次变更通过后的冻结快照）。 */
export const listBaselines = (id: string) =>
  get<Record<string, unknown>[]>(`/projects/${id}/baselines`)

export const baselineDetail = (id: string, baselineId: string) =>
  get<Record<string, unknown>>(`/projects/${id}/baselines/${baselineId}`)

export const listMembers = (id: string) => get<Record<string, unknown>[]>(`/projects/${id}/members`)

export const addMember = (id: string, data: Record<string, unknown>) =>
  post<{ id: string }>(`/projects/${id}/members`, data)

export const removeMember = (id: string, memberId: string) =>
  del<null>(`/projects/${id}/members/${memberId}`)

export const changeProjectPm = (id: string, pmId: string) =>
  put<{ id: string; pmId: string }>(`/projects/${id}/pm`, { pmId })

/* ------------------------------ 变更 ------------------------------ */

/** 周期排期明细：角色（开发/测试…）+ 负责人 + 日期范围。 */
export interface ChangeSchedule {
  id?: string
  roleName: string
  ownerId: string | number
  ownerName?: string
  planStart: string
  planEnd: string
  remark?: string
  applied?: number
}

export interface ChangeOptions {
  scheduleRoles: string[]
  changeTypes: string[]
  dimensions: string[]
  statuses: string[]
  /** 可发起变更的项目状态（R-CHG-02，后端下发，避免前端硬编码漂移）。 */
  projectStatuses: string[]
}

export const listChanges = (params: Record<string, unknown>) =>
  get<Page<Record<string, unknown>>>('/changes', params)

/** 变更页面选项（排期角色、类型/状态枚举，后台可调）。 */
export const changeOptions = () => get<ChangeOptions>('/changes/options')

export const changeDetail = (id: string) => get<Record<string, unknown>>(`/changes/${id}`)

export const createChange = (data: Record<string, unknown>) =>
  post<{ id: string; requestCode: string }>('/changes', data)

/** 编辑草稿基本信息（标题/原因/内容/期望结果/紧急）。 */
export const updateChange = (id: string, data: Record<string, unknown>) =>
  put<{ id: string; title: string; status: string }>(`/changes/${id}`, data)

/** 整体覆盖保存周期排期。 */
export const saveChangeSchedules = (id: string, items: ChangeSchedule[]) =>
  put<{ count: number }>(`/changes/${id}/schedules`, { items })

export const submitChange = (id: string) => post<{ status: string }>(`/changes/${id}/submit`)

export const assessChange = (id: string, data: Record<string, unknown>) =>
  post<{ level: string; status: string }>(`/changes/${id}/assess`, data)

/** 审批意见：后端字段为 `opinion`。 */
export const approveChange = (id: string, opinion = '') =>
  post<{ status: string }>(`/changes/${id}/approve`, { opinion })

export const rejectChange = (id: string, opinion = '') =>
  post<{ status: string }>(`/changes/${id}/reject`, { opinion })

export const changeAction = (id: string, action: string, payload: Record<string, unknown> = {}) =>
  post<{ status: string }>(`/changes/${id}/${action}`, payload)

/* ------------------------------ 日志 ------------------------------ */

export const saveWorklog = (data: Record<string, unknown>) =>
  post<Record<string, unknown>>('/worklogs', data)

/** 更新自己的草稿 / 被驳回日志。 */
export const updateWorklog = (id: string, data: Record<string, unknown>) =>
  put<Record<string, unknown>>(`/worklogs/${id}`, data)

export const worklogAction = (id: string, action: string, payload: Record<string, unknown> = {}) =>
  post<Record<string, unknown>>(`/worklogs/${id}/${action}`, payload)

export const listWorklogs = (params: Record<string, unknown>) =>
  get<Page<Record<string, unknown>>>('/worklogs', params)

/** 按当前筛选条件导出工作日志 CSV。 */
export const exportWorklogs = (params: Record<string, unknown>) => {
  const query = new URLSearchParams()
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') {
      query.set(key, String(value))
    }
  })
  const date = new Date().toISOString().slice(0, 10)
  return download(`/worklogs/export?${query.toString()}`, `worklogs-${date}.csv`)
}

/** 按当日 / 本周 / 本月汇总个人工时。 */
export const worklogSummary = (params: Record<string, unknown>) =>
  get<Record<string, unknown>>('/worklogs/summary', params)

/** 填报选项：补填天数上限、工时阈值与我参与的项目。 */
export const worklogOptions = () => get<Record<string, unknown>>('/worklogs/options')

/** 某人某天的累计工时与预警提示（不禁止提交）。 */
export const worklogDaySummary = (date: string, userId?: number) =>
  get<Record<string, unknown>>('/worklogs/day-summary', { date, userId })

export const worklogDetail = (id: string) => get<Record<string, unknown>>(`/worklogs/${id}`)

export const deleteWorklog = (id: string) => del<{ id: string }>(`/worklogs/${id}`)

export const worklogStats = (params: Record<string, unknown>) =>
  get<Record<string, number>>('/worklogs/stats', params)

export const worklogComments = (id: string) =>
  get<Record<string, unknown>[]>(`/worklogs/${id}/comments`)

export const addWorklogComment = (id: string, content: string, parentId: string | number = 0) =>
  post<{ id: string; parentId: string }>(`/worklogs/${id}/comments`, { content, parentId })

export const deleteWorklogComment = (worklogId: string, commentId: string) =>
  del<{ id: string }>(`/worklogs/${worklogId}/comments/${commentId}`)

/** 日志催办提醒（默认本人待处理）。 */
export const worklogReminders = (params: Record<string, unknown>) =>
  get<Page<Record<string, unknown>>>('/worklogs/reminders', params)

export const readWorklogReminder = (id: string) =>
  post<{ id: string; status: string }>(`/worklogs/reminders/${id}/read`)

export const readAllWorklogReminders = () =>
  post<{ count: number }>('/worklogs/reminders/read-all')

/** 指定日期待催办人员（需 worklog:manage）。 */
export const worklogReminderTargets = (date: string) =>
  get<Record<string, unknown>[]>('/worklogs/reminder-targets', { date })

/** 手动发起催办。 */
export const worklogRemind = (data: {
  userId: string | number
  logDate: string
  content?: string
}) => post<{ id: string }>('/worklogs/reminders', data)

/* ------------------------------ 消息通知 ------------------------------ */

export interface NoticeItem {
  id: string
  title: string
  content: string
  noticeType: string
  bizType: string
  bizId: string
  readStatus: number
  createTime: string
}

export const listNotices = (params: Record<string, unknown>) =>
  get<Page<NoticeItem>>('/notices', params)

export const noticeUnreadCount = () => get<{ count: number }>('/notices/unread-count')

export const readNotice = (id: string) =>
  post<{ id: string; readStatus: number }>(`/notices/${id}/read`)

export const readAllNotices = () => post<{ count: number }>('/notices/read-all')

/* ------------------------------ 邮件通知 ------------------------------ */

export interface MailConfig {
  enabled: boolean
  smtpHost: string
  smtpPort: number
  security: string
  smtpUser: string
  passwordSet: boolean
  smtpFrom: string
  fromName: string
  timeoutSeconds: number
  keepDays: number
  excludeOperator: boolean
  testTo: string
}

export interface MailTemplate {
  eventCode: string
  name: string
  message: string
  subject: string
  body: string
  receiverRoles: string
  enabled: boolean
  customized: boolean
}

export interface MailLog {
  id: string
  eventCode: string
  eventName: string
  recipient: string
  recipientName: string
  subject: string
  status: string
  retryCount: number
  error: string
  bizType: string
  bizId: string
  sentAt: string
  createTime: string
}

export const mailConfig = () => get<MailConfig>('/mail/config')

export const saveMailConfig = (data: Record<string, unknown>) =>
  put<{ saved: number }>('/mail/config', data)

export const testMail = (to: string) => post<{ sent: boolean }>('/mail/test', { to })

export const mailTemplates = () => get<MailTemplate[]>('/mail/templates')

export const saveMailTemplate = (eventCode: string, data: Record<string, unknown>) =>
  put<{ eventCode: string }>(`/mail/templates/${eventCode}`, data)

export const resetMailTemplate = (eventCode: string) =>
  post<{ eventCode: string }>(`/mail/templates/${eventCode}/reset`)

export const mailLogs = (params: Record<string, unknown>) =>
  get<Page<MailLog>>('/mail/logs', params)

export const resendMail = (id: string) => post<{ resent: boolean }>(`/mail/logs/${id}/resend`)

/* ------------------------------ 看板 ------------------------------ */

/** 我的待办项（工作台卡片：我的任务 / 我负责的项目 / 待确认日志 / 待审批变更等）。 */
export interface TodoItem {
  key: string
  label: string
  desc: string
  count: number
  path: string
  tone: 'primary' | 'warning' | 'danger'
}

export const myTodo = () => get<TodoItem[]>('/reports/my-todo')

/** 公司看板；`days` 仅影响趋势区间（KPI 与表格为实时指标）。 */
export const companyBoard = (days = 30) =>
  get<Record<string, unknown>>('/reports/company', { days })

/** 当前用户数据范围内可查看的部门（部门看板筛选）。 */
export const reportDepts = () =>
  get<{ id: string; parentId: string; deptName: string }[]>('/reports/depts')

/** 部门看板；`includeSub` 为 true 时连同下级部门一起统计。 */
export const deptBoard = (deptIds: string[], includeSub = false) =>
  get<Record<string, unknown>>('/reports/dept', {
    deptIds: deptIds.join(','),
    ...(includeSub ? { includeSub: true } : {})
  })

/** 部门近 N 天趋势（读日聚合快照）。 */
export const deptTrend = (deptIds: string[], includeSub = false, days = 30) =>
  get<Record<string, unknown>>('/reports/dept/trend', {
    deptIds: deptIds.join(','),
    days,
    ...(includeSub ? { includeSub: true } : {})
  })

/** 部门成员近 N 天负载（已确认工时 / 项目数 / 日志填写率）。 */
export const deptMembers = (deptIds: string[], includeSub = false, days = 30) =>
  get<Record<string, unknown>>('/reports/dept/members', {
    deptIds: deptIds.join(','),
    days,
    ...(includeSub ? { includeSub: true } : {})
  })

export const projectBoard = (id: string) => get<Record<string, unknown>>(`/reports/project/${id}`)

export const personalBoard = (params: Record<string, unknown>) =>
  get<Record<string, unknown>>('/reports/personal', params)

export const aggregateDaily = (statDate = '') => post<Record<string, number>>('/reports/aggregate', { statDate })

/* ------------------------------ CRM ------------------------------ */

/** 客户与商机概览（列表顶部统计卡片）。 */
export const crmSummary = () => get<Record<string, any>>('/crm/summary')

/** 数据范围内可选负责人 / 转项目负责人。 */
export const crmStaff = () => get<Record<string, any>[]>('/crm/staff')

/** 客户与商机页面参数（赢单阶段等后台可调）。 */
export const crmOptions = () => get<{ winStage: string }>('/crm/options')

export const listCustomers = (params: Record<string, unknown>) =>
  get<Page<Record<string, unknown>>>('/crm/customers', params)

export const customerDetail = (id: string) => get<Record<string, unknown>>(`/crm/customers/${id}`)

export const createCustomer = (data: Record<string, unknown>) =>
  post<{ id: string; customerCode: string }>('/crm/customers', data)

export const updateCustomer = (id: string, data: Record<string, unknown>) =>
  put<{ id: string }>(`/crm/customers/${id}`, data)

export const deleteCustomer = (id: string) => del<{ id: string }>(`/crm/customers/${id}`)

export const changeCustomerStatus = (id: string, status: string) =>
  put<{ id: string; status: string }>(`/crm/customers/${id}/status`, { status })

export const customerContacts = (id: string) =>
  get<Record<string, unknown>[]>(`/crm/customers/${id}/contacts`)

export const createContact = (customerId: string, data: Record<string, unknown>) =>
  post<{ id: string }>(`/crm/customers/${customerId}/contacts`, data)

export const updateContact = (id: string, data: Record<string, unknown>) =>
  put<{ id: string; isPrimary: number }>(`/crm/contacts/${id}`, data)

export const deleteContact = (id: string) => del<{ id: string }>(`/crm/contacts/${id}`)

export const listOpportunities = (params: Record<string, unknown>) =>
  get<Page<Record<string, unknown>>>('/crm/opportunities', params)

export const opportunityDetail = (id: string) =>
  get<Record<string, unknown>>(`/crm/opportunities/${id}`)

export const createOpportunity = (data: Record<string, unknown>) =>
  post<{ id: string; oppCode: string }>('/crm/opportunities', data)

export const updateOpportunity = (id: string, data: Record<string, unknown>) =>
  put<{ id: string; stage: string; status: string }>(`/crm/opportunities/${id}`, data)

export const deleteOpportunity = (id: string) =>
  del<{ id: string }>(`/crm/opportunities/${id}`)

export const pushOppStage = (id: string, stage: string, lostReason = '') =>
  put<{ id: string; stage: string; status: string }>(`/crm/opportunities/${id}/stage`, {
    stage,
    lostReason
  })

export const changeOppStatus = (id: string, status: string, lostReason = '') =>
  put<{ id: string; stage: string; status: string }>(`/crm/opportunities/${id}/status`, {
    status,
    lostReason
  })

export const convertOpp = (id: string, data: Record<string, unknown>) =>
  post<{ projectId: string; projectCode: string; projectName: string; status: string }>(
    `/crm/opportunities/${id}/convert`,
    data
  )

export const oppFollows = (id: string) =>
  get<Record<string, unknown>[]>(`/crm/opportunities/${id}/follows`)

export const addOppFollow = (id: string, data: Record<string, unknown>) =>
  post<{ id: string }>(`/crm/opportunities/${id}/follows`, data)

export const deleteOppFollow = (id: string) => del<{ id: string }>(`/crm/follows/${id}`)

/* ------------------------------ 组织与参数 ------------------------------ */

export const deptTree = () => get<Record<string, unknown>[]>('/depts/tree')

/** 部门选择项（只含标识信息，登录即可；选部门下拉一律用它，不占用 org:dept:view）。 */
export interface DeptOption {
  id: string
  parentId: string
  deptName: string
}

export const deptOptions = () => get<DeptOption[]>('/depts/options')

export const createDept = (data: Record<string, unknown>) =>
  post<{ id: string; deptCode: string }>('/depts', data)

export const updateDept = (id: string, data: Record<string, unknown>) =>
  put<{ id: string; deptName: string }>(`/depts/${id}`, data)

export const deleteDept = (id: string) => del<null>(`/depts/${id}`)

export const listUsers = (params: Record<string, unknown>) =>
  get<Page<Record<string, unknown>>>('/users', params)

/** 人员选择项（只含标识信息，登录即可；选人下拉一律用它，不占用 org:user:view）。 */
export interface UserOption {
  id: string
  username: string
  realName: string
  deptId: string
}

export const userOptions = () => get<UserOption[]>('/users/options')

export const createUser = (data: Record<string, unknown>) => post<{ id: string }>('/users', data)

export const updateUser = (id: string, data: Record<string, unknown>) =>
  put<{ id: string }>(`/users/${id}`, data)

export const changeUserStatus = (id: string, status: string) =>
  put<{ id: string; status: string }>(`/users/${id}/status`, { status })

/** 解除登录失败锁定（不重置密码）。 */
export const unlockUser = (id: string) => post<{ id: string }>(`/users/${id}/unlock`)

/** 删除用户（逻辑删除，需 org:user:delete）。 */
export const deleteUser = (id: string) => del<null>(`/users/${id}`)

/** 批量启用/停用。 */
export const batchUserStatus = (userIds: string[], status: string) =>
  post<{ count: number }>('/users/batch-status', { userIds, status })

/** 批量删除（逻辑删除）。 */
export const batchDeleteUsers = (userIds: string[]) =>
  post<{ count: number }>('/users/batch-delete', { userIds })

export const resetUserPassword = (id: string, password: string) =>
  put<null>(`/users/${id}/password`, { password })

export const userRoleIds = (id: string) =>
  get<{ userId: string; roleIds: string[] }>(`/users/${id}/roles`)

export const assignUserRoles = (id: string, roleIds: string[]) =>
  post<null>(`/users/${id}/roles`, { roleIds })

export interface RoleItem {
  id: string
  roleCode: string
  roleName: string
  dataScope: string
  customDeptIds: string
  builtin: number
  status: string
  sort: number
  userCount: number
  permCount: number
}

export interface PermissionItem {
  id: string
  permCode: string
  permName: string
  permType: string
  parentId: string
}

export const listRoles = () => get<RoleItem[]>('/roles')

export const createRole = (data: Record<string, unknown>) =>
  post<{ id: string; roleCode: string }>('/roles', data)

export const updateRole = (id: string, data: Record<string, unknown>) =>
  put<{ id: string; roleName: string; dataScope: string }>(`/roles/${id}`, data)

export const deleteRole = (id: string) => del<null>(`/roles/${id}`)

export const rolePermissionIds = (id: string) =>
  get<{ roleId: string; permIds: string[] }>(`/roles/${id}/permissions`)

export const updateRolePermissions = (id: string, permIds: string[]) =>
  put<null>(`/roles/${id}/permissions`, { permIds })

export const permissionTree = () => get<PermissionItem[]>('/permissions/tree')

export interface ConfigItem {
  configKey: string
  configValue: string
  valueType: 'BOOL' | 'INT' | 'FLOAT' | 'STRING'
  groupName: string
  defaultValue: string
  remark: string
  builtin: number
}

export const listConfigs = () => get<ConfigItem[]>('/configs')

export const updateConfig = (key: string, value: string) =>
  put<null>(`/configs/${key}`, { configValue: value })

/** 批量保存参数（先整体校验，再统一写库）。 */
export const updateConfigs = (items: { configKey: string; configValue: string }[]) =>
  put<{ updated: number }>('/configs', { items })

/** 恢复指定参数的默认值。 */
export const resetConfigs = (configKeys: string[]) =>
  post<{ reset: number }>('/configs/reset', { configKeys })

export const dictItems = (code: string) => get<Record<string, unknown>[]>(`/dicts/${code}`)

/* ------------------------------ 审计留痕 ------------------------------ */

export const listOperateLogs = (params: Record<string, unknown>) =>
  get<Page<Record<string, unknown>>>('/audit/operate-logs', params)

export const listLoginLogs = (params: Record<string, unknown>) =>
  get<Page<Record<string, unknown>>>('/audit/login-logs', params)

/** 审计日志中出现过的业务模块（筛选下拉）。 */
export const listAuditModules = () => get<string[]>('/audit/modules')

export interface ArchivePolicy {
  keepMonths: number
  defaultKeepMonths: number
  tables: string[]
}

/** 归档策略：默认保留月数与参与归档的表。 */
export const auditArchivePolicy = () => get<ArchivePolicy>('/audit/archive/policy')

export interface ArchiveReport {
  dryRun: boolean
  cutoff: string
  keepMonths: number
  total: number
  tables: Record<string, Record<string, number>>
}

export const archiveAudit = (data: { keepMonths: number; dryRun: boolean }) =>
  post<ArchiveReport>('/audit/archive', data)
