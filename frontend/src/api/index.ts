import { del, download, get, post, put, upload, type Page } from './http'

export type { Page }

/* ------------------------------ 认证 ------------------------------ */

export interface LoginResult {
  token: string
  expiresIn: number
  user: { id: number; username: string; realName: string; deptId: number; status: string }
  roles: string[]
  permissions: string[]
}

export interface Profile {
  id: number
  username: string
  realName: string
  deptId: number
  roles: string[]
  permissions: string[]
  allScope: boolean
}

export const login = (username: string, password: string) =>
  post<LoginResult>('/auth/login', { username, password })

export const logout = () => post<null>('/auth/logout', { token: localStorage.getItem('pms_token') })

export const profile = () => get<Profile>('/auth/profile')

/* ------------------------------ 项目 ------------------------------ */

export const listProjects = (params: Record<string, unknown>) =>
  get<Page<Record<string, unknown>>>('/projects', params)

export const createProject = (data: Record<string, unknown>) =>
  post<{ id: number; projectCode: string; status: string }>('/projects', data)

export const projectDetail = (id: number) => get<Record<string, unknown>>(`/projects/${id}`)

export const submitProject = (id: number) => post<{ status: string }>(`/projects/${id}/submit`)

export const approveProject = (id: number) => post<{ status: string }>(`/projects/${id}/approve`)

export const rejectProject = (id: number, reason: string) =>
  post<{ status: string }>(`/projects/${id}/reject`, { reason })

export const changeProjectStatus = (id: number, status: string) =>
  put<{ status: string }>(`/projects/${id}/status`, { status })

export const listStages = (id: number) => get<Record<string, unknown>[]>(`/projects/${id}/stages`)

export const createStage = (id: number, data: Record<string, unknown>) =>
  post<{ id: number }>(`/projects/${id}/stages`, data)

export const updateStage = (id: number, stageId: number, data: Record<string, unknown>) =>
  put<{ id: number }>(`/projects/${id}/stages/${stageId}`, data)

export const deleteStage = (id: number, stageId: number) =>
  del<unknown>(`/projects/${id}/stages/${stageId}`)

export const stageStatus = (id: number, stageId: number, target: string) =>
  put<{ id: number; status: string }>(`/projects/${id}/stages/${stageId}/status`, { target })

export const listTasks = (id: number) => get<Record<string, unknown>[]>(`/projects/${id}/tasks`)

export const createTask = (id: number, data: Record<string, unknown>) =>
  post<{ id: number }>(`/projects/${id}/tasks`, data)

export const updateTaskProgress = (id: number, taskId: number, progress: number) =>
  put<{ progress: number }>(`/projects/${id}/tasks/${taskId}/progress`, { progress })

export const recalcProgress = (id: number) => get<{ progress: number }>(`/projects/${id}/progress`)

export const listMilestones = (id: number) =>
  get<Record<string, unknown>[]>(`/projects/${id}/milestones`)

export const createMilestone = (id: number, data: Record<string, unknown>) =>
  post<{ id: number }>(`/projects/${id}/milestones`, data)

export const updateMilestone = (id: number, milestoneId: number, data: Record<string, unknown>) =>
  put<{ id: number }>(`/projects/${id}/milestones/${milestoneId}`, data)

export const deleteMilestone = (id: number, milestoneId: number) =>
  del<unknown>(`/projects/${id}/milestones/${milestoneId}`)

export const milestoneStatus = (id: number, milestoneId: number, target: string) =>
  put<{ id: number; status: string }>(`/projects/${id}/milestones/${milestoneId}/status`, {
    target,
  })

/** 项目总监（可多人，变更审批会签）。 */
export const projectDirectors = (id: number) =>
  get<Record<string, unknown>[]>(`/projects/${id}/directors`)

export const setProjectDirectors = (id: number, userIds: number[]) =>
  put<Record<string, unknown>[]>(`/projects/${id}/directors`, { userIds })

/** 项目/节点文档。 */
export const projectAttachments = (id: number, params: Record<string, unknown> = {}) =>
  get<Record<string, unknown>[]>(`/projects/${id}/attachments`, params)

export const uploadProjectFile = (form: FormData) =>
  upload<Record<string, unknown>>('/files', form)

export const deleteProjectFile = (fileId: number) => del<unknown>(`/files/${fileId}`)

export const downloadProjectFile = (fileId: number, fileName: string) =>
  download(`/files/${fileId}/download`, fileName)

export const listMembers = (id: number) => get<Record<string, unknown>[]>(`/projects/${id}/members`)

export const addMember = (id: number, data: Record<string, unknown>) =>
  post<{ id: number }>(`/projects/${id}/members`, data)

export const removeMember = (id: number, memberId: number) =>
  del<null>(`/projects/${id}/members/${memberId}`)

export const changeProjectPm = (id: number, pmId: number) =>
  put<{ id: number; pmId: number }>(`/projects/${id}/pm`, { pmId })

/* ------------------------------ 变更 ------------------------------ */

export const listChanges = (params: Record<string, unknown>) =>
  get<Page<Record<string, unknown>>>('/changes', params)

export const changeDetail = (id: number) => get<Record<string, unknown>>(`/changes/${id}`)

export const createChange = (data: Record<string, unknown>) =>
  post<{ id: number; requestCode: string }>('/changes', data)

export const submitChange = (id: number) => post<{ status: string }>(`/changes/${id}/submit`)

export const assessChange = (id: number, data: Record<string, unknown>) =>
  post<{ level: string; status: string }>(`/changes/${id}/assess`, data)

export const approveChange = (id: number, comment = '') =>
  post<{ status: string }>(`/changes/${id}/approve`, { comment })

export const rejectChange = (id: number, reason = '') =>
  post<{ status: string }>(`/changes/${id}/reject`, { reason })

export const changeAction = (id: number, action: string, payload: Record<string, unknown> = {}) =>
  post<{ status: string }>(`/changes/${id}/${action}`, payload)

/* ------------------------------ 日志 ------------------------------ */

export const saveWorklog = (data: Record<string, unknown>) =>
  post<{ id: number }>('/worklogs', data)

export const worklogAction = (id: number, action: string, payload: Record<string, unknown> = {}) =>
  post<Record<string, unknown>>(`/worklogs/${id}/${action}`, payload)

export const listWorklogs = (params: Record<string, unknown>) =>
  get<Page<Record<string, unknown>>>('/worklogs', params)

/** 填报选项：补填天数上限、工时阈值与我参与的项目。 */
export const worklogOptions = () => get<Record<string, unknown>>('/worklogs/options')

/** 某人某天的累计工时与预警提示（不禁止提交）。 */
export const worklogDaySummary = (date: string, userId?: number) =>
  get<Record<string, unknown>>('/worklogs/day-summary', { date, userId })

export const worklogDetail = (id: number) => get<Record<string, unknown>>(`/worklogs/${id}`)

export const deleteWorklog = (id: number) => del<{ id: number }>(`/worklogs/${id}`)

export const worklogStats = (params: Record<string, unknown>) =>
  get<Record<string, number>>('/worklogs/stats', params)

export const worklogComments = (id: number) =>
  get<Record<string, unknown>[]>(`/worklogs/${id}/comments`)

/* ------------------------------ 看板 ------------------------------ */

export const companyBoard = () => get<Record<string, unknown>>('/reports/company')

export const deptBoard = (deptIds: number[]) =>
  get<Record<string, unknown>>('/reports/dept', { deptIds: deptIds.join(',') })

export const projectBoard = (id: number) => get<Record<string, unknown>>(`/reports/project/${id}`)

export const personalBoard = (params: Record<string, unknown>) =>
  get<Record<string, unknown>>('/reports/personal', params)

export const aggregateDaily = (statDate = '') => post<Record<string, number>>('/reports/aggregate', { statDate })

/* ------------------------------ CRM ------------------------------ */

export const listCustomers = (params: Record<string, unknown>) =>
  get<Page<Record<string, unknown>>>('/crm/customers', params)

export const createCustomer = (data: Record<string, unknown>) =>
  post<{ id: number }>('/crm/customers', data)

export const listOpportunities = (params: Record<string, unknown>) =>
  get<Page<Record<string, unknown>>>('/crm/opportunities', params)

export const createOpportunity = (data: Record<string, unknown>) =>
  post<{ id: number }>('/crm/opportunities', data)

export const pushOppStage = (id: number, stage: string) =>
  put<{ stageCode: string }>(`/crm/opportunities/${id}/stage`, { stage })

export const convertOpp = (id: number, data: Record<string, unknown>) =>
  post<{ projectId: number }>(`/crm/opportunities/${id}/convert`, data)

/* ------------------------------ 组织与参数 ------------------------------ */

export const deptTree = () => get<Record<string, unknown>[]>('/depts/tree')

export const createDept = (data: Record<string, unknown>) =>
  post<{ id: number; deptCode: string }>('/depts', data)

export const updateDept = (id: number, data: Record<string, unknown>) =>
  put<{ id: number; deptName: string }>(`/depts/${id}`, data)

export const deleteDept = (id: number) => del<null>(`/depts/${id}`)

export const listUsers = (params: Record<string, unknown>) =>
  get<Page<Record<string, unknown>>>('/users', params)

export const createUser = (data: Record<string, unknown>) => post<{ id: number }>('/users', data)

export const updateUser = (id: number, data: Record<string, unknown>) =>
  put<{ id: number }>(`/users/${id}`, data)

export const changeUserStatus = (id: number, status: string) =>
  put<{ id: number; status: string }>(`/users/${id}/status`, { status })

export const resetUserPassword = (id: number, password: string) =>
  put<null>(`/users/${id}/password`, { password })

export const userRoleIds = (id: number) =>
  get<{ userId: number; roleIds: number[] }>(`/users/${id}/roles`)

export const assignUserRoles = (id: number, roleIds: number[]) =>
  post<null>(`/users/${id}/roles`, { roleIds })

export const listRoles = () => get<Record<string, unknown>[]>('/roles')

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
