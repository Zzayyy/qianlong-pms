/**
 * 状态字典：后端只存英文编码，前端统一在此映射中文与标签色。
 * 新增状态时只改这里，页面上不会再出现 `NOT_STARTED` 这类裸编码。
 */

export type TagType = 'primary' | 'success' | 'warning' | 'info' | 'danger'

export interface DictItem {
  label: string
  type: TagType
}

/** 取值：命中字典用字典，未命中回落原码（便于发现漏配）。 */
export const dictOf = (dict: Record<string, DictItem>, code: unknown): DictItem => {
  const key = String(code ?? '')
  return dict[key] || { label: key || '—', type: 'info' }
}

/** 项目状态。 */
export const PROJECT_STATUS: Record<string, DictItem> = {
  DRAFT: { label: '草稿', type: 'info' },
  APPROVING: { label: '审批中', type: 'warning' },
  APPROVED: { label: '已立项', type: 'success' },
  IN_PROGRESS: { label: '进行中', type: 'primary' },
  SUSPENDED: { label: '已暂停', type: 'warning' },
  COMPLETED: { label: '已完成', type: 'success' },
  ACCEPTED: { label: '已验收', type: 'success' },
  TERMINATED: { label: '已终止', type: 'danger' },
  CLOSED: { label: '已关闭', type: 'info' }
}

/** 节点状态：阶段与任务共用。 */
export const NODE_STATUS: Record<string, DictItem> = {
  NOT_STARTED: { label: '未开始', type: 'info' },
  IN_PROGRESS: { label: '进行中', type: 'primary' },
  DONE: { label: '已完成', type: 'success' },
  CANCELLED: { label: '已取消', type: 'info' }
}

/** 里程碑状态。 */
export const MILESTONE_STATUS: Record<string, DictItem> = {
  PENDING: { label: '待达成', type: 'info' },
  DELAYED: { label: '已延期', type: 'danger' },
  REACHED: { label: '已达成', type: 'success' },
  CANCELLED: { label: '已取消', type: 'info' }
}

/** 优先级（任务）。 */
export const PRIORITY: Record<string, DictItem> = {
  HIGH: { label: '高', type: 'danger' },
  MEDIUM: { label: '中', type: 'warning' },
  LOW: { label: '低', type: 'info' }
}

/** 项目组内角色（`t_prj_member.role_in_project`）。 */
export const MEMBER_ROLE: Record<string, DictItem> = {
  PM: { label: '项目经理', type: 'primary' },
  MEMBER: { label: '成员', type: 'info' },
  DEV: { label: '开发', type: 'success' },
  TEST: { label: '测试', type: 'warning' },
  OPS: { label: '运维', type: 'info' },
  IMPL: { label: '实施', type: 'info' },
  DESIGN: { label: '设计', type: 'info' },
  SALES: { label: '销售', type: 'info' }
}

/** 可手动指派的组内角色：项目经理（PM）只能通过「设为负责人」转移，避免越权。 */
export const ASSIGNABLE_MEMBER_ROLE: Record<string, string> = {
  MEMBER: '成员',
  DEV: '开发',
  TEST: '测试',
  IMPL: '实施',
  OPS: '运维',
  DESIGN: '设计',
  SALES: '销售'
}

/** 风险 / 问题类型（`t_prj_risk.risk_type`）。 */
export const RISK_TYPE: Record<string, DictItem> = {
  RISK: { label: '风险', type: 'warning' },
  ISSUE: { label: '问题', type: 'danger' }
}

/** 风险等级。 */
export const RISK_LEVEL: Record<string, DictItem> = {
  HIGH: { label: '高', type: 'danger' },
  MEDIUM: { label: '中', type: 'warning' },
  LOW: { label: '低', type: 'info' }
}

/** 风险状态。 */
export const RISK_STATUS: Record<string, DictItem> = {
  OPEN: { label: '开放', type: 'danger' },
  CLOSED: { label: '已关闭', type: 'success' }
}

/** 基线类型。 */
export const BASELINE_TYPE: Record<string, string> = {
  SCOPE: '范围基线',
  SCHEDULE: '进度基线',
  COST: '成本基线',
  CHANGE: '变更基线'
}

/** 项目健康度。 */
export const HEALTH_STATUS: Record<string, DictItem> = {
  GREEN: { label: '健康', type: 'success' },
  YELLOW: { label: '预警', type: 'warning' },
  RED: { label: '风险', type: 'danger' }
}

/** 健康度对应的圆点颜色修饰（配合 .health.is-xxx 使用）。 */
export const HEALTH_KEY: Record<string, string> = {
  GREEN: 'green',
  YELLOW: 'yellow',
  RED: 'red'
}
