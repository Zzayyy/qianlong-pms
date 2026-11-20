<script setup lang="ts">
import { computed, onMounted, ref, type Component } from 'vue'
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
  TriangleAlert
} from 'lucide-vue-next'
import { companyBoard, myTodo, type TodoItem } from '@/api'
import ChartBox from '@/components/ChartBox.vue'
import { useUserStore } from '@/stores/user'

/* ------------------------------ 类型 ------------------------------ */

type TagType = 'primary' | 'success' | 'info' | 'warning' | 'danger'

interface BoardSummary {
  projectCount: number
  inProgressCount: number
  delayedCount: number
  avgProgress: number
  plannedHours: number
  actualHours: number
  byStatus: Record<string, number>
}

interface CompanyBoard {
  summary?: Partial<BoardSummary>
}

interface KpiCard {
  key: string
  label: string
  icon: Component
  value: string
  sub: string
  /** 平均进度等百分比指标附带底部进度条 */
  bar?: number
  /** 可下钻到项目周期页（支持 `path?query`） */
  to?: string
}

/* ------------------------------ 状态 ------------------------------ */

const store = useUserStore()
const router = useRouter()

const board = ref<CompanyBoard>({})
const loading = ref(false)
const loadedAt = ref('')

const EMPTY_SUMMARY: BoardSummary = {
  projectCount: 0,
  inProgressCount: 0,
  delayedCount: 0,
  avgProgress: 0,
  plannedHours: 0,
  actualHours: 0,
  byStatus: {}
}

const summary = computed<BoardSummary>(() => ({
  ...EMPTY_SUMMARY,
  ...(board.value.summary || {})
}))

/* ------------------------------ 我的待办 ------------------------------ */

const todos = ref<TodoItem[]>([])
const todoLoading = ref(false)

/** 待办图标按 key 映射（后端只下发数据，不关心图标）。 */
const TODO_ICONS: Record<string, Component> = {
  'my-task': CirclePlay,
  'my-project': FolderKanban,
  'log-today': NotebookPen,
  'log-reminder': NotebookPen,
  'log-confirm': TriangleAlert,
  'change-approve': GitPullRequest
}
const todoIcon = (key: string) => TODO_ICONS[key] ?? Activity

const loadTodo = async () => {
  todoLoading.value = true
  try {
    todos.value = (await myTodo()) || []
  } catch {
    todos.value = []
  } finally {
    todoLoading.value = false
  }
}

/** 站内跳转：支持 `path?query` 形式（如 `/projects?status=IN_PROGRESS`）。 */
const go = (target: string) => {
  const [path, search] = target.split('?')
  if (!search) {
    router.push(path)
    return
  }
  router.push({ path, query: Object.fromEntries(new URLSearchParams(search)) })
}

const load = async () => {
  loading.value = true
  try {
    board.value = (await companyBoard()) as unknown as CompanyBoard
    const now = new Date()
    loadedAt.value = `${now.getMonth() + 1}/${now.getDate()} ${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}`
    await loadTodo()
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

/* ------------------------------ 派生指标 ------------------------------ */

const inProgressPercent = computed(() => {
  const total = Number(summary.value.projectCount || 0)
  return total > 0 ? Math.round((Number(summary.value.inProgressCount || 0) / total) * 100) : 0
})

const delayedPercent = computed(() => {
  const total = Number(summary.value.projectCount || 0)
  return total > 0 ? Math.round((Number(summary.value.delayedCount || 0) / total) * 100) : 0
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

/** 条形图按数量倒序，量大的状态排在顶部更易读。 */
const statusChartRows = computed(() => [...statusRows.value].sort((a, b) => b.count - a.count))

/** 条高随条目数自适应，避免少条目时留白、多条目时挤压。 */
const statusChartHeight = computed(() => `${Math.max(statusChartRows.value.length * 30, 96)}px`)

const kpis = computed<KpiCard[]>(() => {
  const s = summary.value
  return [
    {
      key: 'projectCount',
      label: '项目总数',
      icon: FolderKanban,
      value: num(s.projectCount),
      sub: `进行中 ${num(s.inProgressCount)} 个 · 计划 ${num(s.plannedHours)}h`,
      to: '/projects'
    },
    {
      key: 'inProgressCount',
      label: '进行中',
      icon: CirclePlay,
      value: num(s.inProgressCount),
      sub: `占全部项目 ${inProgressPercent.value}%`,
      to: '/projects?status=IN_PROGRESS'
    },
    {
      key: 'delayedCount',
      label: '延期项目',
      icon: TriangleAlert,
      value: num(s.delayedCount),
      sub: Number(s.delayedCount || 0) > 0 ? `占全部项目 ${delayedPercent.value}%` : '暂无延期项目'
    },
    {
      key: 'avgProgress',
      label: '平均进度',
      icon: Gauge,
      value: pct(s.avgProgress, 1),
      sub: `实际投入 ${num(s.actualHours, 0)}h`,
      bar: barWidth(s.avgProgress)
    }
  ]
})

const onKpiClick = (item: KpiCard) => {
  if (item.to) go(item.to)
}

/* ------------------------------ 状态图表 ------------------------------ */

const COLORS = {
  primary: '#3370ff',
  ok: '#2f9e5f',
  warn: '#d68a12',
  danger: '#cf3f3f'
}

/** 状态条颜色跟状态标签一致，避免同一状态两种色系。 */
const STATUS_BAR_COLOR: Record<TagType, string> = {
  primary: COLORS.primary,
  success: COLORS.ok,
  warning: COLORS.warn,
  danger: COLORS.danger,
  info: '#94a3b8'
}

const statusOption = computed(() => {
  const rows = statusChartRows.value
  const max = rows.reduce((acc, row) => Math.max(acc, row.count), 1)
  return {
    grid: { left: 4, right: 76, top: 4, bottom: 2, containLabel: true },
    tooltip: {
      trigger: 'item',
      confine: true,
      backgroundColor: 'rgba(22, 35, 61, 0.92)',
      borderWidth: 0,
      padding: [8, 10],
      textStyle: { color: '#fff', fontSize: 12 },
      formatter: (params: unknown) => {
        const item = params as { name?: string; data?: { value?: number; percent?: number } }
        return `${item.name}：<b>${Number(item.data?.value || 0)}</b> 个（${Number(item.data?.percent || 0)}%）`
      }
    },
    xAxis: { type: 'value', show: false, max },
    yAxis: {
      type: 'category',
      data: rows.map((row) => row.label),
      axisTick: { show: false },
      axisLine: { show: false },
      axisLabel: { fontSize: 12, color: '#5b6779' }
    },
    series: [
      {
        type: 'bar',
        barWidth: 12,
        cursor: 'pointer',
        data: rows.map((row) => ({
          value: row.count,
          code: row.key,
          percent: row.percent,
          itemStyle: { color: STATUS_BAR_COLOR[row.tone], borderRadius: [0, 6, 6, 0] }
        })),
        label: {
          show: true,
          position: 'right',
          fontSize: 12,
          color: '#5b6779',
          formatter: (params: unknown) => {
            const item = params as { data?: { value?: number; percent?: number } }
            return `${Number(item.data?.value || 0)} 个（${Number(item.data?.percent || 0)}%）`
          }
        },
        emphasis: { itemStyle: { opacity: 0.82 } }
      }
    ]
  }
})

/** 点击状态条 → 项目周期页按该状态精确筛选。 */
const onStatusClick = (params: unknown) => {
  const code = (params as { data?: { code?: string } })?.data?.code
  if (!code) return
  go(`/projects?status=${code}`)
}

/* ------------------------------ 导出 ------------------------------ */

const csvCell = (value: unknown) => `"${String(value ?? '').replace(/"/g, '""')}"`

const exportBoard = () => {
  const now = new Date()
  const lines: unknown[][] = []
  lines.push(['公司看板数据导出', now.toLocaleString('zh-CN', { hour12: false })])
  lines.push([])
  lines.push(['关键指标', '数值'])
  kpis.value.forEach((item) => lines.push([item.label, item.value]))
  lines.push([])
  lines.push(['项目状态分布'])
  lines.push(['状态', '项目数', '占比(%)'])
  statusChartRows.value.forEach((row) =>
    lines.push([row.label, row.count, row.percent])
  )

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
    <!-- 页头：标题 + 刷新 / 导出 -->
    <section class="pms-card board-head">
      <div class="head-copy">
        <h1>
          <LayoutDashboard :size="18" :stroke-width="1.9" />
          公司项目总览
        </h1>
        <p>
          全公司项目状态分布与关键指标
          <template v-if="loadedAt"> · 更新于 {{ loadedAt }}</template>
        </p>
      </div>
      <div class="ops-actions">
        <el-button
          v-if="store.has('project:create')"
          :icon="Plus"
          @click="go('/projects?create=1')"
        >
          新建项目
        </el-button>
        <el-button :icon="RefreshCw" :loading="loading" @click="load">刷新</el-button>
        <el-button type="primary" :icon="Download" @click="exportBoard">导出</el-button>
      </div>
    </section>

    <!-- 我的待办：数据驱动，替代原来纯导航的快捷入口 -->
    <section
      v-if="todos.length"
      v-loading="todoLoading"
      class="quick-row"
      aria-label="我的待办"
    >
      <button
        v-for="item in todos"
        :key="item.key"
        type="button"
        class="quick-item"
        :class="`todo-${item.tone}`"
        @click="go(item.path)"
      >
        <span class="quick-icon">
          <component :is="todoIcon(item.key)" :size="16" :stroke-width="1.8" />
        </span>
        <span class="quick-text">
          <b>{{ item.label }}</b>
          <span>{{ item.desc }}</span>
        </span>
        <span class="quick-count">{{ item.count }}</span>
        <ArrowRight class="quick-arrow" :size="14" :stroke-width="1.9" />
      </button>
    </section>

    <!-- 关键指标概览 -->
    <section class="kpi-board" aria-label="关键指标">
      <article
        v-for="item in kpis"
        :key="item.key"
        class="kpi"
        :class="{ 'is-clickable': Boolean(item.to) }"
        @click="onKpiClick(item)"
      >
        <div class="kpi-top">
          <span class="kpi-icon">
            <component :is="item.icon" :size="16" :stroke-width="1.75" />
          </span>
          <span v-if="item.to" class="kpi-hint">
            查看
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

    <!-- 项目状态分布：唯一的明细图表，点击可下钻到项目周期页 -->
    <section class="pms-card status-card">
      <div class="pms-card-head">
        <span class="title">
          <Building2 :size="15" :stroke-width="1.9" />
          项目状态
        </span>
        <span class="pms-note">{{ statusChartRows.length }} 种状态 · 点击条形查看项目</span>
      </div>
      <template v-if="statusChartRows.length">
        <ChartBox
          :option="statusOption"
          :height="statusChartHeight"
          @chart-click="onStatusClick"
        />
        <p class="status-foot">
          共 {{ summary.projectCount }} 个项目 · 点击条形跳转到对应状态的项目列表
        </p>
      </template>
      <el-empty v-else description="暂无项目" :image-size="56" />
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

.ops-actions {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  margin-left: auto;
}

/* ------------------------------ 我的待办 ------------------------------ */
.quick-row {
  display: grid;
  /* 待办条数不固定（1~6 项），用 auto-fit 让卡片自动铺满一行，避免右侧留空 */
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
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

/* 待办数量徽标：靠右、与箭头同组 */
.quick-count {
  flex: none;
  min-width: 22px;
  height: 20px;
  display: inline-grid;
  place-items: center;
  margin-left: auto;
  padding: 0 6px;
  border-radius: 999px;
  background: var(--pms-primary-weak);
  color: var(--pms-primary-deep);
  font-size: 11.5px;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}

.todo-warning .quick-icon {
  color: #d48806;
}

.todo-warning .quick-count {
  background: #fff5e6;
  color: #ad6800;
}

.todo-danger .quick-icon {
  color: #cf1322;
}

.todo-danger .quick-count {
  background: #fdecec;
  color: #cf1322;
}

.quick-arrow {
  flex: none;
  margin-left: 4px;
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
  min-height: 118px;
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

.kpi.is-clickable:hover .kpi-hint {
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

.kpi:nth-child(2) .kpi-icon {
  background: var(--pms-primary-weak);
  color: var(--pms-primary);
}

/* ------------------------------ 项目状态 ------------------------------ */
.status-card :deep(.chart-box) {
  margin-top: 4px;
}

.status-foot {
  margin: 10px 0 0;
  font-size: 11.5px;
  line-height: 1.6;
  color: var(--pms-text-3);
}

.dashboard :deep(.el-empty) {
  padding: 16px 0;
}

/* ------------------------------ 响应式 ------------------------------ */
@media (max-width: 1024px) {
  .kpi-board {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .quick-row {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 768px) {
  .kpi {
    min-height: 108px;
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

  .dashboard :deep(.pms-card-head .pms-note) {
    display: none;
  }
}

@media (prefers-reduced-motion: reduce) {
  .quick-item,
  .quick-arrow,
  .kpi,
  .kpi-track i {
    transition: none;
  }
}
</style>
