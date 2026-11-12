<script setup lang="ts">
import { computed, onMounted, ref, type Component } from 'vue'
import {
  Building2,
  CirclePlay,
  FolderKanban,
  Gauge,
  NotebookPen,
  ShieldAlert,
  TrendingDown,
  TrendingUp,
  TriangleAlert
} from 'lucide-vue-next'
import { deptBoard, deptMembers, deptTrend, projectBoard, reportDepts } from '@/api'
import ChartBox from '@/components/ChartBox.vue'
import { useUserStore } from '@/stores/user'

interface DeptRow {
  id: string
  parentId: string
  deptName: string
}

interface DeptNode {
  value: string
  label: string
  children?: DeptNode[]
}

interface ProjectMetric {
  projectId: string
  projectName: string
  deptId: string
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
  byHealth: Record<string, number>
}

interface StageItem {
  id: string
  stageName: string
  progress: number
  weight: number
  planStart: string
  planEnd: string
}

interface MilestoneItem {
  id: string
  name: string
  planDate: string
  actualDate: string
  status: string
  delayDays: number
}

interface ProjectBoardData {
  metric: ProjectMetric
  stages: StageItem[]
  milestones: MilestoneItem[]
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

interface MemberLoad {
  userId: string
  realName: string
  deptId: string
  hours: number
  projects: number
  logDays: number
  fillRate: number
}

type TagType = 'primary' | 'success' | 'info' | 'warning' | 'danger'

const ALL_DEPT = '__all__'

const store = useUserStore()
const loading = ref(false)
const flatDepts = ref<DeptRow[]>([])
const deptId = ref('')
const summary = ref<BoardSummary>({
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
  byHealth: {}
})
const projects = ref<ProjectMetric[]>([])
/** 是否连同下级部门一起统计（部门领导看整棵子树）。 */
const includeSub = ref(false)
/** 项目明细的快捷筛选与关键字（纯前端过滤，KPI 卡片可联动）。 */
const filterKey = ref('')
const keyword = ref('')
const FILTER_TABS = [
  { key: '', label: '全部' },
  { key: 'RUNNING', label: '进行中' },
  { key: 'DELAYED', label: '延期' },
  { key: 'RISK', label: '有风险' }
]
const filteredProjects = computed(() => {
  const kw = keyword.value.trim().toLowerCase()
  return projects.value.filter((row) => {
    if (filterKey.value === 'RUNNING' && row.status !== 'IN_PROGRESS') return false
    if (filterKey.value === 'DELAYED' && Number(row.delayDays || 0) <= 0) return false
    if (filterKey.value === 'RISK' && Number(row.riskOpen || 0) <= 0) return false
    if (!kw) return true
    return String(row.projectName || '').toLowerCase().includes(kw)
  })
})
const toggleFilter = (key?: string) => {
  if (!key) return
  filterKey.value = filterKey.value === key ? '' : key
}

/* ------------------------------ 趋势与成员负载 ------------------------------ */
const trendDays = ref(30)
const trend = ref<TrendPoint[]>([])
const memberLoad = ref<MemberLoad[]>([])
/**
 * 趋势图配置：平均进度折线（左轴 0~100）+ 健康度「风险」项目数柱（右轴）。
 * 配色统一到系统主色的深浅两档，柱状用极浅的蓝，避免抢折线的视觉。
 */
const trendOption = computed(() => {
  const items = trend.value
  const axisText = { fontSize: 10, color: '#8a93a6' }
  return {
    grid: { left: 4, right: 4, top: 28, bottom: 2, containLabel: true },
    tooltip: {
      trigger: 'axis',
      confine: true,
      axisPointer: { type: 'shadow', shadowStyle: { color: 'rgba(51,112,255,0.06)' } },
      formatter: (params: any) => {
        const list = Array.isArray(params) ? params : [params]
        const head = list[0]?.axisValueLabel || list[0]?.name || ''
        const rows = list.map((item: any) => {
          const isProgress = item.seriesName === '平均进度'
          const value = isProgress
            ? `${Number(item.value || 0).toFixed(1)}%`
            : `${Number(item.value || 0)} 个`
          return `${item.marker}${item.seriesName}　<b>${value}</b>`
        })
        return [head, ...rows].join('<br/>')
      }
    },
    legend: {
      top: 0,
      right: 0,
      itemWidth: 10,
      itemHeight: 10,
      itemGap: 14,
      textStyle: { fontSize: 11, color: '#5b6479' }
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
        // 轴名会与右上角图例重叠，单位已由 tooltip 与图例表达，这里不再重复
        type: 'value',
        max: 100,
        splitNumber: 2,
        axisLabel: { ...axisText, formatter: '{value}%' },
        splitLine: { lineStyle: { color: '#eef2f8' } }
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
        symbolSize: 4,
        showSymbol: false,
        data: items.map((point) => Number(point.avgProgress || 0)),
        lineStyle: { width: 2, color: '#3370ff' },
        itemStyle: { color: '#3370ff', borderColor: '#fff', borderWidth: 1.5 },
        areaStyle: {
          color: {
            type: 'linear',
            x: 0,
            y: 0,
            x2: 0,
            y2: 1,
            colorStops: [
              { offset: 0, color: 'rgba(51,112,255,0.16)' },
              { offset: 1, color: 'rgba(51,112,255,0)' }
            ]
          }
        }
      },
      {
        name: '风险项目',
        type: 'bar',
        yAxisIndex: 1,
        barWidth: '34%',
        data: items.map((point) => Number(point.redCount || 0)),
        itemStyle: { color: '#cfe0ff', borderRadius: [4, 4, 0, 0] },
        emphasis: { itemStyle: { color: '#b9d2ff' } }
      }
    ]
  }
})

const trendLatest = computed(() => trend.value[trend.value.length - 1] || null)
const trendRange = computed(() => {
  if (!trend.value.length) return ''
  const first = String(trend.value[0].date || '').slice(5)
  const last = String(trend.value[trend.value.length - 1].date || '').slice(5)
  return `${first} → ${last}`
})

const loadInsights = async () => {
  const ids = selectedDeptIds()
  if (!ids.length) return
  const [trendData, memberData] = await Promise.all([
    deptTrend(ids, includeSub.value, trendDays.value).catch(() => null),
    deptMembers(ids, includeSub.value, trendDays.value).catch(() => null)
  ])
  trend.value = ((trendData?.points as unknown as TrendPoint[]) || []).slice()
  memberLoad.value = ((memberData?.members as unknown as MemberLoad[]) || []).slice()
}

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
const statusLabel = (status: string) => STATUS_META[status]?.label ?? status ?? '-'
const statusTone = (status: string): TagType => STATUS_META[status]?.tone ?? 'info'

const HEALTH_META: Record<string, { label: string; tone: TagType; dot: string }> = {
  GREEN: { label: '健康', tone: 'success', dot: 'ok' },
  YELLOW: { label: '预警', tone: 'warning', dot: 'warn' },
  RED: { label: '风险', tone: 'danger', dot: 'danger' }
}
const healthMeta = (health: string) =>
  HEALTH_META[health] || { label: health || '-', tone: 'info' as TagType, dot: 'ok' }

const MILESTONE_META: Record<string, { label: string; tone: TagType }> = {
  PENDING: { label: '待达成', tone: 'info' },
  DELAYED: { label: '已延期', tone: 'warning' },
  REACHED: { label: '已达成', tone: 'success' },
  CANCELLED: { label: '已取消', tone: 'info' }
}
const milestoneMeta = (status: string) =>
  MILESTONE_META[status] || { label: status || '-', tone: 'info' as TagType }

const num = (value: unknown, digits = 0) => {
  const parsed = Number(value)
  if (!Number.isFinite(parsed)) return '0'
  return digits > 0 ? parsed.toFixed(digits) : String(Math.round(parsed))
}

const buildDeptTree = (list: DeptRow[]): DeptNode[] => {
  const nodes = new Map<string, DeptNode>()
  list.forEach((item) =>
    nodes.set(String(item.id), {
      value: String(item.id),
      label: item.deptName,
      children: []
    })
  )
  const roots: DeptNode[] = []
  list.forEach((item) => {
    const node = nodes.get(String(item.id))
    if (!node) return
    const parent = nodes.get(String(item.parentId))
    if (parent && parent !== node) parent.children?.push(node)
    else roots.push(node)
  })
  return roots
}

const deptOptions = computed<DeptNode[]>(() => {
  const roots = buildDeptTree(flatDepts.value)
  if (flatDepts.value.length > 1) {
    return [{ value: ALL_DEPT, label: '全部可见部门' }, ...roots]
  }
  return roots
})

const deptLabel = computed(() => {
  if (deptId.value === ALL_DEPT) return '全部可见部门'
  return flatDepts.value.find((item) => String(item.id) === deptId.value)?.deptName || '本部门'
})

const selectedDeptIds = () => {
  if (deptId.value === ALL_DEPT) return flatDepts.value.map((item) => String(item.id))
  return deptId.value ? [deptId.value] : []
}

const healthList = computed(() => {
  const total = Number(summary.value.projectCount || 0)
  return ['GREEN', 'YELLOW', 'RED'].map((key) => {
    const count = Number(summary.value.byHealth?.[key] || 0)
    return {
      key,
      ...HEALTH_META[key],
      count,
      percent: total > 0 ? Math.round((count / total) * 100) : 0
    }
  })
})

const plannedHours = computed(() => Number(summary.value.plannedHours || 0))
const actualHours = computed(() => Number(summary.value.actualHours || 0))
const execPercent = computed(() =>
  plannedHours.value > 0 ? Math.min((actualHours.value / plannedHours.value) * 100, 100) : 0
)

interface KpiItem {
  key: string
  label: string
  icon: Component
  tone?: string
  value: string
  /** 可点击的 KPI 会带上对应筛选键，点击联动下方项目明细。 */
  filter?: string
}

const kpis = computed<KpiItem[]>(() => [
  {
    key: 'projectCount',
    label: '项目总数',
    icon: FolderKanban,
    value: num(summary.value.projectCount)
  },
  {
    key: 'inProgressCount',
    label: '进行中',
    icon: CirclePlay,
    tone: 'primary',
    value: num(summary.value.inProgressCount),
    filter: 'RUNNING'
  },
  {
    key: 'delayedCount',
    label: '延期项目',
    icon: TriangleAlert,
    tone: 'warning',
    value: num(summary.value.delayedCount),
    filter: 'DELAYED'
  },
  {
    key: 'avgProgress',
    label: '平均进度',
    icon: Gauge,
    value: `${num(summary.value.avgProgress, 1)}%`
  },
  {
    key: 'avgSpi',
    label: '平均 SPI',
    icon: TrendingUp,
    value: num(summary.value.avgSpi, 2)
  },
  {
    key: 'avgCpi',
    label: '平均 CPI',
    icon: TrendingDown,
    value: num(summary.value.avgCpi, 2)
  },
  {
    key: 'riskOpen',
    label: '开放风险',
    icon: ShieldAlert,
    tone: 'danger',
    value: num(summary.value.riskOpen),
    filter: 'RISK'
  },
  {
    key: 'avgLogFillRate',
    label: '日志填写率',
    icon: NotebookPen,
    value: `${num(summary.value.avgLogFillRate, 1)}%`
  }
])

const loadDepts = async () => {
  try {
    flatDepts.value = (await reportDepts()) as unknown as DeptRow[]
  } catch {
    flatDepts.value = []
  }
  const own = String(store.profile?.deptId || '')
  if (flatDepts.value.some((item) => String(item.id) === own)) {
    deptId.value = own
  } else {
    const roots = buildDeptTree(flatDepts.value)
    deptId.value = roots[0]?.value || ALL_DEPT
  }
}

const loadBoard = async () => {
  if (!deptId.value) return
  loading.value = true
  try {
    const data = await deptBoard(selectedDeptIds(), includeSub.value)
    summary.value = (data.summary as unknown as BoardSummary) || summary.value
    const rows = ((data.projects as unknown as ProjectMetric[]) || []).slice()
    const healthOrder: Record<string, number> = { RED: 0, YELLOW: 1, GREEN: 2 }
    rows.sort(
      (a, b) =>
        (healthOrder[a.health] ?? 3) - (healthOrder[b.health] ?? 3) ||
        Number(b.delayDays || 0) - Number(a.delayDays || 0)
    )
    projects.value = rows
    await loadInsights()
  } catch {
    projects.value = []
  } finally {
    loading.value = false
  }
}

/* ------------------------------ 项目下钻 ------------------------------ */
const projectVisible = ref(false)
const projectLoading = ref(false)
const projectData = ref<ProjectBoardData | null>(null)
const projectMetric = computed(() => projectData.value?.metric || null)

const openProject = async (row: any) => {
  projectVisible.value = true
  projectLoading.value = true
  projectData.value = null
  try {
    projectData.value = (await projectBoard(row.projectId)) as unknown as ProjectBoardData
  } catch {
    projectVisible.value = false
  } finally {
    projectLoading.value = false
  }
}

const indexTone = (value: number) => {
  const parsed = Number(value)
  if (parsed >= 1) return 'index-ok'
  return parsed >= 0.9 ? 'index-warn' : 'index-bad'
}

const formatDate = (value: string) => (value ? String(value).slice(0, 10) : '—')

onMounted(async () => {
  await loadDepts()
  await loadBoard()
})
</script>

<template>
  <div class="pms-page">
    <div class="pms-card board-head">
      <div class="head-copy">
        <h2>
          <Building2 :size="18" :stroke-width="1.9" />
          部门看板
        </h2>
        <p>按部门查看项目健康度、进度、成本与日志填写情况，点击项目可下钻阶段与里程碑。</p>
      </div>
      <div class="head-ops">
        <div class="ops-main">
          <el-tree-select
            v-model="deptId"
            class="dept-select"
            :data="deptOptions"
            default-expand-all
            filterable
            placeholder="选择部门"
            @change="loadBoard"
          />
        </div>
        <div class="ops-actions">
          <el-checkbox v-model="includeSub" size="small" @change="loadBoard">含下级部门</el-checkbox>
          <el-button :loading="loading" @click="loadBoard">刷新</el-button>
        </div>
      </div>
    </div>

    <section class="kpi-board" v-loading="loading">
      <article
        v-for="item in kpis"
        :key="item.key"
        class="kpi"
        :class="[
          `tone-${item.tone || 'default'}`,
          { 'is-clickable': Boolean(item.filter), 'is-active': item.filter && filterKey === item.filter }
        ]"
        @click="toggleFilter(item.filter)"
      >
        <span class="kpi-icon">
          <component :is="item.icon" :size="16" :stroke-width="1.75" />
        </span>
        <span class="kpi-value">{{ item.value }}</span>
        <span class="kpi-label">{{ item.label }}</span>
      </article>
    </section>

    <div class="insight-grid">
      <div class="pms-card">
        <h3>
          健康度分布
          <span class="card-note">{{ deptLabel }} · {{ summary.projectCount ?? 0 }} 个项目</span>
        </h3>
        <div class="health-bar">
          <span
            v-for="item in healthList"
            :key="item.key"
            :class="`bg-${item.dot}`"
            :style="{ width: `${item.percent}%` }"
          ></span>
        </div>
        <div class="health-list">
          <div v-for="item in healthList" :key="item.key" class="health-item">
            <span class="health-dot" :class="`dot-${item.dot}`"></span>
            <span class="health-label">{{ item.label }}</span>
            <span class="health-value">{{ item.count }}</span>
            <span class="health-pct">{{ item.percent }}%</span>
          </div>
        </div>
      </div>

      <div class="pms-card">
        <h3>
          工时与执行
          <span class="card-note">计划 / 实际</span>
        </h3>
        <div class="hours-summary">
          <span>计划工时 <b>{{ num(plannedHours, 1) }}h</b></span>
          <span>实际工时 <b>{{ num(actualHours, 1) }}h</b></span>
          <span class="hours-ratio">{{ num(execPercent, 0) }}%</span>
        </div>
        <div class="hours-track">
          <span class="hours-fill" :style="{ width: `${execPercent}%` }"></span>
        </div>
        <div class="mini-stats">
          <div class="mini-stat">
            <span>日志填写率</span>
            <b>{{ num(summary.avgLogFillRate, 1) }}%</b>
          </div>
          <div class="mini-stat">
            <span>变更数量</span>
            <b>{{ num(summary.changeCount) }}</b>
          </div>
          <div class="mini-stat">
            <span>未关闭问题</span>
            <b>{{ num(summary.issueOpen) }}</b>
          </div>
          <div class="mini-stat">
            <span>风险项</span>
            <b class="danger-text">{{ num(summary.riskOpen) }}</b>
          </div>
        </div>
      </div>
    </div>

    <div class="insight-grid">
    <div class="pms-card">
      <div class="card-head">
        <h3>
          近 {{ trendDays }} 天趋势
          <span class="card-note">折线＝平均进度，柱＝当天健康度为「风险」的项目数</span>
        </h3>
        <el-select v-model="trendDays" size="small" class="days-select" @change="loadInsights">
          <el-option :value="7" label="近 7 天" />
          <el-option :value="30" label="近 30 天" />
          <el-option :value="90" label="近 90 天" />
        </el-select>
      </div>
      <template v-if="trend.length >= 2">
        <ChartBox :option="trendOption" height="176px" />
        <div class="trend-meta">
          <span class="card-note">{{ trendRange }}</span>
          <span v-if="trendLatest">
            最新：平均进度 <b>{{ num(trendLatest.avgProgress, 1) }}%</b>
            · 风险项目 <b>{{ trendLatest.redCount }}</b>
            · 预警项目 <b>{{ trendLatest.yellowCount }}</b>
            · 实际工时 <b>{{ num(trendLatest.actualHours, 1) }}h</b>
          </span>
        </div>
      </template>
      <el-empty
        v-else
        description="暂无日聚合快照：执行一次「日预聚合」后即可看到趋势"
        :image-size="60"
      />
    </div>

    <div class="pms-card">
      <h3>
        成员负载
        <span class="card-note">近 {{ trendDays }} 天 · {{ memberLoad.length }} 人</span>
      </h3>
      <el-table :data="memberLoad" size="small" max-height="264">
        <template #empty>
          <el-empty description="该范围内暂无在职成员，或还没有已确认的工时" :image-size="60" />
        </template>
        <el-table-column label="成员" min-width="120">
          <template #default="{ row }">{{ row.realName || row.userId }}</template>
        </el-table-column>
        <el-table-column label="工时" width="88" align="right">
          <template #default="{ row }">
            <b class="num-cell">{{ num(row.hours, 1) }}h</b>
          </template>
        </el-table-column>
        <el-table-column label="项目" width="80" align="right">
          <template #default="{ row }">{{ row.projects }}</template>
        </el-table-column>
        <el-table-column label="日志" width="80" align="right" class-name="pms-mobile-hide">
          <template #default="{ row }">{{ row.logDays }}</template>
        </el-table-column>
        <el-table-column label="填写率" min-width="140">
          <template #default="{ row }">
            <div class="progress-cell">
              <el-progress
                :percentage="Math.min(Math.max(Number(row.fillRate) || 0, 0), 100)"
                :stroke-width="6"
                :show-text="false"
              />
              <span class="progress-text" :class="{ 'danger-text': Number(row.fillRate) < 60 }">
                {{ num(row.fillRate, 0) }}%
              </span>
            </div>
          </template>
        </el-table-column>
      </el-table>
    </div>
    </div>

    <div class="pms-card">
      <h3>
        项目明细
        <span class="card-note">风险优先排序，点击查看项目看板</span>
      </h3>
      <div class="table-toolbar">
        <div class="filter-tabs">
          <button
            v-for="item in FILTER_TABS"
            :key="item.key"
            type="button"
            :class="{ 'is-active': filterKey === item.key }"
            @click="filterKey = item.key"
          >
            {{ item.label }}
          </button>
        </div>
        <span class="card-note">{{ filteredProjects.length }} / {{ projects.length }} 个项目</span>
        <el-input
          v-model="keyword"
          class="table-search"
          size="small"
          placeholder="搜索项目名称"
          clearable
        />
      </div>
      <el-table :data="filteredProjects" size="small">
        <template #empty>
          <el-empty
            :description="filterKey || keyword ? '没有匹配的项目' : '当前部门暂无可查看项目'"
            :image-size="64"
          />
        </template>
        <el-table-column prop="projectName" label="项目" min-width="170" show-overflow-tooltip />
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="statusTone(row.status)" size="small" effect="plain">
              {{ statusLabel(row.status) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="健康度" width="84">
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
                :percentage="Math.min(Math.max(Number(row.progress) || 0, 0), 100)"
                :stroke-width="6"
                :show-text="false"
              />
              <span class="progress-text">{{ num(row.progress, 1) }}%</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="SPI" width="76">
          <template #default="{ row }">
            <span :class="indexTone(row.spi)">{{ num(row.spi, 2) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="CPI" width="76">
          <template #default="{ row }">
            <span :class="indexTone(row.cpi)">{{ num(row.cpi, 2) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="延期(天)" width="90">
          <template #default="{ row }">
            <span :class="{ 'delay-bad': Number(row.delayDays) > 0 }">{{ row.delayDays }}</span>
          </template>
        </el-table-column>
        <el-table-column label="风险" width="72">
          <template #default="{ row }">
            <span :class="{ 'danger-text': Number(row.riskOpen) > 0 }">{{ row.riskOpen }}</span>
          </template>
        </el-table-column>
        <el-table-column label="日志填写率" width="110" class-name="pms-mobile-hide">
          <template #default="{ row }">
            <span :class="{ 'danger-text': Number(row.logFillRate) < 60 }">
              {{ num(row.logFillRate, 0) }}%
            </span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="72">
          <template #default="{ row }">
            <el-button link type="primary" @click="openProject(row)">查看</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <el-drawer v-model="projectVisible" title="项目看板" size="min(720px, 94vw)">
      <div v-loading="projectLoading" class="project-detail">
        <template v-if="projectMetric && projectData">
          <div class="pd-head">
            <div>
              <h3>{{ projectMetric.projectName }}</h3>
              <p class="pd-meta">项目指标来自最新进度、工时与风险数据</p>
            </div>
            <div class="pd-tags">
              <el-tag :type="statusTone(projectMetric.status)" size="small" effect="plain">
                {{ statusLabel(projectMetric.status) }}
              </el-tag>
              <el-tag :type="healthMeta(projectMetric.health).tone" size="small">
                {{ healthMeta(projectMetric.health).label }}
              </el-tag>
            </div>
          </div>

          <div class="pd-metrics">
            <div class="pd-metric">
              <span>进度</span>
              <b>{{ num(projectMetric.progress, 1) }}%</b>
            </div>
            <div class="pd-metric">
              <span>SPI</span>
              <b :class="indexTone(projectMetric.spi)">{{ num(projectMetric.spi, 2) }}</b>
            </div>
            <div class="pd-metric">
              <span>CPI</span>
              <b :class="indexTone(projectMetric.cpi)">{{ num(projectMetric.cpi, 2) }}</b>
            </div>
            <div class="pd-metric">
              <span>延期</span>
              <b :class="{ 'delay-bad': Number(projectMetric.delayDays) > 0 }">
                {{ projectMetric.delayDays }} 天
              </b>
            </div>
            <div class="pd-metric">
              <span>计划工时</span>
              <b>{{ num(projectMetric.plannedHours, 1) }}h</b>
            </div>
            <div class="pd-metric">
              <span>实际工时</span>
              <b>{{ num(projectMetric.actualHours, 1) }}h</b>
            </div>
            <div class="pd-metric">
              <span>开放风险</span>
              <b :class="{ 'danger-text': Number(projectMetric.riskOpen) > 0 }">
                {{ projectMetric.riskOpen }}
              </b>
            </div>
            <div class="pd-metric">
              <span>日志填写率</span>
              <b>{{ num(projectMetric.logFillRate, 1) }}%</b>
            </div>
          </div>

          <section class="pd-section">
            <h4>阶段进度</h4>
            <div v-if="projectData.stages.length" class="stage-list">
              <div v-for="item in projectData.stages" :key="String(item.id)" class="stage-item">
                <div class="stage-top">
                  <b>{{ item.stageName }}</b>
                  <span>{{ num(item.progress, 1) }}%</span>
                </div>
                <el-progress
                  :percentage="Math.min(Math.max(Number(item.progress) || 0, 0), 100)"
                  :stroke-width="6"
                  :show-text="false"
                  class="stage-progress"
                />
                <p class="stage-date">{{ formatDate(item.planStart) }} ~ {{ formatDate(item.planEnd) }}</p>
              </div>
            </div>
            <el-empty v-else description="暂无阶段" :image-size="60" />
          </section>

          <section class="pd-section">
            <h4>里程碑</h4>
            <el-table v-if="projectData.milestones.length" :data="projectData.milestones" size="small">
              <el-table-column prop="name" label="里程碑" min-width="160" />
              <el-table-column label="计划日期" width="110">
                <template #default="{ row }">{{ formatDate(row.planDate) }}</template>
              </el-table-column>
              <el-table-column label="实际日期" width="110">
                <template #default="{ row }">{{ formatDate(row.actualDate) }}</template>
              </el-table-column>
              <el-table-column label="状态" width="100">
                <template #default="{ row }">
                  <el-tag :type="milestoneMeta(row.status).tone" size="small" effect="plain">
                    {{ milestoneMeta(row.status).label }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column label="延期(天)" width="90">
                <template #default="{ row }">
                  <span :class="{ 'delay-bad': Number(row.delayDays) > 0 }">{{ row.delayDays }}</span>
                </template>
              </el-table-column>
            </el-table>
            <el-empty v-else description="暂无里程碑" :image-size="60" />
          </section>
        </template>
      </div>
      <template #footer>
        <el-button @click="projectVisible = false">关闭</el-button>
      </template>
    </el-drawer>
  </div>
</template>

<style scoped>
.board-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 12px 16px;
}

.head-copy {
  flex: 1 1 360px;
  min-width: 0;
}

.head-copy h2 {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 0;
  font-size: 18px;
  font-weight: 600;
  color: var(--pms-text);
}

.head-copy p {
  margin: 6px 0 0;
  font-size: 12.5px;
  line-height: 1.7;
  color: var(--pms-text-3);
}

/* 操作区：主控（部门选择）靠左、动作（含下级/刷新）靠右，窄屏铺满整行 */
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

.dept-select {
  width: 230px;
}

/* ---------------- KPI ---------------- */
.kpi-board {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 1px;
  margin-bottom: 14px;
  background: var(--pms-line);
  border: 1px solid var(--pms-line);
  border-radius: var(--pms-radius);
  overflow: hidden;
}

.kpi {
  display: flex;
  flex-direction: column;
  gap: 5px;
  padding: 16px 18px 17px;
  background: var(--pms-surface);
  transition: background-color 0.18s ease;
}

.kpi:hover {
  background: #fbfcff;
}

/* 可点击的 KPI（进行中 / 延期 / 开放风险）→ 联动下方项目明细 */
.kpi.is-clickable {
  cursor: pointer;
}

.kpi.is-active {
  background: #f2f7ff;
  box-shadow: inset 0 0 0 1.5px var(--pms-primary);
}

/* ---------------- 项目明细工具栏 ---------------- */
.table-toolbar {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
  margin-bottom: 10px;
}

.filter-tabs {
  display: inline-flex;
  flex-wrap: wrap;
  gap: 2px;
  padding: 3px;
  border: 1px solid #e3e9f4;
  border-radius: 9px;
  background: #eef2f8;
}

.filter-tabs button {
  height: 26px;
  padding: 0 12px;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: var(--pms-text-2);
  font-size: 12.5px;
  cursor: pointer;
  transition:
    background-color 0.16s ease,
    color 0.16s ease;
}

.filter-tabs button:hover {
  color: var(--pms-text);
}

.filter-tabs button.is-active {
  background: var(--pms-surface);
  color: var(--pms-primary-deep);
  box-shadow: 0 1px 2px rgba(16, 35, 70, 0.08);
}

.table-search {
  width: 200px;
  margin-left: auto;
}

.kpi-icon {
  width: 28px;
  height: 28px;
  margin-bottom: 3px;
  display: grid;
  place-items: center;
  border-radius: 8px;
  background: #f2f5fb;
  color: var(--pms-text-2);
}

.kpi-value {
  font-size: 23px;
  font-weight: 600;
  line-height: 1.25;
  letter-spacing: -0.01em;
  color: var(--pms-text);
  font-variant-numeric: tabular-nums;
}

.kpi-label {
  font-size: 12.5px;
  color: var(--pms-text-3);
}

.tone-primary .kpi-icon {
  background: var(--pms-primary-weak);
  color: var(--pms-primary);
}

.tone-warning .kpi-icon {
  background: #fff5e6;
  color: #b8770f;
}

.tone-danger .kpi-icon {
  background: #fdeeee;
  color: #bf3b32;
}

/* ---------------- 概览卡 ---------------- */
.insight-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
  margin-bottom: 14px;
}

.insight-grid .pms-card {
  margin-bottom: 0;
}

.insight-grid h3 {
  margin-bottom: 14px;
}

.card-note {
  margin-left: auto;
  font-size: 12px;
  font-weight: 400;
  color: var(--pms-text-3);
}

/* ---------------- 趋势卡片 ---------------- */
.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 10px;
  margin-bottom: 14px;
}

/* 卡片头里的 h3 不是 .pms-card 的直接子元素，需补回与其它卡片一致的标题字号 */
.card-head h3 {
  display: flex;
  flex: 1 1 auto;
  align-items: center;
  gap: 8px;
  min-width: 0;
  margin: 0;
  font-size: 14.5px;
  font-weight: 600;
  line-height: 1.4;
  color: var(--pms-text);
}

.days-select {
  width: 112px;
}

.trend-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 8px;
  font-size: 12.5px;
  color: var(--pms-text-2);
}

.num-cell {
  font-variant-numeric: tabular-nums;
}

.health-bar {
  display: flex;
  height: 10px;
  margin-bottom: 14px;
  overflow: hidden;
  border-radius: 6px;
  background: #eef2f8;
}

.health-bar span {
  height: 100%;
  transition: width 0.2s ease;
}

.bg-ok {
  background: #2f9e5f;
}

.bg-warn {
  background: #d68a12;
}

.bg-danger {
  background: #cf3f3f;
}

.health-list {
  display: grid;
  gap: 8px;
}

.health-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 9px 12px;
  border: 1px solid var(--pms-line);
  border-radius: 8px;
  background: #fbfcff;
}

.health-dot {
  flex: none;
  width: 8px;
  height: 8px;
  border-radius: 50%;
}

.dot-ok {
  background: #2f9e5f;
}

.dot-warn {
  background: #d68a12;
}

.dot-danger {
  background: #cf3f3f;
}

.health-label {
  font-size: 13px;
  color: var(--pms-text-2);
}

.health-value {
  margin-left: auto;
  font-size: 15px;
  font-weight: 600;
  color: var(--pms-text);
  font-variant-numeric: tabular-nums;
}

.health-pct {
  width: 40px;
  font-size: 11.5px;
  color: var(--pms-text-3);
  text-align: right;
}

.hours-summary {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-bottom: 8px;
  font-size: 12.5px;
  color: var(--pms-text-3);
}

.hours-summary b {
  color: var(--pms-text);
  font-variant-numeric: tabular-nums;
}

.hours-ratio {
  margin-left: auto;
  font-size: 15px;
  font-weight: 600;
  color: var(--pms-primary-deep);
}

.hours-track {
  height: 10px;
  margin-bottom: 14px;
  overflow: hidden;
  border-radius: 6px;
  background: #eef2f8;
}

.hours-fill {
  display: block;
  height: 100%;
  border-radius: 6px;
  background: linear-gradient(90deg, #7aa2ff, #3370ff);
}

.mini-stats {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}

.mini-stat {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 8px 10px;
  border: 1px solid var(--pms-line);
  border-radius: 8px;
  background: #fafbfe;
}

.mini-stat span {
  font-size: 11.5px;
  color: var(--pms-text-3);
}

.mini-stat b {
  font-size: 16px;
  font-weight: 600;
  color: var(--pms-text);
  font-variant-numeric: tabular-nums;
}

/* ---------------- 项目表 ---------------- */
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
  width: 42px;
  font-size: 12px;
  color: var(--pms-text-2);
  text-align: right;
  font-variant-numeric: tabular-nums;
}

.index-ok {
  color: #2f9e5f;
  font-variant-numeric: tabular-nums;
}

.index-warn {
  color: #b8770f;
  font-variant-numeric: tabular-nums;
}

.index-bad {
  color: #cf3f3f;
  font-variant-numeric: tabular-nums;
}

.delay-bad,
.danger-text {
  color: #cf3f3f;
  font-weight: 500;
}

/* ---------------- 项目抽屉 ---------------- */
.project-detail {
  padding: 4px 20px 24px;
}

.pd-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.pd-head h3 {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
}

.pd-meta {
  margin: 5px 0 0;
  font-size: 12px;
  color: var(--pms-text-3);
}

.pd-tags {
  display: flex;
  align-items: center;
  gap: 6px;
  flex: none;
}

.pd-metrics {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
  margin: 16px 0;
}

.pd-metric {
  display: flex;
  flex-direction: column;
  gap: 3px;
  padding: 10px;
  border: 1px solid var(--pms-line);
  border-radius: 8px;
  background: #fafbfe;
}

.pd-metric span {
  font-size: 11.5px;
  color: var(--pms-text-3);
}

.pd-metric b {
  font-size: 15px;
  font-weight: 600;
  color: var(--pms-text);
  font-variant-numeric: tabular-nums;
}

.pd-section {
  margin-top: 18px;
}

.pd-section h4 {
  margin: 0 0 10px;
  font-size: 13px;
  font-weight: 600;
}

.stage-list {
  display: grid;
  gap: 10px;
}

.stage-item {
  padding: 10px 12px 8px;
  border: 1px solid var(--pms-line);
  border-radius: 8px;
  background: #fafbfe;
}

.stage-top {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
  font-size: 13px;
  color: var(--pms-text);
}

.stage-top span {
  font-size: 12px;
  color: var(--pms-text-2);
  font-variant-numeric: tabular-nums;
}

.stage-progress {
  margin-top: 6px;
}

.stage-date {
  margin: 6px 0 0;
  font-size: 11.5px;
  color: var(--pms-text-3);
}

@media (max-width: 1024px) {
  .kpi-board {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 900px) {
  .insight-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 768px) {
  .head-ops {
    width: 100%;
    margin-left: 0;
  }

  .ops-main {
    flex: 1 1 auto;
  }

  .dept-select {
    flex: 1;
    width: auto;
  }

  .kpi {
    padding: 13px 14px;
  }

  .kpi-value {
    font-size: 20px;
  }

  .card-note {
    display: none;
  }

  .project-detail {
    padding: 4px 14px 20px;
  }

  .pd-metrics {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .table-search {
    width: 100%;
    margin-left: 0;
  }

  .days-select {
    width: 100%;
  }

  .card-head {
    align-items: flex-start;
  }

  .card-head h3 {
    font-size: 14px;
  }
}
</style>
