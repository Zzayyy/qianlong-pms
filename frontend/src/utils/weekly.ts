import { ElMessageBox } from 'element-plus'
import { listWeeklies } from '@/api'

/** 与后端 `week_label` 一致的 ISO 周标签，如 `2026-W47`。 */
export const weekLabelOf = (weekStart: string) => {
  const base = new Date(`${(weekStart || '').slice(0, 10)}T00:00:00`)
  if (Number.isNaN(base.getTime())) return ''
  // 该周的周四决定 ISO 年份；用 UTC 计算避免时区把周一算回上一周
  const target = new Date(Date.UTC(base.getFullYear(), base.getMonth(), base.getDate()))
  const weekday = target.getUTCDay() || 7
  target.setUTCDate(target.getUTCDate() + 4 - weekday)
  const yearStart = Date.UTC(target.getUTCFullYear(), 0, 1)
  const week = Math.ceil(((target.getTime() - yearStart) / 86400000 + 1) / 7)
  return `${target.getUTCFullYear()}-W${String(week).padStart(2, '0')}`
}

/**
 * 周选择器的返回值换算成 ISO 周一。
 *
 * Element Plus 的 `type="week"` 用 dayjs 的 `startOf('week')` 取周首日，本项目没注册
 * dayjs 的中文包（Element Plus 的 zh-cn 语言包不包含 dayjs locale），实际是 en：周首日
 * 为**周日**，所以选中的是 `2026-11-15` 这类周日；而后端周报的 `week_start` 一律存 ISO
 * 周一（`2026-11-16`），不换算就会按周过滤不到数据。
 */
export const toWeekStart = (value?: string) => {
  if (!value) return ''
  const date = new Date(`${value.slice(0, 10)}T00:00:00`)
  if (Number.isNaN(date.getTime())) return ''
  // 先回到所在「周日开始」自然周的周日，再往后一天即该周的 ISO 周一
  const monday = new Date(date)
  monday.setDate(date.getDate() - date.getDay() + 1)
  const month = String(monday.getMonth() + 1).padStart(2, '0')
  const day = String(monday.getDate()).padStart(2, '0')
  return `${monday.getFullYear()}-${month}-${day}`
}

/** 指定日期（默认今天）所在自然周的周一，格式 YYYY-MM-DD。 */
export const mondayOf = (value?: string) => {
  const base = value ? new Date(`${value.slice(0, 10)}T00:00:00`) : new Date()
  // 周日 getDay() 为 0，按 ISO 周算作第 7 天
  const weekday = base.getDay() || 7
  base.setDate(base.getDate() - (weekday - 1))
  const month = String(base.getMonth() + 1).padStart(2, '0')
  const day = String(base.getDate()).padStart(2, '0')
  return `${base.getFullYear()}-${month}-${day}`
}

/**
 * 生成周报前的覆盖确认：同一项目（或本人）同一周只会有一条周报，
 * 再次生成是「覆盖 + 版本 +1」，所以这里先查一次并让用户确认。
 * 返回 false 表示用户取消或查询失败需中止。
 */
export const confirmWeeklyOverwrite = async (options: {
  scope: 'PROJECT' | 'PERSONAL'
  projectId?: string | number
  weekStart: string
}) => {
  const isProject = options.scope === 'PROJECT'
  const weekStart = toWeekStart(options.weekStart) || mondayOf()
  let existing: { weekLabel?: string; status?: string; revision?: number } | undefined
  try {
    const data = await listWeeklies({
      scope: options.scope,
      projectId: isProject ? options.projectId : undefined,
      weekStart,
      pageNum: 1,
      pageSize: 1
    })
    existing = (data.list || [])[0]
  } catch {
    // 查询失败不拦生成（后端仍会做权限与覆盖校验）
    return true
  }
  if (!existing) return true
  const target = isProject ? '该周项目周报' : '该周周总结'
  const revision = Number(existing.revision || 1)
  const tip =
    existing.status === 'CONFIRMED'
      ? `${target}已确认归档（${existing.weekLabel}），重新生成会覆盖已确认的正文并回到「待确认」，需要重新确认。是否继续？`
      : `${target}已存在（${existing.weekLabel}，待确认 v${revision}），重新生成会覆盖现有正文，版本升到 v${revision + 1}。是否继续？`
  try {
    await ElMessageBox.confirm(tip, '该周已有周报', {
      type: 'warning',
      confirmButtonText: '覆盖生成',
      cancelButtonText: '取消'
    })
    return true
  } catch {
    return false
  }
}
