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
import { deptBoard, projectBoard, reportDepts } from '@/api'
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
    value: num(summary.value.inProgressCount)
  },
  {
    key: 'delayedCount',
    label: '延期项目',
    icon: TriangleAlert,
    tone: 'warning',
    value: num(summary.value.delayedCount)
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
    value: num(summary.value.riskOpen)
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
    const data = await deptBoard(selectedDeptIds())
    summary.value = (data.summary as unknown as BoardSummary) || summary.value
    const rows = ((data.projects as unknown as ProjectMetric[]) || []).slice()
    const healthOrder: Record<string, number> = { RED: 0, YELLOW: 1, GREEN: 2 }
    rows.sort(
      (a, b) =>
        (healthOrder[a.health] ?? 3) - (healthOrder[b.health] ?? 3) ||
        Number(b.delayDays || 0) - Number(a.delayDays || 0)
    )
    projects.value = rows
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
        <el-tree-select
          v-model="deptId"
          class="dept-select"
          :data="deptOptions"
          default-expand-all
          filterable
          placeholder="选择部门"
          @change="loadBoard"
        />
        <el-button :loading="loading" @click="loadBoard">刷新</el-button>
      </div>
    </div>

    <section class="kpi-board" v-loading="loading">
      <article
        v-for="item in kpis"
        :key="item.key"
        class="kpi"
        :class="`tone-${item.tone || 'default'}`"
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

    <div class="pms-card">
      <h3>
        项目明细
        <span class="card-note">风险优先排序，点击查看项目看板</span>
      </h3>
      <el-table :data="projects" size="small" empty-text="当前部门暂无可查看项目">
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
  align-items: flex-start;
  flex-wrap: wrap;
  gap: 12px;
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

.head-ops {
  flex: none;
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
}
</style>
