<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  deleteWorklog,
  listTasks,
  listWorklogs,
  saveWorklog,
  worklogAction,
  worklogDaySummary,
  worklogDetail,
  worklogOptions,
  worklogStats
} from '@/api'
import { useUserStore } from '@/stores/user'

const store = useUserStore()
const loading = ref(false)

/** 本地日期（避免 toISOString 在 UTC+8 凌晨回退到前一天）。 */
const localToday = () => {
  const now = new Date()
  const month = String(now.getMonth() + 1).padStart(2, '0')
  const day = String(now.getDate()).padStart(2, '0')
  return `${now.getFullYear()}-${month}-${day}`
}

/** 填报选项（补填窗口、工时阈值、我参与的项目）。 */
const options = ref<any>({ backfillMaxDays: 5, warnHours: 8, maxHours: 24, step: 0.5, projects: [] })
const projects = computed<any[]>(() => options.value.projects || [])
const tasks = ref<any[]>([])

const emptyForm = () => ({
  id: 0,
  logDate: localToday(),
  projectId: 0,
  taskId: 0,
  totalHours: 8,
  content: '',
  problem: '',
  plan: '',
  riskFlag: false,
  progressAfter: 0
})

const form = ref<any>(emptyForm())
const dayRows = ref<any[]>([])
const daySummary = ref<any>({ totalHours: 0, warnHours: 8, logCount: 0, overWarn: false })

const rows = ref<any[]>([])
const total = ref(0)
const page = ref({ pageNum: 1, pageSize: 10 })
const stats = ref<any>({})

const canConfirm = computed(() => store.has('worklog:confirm'))
const isEditing = computed(() => Number(form.value.id) > 0)

const disabledDate = (time: Date) => {
  const maxDays = Number(options.value.backfillMaxDays ?? 5)
  const start = new Date()
  start.setHours(0, 0, 0, 0)
  start.setDate(start.getDate() - maxDays)
  return time.getTime() > Date.now() || time.getTime() < start.getTime()
}

const loadOptions = async () => {
  options.value = await worklogOptions()
}

const loadTasks = async (projectId: string | number) => {
  tasks.value = []
  if (!projectId) return
  try {
    tasks.value = (await listTasks(String(projectId))) as any[]
  } catch {
    tasks.value = []
  }
}

const onProjectChange = async () => {
  form.value.taskId = 0
  await loadTasks(form.value.projectId)
}

const onDateChange = async () => {
  cancelEdit()
  await loadDay()
}

const loadDay = async () => {
  const [logs, summary] = await Promise.all([
    listWorklogs({
      pageNum: 1,
      pageSize: 100,
      userId: store.profile?.id,
      dateFrom: form.value.logDate,
      dateTo: form.value.logDate
    }),
    worklogDaySummary(form.value.logDate)
  ])
  dayRows.value = logs.list || []
  daySummary.value = summary || {}
  if (form.value.logDate === localToday()) {
    todayFilled.value = Number((summary || {}).logCount || 0) > 0
  }
}

const load = async () => {
  loading.value = true
  try {
    const data = await listWorklogs({ pageNum: page.value.pageNum, pageSize: page.value.pageSize })
    rows.value = data.list || []
    total.value = data.total || 0
  } finally {
    loading.value = false
  }
}

const loadStats = async () => {
  const end = new Date()
  const start = new Date(end.getTime() - 30 * 86400000)
  const from = `${start.getFullYear()}-${String(start.getMonth() + 1).padStart(2, '0')}-${String(start.getDate()).padStart(2, '0')}`
  stats.value = await worklogStats({ dateFrom: from, dateTo: localToday(), userId: store.profile?.id })
}

const cancelEdit = () => {
  form.value = emptyForm()
  tasks.value = []
}

const validate = () => {
  if (!form.value.projectId) {
    ElMessage.warning('请先选择项目')
    return false
  }
  if (!form.value.totalHours || Number(form.value.totalHours) <= 0) {
    ElMessage.warning('请填写大于 0 的工时')
    return false
  }
  return true
}

const doSave = async () => {
  if (!validate()) return
  const result: any = await saveWorklog({ ...form.value })
  form.value.id = result.id
  if (result.warning) {
    ElMessage.warning(result.warning)
  } else {
    ElMessage.success('已保存草稿')
  }
  await loadDay()
}

const doSubmit = async () => {
  if (!validate()) return
  const saved: any = await saveWorklog({ ...form.value })
  const result: any = await worklogAction(saved.id, 'submit')
  if (result.warning) {
    ElMessage.warning(result.warning)
  }
  const extra = result.status === 'PENDING_APPROVE' ? '（需补填审批）' : ''
  ElMessage.success(`已提交，状态 ${result.status}${extra}`)
  cancelEdit()
  await loadDay()
  await load()
}

const doEdit = async (row: any) => {
  const data: any = await worklogDetail(row.id)
  const worklog = data.worklog || {}
  form.value = {
    id: worklog.id,
    logDate: worklog.logDate,
    projectId: Number(worklog.projectId || 0),
    taskId: Number(worklog.taskId || 0),
    totalHours: Number(worklog.totalHours || 0),
    content: worklog.content || '',
    problem: worklog.problem || '',
    plan: worklog.plan || '',
    riskFlag: !!worklog.riskFlag,
    progressAfter: 0
  }
  await loadTasks(form.value.projectId)
  window.scrollTo({ top: 0, behavior: 'smooth' })
}

const doDelete = async (row: any) => {
  await ElMessageBox.confirm('确认删除该条日志？', '提示', { type: 'warning' })
  await deleteWorklog(row.id)
  ElMessage.success('已删除')
  if (Number(form.value.id) === Number(row.id)) cancelEdit()
  await loadDay()
  await load()
}

const act = async (row: any, action: string) => {
  await worklogAction(row.id, action)
  ElMessage.success(`已${action}`)
  await loadDay()
  await load()
}

const editable = (row: any) =>
  Number(row.userId) === Number(store.profile?.id) && ['DRAFT', 'REJECTED'].includes(String(row.status))

/** 今日是否已填报（只提示，不阻断）。 */
const todayFilled = ref(true)

const checkToday = async () => {
  try {
    const summary: any = await worklogDaySummary(localToday())
    todayFilled.value = Number(summary.logCount || 0) > 0
  } catch {
    todayFilled.value = true
  }
}

onMounted(async () => {
  await loadOptions()
  await loadDay()
  await load()
  await loadStats()
  await checkToday()
})
</script>

<template>
  <div class="pms-page" v-loading="loading">
    <el-alert
      v-if="!todayFilled"
      type="info"
      show-icon
      title="今天还没有填写工作日志"
      description="工作日志全员可填、自愿填写，未填不影响其他流程；如需补填，可选择最近 5 天内的日期。"
      style="margin-bottom: 12px"
    />
    <div class="pms-card">
      <h3>{{ isEditing ? '编辑日志' : '填写日志' }}（一人一天可多条，按项目填报）</h3>
      <el-form :model="form" label-width="110px" size="small">
        <el-row :gutter="8">
          <el-col :xs="24" :sm="8">
            <el-form-item label="日期">
              <el-date-picker
                v-model="form.logDate"
                type="date"
                value-format="YYYY-MM-DD"
                :disabled-date="disabledDate"
                style="width: 100%"
                @change="onDateChange"
              />
            </el-form-item>
          </el-col>
          <el-col :xs="24" :sm="8">
            <el-form-item label="项目">
              <el-select v-model="form.projectId" filterable placeholder="选择我参与的项目" style="width: 100%" @change="onProjectChange">
                <el-option
                  v-for="item in projects"
                  :key="item.id"
                  :label="`${item.projectName}（${item.projectCode}）`"
                  :value="item.id"
                />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :xs="24" :sm="8">
            <el-form-item label="任务">
              <el-select v-model="form.taskId" filterable clearable placeholder="可选" style="width: 100%">
                <el-option v-for="item in tasks" :key="item.id" :label="item.taskName" :value="item.id" />
              </el-select>
            </el-form-item>
          </el-col>
        </el-row>
        <el-row :gutter="8">
          <el-col :xs="24" :sm="8">
            <el-form-item label="本人工时">
              <el-input-number
                v-model="form.totalHours"
                :step="Number(options.step || 0.5)"
                :min="0"
                :max="Number(options.maxHours || 24)"
                style="width: 100%"
              />
            </el-form-item>
          </el-col>
          <el-col :xs="24" :sm="8">
            <el-form-item label="任务进度%">
              <el-input-number v-model="form.progressAfter" :min="0" :max="100" style="width: 100%" />
            </el-form-item>
          </el-col>
          <el-col :xs="24" :sm="8">
            <el-form-item label="标记风险">
              <el-switch v-model="form.riskFlag" />
            </el-form-item>
          </el-col>
        </el-row>
        <el-form-item label="工作内容">
          <el-input v-model="form.content" type="textarea" :rows="2" placeholder="今天在该项目完成了什么" />
        </el-form-item>
        <el-row :gutter="8">
          <el-col :xs="24" :sm="12">
            <el-form-item label="问题与阻塞"><el-input v-model="form.problem" type="textarea" :rows="2" /></el-form-item>
          </el-col>
          <el-col :xs="24" :sm="12">
            <el-form-item label="明日计划"><el-input v-model="form.plan" type="textarea" :rows="2" /></el-form-item>
          </el-col>
        </el-row>

        <el-alert
          v-if="daySummary.overWarn"
          type="warning"
          show-icon
          :closable="false"
          :title="daySummary.warning || `当天已填 ${daySummary.totalHours}h，超过 ${daySummary.warnHours}h 预警线`"
          description="该提示不影响保存与提交，请确认工时是否合理。"
          style="margin-bottom: 8px"
        />
        <el-alert
          v-else
          type="info"
          :closable="false"
          :title="`当天已填 ${daySummary.totalHours || 0}h / 预警线 ${daySummary.warnHours || 8}h，共 ${daySummary.logCount || 0} 条日志`"
          style="margin-bottom: 8px"
        />

        <el-row style="margin-top: 8px">
          <el-button size="small" type="primary" @click="doSubmit">提交</el-button>
          <el-button size="small" @click="doSave">保存草稿</el-button>
          <el-button v-if="isEditing" size="small" @click="cancelEdit">取消编辑</el-button>
          <span style="margin-left: 12px; color: #909399; font-size: 12px">
            可选日期范围为最近 {{ options.backfillMaxDays ?? 5 }} 天（后台参数可调）
          </span>
        </el-row>
      </el-form>
    </div>

    <div class="pms-card">
      <h3>当天日志（{{ form.logDate }}）</h3>
      <el-table :data="dayRows" size="small">
        <el-table-column prop="worklogNo" label="编号" width="150" class-name="pms-mobile-hide" />
        <el-table-column prop="projectName" label="项目" min-width="160">
          <template #default="{ row }">{{ row.projectName || '非项目' }}</template>
        </el-table-column>
        <el-table-column prop="totalHours" label="工时" width="80" />
        <el-table-column prop="content" label="工作内容" min-width="200" class-name="pms-mobile-hide" />
        <el-table-column prop="status" label="状态" width="130" />
        <el-table-column label="操作" width="180">
          <template #default="{ row }">
            <template v-if="editable(row)">
              <el-button size="small" @click="doEdit(row)">编辑</el-button>
              <el-button size="small" type="danger" @click="doDelete(row)">删除</el-button>
            </template>
            <span v-else style="color: #909399">—</span>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <div class="pms-card">
      <h3>我的统计（近 30 天）</h3>
      <el-row :gutter="12">
        <el-col v-for="(value, key) in {
          应填天数: stats.requiredDays,
          已提交天数: stats.submittedDays,
          填写率: stats.fillRate,
          及时率: stats.onTimeRate,
          总工时: stats.totalHours
        }" :key="key" :xs="12" :sm="8" :md="6">
          <div class="pms-kpi">
            <div class="pms-kpi-value">{{ value ?? 0 }}</div>
            <div class="pms-kpi-label">{{ key }}</div>
          </div>
        </el-col>
      </el-row>
    </div>

    <div class="pms-card">
      <h3>日志列表</h3>
      <el-table :data="rows" size="small">
        <el-table-column prop="worklogNo" label="编号" width="150" class-name="pms-mobile-hide" />
        <el-table-column prop="logDate" label="日期" width="120" />
        <el-table-column prop="projectName" label="项目" min-width="150">
          <template #default="{ row }">{{ row.projectName || '非项目' }}</template>
        </el-table-column>
        <el-table-column prop="totalHours" label="工时" width="80" />
        <el-table-column prop="status" label="状态" width="130" />
        <el-table-column prop="lateDays" label="补填(天)" width="100" class-name="pms-mobile-hide" />
        <el-table-column v-if="canConfirm" label="操作" width="220">
          <template #default="{ row }">
            <el-button size="small" type="success" @click="act(row, 'confirm')">确认</el-button>
            <el-button size="small" type="danger" @click="act(row, 'reject')">驳回</el-button>
            <el-button size="small" @click="act(row, 'unconfirm')">撤销</el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-pagination
        v-model:current-page="page.pageNum"
        v-model:page-size="page.pageSize"
        :total="total"
        layout="prev, pager, next, total"
        @current-change="load"
      />
    </div>
  </div>
</template>
