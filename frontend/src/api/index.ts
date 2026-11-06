import { del, download, get, post, put, upload, type Page } from './http'

export type { Page }

/* ------------------------------ 认证 ------------------------------ */

export interface LoginResult {
  token: string
  expiresIn: number
  user: { id: string; username: string; realName: string; deptId: string; status: string }
  roles: string[]
  permissions: string[]
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

export const changeProjectStatus = (id: string, status: string) =>
  put<{ status: string }>(`/projects/${id}/status`, { status })

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

export const listMembers = (id: string) => get<Record<string, unknown>[]>(`/projects/${id}/members`)

export const addMember = (id: string, data: Record<string, unknown>) =>
  post<{ id: string }>(`/projects/${id}/members`, data)

export const removeMember = (id: string, memberId: string) =>
  del<null>(`/projects/${id}/members/${memberId}`)

export const changeProjectPm = (id: string, pmId: string) =>
  put<{ id: string; pmId: string }>(`/projects/${id}/pm`, { pmId })

/* ------------------------------ 变更 ------------------------------ */

export const listChanges = (params: Record<string, unknown>) =>
  get<Page<Record<string, unknown>>>('/changes', params)

export const changeDetail = (id: string) => get<Record<string, unknown>>(`/changes/${id}`)

export const createChange = (data: Record<string, unknown>) =>
  post<{ id: string; requestCode: string }>('/changes', data)

export const submitChange = (id: string) => post<{ status: string }>(`/changes/${id}/submit`)

export const assessChange = (id: string, data: Record<string, unknown>) =>
  post<{ level: string; status: string }>(`/changes/${id}/assess`, data)

export const approveChange = (id: string, comment = '') =>
  post<{ status: string }>(`/changes/${id}/approve`, { comment })

export const rejectChange = (id: string, reason = '') =>
  post<{ status: string }>(`/changes/${id}/reject`, { reason })

export const changeAction = (id: string, action: string, payload: Record<string, unknown> = {}) =>
  post<{ status: string }>(`/changes/${id}/${action}`, payload)

/* ------------------------------ 日志 ------------------------------ */

export const saveWorklog = (data: Record<string, unknown>) =>
  post<{ id: string }>('/worklogs', data)

export const worklogAction = (id: string, action: string, payload: Record<string, unknown> = {}) =>
  post<Record<string, unknown>>(`/worklogs/${id}/${action}`, payload)

export const listWorklogs = (params: Record<string, unknown>) =>
  get<Page<Record<string, unknown>>>('/worklogs', params)

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

/* ------------------------------ 看板 ------------------------------ */

export const companyBoard = () => get<Record<string, unknown>>('/reports/company')

export const deptBoard = (deptIds: string[]) =>
  get<Record<string, unknown>>('/reports/dept', { deptIds: deptIds.join(',') })

export const projectBoard = (id: string) => get<Record<string, unknown>>(`/reports/project/${id}`)

export const personalBoard = (params: Record<string, unknown>) =>
  get<Record<string, unknown>>('/reports/personal', params)

export const aggregateDaily = (statDate = '') => post<Record<string, number>>('/reports/aggregate', { statDate })

/* ------------------------------ CRM ------------------------------ */

export const listCustomers = (params: Record<string, unknown>) =>
  get<Page<Record<string, unknown>>>('/crm/customers', params)

export const createCustomer = (data: Record<string, unknown>) =>
  post<{ id: string }>('/crm/customers', data)

export const listOpportunities = (params: Record<string, unknown>) =>
  get<Page<Record<string, unknown>>>('/crm/opportunities', params)

export const createOpportunity = (data: Record<string, unknown>) =>
  post<{ id: string }>('/crm/opportunities', data)

export const pushOppStage = (id: string, stage: string) =>
  put<{ stageCode: string }>(`/crm/opportunities/${id}/stage`, { stage })

export const convertOpp = (id: string, data: Record<string, unknown>) =>
  post<{ projectId: string }>(`/crm/opportunities/${id}/convert`, data)

/* ------------------------------ 组织与参数 ------------------------------ */

export const deptTree = () => get<Record<string, unknown>[]>('/depts/tree')

export const createDept = (data: Record<string, unknown>) =>
  post<{ id: string; deptCode: string }>('/depts', data)

export const updateDept = (id: string, data: Record<string, unknown>) =>
  put<{ id: string; deptName: string }>(`/depts/${id}`, data)

export const deleteDept = (id: string) => del<null>(`/depts/${id}`)

export const listUsers = (params: Record<string, unknown>) =>
  get<Page<Record<string, unknown>>>('/users', params)

export const createUser = (data: Record<string, unknown>) => post<{ id: string }>('/users', data)

export const updateUser = (id: string, data: Record<string, unknown>) =>
  put<{ id: string }>(`/users/${id}`, data)

export const changeUserStatus = (id: string, status: string) =>
  put<{ id: string; status: string }>(`/users/${id}/status`, { status })

/** 解除登录失败锁定（不重置密码）。 */
export const unlockUser = (id: string) => post<{ id: string }>(`/users/${id}/unlock`)

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

export const listConfigs = () => get<Record<string, unknown>[]>('/configs')

export const updateConfig = (key: string, value: string) =>
  put<null>(`/configs/${key}`, { configValue: value })

export const dictItems = (code: string) => get<Record<string, unknown>[]>(`/dicts/${code}`)

/* ------------------------------ 审计留痕 ------------------------------ */

export const listOperateLogs = (params: Record<string, unknown>) =>
  get<Page<Record<string, unknown>>>('/audit/operate-logs', params)

export const listLoginLogs = (params: Record<string, unknown>) =>
  get<Page<Record<string, unknown>>>('/audit/login-logs', params)

export const archiveAudit = (data: { keepMonths: number; dryRun: boolean }) =>
  post<Record<string, unknown>>('/audit/archive', data)
