<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  addWorklogComment,
  deleteWorklog,
  listTasks,
  listWorklogs,
  saveWorklog,
  updateWorklog,
  worklogAction,
  worklogComments,
  worklogDaySummary,
  worklogDetail,
  worklogOptions,
  worklogSummary
} from '@/api'
import { useUserStore } from '@/stores/user'

interface WorklogProject {
  id: string
  projectCode: string
  projectName: string
  status: string
}

interface WorklogOption {
  backfillMaxDays: number
  warnHours: number
  maxHours: number
  step: number
  today: string
  projects: WorklogProject[]
}

interface TaskItem {
  id: string
  taskName: string
}

interface WorklogRow {
  id: string
  worklogNo: string
  userId: string
  userName: string
  realName: string
  projectId: string
  projectName: string
  taskId: string
  taskName: string
  logDate: string
  totalHours: number
  content: string
  problem: string
  plan: string
  status: string
  isLate: number
  lateDays: number
  riskFlag: number
  submitTime: string
  confirmTime: string
  rejectReason: string
}

interface WorklogItem {
  projectId: string
  projectName: string
  taskId: string
  taskName: string
  hours: number
  content: string
  progressAfter: number
}

interface WorklogDetail {
  worklog: WorklogRow
  items: WorklogItem[]
}

interface WorklogComment {
  id: string
  userId: string
  userName: string
  realName: string
  content: string
  createTime: string
}

interface DaySummary {
  date: string
  totalHours: number
  warnHours: number
  maxHours: number
  logCount: number
  overWarn: boolean
  warning: string
}

interface DayPoint {
  date: string
  hours: number
  count: number
}

interface ProjectHours {
  projectId: string
  projectName: string
  hours: number
  logCount: number
}

interface WorklogSummary {
  period: string
  dateFrom: string
  dateTo: string
  totalHours: number
  logCount: number
  filledDays: number
  requiredDays: number
  fillRate: number
  avgHoursPerWorkday: number
  lateCount: number
  warnHours: number
  maxHours: number
  overWarn: boolean
  byStatus: Record<string, number>
  byProject: ProjectHours[]
  days: DayPoint[]
}

type TagType = 'success' | 'warning' | 'info' | 'danger'
type PeriodKey = 'day' | 'week' | 'month'
type TabKey = 'mine' | 'pending'

const store = useUserStore()
const canCreate = computed(() => store.has('worklog:create'))
const canConfirm = computed(() => store.has('worklog:confirm'))
const currentUserId = computed(() => String(store.profile?.id || ''))

const PERIODS: { value: PeriodKey; label: string }[] = [
  { value: 'day', label: '今日' },
  { value: 'week', label: '本周' },
  { value: 'month', label: '本月' }
]

const STATUS_META: Record<string, { label: string; type: TagType }> = {
  DRAFT: { label: '草稿', type: 'info' },
  SUBMITTED: { label: '待确认', type: 'warning' },
  PENDING_APPROVE: { label: '补填待审批', type: 'warning' },
  CONFIRMED: { label: '已确认', type: 'success' },
  REJECTED: { label: '已驳回', type: 'danger' }
}
const statusMeta = (status: string) =>
  STATUS_META[status] || { label: status || '-', type: 'info' as TagType }

const localToday = () => {
  const now = new Date()
  const month = String(now.getMonth() + 1).padStart(2, '0')
  const day = String(now.getDate()).padStart(2, '0')
  return `${now.getFullYear()}-${month}-${day}`
}

const timeText = (value: string) => (value ? value.replace('T', ' ').slice(0, 16) : '—')

const isNarrow = ref(false)
const syncWidth = () => {
  isNarrow.value = window.innerWidth <= 768
}

/* ------------------------------ 工时概览 ------------------------------ */
const period = ref<PeriodKey>('day')
const summary = ref<WorklogSummary | null>(null)
const summaryLoading = ref(false)

const loadSummary = async () => {
  summaryLoading.value = true
  try {
    summary.value = (await worklogSummary({
      period: period.value,
      date: localToday()
    })) as unknown as WorklogSummary
  } catch {
    /* 错误提示由请求拦截器统一弹出 */
  } finally {
    summaryLoading.value = false
  }
}

const summaryRange = computed(() => {
  const data = summary.value
  if (!data) return ''
  return data.dateFrom === data.dateTo ? data.dateFrom : `${data.dateFrom} ~ ${data.dateTo}`
})

const trendDays = computed(() => summary.value?.days || [])
const maxTrendHours = computed(() =>
  Math.max(...trendDays.value.map((item) => Number(item.hours || 0)), 1)
)
const barHeight = (day: DayPoint) => {
  const hours = Number(day.hours || 0)
  if (hours <= 0) return '2px'
  return `${Math.max((hours / maxTrendHours.value) * 100, 8)}%`
}
const dayLabel = (iso: string) => iso.slice(5).replace('-', '/')
const showDayLabel = (index: number) => {
  const size = trendDays.value.length
  if (size <= 8) return true
  return index === 0 || index === size - 1 || index % 5 === 0
}

const maxProjectHours = computed(() =>
  Math.max(...(summary.value?.byProject || []).map((item) => Number(item.hours || 0)), 1)
)
const projectWidth = (item: ProjectHours) =>
  `${Math.max((Number(item.hours || 0) / maxProjectHours.value) * 100, 3)}%`

const todaySummary = ref<DaySummary | null>(null)
const todayMissing = computed(
  () => !!todaySummary.value && Number(todaySummary.value.logCount || 0) === 0
)
const loadToday = async () => {
  try {
    todaySummary.value = (await worklogDaySummary(localToday())) as unknown as DaySummary
  } catch {
    todaySummary.value = null
  }
}

/* ------------------------------ 日志列表 ------------------------------ */
const tab = ref<TabKey>('mine')
const rows = ref<WorklogRow[]>([])
const total = ref(0)
const listLoading = ref(false)
const page = reactive({ pageNum: 1, pageSize: 10 })
const filters = reactive({
  dateRange: [] as string[] | null,
  projectId: '',
  status: '',
  keyword: ''
})

const loadLogs = async () => {
  listLoading.value = true
  try {
    const range = filters.dateRange || []
    const params: Record<string, unknown> = {
      scope: tab.value === 'mine' ? 'mine' : 'visible',
      pageNum: page.pageNum,
      pageSize: page.pageSize,
      projectId: filters.projectId || undefined,
      keyword: filters.keyword.trim() || undefined,
      dateFrom: range[0],
      dateTo: range[1]
    }
    if (tab.value === 'pending') {
      params.status = 'SUBMITTED,PENDING_APPROVE'
    } else if (filters.status) {
      params.status = filters.status
    }
    const data = await listWorklogs(params)
    rows.value = (data.list || []) as unknown as WorklogRow[]
    total.value = Number(data.total || 0)
  } catch {
    /* 错误提示由请求拦截器统一弹出 */
  } finally {
    listLoading.value = false
  }
}

const searchLogs = () => {
  page.pageNum = 1
  loadLogs()
}

const resetFilters = () => {
  filters.dateRange = []
  filters.projectId = ''
  filters.status = ''
  filters.keyword = ''
  searchLogs()
}

const switchTab = (key: TabKey) => {
  if (tab.value === key) return
  tab.value = key
  page.pageNum = 1
  loadLogs()
}

const editable = (row: any) =>
  tab.value === 'mine' &&
  String(row.userId) === currentUserId.value &&
  ['DRAFT', 'REJECTED'].includes(String(row.status))

const authorLabel = (row: any) =>
  row.realName || row.userName || (String(row.userId) === currentUserId.value ? '我' : `用户 ${row.userId}`)

/* ------------------------------ 选项与任务 ------------------------------ */
const options = ref<WorklogOption>({
  backfillMaxDays: 5,
  warnHours: 8,
  maxHours: 24,
  step: 0.5,
  today: localToday(),
  projects: []
})
const tasks = ref<TaskItem[]>([])

const loadOptions = async () => {
  try {
    options.value = (await worklogOptions()) as unknown as WorklogOption
  } catch {
    /* 使用默认配置兜底 */
  }
}

const loadTasks = async (projectId: string) => {
  tasks.value = []
  if (!projectId) return
  try {
    tasks.value = (await listTasks(projectId)) as unknown as TaskItem[]
  } catch {
    tasks.value = []
  }
}

const disabledDate = (time: Date) => {
  const maxDays = Number(options.value.backfillMaxDays ?? 5)
  const start = new Date()
  start.setHours(0, 0, 0, 0)
  start.setDate(start.getDate() - maxDays)
  return time.getTime() > Date.now() || time.getTime() < start.getTime()
}

/* ------------------------------ 填写 / 编辑 ------------------------------ */
const formVisible = ref(false)
const formMode = ref<'create' | 'edit'>('create')
const formSaving = ref(false)
const formSubmitting = ref(false)
const form = reactive({
  id: '',
  logDate: localToday(),
  projectId: '',
  taskId: '',
  totalHours: 8,
  progressAfter: 0,
  riskFlag: false,
  content: '',
  problem: '',
  plan: ''
})
const daySummary = ref<DaySummary | null>(null)

const resetForm = () => {
  Object.assign(form, {
    id: '',
    logDate: localToday(),
    projectId: '',
    taskId: '',
    totalHours: 8,
    progressAfter: 0,
    riskFlag: false,
    content: '',
    problem: '',
    plan: ''
  })
  tasks.value = []
}

const openCreate = () => {
  formMode.value = 'create'
  resetForm()
  formVisible.value = true
  loadDaySummary()
}

const openEdit = async (row: any) => {
  try {
    const data = (await worklogDetail(row.id)) as unknown as WorklogDetail
    const worklog = data.worklog
    formMode.value = 'edit'
    Object.assign(form, {
      id: worklog.id,
      logDate: worklog.logDate,
      projectId: String(worklog.projectId || ''),
      taskId: String(worklog.taskId || ''),
      totalHours: Number(worklog.totalHours || 0),
      progressAfter: Number(data.items?.[0]?.progressAfter || 0),
      riskFlag: Boolean(worklog.riskFlag),
      content: worklog.content || '',
      problem: worklog.problem || '',
      plan: worklog.plan || ''
    })
    await loadTasks(form.projectId)
    await loadDaySummary()
    formVisible.value = true
    detailVisible.value = false
  } catch {
    /* 错误提示由请求拦截器统一弹出 */
  }
}

const onProjectChange = async () => {
  form.taskId = ''
  await loadTasks(form.projectId)
}

const loadDaySummary = async () => {
  try {
    daySummary.value = (await worklogDaySummary(form.logDate)) as unknown as DaySummary
  } catch {
    daySummary.value = null
  }
}

const dayStrip = computed(() => {
  const data = daySummary.value
  const warn = Number(data?.warnHours ?? options.value.warnHours ?? 8)
  const hours = Number(data?.totalHours || 0)
  return {
    hours,
    warn,
    count: Number(data?.logCount || 0),
    over: hours > warn
  }
})

const validateForm = () => {
  if (!form.projectId) {
    ElMessage.warning('请选择项目')
    return false
  }
  if (!form.totalHours || Number(form.totalHours) <= 0) {
    ElMessage.warning('请填写大于 0 的工时')
    return false
  }
  if (!form.content.trim()) {
    ElMessage.warning('请填写工作内容')
    return false
  }
  return true
}

const persistForm = async (submitAfter: boolean) => {
  if (!canCreate.value || formSaving.value || formSubmitting.value) return
  if (!validateForm()) return
  if (submitAfter) formSubmitting.value = true
  else formSaving.value = true
  try {
    const payload = {
      logDate: form.logDate,
      projectId: form.projectId,
      taskId: form.taskId || 0,
      totalHours: Number(form.totalHours),
      content: form.content.trim(),
      problem: form.problem,
      plan: form.plan,
      riskFlag: form.riskFlag,
      progressAfter: Number(form.progressAfter)
    }
    const saved =
      formMode.value === 'edit' ? await updateWorklog(form.id, payload) : await saveWorklog(payload)
    const savedId = String(saved.id || form.id)
    form.id = savedId
    formMode.value = 'edit'
    if (saved.warning) ElMessage.warning(String(saved.warning))

    if (submitAfter) {
      const result = await worklogAction(savedId, 'submit')
      if (result.warning) {
        ElMessage.warning(String(result.warning))
      } else {
        ElMessage.success(
          result.status === 'PENDING_APPROVE' ? '已提交，等待补填审批' : '日志已提交'
        )
      }
    } else {
      ElMessage.success('草稿已保存')
    }
    formVisible.value = false
    await refreshAll()
  } catch {
    /* 错误提示由请求拦截器统一弹出 */
  } finally {
    formSaving.value = false
    formSubmitting.value = false
  }
}

/* ------------------------------ 详情与评论 ------------------------------ */
const detailVisible = ref(false)
const detailLoading = ref(false)
const detail = ref<WorklogDetail | null>(null)
const comments = ref<WorklogComment[]>([])
const commentText = ref('')
const commentSaving = ref(false)

const detailWorklog = computed(() => detail.value?.worklog || null)
const isOwner = computed(
  () => String(detailWorklog.value?.userId || '') === currentUserId.value
)
const canEditDetail = computed(
  () => isOwner.value && ['DRAFT', 'REJECTED'].includes(String(detailWorklog.value?.status))
)
const canSubmitDetail = computed(
  () => isOwner.value && ['DRAFT', 'REJECTED'].includes(String(detailWorklog.value?.status))
)
const canDeleteDetail = computed(() => canEditDetail.value)
const canConfirmDetail = computed(
  () => canConfirm.value && detailWorklog.value?.status === 'SUBMITTED'
)
const canApproveLate = computed(
  () => canConfirm.value && detailWorklog.value?.status === 'PENDING_APPROVE'
)
const canUnconfirmDetail = computed(
  () => canConfirm.value && detailWorklog.value?.status === 'CONFIRMED'
)

const openDetail = async (row: any) => {
  detailVisible.value = true
  detailLoading.value = true
  detail.value = null
  comments.value = []
  try {
    const [data, commentRows] = await Promise.all([
      worklogDetail(row.id),
      worklogComments(row.id)
    ])
    detail.value = data as unknown as WorklogDetail
    comments.value = (commentRows || []) as unknown as WorklogComment[]
  } catch {
    detailVisible.value = false
  } finally {
    detailLoading.value = false
  }
}

const reloadDetail = async (id: string) => {
  if (!id) return
  try {
    const [data, commentRows] = await Promise.all([worklogDetail(id), worklogComments(id)])
    detail.value = data as unknown as WorklogDetail
    comments.value = (commentRows || []) as unknown as WorklogComment[]
  } catch {
    /* 错误提示由请求拦截器统一弹出 */
  }
}

const commentAuthor = (comment: WorklogComment) =>
  comment.realName || comment.userName || '用户'
const commentInitial = (comment: WorklogComment) => commentAuthor(comment).slice(0, 1)

const addComment = async () => {
  const worklog = detailWorklog.value
  const content = commentText.value.trim()
  if (!worklog || !content || commentSaving.value) return
  commentSaving.value = true
  try {
    await addWorklogComment(worklog.id, content)
    commentText.value = ''
    comments.value = (await worklogComments(
      worklog.id
    )) as unknown as WorklogComment[]
  } catch {
    /* 错误提示由请求拦截器统一弹出 */
  } finally {
    commentSaving.value = false
  }
}

/* ------------------------------ 列表操作 ------------------------------ */
const refreshAll = async () => {
  await Promise.all([loadLogs(), loadSummary(), loadToday()])
  if (formVisible.value) await loadDaySummary()
  if (detailVisible.value && detailWorklog.value) await reloadDetail(detailWorklog.value.id)
}

const submitRow = async (row: any) => {
  try {
    const result = await worklogAction(row.id, 'submit')
    if (result.warning) ElMessage.warning(String(result.warning))
    else ElMessage.success(result.status === 'PENDING_APPROVE' ? '已提交，等待补填审批' : '日志已提交')
    await refreshAll()
  } catch {
    /* 错误提示由请求拦截器统一弹出 */
  }
}

const confirmRow = async (row: any) => {
  try {
    await worklogAction(row.id, 'confirm')
    ElMessage.success('已确认')
    await refreshAll()
  } catch {
    /* 错误提示由请求拦截器统一弹出 */
  }
}

const approveLateRow = async (row: any) => {
  try {
    await worklogAction(row.id, 'approve-late')
    ElMessage.success('补填已通过')
    await refreshAll()
  } catch {
    /* 错误提示由请求拦截器统一弹出 */
  }
}

const askRejectReason = async () => {
  try {
    const result = await ElMessageBox.prompt('请填写驳回原因', '驳回日志', {
      confirmButtonText: '驳回',
      cancelButtonText: '取消',
      inputPlaceholder: '驳回原因（必填）',
      inputValidator: (value: string) =>
        value && value.trim() ? true : '请填写驳回原因'
    })
    return String(result.value || '').trim()
  } catch {
    return ''
  }
}

const rejectRow = async (row: any) => {
  const reason = await askRejectReason()
  if (!reason) return
  try {
    await worklogAction(row.id, 'reject', { reason })
    ElMessage.success('已驳回')
    await refreshAll()
  } catch {
    /* 错误提示由请求拦截器统一弹出 */
  }
}

const removeRow = async (row: any) => {
  try {
    await ElMessageBox.confirm(`确认删除 ${row.logDate} 的这条日志？`, '删除日志', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消'
    })
  } catch {
    return
  }
  try {
    await deleteWorklog(row.id)
    ElMessage.success('日志已删除')
    if (detailWorklog.value?.id === row.id) detailVisible.value = false
    await refreshAll()
  } catch {
    /* 错误提示由请求拦截器统一弹出 */
  }
}

const runDetailAction = async (action: string, payload: Record<string, unknown> = {}) => {
  const worklog = detailWorklog.value
  if (!worklog) return
  try {
    const result = await worklogAction(worklog.id, action, payload)
    if (result.warning) ElMessage.warning(String(result.warning))
    else ElMessage.success('操作成功')
    await refreshAll()
  } catch {
    /* 错误提示由请求拦截器统一弹出 */
  }
}

const rejectDetail = async () => {
  const reason = await askRejectReason()
  if (!reason) return
  await runDetailAction('reject', { reason })
}

onMounted(() => {
  syncWidth()
  window.addEventListener('resize', syncWidth)
  Promise.all([loadOptions(), loadLogs(), loadSummary(), loadToday()])
})

onUnmounted(() => window.removeEventListener('resize', syncWidth))
</script>

<template>
  <div class="pms-page">
    <div class="pms-card page-head">
      <div class="head-copy">
        <h2>
          工作日志
          <el-tag v-if="todayMissing && canCreate" type="warning" effect="plain" size="small">
            今日未填报
          </el-tag>
        </h2>
        <p>按项目记录每天的工作内容、工时与问题，提交后由项目经理确认并回填项目进度。</p>
      </div>
      <div class="head-ops">
        <el-button :loading="listLoading || summaryLoading" @click="refreshAll">刷新</el-button>
        <el-button v-if="canCreate" type="primary" @click="openCreate">写日志</el-button>
      </div>
    </div>

    <div class="pms-card stats-card" v-loading="summaryLoading">
      <div class="stats-head">
        <div class="stats-title">
          <h3>工时概览</h3>
          <span class="range">{{ summaryRange }}</span>
        </div>
        <el-radio-group v-model="period" size="small" @change="loadSummary">
          <el-radio-button v-for="item in PERIODS" :key="item.value" :value="item.value">
            {{ item.label }}
          </el-radio-button>
        </el-radio-group>
      </div>

      <div class="stats-body">
        <div class="kpi-grid">
          <div class="kpi">
            <span class="kpi-label">工时合计</span>
            <span class="kpi-value">{{ summary?.totalHours ?? 0 }}<i>h</i></span>
            <span class="kpi-sub">日均 {{ summary?.avgHoursPerWorkday ?? 0 }}h</span>
          </div>
          <div class="kpi">
            <span class="kpi-label">日志条数</span>
            <span class="kpi-value">{{ summary?.logCount ?? 0 }}<i>条</i></span>
            <span class="kpi-sub">补填 {{ summary?.lateCount ?? 0 }} 条</span>
          </div>
          <div class="kpi">
            <span class="kpi-label">填报天数</span>
            <span class="kpi-value">
              {{ summary?.filledDays ?? 0 }}<i>/ {{ summary?.requiredDays ?? 0 }} 天</i>
            </span>
            <span class="kpi-sub">按工作日计算</span>
          </div>
          <div class="kpi">
            <span class="kpi-label">填写率</span>
            <span class="kpi-value">{{ summary?.fillRate ?? 0 }}<i>%</i></span>
            <span class="kpi-sub">已提交即计入</span>
          </div>
        </div>

        <div v-if="trendDays.length > 1" class="trend">
          <span class="trend-title">每日工时</span>
          <div class="trend-bars">
            <el-tooltip
              v-for="(day, index) in trendDays"
              :key="day.date"
              :content="`${day.date}：${day.hours}h / ${day.count} 条`"
              placement="top"
            >
              <div class="trend-col">
                <div class="trend-bar" :style="{ height: barHeight(day) }"></div>
                <span class="trend-label">{{ showDayLabel(index) ? dayLabel(day.date) : '' }}</span>
              </div>
            </el-tooltip>
          </div>
        </div>
      </div>

      <div v-if="summary?.byProject?.length" class="project-bars">
        <div v-for="item in summary.byProject.slice(0, 6)" :key="String(item.projectId)" class="project-bar">
          <span class="pb-name">{{ item.projectName }}</span>
          <span class="pb-track"><span class="pb-fill" :style="{ width: projectWidth(item) }"></span></span>
          <span class="pb-hours">{{ item.hours }}h</span>
        </div>
      </div>
    </div>

    <div class="pms-card list-card">
      <div class="list-head">
        <div class="seg">
          <button
            type="button"
            :class="{ 'is-active': tab === 'mine' }"
            @click="switchTab('mine')"
          >
            我的日志
          </button>
          <button
            v-if="canConfirm"
            type="button"
            :class="{ 'is-active': tab === 'pending' }"
            @click="switchTab('pending')"
          >
            团队待确认
          </button>
        </div>
        <span class="list-total">共 {{ total }} 条</span>
      </div>

      <div class="filter-row">
        <el-date-picker
          v-model="filters.dateRange"
          class="f-range"
          type="daterange"
          unlink-panels
          range-separator="至"
          start-placeholder="开始日期"
          end-placeholder="结束日期"
          value-format="YYYY-MM-DD"
        />
        <el-select v-model="filters.projectId" class="f-project" placeholder="全部项目" clearable filterable>
          <el-option
            v-for="item in options.projects"
            :key="String(item.id)"
            :label="`${item.projectName}（${item.projectCode}）`"
            :value="String(item.id)"
          />
        </el-select>
        <el-select v-if="tab === 'mine'" v-model="filters.status" class="f-status" placeholder="全部状态" clearable>
          <el-option label="草稿" value="DRAFT" />
          <el-option label="待确认" value="SUBMITTED" />
          <el-option label="补填待审批" value="PENDING_APPROVE" />
          <el-option label="已确认" value="CONFIRMED" />
          <el-option label="已驳回" value="REJECTED" />
        </el-select>
        <el-input
          v-model="filters.keyword"
          class="f-keyword"
          placeholder="搜索工作内容 / 问题 / 编号"
          clearable
          @keyup.enter="searchLogs"
        />
        <div class="filter-actions">
          <el-button type="primary" :loading="listLoading" @click="searchLogs">查询</el-button>
          <el-button @click="resetFilters">重置</el-button>
        </div>
      </div>

      <el-table v-loading="listLoading" :data="rows" size="small">
        <el-table-column label="日期" width="110">
          <template #default="{ row }">{{ row.logDate }}</template>
        </el-table-column>
        <el-table-column label="项目" min-width="170">
          <template #default="{ row }">
            <span class="project-cell">{{ row.projectName || '非项目' }}</span>
          </template>
        </el-table-column>
        <el-table-column
          prop="content"
          label="工作内容"
          min-width="240"
          show-overflow-tooltip
          class-name="pms-mobile-hide"
        />
        <el-table-column label="工时" width="80" align="right">
          <template #default="{ row }">
            <span class="hours-cell">{{ row.totalHours }}h</span>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="120">
          <template #default="{ row }">
            <el-tag size="small" :type="statusMeta(row.status).type">
              {{ statusMeta(row.status).label }}
            </el-tag>
            <el-tag v-if="row.riskFlag" size="small" type="danger" effect="plain" class="risk-tag">
              风险
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column v-if="tab === 'pending'" label="提交人" width="120">
          <template #default="{ row }">{{ authorLabel(row) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="200">
          <template #default="{ row }">
            <el-button link type="primary" @click="openDetail(row)">详情</el-button>
            <template v-if="editable(row)">
              <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
              <el-button link type="primary" @click="submitRow(row)">提交</el-button>
            </template>
            <template v-else-if="tab === 'pending'">
              <el-button
                v-if="row.status === 'SUBMITTED'"
                link
                type="success"
                @click="confirmRow(row)"
              >
                确认
              </el-button>
              <el-button
                v-if="row.status === 'PENDING_APPROVE'"
                link
                type="primary"
                @click="approveLateRow(row)"
              >
                通过
              </el-button>
              <el-button link type="danger" @click="rejectRow(row)">驳回</el-button>
            </template>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty :description="tab === 'mine' ? '还没有日志，点右上角「写日志」开始记录' : '暂无待确认日志'" :image-size="76" />
        </template>
      </el-table>

      <el-pagination
        v-model:current-page="page.pageNum"
        v-model:page-size="page.pageSize"
        :total="total"
        :page-sizes="[10, 20, 50]"
        :layout="isNarrow ? 'prev, pager, next' : 'total, sizes, prev, pager, next'"
        class="pager"
        @current-change="loadLogs"
        @size-change="searchLogs"
      />
    </div>

    <el-drawer
      v-model="formVisible"
      :title="formMode === 'edit' ? '编辑日志' : '写工作日志'"
      size="min(720px, 94vw)"
    >
      <div class="drawer-body">
        <el-alert
          v-if="!options.projects.length"
          type="info"
          :closable="false"
          show-icon
          title="暂无可填报项目"
          description="请先联系项目经理将你加入项目成员，再填写工作日志。"
          style="margin-bottom: 14px"
        />
        <div class="form-grid">
          <div class="field">
            <label>日期 <em>*</em></label>
            <el-date-picker
              v-model="form.logDate"
              type="date"
              value-format="YYYY-MM-DD"
              :disabled-date="disabledDate"
              @change="loadDaySummary"
            />
          </div>
          <div class="field">
            <label>项目 <em>*</em></label>
            <el-select v-model="form.projectId" filterable placeholder="选择我参与的项目" @change="onProjectChange">
              <el-option
                v-for="item in options.projects"
                :key="String(item.id)"
                :label="`${item.projectName}（${item.projectCode}）`"
                :value="String(item.id)"
              />
            </el-select>
          </div>
          <div class="field">
            <label>任务</label>
            <el-select v-model="form.taskId" filterable clearable placeholder="可选，选择所属任务">
              <el-option v-for="item in tasks" :key="String(item.id)" :label="item.taskName" :value="String(item.id)" />
            </el-select>
          </div>
          <div class="field">
            <label>本人工时 <em>*</em></label>
            <el-input-number
              v-model="form.totalHours"
              :step="Number(options.step || 0.5)"
              :min="0"
              :max="Number(options.maxHours || 24)"
            />
          </div>
          <div class="field">
            <label>任务进度（%）</label>
            <el-input-number v-model="form.progressAfter" :min="0" :max="100" />
          </div>
          <div class="field">
            <label>风险标记</label>
            <el-switch v-model="form.riskFlag" active-text="存在风险" />
          </div>
          <div class="field span-2">
            <label>工作内容 <em>*</em></label>
            <el-input
              v-model="form.content"
              type="textarea"
              :rows="3"
              maxlength="1000"
              show-word-limit
              placeholder="今天完成了什么？建议写清产出与结果"
            />
          </div>
          <div class="field span-2">
            <label>问题与阻塞</label>
            <el-input
              v-model="form.problem"
              type="textarea"
              :rows="2"
              maxlength="500"
              placeholder="遇到的技术/协作/资源问题（可选）"
            />
          </div>
          <div class="field span-2">
            <label>明日计划</label>
            <el-input
              v-model="form.plan"
              type="textarea"
              :rows="2"
              maxlength="500"
              placeholder="下一步要做的事（可选）"
            />
          </div>
        </div>

        <div class="day-strip">
          <span>当天已填 <b :class="{ over: dayStrip.over }">{{ dayStrip.hours }}h</b></span>
          <span>预警线 <b>{{ dayStrip.warn }}h</b></span>
          <span>日志 <b>{{ dayStrip.count }} 条</b></span>
          <el-tag v-if="dayStrip.over" type="warning" size="small" effect="plain">已超预警线，仅提示不阻断</el-tag>
          <el-tag v-else type="info" size="small" effect="plain">可继续添加</el-tag>
        </div>
      </div>
      <template #footer>
        <div class="drawer-footer form-footer">
          <span class="footer-tip">可选日期为最近 {{ options.backfillMaxDays }} 天</span>
          <span class="footer-spacer"></span>
          <el-button @click="formVisible = false">取消</el-button>
          <el-button :loading="formSaving" :disabled="formSubmitting" @click="persistForm(false)">
            保存草稿
          </el-button>
          <el-button type="primary" :loading="formSubmitting" :disabled="formSaving" @click="persistForm(true)">
            提交
          </el-button>
        </div>
      </template>
    </el-drawer>

    <el-drawer v-model="detailVisible" title="日志详情" size="min(680px, 94vw)">
      <div v-loading="detailLoading" class="detail">
        <template v-if="detail">
          <div class="detail-head">
            <div>
              <h3>{{ detail.worklog.projectName || '非项目' }}</h3>
              <p class="detail-meta">
                {{ detail.worklog.logDate }} · {{ detail.worklog.worklogNo }}
                <template v-if="detail.worklog.userId">
                  · {{ detail.worklog.realName || detail.worklog.userName }}
                </template>
              </p>
            </div>
            <div class="detail-tags">
              <el-tag :type="statusMeta(detail.worklog.status).type">
                {{ statusMeta(detail.worklog.status).label }}
              </el-tag>
              <el-tag v-if="detail.worklog.riskFlag" type="danger" effect="plain">风险</el-tag>
            </div>
          </div>

          <div class="metrics">
            <div class="metric">
              <span>日期</span>
              <b>{{ detail.worklog.logDate }}</b>
            </div>
            <div class="metric">
              <span>工时</span>
              <b>{{ detail.worklog.totalHours }}h</b>
            </div>
            <div class="metric">
              <span>任务</span>
              <b>{{ detail.worklog.taskName || '未关联' }}</b>
            </div>
            <div class="metric">
              <span>{{ detail.worklog.lateDays > 0 ? '补填' : '提交时间' }}</span>
              <b>
                {{
                  detail.worklog.lateDays > 0
                    ? `${detail.worklog.lateDays} 天`
                    : timeText(detail.worklog.submitTime)
                }}
              </b>
            </div>
          </div>

          <el-alert
            v-if="detail.worklog.rejectReason"
            type="error"
            :closable="false"
            show-icon
            :title="`驳回原因：${detail.worklog.rejectReason}`"
            style="margin-bottom: 4px"
          />

          <section class="detail-section">
            <h4>工作内容</h4>
            <p class="detail-text">{{ detail.worklog.content || '—' }}</p>
          </section>
          <section class="detail-section">
            <h4>问题与阻塞</h4>
            <p class="detail-text">{{ detail.worklog.problem || '—' }}</p>
          </section>
          <section class="detail-section">
            <h4>明日计划</h4>
            <p class="detail-text">{{ detail.worklog.plan || '—' }}</p>
          </section>

          <section class="detail-section">
            <h4>沟通记录</h4>
            <div v-if="comments.length" class="comment-list">
              <div v-for="item in comments" :key="item.id" class="comment">
                <span class="avatar">{{ commentInitial(item) }}</span>
                <div class="comment-main">
                  <div class="comment-head">
                    <b>{{ commentAuthor(item) }}</b>
                    <span>{{ timeText(item.createTime) }}</span>
                  </div>
                  <p>{{ item.content }}</p>
                </div>
              </div>
            </div>
            <el-empty v-else description="暂无沟通记录" :image-size="64" />
            <div class="comment-editor">
              <el-input
                v-model="commentText"
                type="textarea"
                :rows="2"
                maxlength="1000"
                show-word-limit
                placeholder="补充说明、反馈或确认意见…"
              />
              <el-button
                type="primary"
                :loading="commentSaving"
                :disabled="!commentText.trim()"
                @click="addComment"
              >
                发送
              </el-button>
            </div>
          </section>
        </template>
      </div>
      <template #footer>
        <div class="drawer-footer">
          <el-button v-if="canDeleteDetail" type="danger" link @click="detail && removeRow(detail.worklog)">
            删除日志
          </el-button>
          <span class="footer-spacer"></span>
          <el-button @click="detailVisible = false">关闭</el-button>
          <el-button v-if="canEditDetail && detail" @click="openEdit(detail.worklog)">编辑</el-button>
          <el-button v-if="canSubmitDetail" type="primary" @click="runDetailAction('submit')">
            提交
          </el-button>
          <el-button v-if="canConfirmDetail" type="success" @click="runDetailAction('confirm')">
            确认
          </el-button>
          <el-button v-if="canApproveLate" type="primary" @click="runDetailAction('approve-late')">
            通过补填
          </el-button>
          <el-button v-if="canConfirmDetail || canApproveLate" type="danger" plain @click="rejectDetail">
            驳回
          </el-button>
          <el-button v-if="canUnconfirmDetail" @click="runDetailAction('unconfirm')">
            撤销确认
          </el-button>
        </div>
      </template>
    </el-drawer>
  </div>
</template>

<style scoped>
.page-head {
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
  letter-spacing: 0.01em;
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

/* ---------------- 工时概览 ---------------- */
.stats-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 10px;
  margin-bottom: 14px;
}

.stats-title {
  display: flex;
  align-items: baseline;
  gap: 10px;
}

.stats-title h3 {
  margin: 0;
  font-size: 14.5px;
  font-weight: 600;
}

.range {
  font-size: 12px;
  color: var(--pms-text-3);
  font-variant-numeric: tabular-nums;
}

.stats-body {
  display: grid;
  grid-template-columns: minmax(0, 1.15fr) minmax(220px, 0.85fr);
  gap: 20px;
  align-items: end;
}

.stats-body.is-single {
  grid-template-columns: minmax(0, 1fr);
}

.kpi-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
}

.kpi {
  display: flex;
  flex-direction: column;
  gap: 3px;
  padding: 10px 12px;
  border: 1px solid var(--pms-line);
  border-radius: 10px;
  background: #fafbfe;
}

.kpi-label {
  font-size: 12px;
  color: var(--pms-text-3);
}

.kpi-value {
  font-size: 21px;
  font-weight: 600;
  line-height: 1.25;
  color: var(--pms-text);
  font-variant-numeric: tabular-nums;
}

.kpi-value i {
  margin-left: 2px;
  font-size: 11.5px;
  font-style: normal;
  font-weight: 500;
  color: var(--pms-text-3);
}

.kpi-sub {
  font-size: 11.5px;
  color: var(--pms-text-3);
}

.trend {
  display: flex;
  flex-direction: column;
  justify-content: flex-end;
  gap: 6px;
  height: 96px;
  padding-bottom: 2px;
}

.trend-title {
  font-size: 11.5px;
  color: var(--pms-text-3);
}

.trend-bars {
  display: flex;
  align-items: flex-end;
  gap: 4px;
  width: 100%;
  flex: 1;
  min-height: 0;
}

.trend-col {
  flex: 1;
  min-width: 0;
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: flex-end;
  gap: 4px;
}

.trend-bar {
  width: 100%;
  max-width: 18px;
  min-height: 2px;
  border-radius: 4px 4px 0 0;
  background: linear-gradient(180deg, #7aa2ff, #3370ff);
  transition: height 0.2s ease;
}

.trend-label {
  font-size: 10px;
  line-height: 1;
  color: var(--pms-text-3);
  white-space: nowrap;
}

.project-bars {
  display: grid;
  gap: 8px;
  margin-top: 16px;
  padding-top: 14px;
  border-top: 1px solid var(--pms-line-soft);
}

.project-bar {
  display: grid;
  grid-template-columns: 130px minmax(0, 1fr) 64px;
  align-items: center;
  gap: 10px;
}

.pb-name {
  overflow: hidden;
  font-size: 12.5px;
  color: var(--pms-text-2);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.pb-track {
  height: 8px;
  overflow: hidden;
  border-radius: 5px;
  background: #eef2f8;
}

.pb-fill {
  display: block;
  height: 100%;
  border-radius: 5px;
  background: linear-gradient(90deg, #7aa2ff, #3370ff);
}

.pb-hours {
  font-size: 12px;
  color: var(--pms-text-2);
  text-align: right;
  font-variant-numeric: tabular-nums;
}

/* ---------------- 列表 ---------------- */
.list-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 14px;
}

.seg {
  display: inline-flex;
  gap: 2px;
  padding: 3px;
  border: 1px solid #e3e9f4;
  border-radius: 10px;
  background: #eef2f8;
}

.seg button {
  height: 30px;
  padding: 0 16px;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: var(--pms-text-2);
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition:
    background-color 0.16s ease,
    color 0.16s ease;
}

.seg button:hover {
  color: var(--pms-text);
}

.seg button.is-active {
  background: var(--pms-surface);
  color: var(--pms-primary-deep);
  box-shadow: 0 1px 2px rgba(16, 35, 70, 0.08);
}

.list-total {
  font-size: 12.5px;
  color: var(--pms-text-3);
  font-variant-numeric: tabular-nums;
}

.filter-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
  margin-bottom: 14px;
}

/* Element Plus 组件根节点不带 scoped 属性，尺寸规则需用 :deep 命中 */
.filter-row :deep(.f-range) {
  flex: 0 0 260px;
}

.filter-row :deep(.f-project) {
  flex: 0 0 200px;
}

.filter-row :deep(.f-status) {
  flex: 0 0 140px;
}

.filter-row :deep(.f-keyword) {
  flex: 1 1 220px;
  min-width: 180px;
}

.filter-row :deep(.el-date-editor),
.filter-row :deep(.el-select),
.filter-row :deep(.el-input) {
  width: 100%;
}

.filter-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-left: auto;
  white-space: nowrap;
}

.project-cell {
  display: inline-block;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  vertical-align: bottom;
}

.hours-cell {
  font-variant-numeric: tabular-nums;
  font-weight: 500;
}

.risk-tag {
  margin-left: 4px;
}

.pager {
  flex-wrap: wrap;
  row-gap: 8px;
  margin-top: 14px;
  justify-content: flex-end;
}

/* ---------------- 填写抽屉 ---------------- */
.drawer-body {
  padding: 4px 20px 20px;
}

.form-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px 16px;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 0;
}

.field > label {
  font-size: 12.5px;
  font-weight: 500;
  color: var(--pms-text-2);
}

.field em {
  margin-left: 2px;
  font-style: normal;
  color: var(--el-color-danger);
}

.field.span-2 {
  grid-column: span 2;
}

.field :deep(.el-date-editor),
.field :deep(.el-select),
.field :deep(.el-input-number) {
  width: 100%;
}

.day-strip {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
  margin-top: 16px;
  padding: 10px 12px;
  border-radius: 8px;
  background: #f7f9fd;
  font-size: 12.5px;
  color: var(--pms-text-2);
}

.day-strip b {
  font-variant-numeric: tabular-nums;
  color: var(--pms-text);
}

.day-strip b.over {
  color: #c47f17;
}

.drawer-footer {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  width: 100%;
}

.footer-tip {
  font-size: 12px;
  color: var(--pms-text-3);
}

.footer-spacer {
  flex: 1;
}

/* ---------------- 详情抽屉 ---------------- */
.detail {
  padding: 4px 20px 24px;
}

.detail-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.detail-head h3 {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
}

.detail-meta {
  margin: 5px 0 0;
  font-size: 12px;
  color: var(--pms-text-3);
}

.detail-tags {
  display: flex;
  align-items: center;
  gap: 6px;
  flex: none;
}

.metrics {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
  margin: 16px 0 14px;
}

.metric {
  display: flex;
  flex-direction: column;
  gap: 3px;
  padding: 10px;
  border: 1px solid var(--pms-line);
  border-radius: 8px;
  background: #fafbfe;
  min-width: 0;
}

.metric span {
  font-size: 11.5px;
  color: var(--pms-text-3);
}

.metric b {
  overflow: hidden;
  font-size: 13px;
  font-weight: 600;
  color: var(--pms-text);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.detail-section {
  margin-top: 18px;
}

.detail-section h4 {
  margin: 0 0 8px;
  font-size: 13px;
  font-weight: 600;
  color: var(--pms-text);
}

.detail-text {
  margin: 0;
  padding: 12px 14px;
  border: 1px solid var(--pms-line);
  border-radius: 8px;
  background: #fafbfe;
  font-size: 13px;
  line-height: 1.75;
  color: var(--pms-text-2);
  white-space: pre-wrap;
  word-break: break-word;
}

.comment-list {
  display: grid;
  gap: 12px;
}

.comment {
  display: flex;
  gap: 10px;
}

.comment .avatar {
  flex: none;
  width: 28px;
  height: 28px;
  display: grid;
  place-items: center;
  border-radius: 50%;
  background: var(--pms-primary-weak);
  color: var(--pms-primary-deep);
  font-size: 12px;
  font-weight: 600;
}

.comment-main {
  min-width: 0;
}

.comment-head {
  display: flex;
  align-items: baseline;
  gap: 8px;
}

.comment-head b {
  font-size: 12.5px;
  color: var(--pms-text);
}

.comment-head span {
  font-size: 11.5px;
  color: var(--pms-text-3);
}

.comment-main p {
  margin: 3px 0 0;
  font-size: 13px;
  line-height: 1.65;
  color: var(--pms-text-2);
  white-space: pre-wrap;
  word-break: break-word;
}

.comment-editor {
  display: flex;
  align-items: flex-end;
  gap: 8px;
  margin-top: 12px;
}

.comment-editor :deep(.el-textarea) {
  flex: 1;
}

@media (max-width: 900px) {
  .stats-body {
    grid-template-columns: 1fr;
  }

  .trend {
    height: 70px;
  }
}

@media (max-width: 768px) {
  .page-head .head-ops {
    width: 100%;
    margin-left: 0;
    justify-content: flex-end;
  }

  .kpi-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .filter-row > * {
    flex: 1 1 100%;
    min-width: 0;
  }

  .filter-row :deep(.f-range),
  .filter-row :deep(.f-project),
  .filter-row :deep(.f-status),
  .filter-row :deep(.f-keyword) {
    flex: 1 1 100%;
    min-width: 0;
  }

  .filter-actions {
    width: 100%;
    margin-left: 0;
    justify-content: flex-end;
  }

  .form-grid {
    grid-template-columns: 1fr;
  }

  .field.span-2 {
    grid-column: auto;
  }

  .metrics {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .drawer-body,
  .detail {
    padding: 4px 14px 20px;
  }

  .form-footer .footer-tip {
    width: 100%;
  }

  .form-footer .footer-spacer {
    display: none;
  }

  .form-footer > .el-button,
  .form-footer > .el-button + .el-button {
    flex: 1;
    margin-left: 0;
  }

  .pager {
    justify-content: center;
  }

  .project-bar {
    grid-template-columns: 96px minmax(0, 1fr) 56px;
  }
}
</style>
