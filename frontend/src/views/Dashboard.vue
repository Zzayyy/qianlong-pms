<script setup lang="ts">
import { computed, nextTick, onMounted, ref, type Component } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  Activity,
  ArrowRight,
  Building2,
  CirclePlay,
  Download,
  FolderKanban,
  Gauge,
  GitPullRequest,
  LayoutDashboard,
  NotebookPen,
  Plus,
  RefreshCw,
  ShieldAlert,
  TrendingDown,
  TrendingUp,
  TriangleAlert
} from 'lucide-vue-next'
import { companyBoard } from '@/api'
import ChartBox from '@/components/ChartBox.vue'
import { useUserStore } from '@/stores/user'

/* ------------------------------ 类型 ------------------------------ */

type Tone = 'primary' | 'success' | 'warning' | 'danger' | 'default'
type TagType = 'primary' | 'success' | 'info' | 'warning' | 'danger'
type DelayFilter = 'ALL' | 'SEVERE' | 'RISK'

interface BoardSummary {
  projectCount: number
  inProgressCount: number
  delayedCount: number
  avgProgress: number
  avgSpi: number
  avgCpi: number
  riskOpen: number
  issueOpen: number
  changeCount: number
  plannedHours: number
  actualHours: number
  avgLogFillRate: number
  byStatus: Record<string, number>
  byHealth: Record<string, number>
}

interface ProjectMetric {
  projectId: string
  projectName: string
  deptId: string
  deptName?: string
  status: string
  health: string
  progress: number
  spi: number
  cpi: number
  delayDays: number
  plannedHours: number
  actualHours: number
  riskOpen: number
  issueOpen: number
  changeCount: number
  logFillRate: number
}

interface DeptStat {
  deptId: string
  deptName: string
  projectCount: number
  inProgressCount: number
  delayedCount: number
  riskOpen: number
  issueOpen: number
  changeCount: number
  avgProgress: number
  avgSpi: number
  avgCpi: number
  plannedHours: number
  actualHours: number
  avgLogFillRate: number
  redCount: number
  yellowCount: number
}

interface TrendPoint {
  date: string
  projectCount: number
  avgProgress: number
  avgSpi: number
  redCount: number
  yellowCount: number
  avgDelayDays: number
  actualHours: number
}

interface CompanyBoard {
  summary?: Partial<BoardSummary>
  deptStats?: DeptStat[]
  trend?: { days?: number; points?: TrendPoint[] }
  topDelayed?: ProjectMetric[]
  topRisk?: ProjectMetric[]
}

interface KpiCard {
  key: string
  label: string
  icon: Component
  value: string
  sub: string
  tone?: Tone
  /** 平均进度等百分比指标附带底部进度条 */
  bar?: number
  /** 可点击联动的延期表筛选键 */
  filter?: DelayFilter
}

interface QuickAction {
  key: string
  label: string
  desc: string
  icon: Component
  path: string
  permission: string
}

/* ------------------------------ 状态 ------------------------------ */

const store = useUserStore()
const router = useRouter()

const board = ref<CompanyBoard>({})
const loading = ref(false)
const days = ref(30)
const loadedAt = ref('')
const keyword = ref('')
const deptFilter = ref('')
const delayFilter = ref<DelayFilter>('ALL')
const delayCard = ref<HTMLElement | null>(null)

const EMPTY_SUMMARY: BoardSummary = {
  projectCount: 0,
  inProgressCount: 0,
  delayedCount: 0,
  avgProgress: 0,
  avgSpi: 0,
  avgCpi: 0,
  riskOpen: 0,
  issueOpen: 0,
  changeCount: 0,
  plannedHours: 0,
  actualHours: 0,
  avgLogFillRate: 0,
  byStatus: {},
  byHealth: {}
}

const summary = computed<BoardSummary>(() => ({
  ...EMPTY_SUMMARY,
  ...(board.value.summary || {})
}))
const deptStats = computed(() => board.value.deptStats ?? [])
const trendPoints = computed(() => board.value.trend?.points ?? [])
const topDelayed = computed(() => board.value.topDelayed ?? [])
const topRisk = computed(() => board.value.topRisk ?? [])

const load = async () => {
  loading.value = true
  try {
    board.value = (await companyBoard(days.value)) as unknown as CompanyBoard
    const now = new Date()
    loadedAt.value = `${now.getMonth() + 1}/${now.getDate()} ${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}`
  } catch {
    /* 错误提示由请求拦截器统一弹出 */
  } finally {
    loading.value = false
  }
}

onMounted(load)

/* ------------------------------ 格式化 ------------------------------ */

const num = (value: unknown, digits = 0) => {
  const parsed = Number(value)
  if (!Number.isFinite(parsed)) return '0'
  return digits > 0 ? parsed.toFixed(digits) : String(Math.round(parsed))
}

const pct = (value: unknown, digits = 1) => `${num(value, digits)}%`

const barWidth = (value: unknown) => Math.min(Math.max(Number(value) || 0, 0), 100)

const indexTone = (value: unknown): Tone => {
  const parsed = Number(value)
  if (!Number.isFinite(parsed)) return 'default'
  if (parsed >= 1) return 'success'
  return parsed >= 0.9 ? 'warning' : 'danger'
}

const fillTone = (value: unknown): Tone => {
  const parsed = Number(value)
  if (!Number.isFinite(parsed)) return 'default'
  if (parsed >= 90) return 'success'
  return parsed >= 70 ? 'warning' : 'danger'
}

/* ------------------------------ 字典 ------------------------------ */

const STATUS_META: Record<string, { label: string; tone: TagType }> = {
  DRAFT: { label: '草稿', tone: 'info' },
  APPROVING: { label: '立项审批中', tone: 'warning' },
  APPROVED: { label: '已立项', tone: 'primary' },
  IN_PROGRESS: { label: '进行中', tone: 'primary' },
  SUSPENDED: { label: '已挂起', tone: 'warning' },
  COMPLETED: { label: '已完成', tone: 'success' },
  ACCEPTED: { label: '已验收', tone: 'success' },
  TERMINATED: { label: '已终止', tone: 'danger' },
  CLOSED: { label: '已关闭', tone: 'info' }
}

const statusLabel = (status: unknown) => STATUS_META[String(status)]?.label ?? String(status ?? '-')
const statusTone = (status: unknown): TagType => STATUS_META[String(status)]?.tone ?? 'info'

const HEALTH_META: Record<string, { label: string; tone: TagType; dot: string; color: string }> = {
  GREEN: { label: '健康', tone: 'success', dot: 'ok', color: '#2f9e5f' },
  YELLOW: { label: '预警', tone: 'warning', dot: 'warn', color: '#d68a12' },
  RED: { label: '风险', tone: 'danger', dot: 'danger', color: '#cf3f3f' }
}

const healthMeta = (health: string) =>
  HEALTH_META[health] ?? { label: health || '-', tone: 'info' as TagType, dot: 'ok', color: '#8b95a8' }

/* ------------------------------ 派生指标 ------------------------------ */

const healthList = computed(() => {
  const byHealth = summary.value.byHealth || {}
  const total = Number(summary.value.projectCount || 0)
  return ['GREEN', 'YELLOW', 'RED'].map((key) => {
    const count = Number(byHealth[key] || 0)
    return {
      key,
      ...HEALTH_META[key],
      count,
      percent: total > 0 ? Math.round((count / total) * 100) : 0
    }
  })
})

const STATUS_ORDER = [
  'IN_PROGRESS',
  'APPROVING',
  'APPROVED',
  'SUSPENDED',
  'COMPLETED',
  'ACCEPTED',
  'TERMINATED',
  'CLOSED',
  'DRAFT'
]

const statusRows = computed(() => {
  const byStatus = summary.value.byStatus || {}
  const total = Number(summary.value.projectCount || 0)
  return STATUS_ORDER.filter((key) => Number(byStatus[key] || 0) > 0).map((key) => {
    const count = Number(byStatus[key] || 0)
    return {
      key,
      label: statusLabel(key),
      tone: statusTone(key),
      count,
      percent: total > 0 ? Math.round((count / total) * 100) : 0
    }
  })
})

const plannedHours = computed(() => Number(summary.value.plannedHours || 0))
const actualHours = computed(() => Number(summary.value.actualHours || 0))
const execPercent = computed(() =>
  plannedHours.value > 0
    ? Math.min(Math.round((actualHours.value / plannedHours.value) * 100), 100)
    : 0
)
const inProgressPercent = computed(() => {
  const total = Number(summary.value.projectCount || 0)
  return total > 0 ? Math.round((Number(summary.value.inProgressCount || 0) / total) * 100) : 0
})
const maxDelayDays = computed(() =>
  topDelayed.value.reduce((max, item) => Math.max(max, Number(item.delayDays) || 0), 0)
)

const kpis = computed<KpiCard[]>(() => {
  const s = summary.value
  return [
    {
      key: 'projectCount',
      label: '项目总数',
      icon: FolderKanban,
      value: num(s.projectCount),
      sub: `${deptStats.value.length} 个部门 · 计划 ${num(s.plannedHours, 0)}h`
    },
    {
      key: 'inProgressCount',
      label: '进行中',
      icon: CirclePlay,
      tone: 'primary',
      value: num(s.inProgressCount),
      sub: `占全部项目 ${inProgressPercent.value}%`
    },
    {
      key: 'delayedCount',
      label: '延期项目',
      icon: TriangleAlert,
      tone: 'warning',
      value: num(s.delayedCount),
      sub: maxDelayDays.value > 0 ? `最长延期 ${maxDelayDays.value} 天` : '暂无延期项目',
      filter: 'ALL'
    },
    {
      key: 'avgProgress',
      label: '平均进度',
      icon: Gauge,
      value: pct(s.avgProgress, 1),
      sub: `实际投入 ${num(s.actualHours, 0)}h`,
      bar: barWidth(s.avgProgress)
    },
    {
      key: 'avgSpi',
      label: '平均 SPI',
      icon: TrendingUp,
      tone: indexTone(s.avgSpi),
      value: num(s.avgSpi, 2),
      sub: '进度绩效，≥ 1.00 为良好'
    },
    {
      key: 'avgCpi',
      label: '平均 CPI',
      icon: TrendingDown,
      tone: indexTone(s.avgCpi),
      value: num(s.avgCpi, 2),
      sub: '成本绩效，≥ 1.00 为良好'
    },
    {
      key: 'riskOpen',
      label: '开放风险',
      icon: ShieldAlert,
      tone: 'danger',
      value: num(s.riskOpen),
      sub: `未关闭问题 ${num(s.issueOpen)} 项`,
      filter: 'RISK'
    },
    {
      key: 'avgLogFillRate',
      label: '日志填写率',
      icon: NotebookPen,
      tone: fillTone(s.avgLogFillRate),
      value: pct(s.avgLogFillRate, 1),
      sub: `本期变更 ${num(s.changeCount)} 项`
    }
  ]
})

/* ------------------------------ 快捷操作 ------------------------------ */

const allQuickActions: QuickAction[] = [
  {
    key: 'project',
    label: '新建项目',
    desc: '发起立项与审批',
    icon: Plus,
    path: '/projects',
    permission: 'project:create'
  },
  {
    key: 'worklog',
    label: '填报日志',
    desc: '登记今日工作工时',
    icon: NotebookPen,
    path: '/worklogs',
    permission: 'worklog:create'
  },
  {
    key: 'change',
    label: '发起变更',
    desc: '提交范围或排期调整',
    icon: GitPullRequest,
    path: '/changes',
    permission: 'change:create'
  },
  {
    key: 'dept',
    label: '部门看板',
    desc: '下钻部门成员与趋势',
    icon: Building2,
    path: '/dept-board',
    permission: 'report:view'
  }
]

const quickActions = computed(() => allQuickActions.filter((item) => store.has(item.permission)))

const go = (path: string) => router.push(path)

/* ------------------------------ 筛选与联动 ------------------------------ */

const DELAY_TABS: { key: DelayFilter; label: string }[] = [
  { key: 'ALL', label: '全部延期' },
  { key: 'SEVERE', label: '延期 ≥ 7 天' },
  { key: 'RISK', label: '有开放风险' }
]

const deptOptions = computed(() =>
  deptStats.value.map((item) => ({ value: String(item.deptId), label: item.deptName }))
)

const filteredDelayed = computed(() => {
  const kw = keyword.value.trim().toLowerCase()
  return topDelayed.value.filter((row) => {
    if (delayFilter.value === 'SEVERE' && Number(row.delayDays || 0) < 7) return false
    if (delayFilter.value === 'RISK' && Number(row.riskOpen || 0) <= 0) return false
    if (deptFilter.value && String(row.deptId) !== deptFilter.value) return false
    if (kw && !String(row.projectName || '').toLowerCase().includes(kw)) return false
    return true
  })
})

const isKpiActive = (item: KpiCard) =>
  Boolean(item.filter && item.filter !== 'ALL' && delayFilter.value === item.filter)

const focusDelayed = (filter: DelayFilter) => {
  delayFilter.value = delayFilter.value === filter && filter !== 'ALL' ? 'ALL' : filter
  nextTick(() => delayCard.value?.scrollIntoView({ behavior: 'smooth', block: 'start' }))
}

const onKpiClick = (item: KpiCard) => {
  if (item.filter) focusDelayed(item.filter)
}

const deptMaxCount = computed(() =>
  deptStats.value.reduce((max, item) => Math.max(max, Number(item.projectCount) || 0), 0)
)

const deptBar = (row: unknown) => {
  const item = row as DeptStat
  return deptMaxCount.value > 0
    ? Math.round((Number(item.projectCount || 0) / deptMaxCount.value) * 100)
    : 0
}

const focusDept = (row: unknown) => {
  const item = row as DeptStat
  if (!item?.deptId) return
  const target = String(item.deptId)
  deptFilter.value = deptFilter.value === target ? '' : target
  delayFilter.value = 'ALL'
  nextTick(() => delayCard.value?.scrollIntoView({ behavior: 'smooth', block: 'start' }))
}

const rangeOptions = [
  { label: '近 7 天', value: 7 },
  { label: '近 30 天', value: 30 },
  { label: '近 90 天', value: 90 }
]

const setRange = (value: number) => {
  if (days.value === value) return
  days.value = value
  load()
}

/* ------------------------------ 趋势与图表 ------------------------------ */

const COLORS = {
  primary: '#3370ff',
  primarySoft: '#cfe0ff',
  ok: '#2f9e5f',
  warn: '#d68a12',
  danger: '#cf3f3f',
  axis: '#8b95a8',
  split: '#eef2f8'
}

const trendRange = computed(() => {
  const list = trendPoints.value
  if (!list.length) return ''
  return `${String(list[0].date).slice(5)} 至 ${String(list[list.length - 1].date).slice(5)}`
})

const trendLatest = computed<TrendPoint | null>(
  () => trendPoints.value[trendPoints.value.length - 1] ?? null
)

type TooltipEntry = {
  axisValueLabel?: string
  name?: string
  seriesName?: string
  value?: unknown
  marker?: string
}

const trendOption = computed(() => {
  const items = trendPoints.value
  const axisText = { fontSize: 10, color: COLORS.axis }
  return {
    grid: { left: 4, right: 4, top: 30, bottom: 2, containLabel: true },
    tooltip: {
      trigger: 'axis',
      confine: true,
      backgroundColor: 'rgba(22, 35, 61, 0.92)',
      borderWidth: 0,
      padding: [8, 10],
      textStyle: { color: '#fff', fontSize: 12 },
      axisPointer: { type: 'shadow', shadowStyle: { color: 'rgba(51, 112, 255, 0.06)' } },
      formatter: (params: unknown) => {
        const list = (Array.isArray(params) ? params : [params]) as TooltipEntry[]
        const head = String(list[0]?.axisValueLabel || list[0]?.name || '')
        const rows = list.map((entry) => {
          const isProgress = entry.seriesName === '平均进度'
          const value = isProgress
            ? `${Number(entry.value || 0).toFixed(1)}%`
            : `${Number(entry.value || 0)} 个`
          return `${entry.marker || ''}${entry.seriesName}：<b>${value}</b>`
        })
        return [`<span style="opacity:.72">${head}</span>`, ...rows].join('<br/>')
      }
    },
    legend: {
      top: 0,
      right: 0,
      itemWidth: 9,
      itemHeight: 9,
      itemGap: 12,
      textStyle: { fontSize: 11, color: '#5b6779' }
    },
    xAxis: {
      type: 'category',
      data: items.map((point) => String(point.date || '').slice(5)),
      axisTick: { show: false },
      axisLine: { lineStyle: { color: '#e3e9f4' } },
      axisLabel: axisText
    },
    yAxis: [
      {
        type: 'value',
        max: 100,
        splitNumber: 2,
        axisLabel: { ...axisText, formatter: '{value}%' },
        splitLine: { lineStyle: { color: COLORS.split } }
      },
      {
        type: 'value',
        minInterval: 1,
        axisLabel: axisText,
        splitLine: { show: false }
      }
    ],
    series: [
      {
        name: '平均进度',
        type: 'line',
        smooth: true,
        symbol: 'circle',
        symbolSize: 5,
        showSymbol: false,
        data: items.map((point) => Number(point.avgProgress || 0)),
        lineStyle: { width: 2, color: COLORS.primary },
        itemStyle: { color: COLORS.primary, borderColor: '#fff', borderWidth: 1.5 },
        areaStyle: {
          color: {
            type: 'linear',
            x: 0,
            y: 0,
            x2: 0,
            y2: 1,
            colorStops: [
              { offset: 0, color: 'rgba(51, 112, 255, 0.16)' },
              { offset: 1, color: 'rgba(51, 112, 255, 0)' }
            ]
          }
        }
      },
      {
        name: '风险项目',
        type: 'bar',
        stack: 'health',
        yAxisIndex: 1,
        barWidth: '38%',
        data: items.map((point) => Number(point.redCount || 0)),
        itemStyle: { color: COLORS.danger, borderRadius: [3, 3, 0, 0] }
      },
      {
        name: '预警项目',
        type: 'bar',
        stack: 'health',
        yAxisIndex: 1,
        barWidth: '38%',
        data: items.map((point) => Number(point.yellowCount || 0)),
        itemStyle: { color: '#f0c070', borderRadius: [3, 3, 0, 0] }
      }
    ]
  }
})

const healthOption = computed(() => ({
  tooltip: {
    trigger: 'item',
    confine: true,
    backgroundColor: 'rgba(22, 35, 61, 0.92)',
    borderWidth: 0,
    padding: [8, 10],
    textStyle: { color: '#fff', fontSize: 12 },
    formatter: '{b}：{c} 个（{d}%）'
  },
  series: [
    {
      type: 'pie',
      radius: ['64%', '88%'],
      center: ['50%', '50%'],
      avoidLabelOverlap: false,
      label: { show: false },
      labelLine: { show: false },
      itemStyle: { borderColor: '#fff', borderWidth: 3 },
      emphasis: { scale: true, scaleSize: 4 },
      data: healthList.value.map((item) => ({
        name: item.label,
        value: item.count,
        itemStyle: { color: item.color }
      }))
    }
  ]
}))

/* ------------------------------ 导出 ------------------------------ */

const csvCell = (value: unknown) => `"${String(value ?? '').replace(/"/g, '""')}"`

const exportBoard = () => {
  const now = new Date()
  const lines: unknown[][] = []
  lines.push(['公司看板数据导出', now.toLocaleString('zh-CN', { hour12: false })])
  lines.push(['趋势区间', `近 ${days.value} 天`])
  lines.push([])
  lines.push(['关键指标', '数值'])
  kpis.value.forEach((item) => lines.push([item.label, item.value]))
  lines.push([])
  lines.push(['部门对比'])
  lines.push([
    '部门',
    '项目数',
    '进行中',
    '延期',
    '开放风险',
    '未关闭问题',
    '平均进度(%)',
    '平均SPI',
    '平均CPI',
    '计划工时',
    '实际工时',
    '日志填写率(%)'
  ])
  deptStats.value.forEach((row) => {
    lines.push([
      row.deptName,
      row.projectCount,
      row.inProgressCount,
      row.delayedCount,
      row.riskOpen,
      row.issueOpen,
      row.avgProgress,
      row.avgSpi,
      row.avgCpi,
      row.plannedHours,
      row.actualHours,
      row.avgLogFillRate
    ])
  })
  lines.push([])
  lines.push(['延期项目（前 10）'])
  lines.push([
    '项目',
    '部门',
    '状态',
    '健康度',
    '进度(%)',
    'SPI',
    'CPI',
    '延期(天)',
    '开放风险',
    '日志填写率(%)'
  ])
  filteredDelayed.value.forEach((row) => {
    lines.push([
      row.projectName,
      row.deptName || '',
      statusLabel(row.status),
      healthMeta(row.health).label,
      row.progress,
      row.spi,
      row.cpi,
      row.delayDays,
      row.riskOpen,
      row.logFillRate
    ])
  })

  const csv = `\ufeff${lines
    .map((line) => line.map((cell) => csvCell(cell)).join(','))
    .join('\r\n')}`
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' })
  const href = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = href
  anchor.download = `company-board-${now.toISOString().slice(0, 10)}.csv`
  document.body.appendChild(anchor)
  anchor.click()
  document.body.removeChild(anchor)
  URL.revokeObjectURL(href)
  ElMessage.success('看板数据已导出')
}
</script>

<template>
  <div v-loading="loading" class="pms-page dashboard">
    <!-- 页头：标题 + 时间范围 + 刷新 / 导出 -->
    <section class="pms-card board-head">
      <div class="head-copy">
        <h1>
          <LayoutDashboard :size="18" :stroke-width="1.9" />
          公司项目总览
        </h1>
        <p>
          汇总全公司项目健康度、进度、工时与风险；KPI 与明细为实时数据，趋势按所选区间统计
          <template v-if="loadedAt"> · 更新于 {{ loadedAt }}</template>
        </p>
      </div>
      <div class="head-ops">
        <div class="ops-main">
          <div class="seg" role="group" aria-label="趋势时间范围">
            <button
              v-for="opt in rangeOptions"
              :key="opt.value"
              type="button"
              :class="{ 'is-active': days === opt.value }"
              :aria-pressed="days === opt.value"
              @click="setRange(opt.value)"
            >
              {{ opt.label }}
            </button>
          </div>
        </div>
        <div class="ops-actions">
          <el-button :icon="RefreshCw" :loading="loading" @click="load">刷新</el-button>
          <el-button type="primary" :icon="Download" @click="exportBoard">导出</el-button>
        </div>
      </div>
    </section>

    <!-- 快捷操作入口 -->
    <section v-if="quickActions.length" class="quick-row" aria-label="快捷操作">
      <button
        v-for="item in quickActions"
        :key="item.key"
        type="button"
        class="quick-item"
        @click="go(item.path)"
      >
        <span class="quick-icon">
          <component :is="item.icon" :size="16" :stroke-width="1.8" />
        </span>
        <span class="quick-text">
          <b>{{ item.label }}</b>
          <span>{{ item.desc }}</span>
        </span>
        <ArrowRight class="quick-arrow" :size="14" :stroke-width="1.9" />
      </button>
    </section>

    <!-- 关键指标概览 -->
    <section class="kpi-board" aria-label="关键指标">
      <article
        v-for="item in kpis"
        :key="item.key"
        class="kpi"
        :class="[
          `tone-${item.tone || 'default'}`,
          { 'is-clickable': Boolean(item.filter), 'is-active': isKpiActive(item) }
        ]"
        @click="onKpiClick(item)"
      >
        <div class="kpi-top">
          <span class="kpi-icon">
            <component :is="item.icon" :size="16" :stroke-width="1.75" />
          </span>
          <span v-if="item.filter" class="kpi-hint">
            筛选
            <ArrowRight :size="11" :stroke-width="2" />
          </span>
        </div>
        <span class="kpi-value">{{ item.value }}</span>
        <span class="kpi-label">{{ item.label }}</span>
        <span class="kpi-sub">{{ item.sub }}</span>
        <span v-if="item.bar !== undefined" class="kpi-track" aria-hidden="true">
          <i :style="{ width: `${item.bar}%` }"></i>
        </span>
      </article>
    </section>

    <!-- 趋势 / 健康度 / 状态分布 -->
    <div class="dash-grid cols-3">
      <section class="pms-card trend-card">
        <div class="pms-card-head">
          <span class="title">
            <Activity :size="15" :stroke-width="1.9" />
            项目趋势
          </span>
          <span class="pms-note">
            近 {{ days }} 天{{ trendRange ? ` · ${trendRange}` : '' }}
          </span>
        </div>
        <template v-if="trendPoints.length">
          <ChartBox :option="trendOption" height="212px" />
          <div v-if="trendLatest" class="trend-foot">
            <span>平均进度 <b>{{ pct(trendLatest.avgProgress, 1) }}</b></span>
            <span>风险项目 <b class="is-bad">{{ num(trendLatest.redCount) }}</b></span>
            <span>预警项目 <b class="is-warn">{{ num(trendLatest.yellowCount) }}</b></span>
            <span>当日工时 <b>{{ num(trendLatest.actualHours, 1) }}h</b></span>
          </div>
        </template>
        <el-empty
          v-else
          description="暂无趋势快照，执行「日预聚合」后即可查看"
          :image-size="64"
        />
      </section>

      <section class="pms-card health-card">
        <div class="pms-card-head">
          <span class="title">
            <ShieldAlert :size="15" :stroke-width="1.9" />
            健康度分布
          </span>
          <span class="pms-note">{{ summary.projectCount }} 个项目</span>
        </div>
        <div class="health-body">
          <div class="donut-wrap">
            <ChartBox v-if="summary.projectCount > 0" :option="healthOption" height="150px" />
            <div v-else class="donut-empty">暂无数据</div>
            <div class="donut-center">
              <b>{{ summary.projectCount }}</b>
              <span>项目</span>
            </div>
          </div>
          <div class="health-legend">
            <div v-for="item in healthList" :key="item.key" class="legend-row">
              <span class="dot" :class="`dot-${item.dot}`"></span>
              <span class="legend-label">{{ item.label }}</span>
              <b>{{ item.count }}</b>
              <span class="legend-pct">{{ item.percent }}%</span>
            </div>
          </div>
        </div>
      </section>

      <section class="pms-card status-card">
        <div class="pms-card-head">
          <span class="title">
            <Building2 :size="15" :stroke-width="1.9" />
            项目状态
          </span>
          <span class="pms-note">{{ statusRows.length }} 种状态</span>
        </div>
        <div v-if="statusRows.length" class="status-list">
          <div v-for="item in statusRows" :key="item.key" class="status-row">
            <span class="status-label" :title="item.label">{{ item.label }}</span>
            <span class="status-track">
              <i :class="`bar-${item.tone}`" :style="{ width: `${item.percent}%` }"></i>
            </span>
            <span class="status-count">{{ item.count }}</span>
          </div>
        </div>
        <el-empty v-else description="暂无项目" :image-size="56" />
      </section>
    </div>

    <!-- 部门对比 / 工时执行 / 风险项目 -->
    <div class="dash-grid cols-main">
      <section class="pms-card dept-card">
        <div class="pms-card-head">
          <span class="title">
            <Building2 :size="15" :stroke-width="1.9" />
            部门对比
          </span>
          <span class="pms-note">点击部门行可筛选下方延期项目</span>
        </div>
        <el-table
          :data="deptStats"
          size="small"
          max-height="336"
          empty-text="暂无部门数据"
          @row-click="focusDept"
        >
          <el-table-column prop="deptName" label="部门" min-width="150" show-overflow-tooltip />
          <el-table-column prop="projectCount" label="项目" width="132" sortable>
            <template #default="{ row }">
              <div class="bar-cell">
                <span class="bar-cell-value">{{ row.projectCount }}</span>
                <span class="bar-cell-track">
                  <i :style="{ width: `${deptBar(row)}%` }"></i>
                </span>
              </div>
            </template>
          </el-table-column>
          <el-table-column prop="delayedCount" label="延期" width="78" sortable align="right">
            <template #default="{ row }">
              <span :class="{ 'is-bad': Number(row.delayedCount) > 0 }">
                {{ row.delayedCount }}
              </span>
            </template>
          </el-table-column>
          <el-table-column prop="riskOpen" label="风险" width="78" sortable align="right">
            <template #default="{ row }">
              <span :class="{ 'is-bad': Number(row.riskOpen) > 0 }">{{ row.riskOpen }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="avgProgress" label="平均进度" min-width="146" sortable>
            <template #default="{ row }">
              <div class="progress-cell">
                <el-progress
                  :percentage="barWidth(row.avgProgress)"
                  :stroke-width="6"
                  :show-text="false"
                />
                <span class="progress-text">{{ num(row.avgProgress, 1) }}%</span>
              </div>
            </template>
          </el-table-column>
          <el-table-column prop="avgSpi" label="SPI" width="78" sortable align="right">
            <template #default="{ row }">
              <span :class="`index-${indexTone(row.avgSpi)}`">{{ num(row.avgSpi, 2) }}</span>
            </template>
          </el-table-column>
          <el-table-column
            prop="actualHours"
            label="工时"
            width="96"
            sortable
            align="right"
            class-name="pms-mobile-hide"
          >
            <template #default="{ row }">{{ num(row.actualHours, 1) }}h</template>
          </el-table-column>
          <el-table-column label="操作" width="70" align="right">
            <template #default="{ row }">
              <el-button link type="primary" size="small" @click.stop="focusDept(row)">
                筛选
              </el-button>
            </template>
          </el-table-column>
        </el-table>
      </section>

      <div class="side-stack">
        <section class="pms-card hours-card">
          <div class="pms-card-head">
            <span class="title">
              <Gauge :size="15" :stroke-width="1.9" />
              工时执行
            </span>
            <span class="pms-note">计划 vs 实际</span>
          </div>
          <div class="hours-top">
            <div class="hours-item">
              <span>计划</span>
              <b>{{ num(plannedHours, 1) }}h</b>
            </div>
            <div class="hours-item">
              <span>实际</span>
              <b>{{ num(actualHours, 1) }}h</b>
            </div>
            <div class="hours-ratio">
              <b>{{ execPercent }}%</b>
              <span>执行率</span>
            </div>
          </div>
          <div class="hours-track" aria-hidden="true">
            <i :style="{ width: `${execPercent}%` }"></i>
          </div>
          <div class="hours-mini">
            <span>变更 <b>{{ num(summary.changeCount) }}</b></span>
            <span>未关闭问题 <b>{{ num(summary.issueOpen) }}</b></span>
            <span>日志填写率 <b>{{ num(summary.avgLogFillRate, 1) }}%</b></span>
          </div>
        </section>

        <section class="pms-card risk-card">
          <div class="pms-card-head">
            <span class="title">
              <TriangleAlert :size="15" :stroke-width="1.9" />
              风险项目 Top
            </span>
            <span class="pms-note">{{ topRisk.length }} 个</span>
          </div>
          <div v-if="topRisk.length" class="risk-list">
            <div v-for="item in topRisk" :key="item.projectId" class="risk-row">
              <span class="risk-dot" aria-hidden="true"></span>
              <span class="risk-name" :title="item.projectName">{{ item.projectName }}</span>
              <span class="risk-dept">{{ item.deptName || '—' }}</span>
              <span class="risk-badge">{{ item.riskOpen }}</span>
            </div>
          </div>
          <el-empty v-else description="暂无开放风险" :image-size="56" />
        </section>
      </div>
    </div>

    <!-- 延期项目明细 -->
    <section ref="delayCard" class="pms-card delay-card">
      <div class="pms-card-head">
        <span class="title">
          <TriangleAlert :size="15" :stroke-width="1.9" />
          延期项目
        </span>
        <span class="pms-note">按延期天数排序，取前 10</span>
      </div>

      <div class="table-toolbar">
        <div class="seg" role="group" aria-label="延期筛选">
          <button
            v-for="tab in DELAY_TABS"
            :key="tab.key"
            type="button"
            :class="{ 'is-active': delayFilter === tab.key }"
            :aria-pressed="delayFilter === tab.key"
            @click="delayFilter = tab.key"
          >
            {{ tab.label }}
          </button>
        </div>
        <el-select
          v-model="deptFilter"
          class="dept-select"
          size="small"
          placeholder="全部部门"
          clearable
        >
          <el-option
            v-for="opt in deptOptions"
            :key="opt.value"
            :label="opt.label"
            :value="opt.value"
          />
        </el-select>
        <el-input
          v-model="keyword"
          class="table-search"
          size="small"
          placeholder="搜索项目名称"
          clearable
        />
      </div>

      <el-table :data="filteredDelayed" size="default">
        <template #empty>
          <el-empty
            :description="topDelayed.length ? '没有符合筛选条件的项目' : '暂无延期项目'"
            :image-size="64"
          />
        </template>
        <el-table-column prop="projectName" label="项目" min-width="190" show-overflow-tooltip />
        <el-table-column label="部门" min-width="120" class-name="pms-mobile-hide">
          <template #default="{ row }">{{ row.deptName || '—' }}</template>
        </el-table-column>
        <el-table-column label="状态" width="104">
          <template #default="{ row }">
            <el-tag :type="statusTone(row.status)" size="small" effect="plain">
              {{ statusLabel(row.status) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="健康度" width="92">
          <template #default="{ row }">
            <el-tag :type="healthMeta(row.health).tone" size="small">
              {{ healthMeta(row.health).label }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="进度" width="150">
          <template #default="{ row }">
            <div class="progress-cell">
              <el-progress
                :percentage="barWidth(row.progress)"
                :stroke-width="6"
                :show-text="false"
              />
              <span class="progress-text">{{ num(row.progress, 1) }}%</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="SPI" width="78" align="right" class-name="pms-mobile-hide">
          <template #default="{ row }">
            <span :class="`index-${indexTone(row.spi)}`">{{ num(row.spi, 2) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="CPI" width="78" align="right" class-name="pms-mobile-hide">
          <template #default="{ row }">
            <span :class="`index-${indexTone(row.cpi)}`">{{ num(row.cpi, 2) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="delayDays" label="延期" width="98" sortable align="right">
          <template #default="{ row }">
            <span class="delay-badge">+{{ row.delayDays }} 天</span>
          </template>
        </el-table-column>
        <el-table-column prop="riskOpen" label="风险" width="78" sortable align="right">
          <template #default="{ row }">
            <span :class="{ 'is-bad': Number(row.riskOpen) > 0 }">{{ row.riskOpen }}</span>
          </template>
        </el-table-column>
        <el-table-column
          prop="logFillRate"
          label="日志填写率"
          width="116"
          align="right"
          class-name="pms-mobile-hide"
        >
          <template #default="{ row }">
            <span :class="{ 'is-bad': Number(row.logFillRate) < 60 }">
              {{ num(row.logFillRate, 1) }}%
            </span>
          </template>
        </el-table-column>
      </el-table>

      <p class="table-foot">
        共 {{ filteredDelayed.length }} 个项目 · 指标口径：SPI / CPI ≥ 1.00 为良好，日志填写率低于
        60% 提示风险
      </p>
    </section>
  </div>
</template>

<style scoped>
/* ------------------------------ 页头 ------------------------------ */
.board-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 12px 16px;
}

.head-copy {
  flex: 1 1 320px;
  min-width: 0;
}

.head-copy h1 {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 0;
  font-size: 18px;
  font-weight: 600;
  letter-spacing: -0.01em;
  color: var(--pms-text);
}

.head-copy h1 svg {
  color: var(--pms-primary);
}

.head-copy p {
  margin: 6px 0 0;
  font-size: 12.5px;
  line-height: 1.7;
  color: var(--pms-text-3);
}

/* 操作区：主控（时间范围）靠左、动作（刷新/导出）靠右，窄屏铺满整行 */
.head-ops {
  flex: 0 1 auto;
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
  margin-left: auto;
  min-width: 0;
}

.ops-main {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.ops-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-left: auto;
}

/* ------------------------------ 分段控件 ------------------------------ */
.seg {
  display: inline-flex;
  flex-wrap: wrap;
  gap: 2px;
  padding: 3px;
  border: 1px solid #e3e9f4;
  border-radius: 9px;
  background: #eef2f8;
}

.seg button {
  height: 26px;
  padding: 0 11px;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: var(--pms-text-2);
  font-family: inherit;
  font-size: 12.5px;
  white-space: nowrap;
  cursor: pointer;
  transition:
    background-color 0.16s ease,
    color 0.16s ease,
    box-shadow 0.16s ease;
}

.seg button:hover {
  color: var(--pms-text);
}

.seg button.is-active {
  background: var(--pms-surface);
  color: var(--pms-primary-deep);
  font-weight: 500;
  box-shadow: 0 1px 2px rgba(16, 35, 70, 0.08);
}

.seg button:focus-visible {
  outline: 2px solid var(--pms-primary);
  outline-offset: 1px;
}

/* ------------------------------ 快捷操作 ------------------------------ */
.quick-row {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
  margin-bottom: 14px;
}

.quick-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 11px 14px;
  border: 1px solid var(--pms-line);
  border-radius: var(--pms-radius);
  background: var(--pms-surface);
  font-family: inherit;
  text-align: left;
  cursor: pointer;
  transition:
    border-color 0.16s ease,
    box-shadow 0.16s ease,
    transform 0.16s ease;
}

.quick-item:hover {
  border-color: #c9d9f8;
  box-shadow: 0 6px 16px -12px rgba(16, 35, 70, 0.35);
  transform: translateY(-1px);
}

.quick-icon {
  flex: none;
  width: 30px;
  height: 30px;
  display: grid;
  place-items: center;
  border-radius: 8px;
  background: var(--pms-primary-weak);
  color: var(--pms-primary);
}

.quick-text {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 1px;
}

.quick-text b {
  font-size: 13px;
  font-weight: 600;
  color: var(--pms-text);
}

.quick-text span {
  overflow: hidden;
  font-size: 11.5px;
  color: var(--pms-text-3);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.quick-arrow {
  flex: none;
  margin-left: auto;
  color: #b9c3d4;
  transition:
    color 0.16s ease,
    transform 0.16s ease;
}

.quick-item:hover .quick-arrow {
  color: var(--pms-primary);
  transform: translateX(2px);
}

/* ------------------------------ KPI ------------------------------ */
.kpi-board {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 1px;
  margin-bottom: 14px;
  overflow: hidden;
  border: 1px solid var(--pms-line);
  border-radius: var(--pms-radius);
  background: var(--pms-line);
}

.kpi {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-height: 134px;
  padding: 14px 16px 15px;
  background: var(--pms-surface);
  transition:
    background-color 0.18s ease,
    box-shadow 0.18s ease;
}

.kpi:hover {
  background: #fbfcff;
}

.kpi.is-clickable {
  cursor: pointer;
}

.kpi.is-active {
  background: #f2f7ff;
  box-shadow: inset 0 0 0 1.5px var(--pms-primary);
}

.kpi-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 4px;
}

.kpi-icon {
  width: 28px;
  height: 28px;
  display: grid;
  place-items: center;
  border-radius: 8px;
  background: #f2f5fb;
  color: var(--pms-text-2);
}

.kpi-hint {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  font-size: 11px;
  color: var(--pms-text-3);
  opacity: 0;
  transition: opacity 0.16s ease;
}

.kpi.is-clickable:hover .kpi-hint,
.kpi.is-active .kpi-hint {
  opacity: 1;
}

.kpi-value {
  font-size: 24px;
  font-weight: 600;
  line-height: 1.2;
  letter-spacing: -0.02em;
  color: var(--pms-text);
  font-variant-numeric: tabular-nums;
}

.kpi-label {
  font-size: 12.5px;
  color: var(--pms-text-2);
}

.kpi-sub {
  margin-top: auto;
  overflow: hidden;
  font-size: 11.5px;
  color: var(--pms-text-3);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.kpi-track {
  height: 4px;
  margin-top: 6px;
  overflow: hidden;
  border-radius: 2px;
  background: #eef2f8;
}

.kpi-track i {
  display: block;
  height: 100%;
  border-radius: 2px;
  background: linear-gradient(90deg, #7aa2ff, var(--pms-primary));
  transition: width 0.24s ease;
}

.tone-primary .kpi-icon {
  background: var(--pms-primary-weak);
  color: var(--pms-primary);
}

.tone-success .kpi-icon {
  background: var(--pms-ok-weak);
  color: var(--pms-ok);
}

.tone-warning .kpi-icon {
  background: var(--pms-warn-weak);
  color: var(--pms-warn);
}

.tone-danger .kpi-icon {
  background: var(--pms-danger-weak);
  color: var(--pms-danger);
}

/* ------------------------------ 栅格 ------------------------------ */
.dash-grid {
  display: grid;
  gap: 14px;
  margin-bottom: 14px;
}

.cols-3 {
  grid-template-columns: minmax(0, 1.55fr) minmax(0, 1fr) minmax(0, 0.85fr);
}

.cols-main {
  grid-template-columns: minmax(0, 1.45fr) minmax(0, 1fr);
}

.dash-grid > .pms-card {
  margin-bottom: 0;
}

.side-stack {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.side-stack > .pms-card {
  flex: 1;
  margin-bottom: 0;
}

/* ------------------------------ 趋势 ------------------------------ */
.trend-card :deep(.chart-box) {
  margin: 2px 0 6px;
}

.trend-foot {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 16px;
  padding-top: 10px;
  border-top: 1px solid var(--pms-line-soft);
  font-size: 12px;
  color: var(--pms-text-3);
}

.trend-foot b {
  color: var(--pms-text);
  font-variant-numeric: tabular-nums;
}

/* ------------------------------ 健康度 ------------------------------ */
.health-body {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
}

.donut-wrap {
  position: relative;
  width: 150px;
  flex: none;
}

.donut-center {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  pointer-events: none;
}

.donut-center b {
  font-size: 21px;
  font-weight: 600;
  line-height: 1.2;
  letter-spacing: -0.01em;
  color: var(--pms-text);
  font-variant-numeric: tabular-nums;
}

.donut-center span {
  font-size: 11px;
  color: var(--pms-text-3);
}

.donut-empty {
  height: 150px;
  display: grid;
  place-items: center;
  border-radius: 50%;
  background: #f4f7fd;
  font-size: 12px;
  color: var(--pms-text-3);
}

.health-legend {
  width: 100%;
  display: grid;
  gap: 2px;
}

.legend-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 7px 8px;
  border-radius: 7px;
  font-size: 12.5px;
  color: var(--pms-text-2);
}

.legend-row:hover {
  background: #fafbfe;
}

.legend-label {
  min-width: 0;
}

.legend-row b {
  margin-left: auto;
  font-size: 14px;
  font-weight: 600;
  color: var(--pms-text);
  font-variant-numeric: tabular-nums;
}

.legend-pct {
  width: 36px;
  font-size: 11.5px;
  color: var(--pms-text-3);
  text-align: right;
  font-variant-numeric: tabular-nums;
}

.dot {
  flex: none;
  width: 8px;
  height: 8px;
  border-radius: 50%;
}

.dot-ok {
  background: var(--pms-ok);
}

.dot-warn {
  background: var(--pms-warn);
}

.dot-danger {
  background: var(--pms-danger);
}

/* ------------------------------ 状态分布 ------------------------------ */
.status-list {
  display: grid;
  gap: 11px;
  padding-top: 2px;
}

.status-row {
  display: grid;
  grid-template-columns: 70px minmax(0, 1fr) 28px;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: var(--pms-text-2);
}

.status-label {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.status-track {
  height: 6px;
  overflow: hidden;
  border-radius: 3px;
  background: #f0f4fa;
}

.status-track i {
  display: block;
  height: 100%;
  min-width: 4px;
  border-radius: 3px;
  transition: width 0.24s ease;
}

.status-count {
  font-weight: 600;
  color: var(--pms-text);
  text-align: right;
  font-variant-numeric: tabular-nums;
}

.bar-primary {
  background: var(--pms-primary);
}

.bar-success {
  background: var(--pms-ok);
}

.bar-warning {
  background: var(--pms-warn);
}

.bar-danger {
  background: var(--pms-danger);
}

.bar-info {
  background: #94a3b8;
}

/* ------------------------------ 部门对比 ------------------------------ */
.dept-card :deep(.el-table__row) {
  cursor: pointer;
}

.bar-cell {
  display: flex;
  align-items: center;
  gap: 8px;
}

.bar-cell-value {
  width: 20px;
  font-variant-numeric: tabular-nums;
}

.bar-cell-track {
  flex: 1;
  min-width: 24px;
  height: 5px;
  overflow: hidden;
  border-radius: 3px;
  background: #eef2f8;
}

.bar-cell-track i {
  display: block;
  height: 100%;
  border-radius: 3px;
  background: #b9cffb;
}

.progress-cell {
  display: flex;
  align-items: center;
  gap: 8px;
}

.progress-cell :deep(.el-progress) {
  flex: 1;
  min-width: 0;
}

.progress-text {
  flex: none;
  width: 44px;
  font-size: 12px;
  color: var(--pms-text-2);
  text-align: right;
  font-variant-numeric: tabular-nums;
}

.index-success {
  color: var(--pms-ok);
  font-variant-numeric: tabular-nums;
}

.index-warning {
  color: var(--pms-warn);
  font-variant-numeric: tabular-nums;
}

.index-danger {
  color: var(--pms-danger);
  font-variant-numeric: tabular-nums;
}

.index-default {
  color: var(--pms-text-2);
  font-variant-numeric: tabular-nums;
}

/* ------------------------------ 工时执行 ------------------------------ */
.hours-top {
  display: flex;
  align-items: flex-end;
  gap: 18px;
}

.hours-item {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.hours-item span {
  font-size: 11.5px;
  color: var(--pms-text-3);
}

.hours-item b {
  font-size: 17px;
  font-weight: 600;
  color: var(--pms-text);
  font-variant-numeric: tabular-nums;
}

.hours-ratio {
  margin-left: auto;
  text-align: right;
}

.hours-ratio b {
  display: block;
  font-size: 21px;
  font-weight: 600;
  line-height: 1.2;
  color: var(--pms-primary-deep);
  font-variant-numeric: tabular-nums;
}

.hours-ratio span {
  font-size: 11px;
  color: var(--pms-text-3);
}

.hours-track {
  height: 8px;
  margin: 10px 0 12px;
  overflow: hidden;
  border-radius: 4px;
  background: #eef2f8;
}

.hours-track i {
  display: block;
  height: 100%;
  border-radius: 4px;
  background: linear-gradient(90deg, #7aa2ff, var(--pms-primary));
  transition: width 0.24s ease;
}

.hours-mini {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 14px;
  font-size: 11.5px;
  color: var(--pms-text-3);
}

.hours-mini b {
  margin-left: 2px;
  color: var(--pms-text-2);
  font-variant-numeric: tabular-nums;
}

/* ------------------------------ 风险 Top ------------------------------ */
.risk-list {
  display: grid;
  gap: 2px;
}

.risk-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 7px 8px;
  border-radius: 7px;
  font-size: 12.5px;
}

.risk-row:hover {
  background: #fafbfe;
}

.risk-dot {
  flex: none;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--pms-danger);
}

.risk-name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  color: var(--pms-text);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.risk-dept {
  flex: none;
  max-width: 90px;
  overflow: hidden;
  font-size: 11.5px;
  color: var(--pms-text-3);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.risk-badge {
  flex: none;
  min-width: 22px;
  height: 20px;
  padding: 0 6px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 6px;
  background: var(--pms-danger-weak);
  color: var(--pms-danger);
  font-size: 11.5px;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}

/* ------------------------------ 延期表 ------------------------------ */
.table-toolbar {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
  margin-bottom: 10px;
}

.dept-select {
  width: 170px;
}

.table-search {
  width: 200px;
  margin-left: auto;
}

.table-foot {
  margin: 10px 0 0;
  font-size: 11.5px;
  line-height: 1.6;
  color: var(--pms-text-3);
}

.delay-badge {
  display: inline-flex;
  align-items: center;
  height: 22px;
  padding: 0 8px;
  border-radius: 6px;
  background: var(--pms-warn-weak);
  color: var(--pms-warn);
  font-size: 12px;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}

.is-bad {
  color: var(--pms-danger);
  font-weight: 500;
}

.is-warn {
  color: var(--pms-warn);
}

.dashboard :deep(.el-empty) {
  padding: 16px 0;
}

/* ------------------------------ 响应式 ------------------------------ */
@media (max-width: 1280px) {
  .cols-3 {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .trend-card {
    grid-column: 1 / -1;
  }
}

@media (max-width: 1024px) {
  .kpi-board {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .quick-row {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .cols-main {
    grid-template-columns: 1fr;
  }

  .side-stack {
    gap: 14px;
  }
}

@media (max-width: 860px) {
  .cols-3 {
    grid-template-columns: 1fr;
  }

  .trend-card {
    grid-column: auto;
  }

  .head-ops {
    width: 100%;
    margin-left: 0;
  }

  .ops-main {
    flex: 1 1 auto;
  }

  .ops-main .seg {
    flex: 1 1 auto;
  }

  .ops-main .seg button {
    flex: 1;
  }
}

@media (max-width: 768px) {
  .kpi {
    min-height: 118px;
    padding: 12px 13px 13px;
  }

  .kpi-value {
    font-size: 21px;
  }

  .kpi-sub {
    white-space: normal;
  }

  .quick-row {
    grid-template-columns: 1fr;
    gap: 8px;
  }

  .quick-item {
    padding: 10px 12px;
  }

  .dept-select,
  .table-search {
    width: 100%;
    margin-left: 0;
  }

  .table-toolbar {
    gap: 8px;
  }

  .table-toolbar .seg {
    width: 100%;
  }

  .table-toolbar .seg button {
    flex: 1;
  }

  .dashboard :deep(.pms-card-head .pms-note) {
    display: none;
  }
}

@media (prefers-reduced-motion: reduce) {
  .quick-item,
  .quick-arrow,
  .kpi,
  .kpi-track i,
  .status-track i,
  .hours-track i {
    transition: none;
  }
}
</style>
