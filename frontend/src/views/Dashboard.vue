<script setup lang="ts">
import { computed, onMounted, ref, type Component } from 'vue'
import {
  CirclePlay,
  FolderKanban,
  Gauge,
  RefreshCw,
  ShieldAlert,
  TrendingDown,
  TrendingUp,
  TriangleAlert,
  Activity
} from 'lucide-vue-next'
import { companyBoard } from '@/api'

const board = ref<Record<string, unknown>>({})
const summary = ref<Record<string, unknown>>({})
const topDelayed = ref<Record<string, unknown>[]>([])
const loading = ref(false)

const load = async () => {
  loading.value = true
  try {
    board.value = await companyBoard()
    summary.value = (board.value.summary as Record<string, unknown>) || {}
    topDelayed.value = (board.value.topDelayed as Record<string, unknown>[]) || []
  } finally {
    loading.value = false
  }
}

onMounted(load)

const format = (value: unknown, digits?: number, suffix = '') => {
  if (value === null || value === undefined || value === '') return '-'
  const num = Number(value)
  if (Number.isNaN(num)) return `${value}${suffix}`
  return `${digits === undefined ? num : num.toFixed(digits)}${suffix}`
}

/* 项目状态字典（与后端 dict_project_status 一致） */
type TagType = 'primary' | 'success' | 'info' | 'warning' | 'danger'

const statusMeta: Record<string, { label: string; tone: TagType }> = {
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

const statusLabel = (status: unknown) => statusMeta[String(status)]?.label ?? String(status ?? '-')
const statusTone = (status: unknown): TagType => statusMeta[String(status)]?.tone ?? 'info'

interface KpiItem {
  key: string
  label: string
  icon: Component
  tone?: string
  digits?: number
  suffix?: string
  value: string
}

const kpiDefs: Omit<KpiItem, 'value'>[] = [
  { key: 'projectCount', label: '项目总数', icon: FolderKanban, digits: 0 },
  { key: 'inProgressCount', label: '进行中', icon: CirclePlay, tone: 'primary', digits: 0 },
  { key: 'delayedCount', label: '延期项目', icon: TriangleAlert, tone: 'warning', digits: 0 },
  { key: 'avgProgress', label: '平均进度', icon: Gauge, digits: 1, suffix: '%' },
  { key: 'avgSpi', label: '平均 SPI', icon: TrendingUp, digits: 2 },
  { key: 'avgCpi', label: '平均 CPI', icon: TrendingDown, digits: 2 },
  { key: 'riskOpen', label: '开放风险', icon: ShieldAlert, tone: 'danger', digits: 0 },
  { key: 'changeCount', label: '变更数量', icon: RefreshCw, digits: 0 }
]

const kpis = computed<KpiItem[]>(() =>
  kpiDefs.map((item) => ({
    ...item,
    value: format(summary.value[item.key], item.digits, item.suffix ?? '')
  }))
)

const healthMeta: Record<string, { label: string; tone: string }> = {
  GREEN: { label: '健康', tone: 'ok' },
  YELLOW: { label: '预警', tone: 'warn' },
  RED: { label: '风险', tone: 'danger' }
}

const healthList = computed(() => {
  const byHealth = (summary.value.byHealth as Record<string, number>) || {}
  return ['GREEN', 'YELLOW', 'RED']
    .filter((key) => byHealth[key] !== undefined)
    .map((key) => ({
      key,
      label: healthMeta[key]?.label ?? key,
      tone: healthMeta[key]?.tone ?? 'ok',
      count: byHealth[key]
    }))
})
</script>

<template>
  <div v-loading="loading" class="pms-page">
    <section class="kpi-board">
      <article v-for="item in kpis" :key="item.key" class="kpi" :class="`tone-${item.tone || 'default'}`">
        <span class="kpi-icon">
          <component :is="item.icon" :size="16" :stroke-width="1.75" />
        </span>
        <span class="kpi-value">{{ item.value }}</span>
        <span class="kpi-label">{{ item.label }}</span>
      </article>
    </section>

    <section class="pms-card">
      <h3>
        <Activity :size="15" :stroke-width="1.9" />
        健康度分布
        <span class="card-note">全部在建项目</span>
      </h3>
      <div v-if="healthList.length" class="health">
        <div v-for="item in healthList" :key="item.key" class="health-item">
          <span class="health-dot" :class="`dot-${item.tone}`"></span>
          <span class="health-label">{{ item.label }}</span>
          <span class="health-value">{{ item.count }}</span>
        </div>
      </div>
      <p v-else class="empty">暂无健康度数据</p>
    </section>

    <section class="pms-card">
      <h3>
        <TriangleAlert :size="15" :stroke-width="1.9" />
        延期项目
        <span class="card-note">按延期天数排序，取前 10</span>
      </h3>
      <el-table :data="topDelayed" size="default" empty-text="暂无延期项目">
        <el-table-column prop="projectName" label="项目" min-width="180" />
        <el-table-column label="状态" width="120">
          <template #default="{ row }">
            <el-tag :type="statusTone(row.status)" size="small" effect="plain">
              {{ statusLabel(row.status) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="progress" label="进度%" width="90" />
        <el-table-column prop="spi" label="SPI" width="90" class-name="pms-mobile-hide" />
        <el-table-column prop="cpi" label="CPI" width="90" class-name="pms-mobile-hide" />
        <el-table-column prop="delayDays" label="延期(天)" width="100" />
        <el-table-column prop="logFillRate" label="日志填写率%" width="120" class-name="pms-mobile-hide" />
      </el-table>
    </section>
  </div>
</template>

<style scoped>
/* KPI：单卡网格 + 发丝分隔，避免卡片堆叠 */
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

/* 健康度 */
.health {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

.health-item {
  flex: 1 1 150px;
  max-width: 320px;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 14px;
  border: 1px solid var(--pms-line);
  border-radius: 10px;
  background: #fbfcff;
}

.health-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex: none;
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
  font-size: 16px;
  font-weight: 600;
  color: var(--pms-text);
  font-variant-numeric: tabular-nums;
}

.empty {
  margin: 0;
  padding: 18px 0;
  text-align: center;
  font-size: 13px;
  color: var(--pms-text-3);
}

.card-note {
  margin-left: auto;
  font-size: 12px;
  font-weight: 400;
  color: var(--pms-text-3);
}

@media (max-width: 1024px) {
  .kpi-board {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 768px) {
  .kpi {
    padding: 13px 14px;
  }

  .kpi-value {
    font-size: 20px;
  }

  .card-note {
    display: none;
  }
}
</style>
