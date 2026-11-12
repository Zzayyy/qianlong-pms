<script setup lang="ts">
defineOptions({ name: 'ProjectsPage' })
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus } from 'lucide-vue-next'
import {
  addMember,
  approveProject,
  baselineDetail,
  changeProjectPm,
  changeProjectStatus,
  changeRiskStatus,
  createMilestone,
  createProject,
  createRisk,
  createStage,
  createTask,
  deleteMilestone,
  deleteProjectFile,
  deleteRisk,
  deleteStage,
  deleteTask,
  deptOptions,
  downloadProjectFile,
  listBaselines,
  listMembers,
  listMilestones,
  listProjects,
  listRisks,
  listStages,
  listTasks,
  milestoneStatus,
  projectAttachments,
  projectDetail,
  projectDirectors,
  rejectProject,
  removeMember,
  setProjectDirectors,
  stageStatus,
  submitProject,
  updateMilestone,
  updateRisk,
  updateStage,
  updateTask,
  updateTaskProgress,
  uploadProjectFile,
  userOptions
} from '@/api'
import ChangeBoard from '@/components/ChangeBoard.vue'
import { useUserStore } from '@/stores/user'
import { useKeepAliveRefresh } from '@/utils/keepAlive'
import {
  ASSIGNABLE_MEMBER_ROLE,
  BASELINE_TYPE,
  HEALTH_KEY,
  HEALTH_STATUS,
  MEMBER_ROLE,
  MILESTONE_STATUS,
  NODE_STATUS,
  PRIORITY,
  PROJECT_STATUS,
  RISK_LEVEL,
  RISK_STATUS,
  RISK_TYPE,
  dictOf
} from '@/utils/dict'

const store = useUserStore()
const rows = ref<any[]>([])
const total = ref(0)
const page = ref({ pageNum: 1, pageSize: 10 })
const keyword = ref('')
const deptFilter = ref('')
const pmFilter = ref('')
const healthFilter = ref('')
const loading = ref(false)

/* 组织基础数据：部门与人员（用于下拉选择） */
const depts = ref<any[]>([])
const users = ref<any[]>([])
const canEdit = computed(() => store.has('project:edit'))
const canCreateProject = computed(() => store.has('project:create'))
const canApproveProject = computed(() => store.has('project:approve'))
const canUploadDoc = computed(() => store.has('project:doc:upload'))
const canManageDoc = computed(() => store.has('project:doc:manage'))
const canReportProgress = computed(() => store.has('project:task:progress'))

/**
 * 任务进度上报权限：项目维护者（project:edit）可改全部；
 * 其他角色凭 `project:task:progress` 只能改自己负责的任务（后端同样校验）。
 */
const canProgressTask = (row: any) => {
  if (canEdit.value) return true
  if (!canReportProgress.value) return false
  const me = String(store.profile?.id || '')
  return Boolean(me) && String(row?.ownerId || '') === me
}
const isNarrow = ref(false)
const syncWidth = () => {
  isNarrow.value = window.innerWidth <= 768
}

/** 雪花 ID 超出 JS 安全整数（后端以字符串返回），一律按字符串比较与透传。 */
const userName = (id: string | number) => {
  const hit = users.value.find((item) => String(item.id) === String(id))
  return hit ? hit.realName : String(id || '—')
}

const money = (value: unknown) => {
  const amount = Number(value || 0)
  return amount >= 10000 ? `${Math.round(amount / 1000) / 10} 万` : amount.toLocaleString()
}

/** 状态编码 → 文案/颜色统一走 `@/utils/dict`，避免页面出现 NOT_STARTED 这类裸编码。 */
const statusMeta = (code: string) => dictOf(PROJECT_STATUS, code)
const healthMeta = (code: string) => ({
  label: dictOf(HEALTH_STATUS, code).label,
  key: HEALTH_KEY[String(code || '')] || 'green'
})

const progressWidth = (row: any) => `${Math.min(Math.max(Number(row.progress || 0), 0), 100)}%`

/* 状态页签：分组值以逗号传给后端，避免一屏堆满筛选器 */
const TABS = [
  { key: 'ALL', label: '全部', status: '' },
  { key: 'DRAFT', label: '草稿', status: 'DRAFT' },
  { key: 'APPROVING', label: '审批中', status: 'APPROVING' },
  { key: 'RUNNING', label: '进行中', status: 'APPROVED,IN_PROGRESS,SUSPENDED' },
  { key: 'DONE', label: '已完成', status: 'COMPLETED,ACCEPTED' },
  { key: 'ENDED', label: '已结束', status: 'CLOSED,TERMINATED' }
]
const tab = ref('ALL')
const activeStatus = computed(() => TABS.find((item) => item.key === tab.value)?.status || '')

const createVisible = ref(false)
const createForm = ref<any>({
  projectName: '',
  deptId: '',
  pmId: '',
  contractAmount: 0,
  planStart: '',
  planEnd: '',
  memberIds: [] as string[]
})

const detailVisible = ref(false)
const detail = ref<any>({})
/** 详情页签（打开时重置为「成员」，便于新建项目后连续补人、补节点）。 */
const activeTab = ref('team')
const stages = ref<any[]>([])
const tasks = ref<any[]>([])
const milestones = ref<any[]>([])
const members = ref<any[]>([])
const newPmId = ref('')
const addMemberId = ref<string | null>(null)
const addMemberRole = ref('MEMBER')

/* 项目节点与文档 */
const canManageStage = computed(() => store.has('project:stage:edit'))
/** 当前用户是否本项目的项目经理 / PMO（由详情接口下发，避免点了才报 40301）。 */
const canManage = computed(() => Boolean(detail.value.canManage))
/** 阶段 / 里程碑既要有功能权限，也要是本项目管理者。 */
const canManageNode = computed(() => canManageStage.value && canManage.value)
const isOwner = computed(
  () => String(detail.value.pmId || '') === String(store.profile?.id || '')
)
const directors = ref<any[]>([])
const directorIds = ref<string[]>([])
const docs = ref<any[]>([])
const docFilter = ref('')
const docKeyword = ref('')
const docUploadTarget = ref<'PROJECT' | 'STAGE' | 'MILESTONE' | 'OTHER'>('PROJECT')
const docUploadBizId = ref('')
const uploading = ref(false)
const stageVisible = ref(false)
const stageForm = ref<any>({ id: '', stageName: '', weight: 1, seq: 1, planStart: '', planEnd: '' })

const loadNodeData = async () => {
  directors.value = await projectDirectors(detail.value.id)
  directorIds.value = directors.value.map((item: any) => String(item.userId))
  docs.value = await projectAttachments(detail.value.id)
}

/* ------------------------------ 风险与问题 ------------------------------ */
const risks = ref<any[]>([])
const riskFilter = ref('')
const riskVisible = ref(false)
const riskForm = ref<any>({
  id: '',
  riskType: 'RISK',
  title: '',
  description: '',
  level: 'MEDIUM',
  probability: 50,
  impact: '',
  strategy: '',
  ownerId: '',
  dueDate: ''
})
/** 风险登记与节点维护同权：project:edit + 本项目管理权。 */
const canManageRisk = computed(() => canEdit.value && canManage.value)
const RISK_TABS = computed(() => [
  { key: '', label: '全部', count: risks.value.length },
  { key: 'RISK', label: '风险', count: risks.value.filter((r) => r.riskType === 'RISK').length },
  { key: 'ISSUE', label: '问题', count: risks.value.filter((r) => r.riskType === 'ISSUE').length },
  { key: 'CLOSED', label: '已关闭', count: risks.value.filter((r) => r.status === 'CLOSED').length }
])
const filteredRisks = computed(() =>
  risks.value.filter((item) => {
    if (!riskFilter.value) return true
    if (riskFilter.value === 'CLOSED') return item.status === 'CLOSED'
    return item.riskType === riskFilter.value
  })
)
const openRiskCount = computed(() => risks.value.filter((item) => item.status === 'OPEN').length)

const loadRisks = async () => {
  risks.value = await listRisks(detail.value.id)
}

const openRisk = (row?: any) => {
  riskForm.value = row
    ? {
        id: String(row.id),
        riskType: row.riskType || 'RISK',
        title: row.title,
        description: row.description || '',
        level: row.level || 'MEDIUM',
        probability: Number(row.probability || 0),
        impact: row.impact || '',
        strategy: row.strategy || '',
        ownerId: row.ownerId ? String(row.ownerId) : '',
        dueDate: row.dueDate || ''
      }
    : {
        id: '',
        riskType: riskFilter.value === 'ISSUE' ? 'ISSUE' : 'RISK',
        title: '',
        description: '',
        level: 'MEDIUM',
        probability: 50,
        impact: '',
        strategy: '',
        ownerId: String(store.profile?.id || ''),
        dueDate: ''
      }
  riskVisible.value = true
}

const saveRisk = async () => {
  if (!riskForm.value.title.trim()) {
    ElMessage.warning('请填写风险或问题的标题')
    return
  }
  const payload = {
    riskType: riskForm.value.riskType,
    title: riskForm.value.title.trim(),
    description: riskForm.value.description,
    level: riskForm.value.level,
    probability: Number(riskForm.value.probability || 0),
    impact: riskForm.value.impact,
    strategy: riskForm.value.strategy,
    ownerId: riskForm.value.ownerId || 0,
    // 传空串而非 null，便于后端识别「清空截止日」
    dueDate: riskForm.value.dueDate || ''
  }
  if (riskForm.value.id) {
    await updateRisk(detail.value.id, riskForm.value.id, payload)
  } else {
    await createRisk(detail.value.id, payload)
  }
  riskVisible.value = false
  ElMessage.success(riskForm.value.id ? '已保存' : '已登记')
  await loadRisks()
  // 风险会参与健康度判定（高风险判红、未关闭问题计数），刷新一次
  detail.value = await projectDetail(detail.value.id)
  await load()
}

const toggleRisk = async (row: any) => {
  const closing = row.status !== 'CLOSED'
  if (closing) {
    try {
      await ElMessageBox.confirm(`确认关闭「${row.title}」？关闭后不再计入未关闭风险。`, '关闭风险', {
        type: 'warning',
        confirmButtonText: '关闭',
        cancelButtonText: '取消'
      })
    } catch {
      return
    }
  }
  await changeRiskStatus(detail.value.id, String(row.id), closing ? 'CLOSED' : 'OPEN')
  ElMessage.success(closing ? '已关闭' : '已重新打开')
  await loadRisks()
  detail.value = await projectDetail(detail.value.id)
  await load()
}

const removeRisk = async (row: any) => {
  try {
    await ElMessageBox.confirm(`确认删除「${row.title}」？`, '删除风险', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消'
    })
  } catch {
    return
  }
  await deleteRisk(detail.value.id, String(row.id))
  ElMessage.success('已删除')
  await loadRisks()
  detail.value = await projectDetail(detail.value.id)
  await load()
}

/* ------------------------------ 基线 ------------------------------ */
const baselines = ref<any[]>([])
const baselineListVisible = ref(false)
const baselineVisible = ref(false)
const baselineTitle = ref('')
const baselineContent = ref('')
const baselineLoading = ref(false)

const loadBaselines = async () => {
  baselines.value = await listBaselines(detail.value.id)
}

/** 基线在详情头部以按钮形式入口（不占页签），点开看版本列表。 */
const openBaselineList = async () => {
  baselineListVisible.value = true
  await loadBaselines()
}

const openBaseline = async (row: any) => {
  baselineLoading.value = true
  baselineVisible.value = true
  baselineTitle.value = `${row.version} · ${row.baselineName || '基线快照'}`
  baselineContent.value = ''
  try {
    const data = await baselineDetail(detail.value.id, String(row.id))
    const raw = String(data.content || '')
    try {
      baselineContent.value = JSON.stringify(JSON.parse(raw), null, 2)
    } catch {
      baselineContent.value = raw || '（无快照内容）'
    }
  } finally {
    baselineLoading.value = false
  }
}

/* 项目总监：多选只做「待添加」，已保存的以标签列在下方，保存后清空选择框 */
const directorDraft = ref<string[]>([])
/** 总监姓名：接口已下发 realName，避免没有人员列表权限时把 ID 显示出来。 */
const directorNames = computed(() => {
  const map: Record<string, string> = {}
  directors.value.forEach((item: any) => {
    map[String(item.userId)] = item.realName || ''
  })
  return map
})
const directorName = (userId: string) => directorNames.value[userId] || userName(userId)
const directorOptions = computed(() =>
  users.value.filter((item) => !directorIds.value.includes(String(item.id)))
)
const directorsDirty = computed(
  () =>
    directorDraft.value.length > 0 ||
    [...directorIds.value].sort().join(',') !==
      directors.value.map((item: any) => String(item.userId)).sort().join(',')
)
const removeDirector = (userId: string) => {
  directorIds.value = directorIds.value.filter((item) => item !== userId)
}

const docCount = (stageId: string | number) =>
  docs.value.filter(
    (item) => item.bizType === 'STAGE' && String(item.bizId) === String(stageId)
  ).length

/* ------------------------------ 文档 ------------------------------ */
const DOC_TYPE_LABEL: Record<string, string> = {
  PROJECT: '项目文档',
  STAGE: '阶段文档',
  MILESTONE: '里程碑文档',
  TASK: '任务文档',
  OTHER: '其他'
}
const DOC_TABS = [
  { key: '', label: '全部' },
  { key: 'PROJECT', label: '项目文档' },
  { key: 'STAGE', label: '阶段文档' },
  { key: 'MILESTONE', label: '里程碑文档' },
  { key: 'OTHER', label: '其他' }
]
const docTagType = (bizType: string): 'info' | 'success' | 'warning' | 'primary' => {
  if (bizType === 'PROJECT') return 'info'
  if (bizType === 'STAGE') return 'success'
  if (bizType === 'MILESTONE') return 'warning'
  return 'primary'
}
const docCountOf = (type: string) =>
  type ? docs.value.filter((item) => item.bizType === type).length : docs.value.length

/** 归属节点名称：阶段 / 里程碑被删除时给出兜底文案。 */
const docScopeName = (row: any) => {
  if (row.bizType === 'STAGE') {
    const hit = stages.value.find((item) => String(item.id) === String(row.bizId))
    return hit ? hit.stageName : '阶段已删除'
  }
  if (row.bizType === 'MILESTONE') {
    const hit = milestones.value.find((item) => String(item.id) === String(row.bizId))
    return hit ? hit.milestoneName : '里程碑已删除'
  }
  return ''
}

const filteredDocs = computed(() => {
  const keyword = docKeyword.value.trim().toLowerCase()
  return docs.value.filter((item) => {
    if (docFilter.value && item.bizType !== docFilter.value) return false
    if (!keyword) return true
    const name = String(item.fileName || '').toLowerCase()
    const uploader = String(item.uploader || '').toLowerCase()
    return name.includes(keyword) || uploader.includes(keyword)
  })
})

const docTotalSize = computed(() =>
  filteredDocs.value.reduce((sum, item) => sum + Number(item.size || 0), 0)
)

const formatSize = (bytes: unknown) => {
  const size = Number(bytes || 0)
  if (size <= 0) return '0 KB'
  if (size < 1024 * 1024) return `${Math.max(Math.round(size / 102.4) / 10, 0.1)} KB`
  return `${Math.round(size / 104857.6) / 10} MB`
}

const docExt = (fileName: string) => {
  const parts = String(fileName || '').split('.')
  return parts.length > 1 ? parts[parts.length - 1].toUpperCase().slice(0, 4) : 'FILE'
}

/** `YYYY-MM-DD` → Date，供日期选择器的 default-value 定位到对应月份。 */
const toDate = (iso?: string): Date | undefined => {
  if (!iso) return undefined
  const date = new Date(`${iso}T00:00:00`)
  return Number.isNaN(date.getTime()) ? undefined : date
}

/** 日期 +1 天（用于「接着上一阶段排期」的建议值）。 */
const nextDayText = (iso: string) => {
  if (!iso) return ''
  const date = new Date(`${iso}T00:00:00`)
  if (Number.isNaN(date.getTime())) return ''
  date.setDate(date.getDate() + 1)
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${date.getFullYear()}-${month}-${day}`
}

/** 新增阶段时参考上一个阶段：默认从上一阶段结束的次日开始。 */
const lastStage = computed(() =>
  [...stages.value].sort((a, b) => Number(a.seq || 0) - Number(b.seq || 0)).at(-1)
)

const stageReference = computed(() => {
  if (stageForm.value.id) return ''
  const prev = lastStage.value
  if (!prev) {
    return detail.value.planStart
      ? `项目计划开始于 ${detail.value.planStart}，可直接沿用`
      : '尚未有阶段，可先按项目计划起点排期'
  }
  if (!prev.planStart && !prev.planEnd) {
    return `上一阶段「${prev.stageName}」尚未排期，建议先补上它的计划起止`
  }
  const range = `${prev.planStart || '—'} ~ ${prev.planEnd || '—'}`
  const suggest = nextDayText(prev.planEnd || '')
  return `上一阶段「${prev.stageName}」${range}${suggest ? `，建议本阶段从 ${suggest} 开始` : ''}`
})

const openStage = (row?: any) => {
  if (row) {
    stageForm.value = {
      id: row.id,
      stageName: row.stageName,
      weight: Number(row.weight || 1),
      seq: Number(row.seq || 1),
      planStart: row.planStart || '',
      planEnd: row.planEnd || ''
    }
  } else {
    // 新建：默认接在上一阶段结束的次日，避免不知道从哪天开始
    const prev = lastStage.value
    stageForm.value = {
      id: '',
      stageName: '',
      weight: 1,
      seq: stages.value.length + 1,
      planStart: prev?.planEnd ? nextDayText(prev.planEnd) : detail.value.planStart || '',
      planEnd: ''
    }
  }
  stageVisible.value = true
}

/** 起止跨度（含头含尾）。 */
const daySpan = (start?: string, end?: string) => {
  if (!start || !end) return ''
  const days = (new Date(end).getTime() - new Date(start).getTime()) / 86400000
  return `${Math.round(days) + 1} 天`
}

/** 里程碑逾期天数：未达成且计划日已过。 */
const overdueDays = (row: any) => {
  if (!row?.planDate || row.status === 'REACHED') return 0
  const plan = new Date(`${row.planDate}T00:00:00`).getTime()
  const today = new Date(new Date().toDateString()).getTime()
  if (Number.isNaN(plan) || plan >= today) return 0
  return Math.round((today - plan) / 86400000)
}

/** 把上一阶段结束的次日填入计划开始，并给出明确反馈。 */
const applySuggestedStart = () => {
  const suggest = nextDayText(lastStage.value?.planEnd || '')
  if (!suggest) {
    ElMessage.info('上一阶段还没有计划结束日期，请先补全或手动选择')
    return
  }
  stageForm.value.planStart = suggest
  ElMessage.success(`已填入建议开始日 ${suggest}`)
}

const saveStage = async () => {
  if (!stageForm.value.stageName.trim()) {
    ElMessage.warning('请填写阶段名称')
    return
  }
  if (stageForm.value.planStart && stageForm.value.planEnd && stageForm.value.planEnd < stageForm.value.planStart) {
    ElMessage.warning('计划结束不能早于计划开始')
    return
  }
  const payload = {
    stageName: stageForm.value.stageName,
    weight: Number(stageForm.value.weight || 0),
    seq: Number(stageForm.value.seq || 1),
    planStart: stageForm.value.planStart || null,
    planEnd: stageForm.value.planEnd || null
  }
  if (stageForm.value.id) {
    await updateStage(detail.value.id, stageForm.value.id, payload)
  } else {
    await createStage(detail.value.id, payload)
  }
  stageVisible.value = false
  ElMessage.success('阶段已保存')
  stages.value = await listStages(detail.value.id)
}

const startStage = async (row: any) => {
  await stageStatus(detail.value.id, row.id, 'IN_PROGRESS')
  stages.value = await listStages(detail.value.id)
}

const finishStage = async (row: any) => {
  await stageStatus(detail.value.id, row.id, 'DONE')
  ElMessage.success('阶段已完成')
  stages.value = await listStages(detail.value.id)
  detail.value = await projectDetail(detail.value.id)
}

const removeStage = async (row: any) => {
  await ElMessageBox.confirm(`确认删除阶段「${row.stageName}」？`, '提示', { type: 'warning' })
  await deleteStage(detail.value.id, row.id)
  ElMessage.success('阶段已删除')
  stages.value = await listStages(detail.value.id)
}

const achieveMilestone = async (row: any) => {
  await milestoneStatus(detail.value.id, row.id, 'REACHED')
  milestones.value = await listMilestones(detail.value.id)
}

const removeMilestone = async (row: any) => {
  await ElMessageBox.confirm(`确认删除里程碑「${row.milestoneName}」？`, '提示', { type: 'warning' })
  await deleteMilestone(detail.value.id, row.id)
  milestones.value = await listMilestones(detail.value.id)
}

const saveDirectors = async () => {
  const next = Array.from(new Set([...directorIds.value, ...directorDraft.value]))
  await setProjectDirectors(detail.value.id, next)
  ElMessage.success('项目总监已保存，成员已同步，本项目变更将由其会签')
  directorDraft.value = []
  await loadNodeData()
  // 总监会自动入组/退组，这里同步刷新成员列表，避免停留在旧数据
  members.value = await listMembers(detail.value.id)
}

/** el-upload 自定义上传：统一走 `/files`，成功后刷新列表。 */
const doUpload = async (options: any) => {
  if (!canUploadDoc.value) {
    ElMessage.warning('当前账号无文档上传权限')
    return
  }
  if (!['PROJECT', 'OTHER'].includes(docUploadTarget.value) && !docUploadBizId.value) {
    ElMessage.warning(`请先选择${docUploadTarget.value === 'STAGE' ? '所属阶段' : '所属里程碑'}`)
    return
  }
  uploading.value = true
  try {
    const form = new FormData()
    form.append('file', options.file)
    form.append('projectId', String(detail.value.id))
    form.append('bizType', docUploadTarget.value)
    form.append('bizId', String(docUploadBizId.value || 0))
    await uploadProjectFile(form)
    ElMessage.success('文档已上传')
    docs.value = await projectAttachments(detail.value.id)
    options.onSuccess?.({})
  } catch (error) {
    options.onError?.(error)
  } finally {
    uploading.value = false
  }
}

const downloadDoc = async (row: any) => {
  await downloadProjectFile(String(row.fileId), row.fileName)
}

const removeDoc = async (row: any) => {
  await ElMessageBox.confirm(`确认删除文档「${row.fileName}」？`, '提示', { type: 'warning' })
  await deleteProjectFile(String(row.fileId))
  ElMessage.success('文档已删除')
  docs.value = await projectAttachments(detail.value.id)
}

const load = async () => {
  loading.value = true
  try {
    const data = await listProjects({
      pageNum: page.value.pageNum,
      pageSize: page.value.pageSize,
      keyword: keyword.value.trim() || undefined,
      status: activeStatus.value || undefined,
      deptId: deptFilter.value || undefined,
      pmId: pmFilter.value || undefined,
      health: healthFilter.value || undefined
    })
    rows.value = data.list || []
    total.value = data.total || 0
    markLoaded()
  } finally {
    loading.value = false
  }
}

const { markLoaded } = useKeepAliveRefresh(load)

const search = () => {
  page.value.pageNum = 1
  load()
}

const switchTab = (key: string) => {
  if (tab.value === key) return
  tab.value = key
  search()
}

const resetFilters = () => {
  keyword.value = ''
  deptFilter.value = ''
  pmFilter.value = ''
  healthFilter.value = ''
  tab.value = 'ALL'
  search()
}

const refreshAll = async () => {
  await load()
  if (detailVisible.value && detail.value.id) {
    detail.value = await projectDetail(detail.value.id)
    stages.value = await listStages(detail.value.id)
    tasks.value = await listTasks(detail.value.id)
    milestones.value = await listMilestones(detail.value.id)
    members.value = await listMembers(detail.value.id)
    await loadNodeData()
    await loadRisks()
    await loadBaselines()
  }
}

const loadBase = async () => {
  depts.value = ((await deptOptions()) || []) as any[]
  try {
    users.value = ((await userOptions()) || []) as any[]
  } catch {
    users.value = []
  }
}

const openCreate = () => {
  createForm.value = {
    projectName: '',
    deptId: store.profile?.deptId || depts.value[0]?.id || 0,
    pmId: store.profile?.id || 0,
    contractAmount: 0,
    planStart: '',
    planEnd: '',
    memberIds: store.profile?.id ? [store.profile.id] : []
  }
  createVisible.value = true
}

const doCreate = async () => {
  if (!createForm.value.projectName.trim()) {
    ElMessage.warning('请填写项目名称')
    return
  }
  const memberIds: string[] = createForm.value.memberIds || []
  const result = await createProject({
    projectName: createForm.value.projectName,
    deptId: createForm.value.deptId,
    pmId: createForm.value.pmId,
    contractAmount: createForm.value.contractAmount,
    planStart: createForm.value.planStart || null,
    planEnd: createForm.value.planEnd || null,
    // 立项即带入项目组成员；负责人会自动入组，重复会被忽略
    members: memberIds.map((userId) => ({ userId, roleInProject: 'MEMBER' }))
  })
  createVisible.value = false
  ElMessage.success(`项目已创建：${result.projectCode}`)
  page.value.pageNum = 1
  await load()
  // 新建后直接进入详情，省掉「再找到这条记录点进去」的一步
  await openDetail({ id: result.id })
}

const openDetail = async (row: any) => {
  detail.value = await projectDetail(row.id)
  activeTab.value = 'team'
  newPmId.value = String(detail.value.pmId || '')
  addMemberId.value = null
  stages.value = await listStages(row.id)
  tasks.value = await listTasks(row.id)
  milestones.value = await listMilestones(row.id)
  members.value = await listMembers(row.id)
  await loadNodeData()
  riskFilter.value = ''
  await loadRisks()
  await loadBaselines()
  detailVisible.value = true
}

const refreshDetail = async () => {
  detail.value = await projectDetail(detail.value.id)
  members.value = await listMembers(detail.value.id)
  newPmId.value = String(detail.value.pmId || '')
}

const doChangePm = async () => {
  await changeProjectPm(detail.value.id, newPmId.value)
  ElMessage.success('负责人已变更')
  await refreshDetail()
  await load()
}

const claimProject = async () => {
  await changeProjectPm(detail.value.id, String(store.profile?.id || ''))
  ElMessage.success('已认领为自己的项目')
  await refreshDetail()
  await load()
}

const doAddMember = async () => {
  if (!addMemberId.value) {
    ElMessage.warning('请先选择人员')
    return
  }
  const user = users.value.find((item) => String(item.id) === String(addMemberId.value))
  await addMember(detail.value.id, {
    userId: addMemberId.value,
    deptId: String(user?.deptId || '0'),
    roleInProject: addMemberRole.value
  })
  addMemberId.value = null
  addMemberRole.value = 'MEMBER'
  ElMessage.success('成员已添加')
  await refreshDetail()
}

const doRemoveMember = async (row: any) => {
  const name = row.realName || row.username || '该成员'
  const stillDirector = directors.value.some(
    (item: any) => String(item.userId) === String(row.userId)
  )
  try {
    await ElMessageBox.confirm(
      stillDirector
        ? `「${name}」同时是本项目总监，移出成员后仍保留变更会签权；如需取消请到「项目总监」页签移除。确认移出？`
        : `移出后该成员将无法查看本项目，也不能再填报本项目日志。确认移出「${name}」？`,
      '移出成员',
      { type: 'warning', confirmButtonText: '移出', cancelButtonText: '取消' }
    )
  } catch {
    return
  }
  await removeMember(detail.value.id, row.id)
  ElMessage.success('成员已移出')
  await refreshDetail()
}

const doSubmit = async () => {
  try {
    await ElMessageBox.confirm('提交后进入立项审批，审批期间仍可补充成员与节点。确认提交？', '提交立项审批', {
      type: 'info',
      confirmButtonText: '提交',
      cancelButtonText: '取消'
    })
  } catch {
    return
  }
  await submitProject(detail.value.id)
  ElMessage.success('已提交立项审批')
  detailVisible.value = false
  await load()
}

const doApprove = async () => {
  try {
    await ElMessageBox.confirm('通过后项目立项并冻结初始基线，后续调整需走变更流程。确认通过？', '审批通过', {
      type: 'warning',
      confirmButtonText: '通过',
      cancelButtonText: '取消'
    })
  } catch {
    return
  }
  await approveProject(detail.value.id)
  ElMessage.success('立项已通过并冻结基线')
  detailVisible.value = false
  await load()
}

const doReject = async () => {
  let reason = ''
  try {
    const result = await ElMessageBox.prompt('请填写驳回原因，便于申请人修改后重新提交', '驳回立项', {
      confirmButtonText: '驳回',
      cancelButtonText: '取消',
      inputPlaceholder: '驳回原因（必填）',
      inputValidator: (value: string) => (value && value.trim() ? true : '请填写驳回原因')
    })
    reason = String(result.value || '').trim()
  } catch {
    return
  }
  await rejectProject(detail.value.id, reason)
  ElMessage.success('已驳回')
  detailVisible.value = false
  await load()
}

/** 状态流转的二次确认文案（重启/暂停/完成/验收/关闭都会改项目可见状态，确认一下更稳）。 */
const STATUS_ACTIONS: Record<string, { title: string; tip: string; confirm: string; type: 'warning' | 'info' | 'success' }> = {
  IN_PROGRESS: {
    title: '启动项目',
    tip: '启动后项目进入执行阶段，成员可填报任务与工作日志。',
    confirm: '启动',
    type: 'info'
  },
  SUSPENDED: {
    title: '暂停项目',
    tip: '暂停后任务与工时填报会受影响，确认暂停？',
    confirm: '暂停',
    type: 'warning'
  },
  COMPLETED: {
    title: '标记完成',
    tip: '标记完成后进入验收环节，期间仍可退回进行中。确认项目交付已完成？',
    confirm: '标记完成',
    type: 'warning'
  },
  ACCEPTED: {
    title: '验收通过',
    tip: '验收通过后只能关闭项目或退回进行中，确认验收通过？',
    confirm: '验收通过',
    type: 'success'
  },
  CLOSED: {
    title: '关闭项目',
    tip: '关闭后项目归档，不能再流转。确认关闭？',
    confirm: '关闭',
    type: 'warning'
  }
}

const doStatus = async (status: string) => {
  const action = STATUS_ACTIONS[status]
  if (action) {
    const resuming =
      status === 'IN_PROGRESS' && String(detail.value.status || '') === 'SUSPENDED'
    const reopening =
      status === 'IN_PROGRESS' && String(detail.value.status || '') === 'COMPLETED'
    try {
      await ElMessageBox.confirm(
        resuming ? '恢复后项目回到进行中，继续计入进度与工时。' : reopening ? '重新打开后项目回到进行中，可继续调整节点与任务。' : action.tip,
        resuming ? '恢复项目' : reopening ? '重新打开项目' : action.title,
        {
          type: action.type,
          confirmButtonText: resuming ? '恢复' : reopening ? '重新打开' : action.confirm,
          cancelButtonText: '取消'
        }
      )
    } catch {
      return
    }
  }
  await changeProjectStatus(detail.value.id, status)
  ElMessage.success(`状态已变更为 ${statusMeta(status).label}`)
  await refreshDetail()
  await load()
}

/** 可终止的状态：草稿 / 已立项 / 进行中 / 已暂停（审批中走驳回，完成与验收后走关闭）。 */
const canTerminate = computed(() =>
  ['DRAFT', 'APPROVED', 'IN_PROGRESS', 'SUSPENDED'].includes(String(detail.value.status || ''))
)

/** 终止项目：必填原因，写入 `t_prj_project.terminate_reason`，便于追溯。 */
const doTerminate = async () => {
  let reason = ''
  try {
    const result = await ElMessageBox.prompt(
      '终止后项目归档且不可恢复，成员也不能再填报本项目日志。请填写终止原因，会记录在项目详情中。',
      '终止项目',
      {
        type: 'warning',
        confirmButtonText: '确认终止',
        cancelButtonText: '取消',
        inputType: 'textarea',
        inputPlaceholder: '终止原因（必填）',
        inputValidator: (value: string) => (value && value.trim() ? true : '请填写终止原因')
      }
    )
    reason = String(result.value || '').trim()
  } catch {
    return
  }
  await changeProjectStatus(detail.value.id, 'TERMINATED', reason)
  ElMessage.success('项目已终止')
  await refreshDetail()
  await load()
}

/* 任务：新增 / 编辑 / 删除 / 进度 */
const taskVisible = ref(false)
const taskForm = ref<any>({
  id: '',
  taskName: '',
  stageId: '',
  ownerId: '',
  weight: 1,
  planHours: 8,
  planStart: '',
  planEnd: '',
  priority: 'MEDIUM'
})

/** 某阶段下的任务（`unassigned` 表示未分阶段）。 */
const tasksOfStage = (stageId: string | number) =>
  String(stageId) === 'unassigned'
    ? tasks.value.filter((item) => !item.stageId || String(item.stageId) === '0')
    : tasks.value.filter((item) => String(item.stageId) === String(stageId))

/** 「计划」页签的行：阶段 + 可选的「未分阶段」聚合行。 */
const stageRows = computed(() => {
  const rows: any[] = stages.value.map((item) => ({ ...item }))
  if (tasksOfStage('unassigned').length) {
    rows.push({ id: 'unassigned', stageName: '未分阶段', __pseudo: true })
  }
  return rows
})

/** 阶段 + 任务拍平成树形行（el-table tree-props），避免「表格里再套一张表」。 */
const planTree = computed(() =>
  stageRows.value.map((stage) => ({
    ...stage,
    __key: stage.__pseudo ? 'unassigned' : `s${stage.id}`,
    __kind: stage.__pseudo ? 'pseudo' : 'stage',
    children: tasksOfStage(stage.id).map((task: any) => ({
      ...task,
      __key: `t${task.id}`,
      __kind: 'task'
    }))
  }))
)

/** 阶段行显示其下任务的工时合计（计划 / 实际）。 */
const stageHours = (row: any) => {
  const items = tasksOfStage(row.id)
  return {
    plan: Math.round(items.reduce((sum, task) => sum + Number(task.planHours || 0), 0)),
    actual: Math.round(items.reduce((sum, task) => sum + Number(task.actualHours || 0), 0))
  }
}

/** 树形行斑马区分：阶段行深一档，任务行浅一档。 */
const planRowClass = ({ row }: any) => (row.__kind === 'task' ? 'plan-row-task' : 'plan-row-stage')

/* 展开/收起全部：受控 expand-row-keys，只有「有任务」的阶段参与 */
const expandKeys = ref<string[]>([])
const expandableKeys = computed(() =>
  planTree.value.filter((row) => (row.children?.length ?? 0) > 0).map((row) => row.__key)
)
const allExpanded = computed(
  () => expandableKeys.value.length > 0 && expandKeys.value.length === expandableKeys.value.length
)
const toggleExpandAll = () => {
  expandKeys.value = allExpanded.value ? [] : [...expandableKeys.value]
}
/** 树形表的 expand-change 回传当前展开行数组；单行展开事件回传 boolean，忽略即可。 */
const onExpandChange = (_row: any, expanded: any) => {
  if (!Array.isArray(expanded)) return
  expandKeys.value = expanded.map((item: any) => item.__key)
}
// 数据变化（新增任务、调整进度等）后保持「全展开」，避免刷新后行被折叠
watch(
  () => planTree.value,
  () => {
    expandKeys.value = [...expandableKeys.value]
  },
  { immediate: true }
)


const openTask = (row?: any, presetStageId?: string) => {
  taskForm.value = row
    ? {
        id: String(row.id),
        taskName: row.taskName,
        stageId: row.stageId ? String(row.stageId) : '',
        ownerId: row.ownerId ? String(row.ownerId) : '',
        weight: Number(row.weight || 0),
        planHours: Number(row.planHours || 0),
        planStart: row.planStart || '',
        planEnd: row.planEnd || '',
        priority: row.priority || 'MEDIUM'
      }
    : {
        id: '',
        taskName: '',
        stageId: presetStageId && presetStageId !== 'unassigned'
          ? presetStageId
          : stages.value[0]
            ? String(stages.value[0].id)
            : '',
        ownerId: String(store.profile?.id || ''),
        weight: 1,
        planHours: 8,
        planStart: detail.value.planStart || '',
        planEnd: detail.value.planEnd || '',
        priority: 'MEDIUM'
      }
  taskVisible.value = true
}

const saveTask = async () => {
  if (!taskForm.value.taskName.trim()) {
    ElMessage.warning('请填写任务名称')
    return
  }
  const payload = {
    taskName: taskForm.value.taskName.trim(),
    stageId: taskForm.value.stageId || 0,
    ownerId: taskForm.value.ownerId || 0,
    weight: Number(taskForm.value.weight || 0),
    planHours: Number(taskForm.value.planHours || 0),
    planStart: taskForm.value.planStart || '',
    planEnd: taskForm.value.planEnd || '',
    priority: taskForm.value.priority
  }
  if (taskForm.value.id) {
    await updateTask(detail.value.id, taskForm.value.id, payload)
  } else {
    await createTask(detail.value.id, payload)
  }
  taskVisible.value = false
  ElMessage.success(taskForm.value.id ? '任务已保存' : '任务已创建')
  await refreshTaskTree()
}

/** 任务变更后同时刷新任务与阶段：阶段进度/状态由后端级联重算。 */
const refreshTaskTree = async () => {
  tasks.value = await listTasks(detail.value.id)
  stages.value = await listStages(detail.value.id)
  detail.value = await projectDetail(detail.value.id)
}

const removeTask = async (row: any) => {
  await ElMessageBox.confirm(`确认删除任务「${row.taskName}」？`, '提示', { type: 'warning' })
  await deleteTask(detail.value.id, String(row.id))
  ElMessage.success('任务已删除')
  await refreshTaskTree()
}

const setTaskProgress = async (row: any, value: number) => {
  if (Number(row.progress || 0) === value) return
  await updateTaskProgress(detail.value.id, String(row.id), value)
  await refreshTaskTree()
}

/* 里程碑：新增 / 编辑 / 达成 / 删除 */
const milestoneVisible = ref(false)
const milestoneForm = ref<any>({ id: '', milestoneName: '', planDate: '', ownerId: '' })

const openMilestone = (row?: any) => {
  milestoneForm.value = row
    ? {
        id: String(row.id),
        milestoneName: row.milestoneName,
        planDate: row.planDate || '',
        ownerId: row.ownerId ? String(row.ownerId) : ''
      }
    : {
        id: '',
        milestoneName: '',
        planDate: detail.value.planEnd || '',
        ownerId: String(store.profile?.id || '')
      }
  milestoneVisible.value = true
}

const saveMilestone = async () => {
  if (!milestoneForm.value.milestoneName.trim()) {
    ElMessage.warning('请填写里程碑名称')
    return
  }
  if (!milestoneForm.value.planDate) {
    ElMessage.warning('请选择计划日期')
    return
  }
  const payload = {
    milestoneName: milestoneForm.value.milestoneName.trim(),
    planDate: milestoneForm.value.planDate,
    ownerId: milestoneForm.value.ownerId || 0
  }
  if (milestoneForm.value.id) {
    await updateMilestone(detail.value.id, milestoneForm.value.id, payload)
  } else {
    await createMilestone(detail.value.id, payload)
  }
  milestoneVisible.value = false
  ElMessage.success(milestoneForm.value.id ? '里程碑已保存' : '里程碑已创建')
  milestones.value = await listMilestones(detail.value.id)
}

onMounted(async () => {
  syncWidth()
  window.addEventListener('resize', syncWidth)
  await loadBase()
  await load()
})

onUnmounted(() => window.removeEventListener('resize', syncWidth))
</script>

<template>
  <div class="pms-page">
    <div class="pms-card list-card">
      <div class="list-head">
        <div class="seg">
          <button
            v-for="item in TABS"
            :key="item.key"
            type="button"
            :class="{ 'is-active': tab === item.key }"
            @click="switchTab(item.key)"
          >
            {{ item.label }}
          </button>
        </div>
        <div class="list-side">
          <span class="list-total">共 {{ total }} 个项目</span>
          <el-button size="small" :loading="loading" @click="refreshAll">刷新</el-button>
          <el-button
            v-if="canCreateProject"
            type="primary"
            :icon="Plus"
            class="pms-create-btn"
            @click="openCreate"
          >
            新建项目
          </el-button>
        </div>
      </div>

      <div class="filter-row">
        <el-input
          v-model="keyword"
          class="f-keyword"
          placeholder="搜索项目名称 / 编号"
          clearable
          @keyup.enter="search"
          @clear="search"
        />
        <el-select v-model="deptFilter" class="f-dept" placeholder="全部部门" clearable filterable>
          <el-option v-for="dept in depts" :key="dept.id" :label="dept.deptName" :value="dept.id" />
        </el-select>
        <el-select v-model="pmFilter" class="f-pm" placeholder="全部负责人" clearable filterable>
          <el-option
            v-for="user in users"
            :key="user.id"
            :label="`${user.realName}（${user.username}）`"
            :value="user.id"
          />
        </el-select>
        <el-select v-model="healthFilter" class="f-health" placeholder="全部健康度" clearable>
          <el-option
            v-for="(item, code) in HEALTH_STATUS"
            :key="code"
            :label="item.label"
            :value="code"
          />
        </el-select>
        <div class="filter-actions">
          <el-button type="primary" :loading="loading" @click="search">查询</el-button>
          <el-button @click="resetFilters">重置</el-button>
        </div>
      </div>

      <el-table v-loading="loading" :data="rows" size="small" @row-click="openDetail">
        <el-table-column label="项目" min-width="200">
          <template #default="{ row }">
            <div class="cell-main">{{ row.projectName }}</div>
            <div class="cell-sub">{{ row.projectCode }}</div>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag size="small" :type="statusMeta(row.status).type">
              {{ statusMeta(row.status).label }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="健康度" width="92">
          <template #default="{ row }">
            <span class="health" :class="`is-${healthMeta(row.health).key}`">
              <i></i>{{ healthMeta(row.health).label }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="进度" width="150">
          <template #default="{ row }">
            <div class="progress-cell">
              <span class="progress-track">
                <span class="progress-fill" :style="{ width: progressWidth(row) }"></span>
              </span>
              <b>{{ Math.round(Number(row.progress || 0)) }}%</b>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="负责人" width="110" class-name="pms-mobile-hide">
          <template #default="{ row }">{{ row.pmName || userName(row.pmId) }}</template>
        </el-table-column>
        <el-table-column label="计划周期" width="190" class-name="pms-mobile-hide">
          <template #default="{ row }">{{ row.planStart || '—' }} ~ {{ row.planEnd || '—' }}</template>
        </el-table-column>
        <el-table-column label="合同额" width="110" align="right" class-name="pms-mobile-hide">
          <template #default="{ row }">
            <span class="num-cell">{{ money(row.contractAmount) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="84">
          <template #default="{ row }">
            <el-button link type="primary" @click.stop="openDetail(row)">详情</el-button>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty description="还没有项目，点右上角「新建项目」开始" :image-size="76" />
        </template>
      </el-table>

      <el-pagination
        v-model:current-page="page.pageNum"
        v-model:page-size="page.pageSize"
        :total="total"
        :page-sizes="[10, 20, 50]"
        :layout="isNarrow ? 'prev, pager, next' : 'total, sizes, prev, pager, next'"
        class="pager"
        @current-change="load"
        @size-change="search"
      />
    </div>

    <el-dialog v-model="createVisible" title="新建项目" width="min(780px, 94vw)" align-center :close-on-click-modal="false">
      <div class="dialog-body">
        <p class="form-hint">立项后提交审批并冻结初始基线；审批通过才可启动、填报任务与工作日志。</p>
        <div class="form-grid">
          <div class="field span-2">
            <label>项目名称 <em>*</em></label>
            <el-input v-model="createForm.projectName" maxlength="200" show-word-limit placeholder="如：XX 客户订单系统中台建设" />
          </div>
          <div class="field">
            <label>所属部门 <em>*</em></label>
            <el-select v-model="createForm.deptId" filterable placeholder="选择部门">
              <el-option v-for="dept in depts" :key="dept.id" :label="dept.deptName" :value="dept.id" />
            </el-select>
          </div>
          <div class="field">
            <label>负责人 <em>*</em></label>
            <el-select v-model="createForm.pmId" filterable placeholder="选择负责人">
              <el-option
                v-for="user in users"
                :key="user.id"
                :label="`${user.realName}（${user.username}）`"
                :value="user.id"
              />
            </el-select>
          </div>
          <div class="field span-2">
            <label>项目组成员</label>
            <el-select
              v-model="createForm.memberIds"
              multiple
              filterable
              collapse-tags
              collapse-tags-tooltip
              :max-collapse-tags="4"
              placeholder="可选，负责人会自动入组"
            >
              <el-option
                v-for="user in users"
                :key="user.id"
                :label="`${user.realName}（${user.username}）`"
                :value="user.id"
              />
            </el-select>
          </div>
          <div class="field">
            <label>合同金额（元）</label>
            <el-input-number v-model="createForm.contractAmount" :min="0" :step="1000" />
          </div>
          <div class="field">
            <label>计划开始</label>
            <el-date-picker v-model="createForm.planStart" type="date" value-format="YYYY-MM-DD" placeholder="选择日期" />
          </div>
          <div class="field">
            <label>计划结束</label>
            <el-date-picker v-model="createForm.planEnd" type="date" value-format="YYYY-MM-DD" placeholder="选择日期" />
          </div>
        </div>
      </div>
      <template #footer>
        <div class="drawer-footer">
          <span class="footer-spacer"></span>
          <el-button @click="createVisible = false">取消</el-button>
          <el-button type="primary" @click="doCreate">保存</el-button>
        </div>
      </template>
    </el-dialog>

    <el-drawer v-model="detailVisible" title="项目详情" size="min(1180px, 96vw)">
      <div class="detail">
        <div class="detail-head">
          <div>
            <h3>{{ detail.projectName || '项目详情' }}</h3>
            <p class="detail-meta">
              {{ detail.projectCode }} · 负责人 {{ detail.pmName || userName(detail.pmId) }}
            </p>
          </div>
          <div class="detail-tags">
            <el-tag :type="statusMeta(detail.status).type">{{ statusMeta(detail.status).label }}</el-tag>
            <span class="health" :class="`is-${healthMeta(detail.health).key}`">
              <i></i>{{ healthMeta(detail.health).label }}
            </span>
            <el-button link type="primary" @click="openBaselineList">
              基线 {{ baselines.length }}
            </el-button>
          </div>
        </div>

        <div class="metrics">
          <div class="metric">
            <span>进度</span>
            <b>{{ Math.round(Number(detail.progress || 0)) }}%</b>
          </div>
          <div class="metric">
            <span>计划周期</span>
            <b>{{ detail.planStart || '—' }} ~ {{ detail.planEnd || '—' }}</b>
          </div>
          <div class="metric">
            <span>合同额</span>
            <b>{{ money(detail.contractAmount) }}</b>
          </div>
          <div class="metric">
            <span>健康度</span>
            <b>{{ healthMeta(detail.health).label }}</b>
          </div>
        </div>

        <div class="ops-row">
          <!-- 无 project:edit 的角色（如销售）看不到人员下拉，直接展示负责人姓名 -->
          <template v-if="canEdit">
            <el-select v-model="newPmId" class="ops-select" filterable size="small" placeholder="选择新的负责人">
              <el-option
                v-for="user in users"
                :key="user.id"
                :label="`${user.realName}（${user.username}）`"
                :value="user.id"
              />
            </el-select>
            <el-button size="small" @click="doChangePm">设为负责人</el-button>
            <el-button size="small" :disabled="Boolean(detail.pmId)" @click="claimProject">认领给我</el-button>
          </template>
          <span v-else class="ops-hint">负责人：{{ detail.pmName || userName(detail.pmId) }}</span>
          <span v-if="canEdit && !canManage && !isOwner" class="ops-hint">
            仅项目经理、PMO 或管理员可维护成员、节点与文档状态
          </span>
        </div>

        <el-alert
          v-if="detail.status === 'TERMINATED'"
          class="terminate-alert"
          type="error"
          :closable="false"
          show-icon
          :title="`项目已终止：${detail.terminateReason || '未填写原因'}`"
        />

        <el-tabs v-model="activeTab" style="margin-top: 14px">
          <el-tab-pane label="团队" name="team">
            <div class="block-head">
              <h4>项目总监</h4>
              <span class="block-tip">可多人会签 · 被指派者自动入组并取得变更审核权</span>
            </div>
            <div class="pane-ops">
              <el-select
                v-model="directorDraft"
                class="ops-select wide"
                multiple
                filterable
                collapse-tags
                collapse-tags-tooltip
                :max-collapse-tags="3"
                size="small"
                placeholder="添加项目总监（可多人，一次多选）"
                :disabled="!canEdit || !canManage"
              >
                <el-option
                  v-for="user in directorOptions"
                  :key="user.id"
                  :label="`${user.realName}（${user.username}）`"
                  :value="String(user.id)"
                />
              </el-select>
              <el-button
                size="small"
                type="primary"
                :disabled="!canEdit || !canManage || !directorsDirty"
                @click="saveDirectors"
              >
                保存总监<template v-if="directorDraft.length">（+{{ directorDraft.length }}）</template>
              </el-button>
              <span v-if="directorsDirty" class="ops-hint">有未保存的改动</span>
              <span v-else class="ops-hint">可多人会签 · 被指派者自动入组并取得变更审核权</span>
            </div>

            <div v-if="directorIds.length" class="tag-list">
              <el-tag
                v-for="userId in directorIds"
                :key="userId"
                effect="plain"
                :closable="canEdit && canManage"
                @close="removeDirector(userId)"
              >
                {{ directorName(userId) }}
              </el-tag>
            </div>
            <div v-else class="tag-list">
              <span class="empty-tip">尚未指派：未指派时本项目无法提交变更评估</span>
            </div>

            <div class="block-head block-head-gap">
              <h4>项目成员</h4>
              <span class="block-tip">项目经理角色通过上方「设为负责人」转移，不在成员里指派</span>
            </div>
            <div class="pane-ops">
              <el-select
                v-model="addMemberId"
                class="ops-select"
                filterable
                clearable
                size="small"
                placeholder="选择要加入的人员"
              >
                <el-option
                  v-for="user in users"
                  :key="user.id"
                  :label="`${user.realName}（${user.username}）`"
                  :value="user.id"
                />
              </el-select>
              <el-select v-model="addMemberRole" class="ops-select narrow" size="small" placeholder="组内角色">
                <el-option
                  v-for="(label, code) in ASSIGNABLE_MEMBER_ROLE"
                  :key="code"
                  :label="label"
                  :value="code"
                />
              </el-select>
              <el-button size="small" type="primary" :disabled="!canEdit" @click="doAddMember">添加成员</el-button>
            </div>
            <el-table :data="members" size="small" empty-text="暂无成员">
              <el-table-column label="姓名" min-width="130">
                <template #default="{ row }">
                  <span :class="{ muted: row.userMissing }">{{ row.realName || '账号已删除' }}</span>
                </template>
              </el-table-column>
              <el-table-column prop="username" label="账号" min-width="120" class-name="pms-mobile-hide" />
              <el-table-column label="组内角色" width="110">
                <template #default="{ row }">
                  <el-tag size="small" effect="plain" :type="dictOf(MEMBER_ROLE, row.roleInProject).type">
                    {{ dictOf(MEMBER_ROLE, row.roleInProject).label }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column prop="joinDate" label="加入日期" width="120" class-name="pms-mobile-hide" />
              <el-table-column label="操作" width="90">
                <template #default="{ row }">
                  <el-button
                    link
                    type="danger"
                    :disabled="!canEdit || String(row.userId) === String(detail.pmId)"
                    :title="String(row.userId) === String(detail.pmId) ? '项目负责人需先变更负责人' : ''"
                    @click="doRemoveMember(row)"
                  >
                    移出
                  </el-button>
                </template>
              </el-table-column>
            </el-table>
          </el-tab-pane>

          <el-tab-pane label="计划" name="plan">
            <div class="plan-head">
              <div class="plan-title">
                <h4>阶段</h4>
                <span class="count-chip">{{ stages.length }}</span>
                <span class="plan-tip">展开阶段维护任务，进度行内调整会级联重算项目进度</span>
              </div>
              <div class="plan-ops">
                <el-button
                  size="small"
                  text
                  :disabled="!expandableKeys.length"
                  @click="toggleExpandAll"
                >
                  {{ allExpanded ? '收起全部' : '展开全部' }}
                </el-button>
                <el-button size="small" :disabled="!canEdit" @click="openTask()">新增任务</el-button>
                <el-button size="small" type="primary" :disabled="!canManageNode" @click="openStage()">
                  新增阶段
                </el-button>
              </div>
            </div>
            <el-table
              :data="planTree"
              size="small"
              row-key="__key"
              class="plan-table"
              :row-class-name="planRowClass"
              :expand-row-keys="expandKeys"
              :tree-props="{ children: 'children' }"
              @expand-change="onExpandChange"
            >
              <template #empty>
                <el-empty description="还没有阶段，建议按「需求 / 开发 / 测试 / 上线」拆分" :image-size="64">
                  <el-button v-if="canManageNode" size="small" type="primary" @click="openStage()">新增阶段</el-button>
                </el-empty>
              </template>
              <el-table-column label="阶段 / 任务" min-width="300">
                <template #default="{ row }">
                  <div class="plan-name">
                    <span v-if="row.__kind === 'task'" class="plan-bullet"></span>
                    <div class="plan-name-text">
                      <div class="cell-main">
                        {{ row.__kind === 'task' ? row.taskName : row.stageName }}
                      </div>
                      <div class="cell-sub">
                        <template v-if="row.__kind === 'stage'">
                          权重 {{ row.weight }} · 文档 {{ docCount(row.id) }} ·
                          {{ tasksOfStage(row.id).length }} 个任务
                        </template>
                        <template v-else-if="row.__kind === 'pseudo'">未绑定阶段的任务</template>
                        <template v-else>
                          负责人 {{ row.ownerName || userName(row.ownerId) }} ·
                          {{ row.taskCode || '—' }}
                        </template>
                      </div>
                    </div>
                  </div>
                </template>
              </el-table-column>
              <el-table-column label="计划起止" width="230">
                <template #default="{ row }">
                  <div v-if="row.planStart || row.planEnd" class="cell-main num-cell date-range">
                    {{ row.planStart || '—' }} ~ {{ row.planEnd || '—' }}
                    <span v-if="daySpan(row.planStart, row.planEnd)" class="date-span">
                      {{ daySpan(row.planStart, row.planEnd) }}
                    </span>
                  </div>
                  <span v-else class="muted">{{ row.__pseudo ? '—' : '未排期' }}</span>
                </template>
              </el-table-column>
              <el-table-column label="工时(计划/实际)" width="130" align="right">
                <template #default="{ row }">
                  <span v-if="row.__kind === 'task'" class="num-cell">
                    {{ Number(row.planHours || 0) }}h / {{ Number(row.actualHours || 0) }}h
                  </span>
                  <span v-else-if="row.__kind === 'stage'" class="num-cell">
                    {{ stageHours(row).plan }}h / {{ stageHours(row).actual }}h
                  </span>
                  <span v-else class="muted">—</span>
                </template>
              </el-table-column>
              <el-table-column label="进度" width="160">
                <template #default="{ row }">
                  <el-input-number
                    v-if="row.__kind === 'task'"
                    size="small"
                    :min="0"
                    :max="100"
                    :step="5"
                    controls-position="right"
                    :disabled="!canProgressTask(row)"
                    :model-value="Number(row.progress || 0)"
                    @change="(value: any) => setTaskProgress(row, Number(value || 0))"
                  />
                  <div v-else-if="row.__kind === 'stage'" class="progress-cell">
                    <span class="progress-track">
                      <span class="progress-fill" :style="{ width: progressWidth(row) }"></span>
                    </span>
                    <b>{{ Math.round(Number(row.progress || 0)) }}%</b>
                  </div>
                  <span v-else class="muted">—</span>
                </template>
              </el-table-column>
              <el-table-column label="状态" width="100">
                <template #default="{ row }">
                  <el-tag
                    v-if="row.__kind !== 'pseudo'"
                    size="small"
                    effect="plain"
                    :type="dictOf(NODE_STATUS, row.status).type"
                  >
                    {{ dictOf(NODE_STATUS, row.status).label }}
                  </el-tag>
                  <span v-else class="muted">—</span>
                </template>
              </el-table-column>
              <el-table-column label="操作" width="196">
                <template #default="{ row }">
                  <span v-if="row.__kind === 'pseudo'" class="muted">—</span>
                  <div v-else-if="row.__kind === 'stage'" class="ops-cell">
                    <el-button
                      link
                      type="primary"
                      :disabled="!canManageNode || ['IN_PROGRESS', 'DONE'].includes(row.status)"
                      @click="startStage(row)"
                    >
                      开始
                    </el-button>
                    <el-button
                      link
                      type="success"
                      :disabled="!canManageNode || row.status === 'DONE'"
                      @click="finishStage(row)"
                    >
                      完成
                    </el-button>
                    <el-button link type="primary" :disabled="!canManageNode" @click="openStage(row)">
                      编辑
                    </el-button>
                    <el-button link type="danger" :disabled="!canManageNode" @click="removeStage(row)">
                      删除
                    </el-button>
                  </div>
                  <div v-else class="ops-cell">
                    <el-button link type="primary" :disabled="!canEdit" @click="openTask(row)">编辑</el-button>
                    <el-button link type="danger" :disabled="!canEdit" @click="removeTask(row)">删除</el-button>
                  </div>
                </template>
              </el-table-column>
            </el-table>

            <div class="plan-head plan-head-gap">
              <div class="plan-title">
                <h4>里程碑</h4>
                <span class="count-chip">{{ milestones.length }}</span>
                <span class="plan-tip">关键交付节点，达成后记录实际日期</span>
              </div>
              <div class="plan-ops">
                <el-button size="small" type="primary" :disabled="!canManageNode" @click="openMilestone()">
                  新增里程碑
                </el-button>
              </div>
            </div>
            <el-table :data="milestones" size="small" class="plan-table">
              <template #empty>
                <el-empty description="还没有里程碑，用来标注关键交付节点" :image-size="64">
                  <el-button v-if="canManageNode" size="small" type="primary" @click="openMilestone()">
                    新增里程碑
                  </el-button>
                </el-empty>
              </template>
              <el-table-column label="里程碑" min-width="220">
                <template #default="{ row }">
                  <div class="plan-name-text">
                    <div class="cell-main">{{ row.milestoneName }}</div>
                    <div class="cell-sub ms-sub">
                      计划 {{ row.planDate || '—' }}
                      <span v-if="overdueDays(row)" class="overdue">逾期 {{ overdueDays(row) }} 天</span>
                    </div>
                  </div>
                </template>
              </el-table-column>
              <el-table-column label="负责人" width="100">
                <template #default="{ row }">{{ row.ownerName || userName(row.ownerId) }}</template>
              </el-table-column>
              <el-table-column label="达成情况" width="180">
                <template #default="{ row }">
                  <el-tag size="small" effect="plain" :type="dictOf(MILESTONE_STATUS, row.status).type">
                    {{ dictOf(MILESTONE_STATUS, row.status).label }}
                  </el-tag>
                  <span v-if="row.actualDate" class="date-span">{{ row.actualDate }}</span>
                </template>
              </el-table-column>
              <el-table-column label="操作" width="150">
                <template #default="{ row }">
                  <div class="ops-cell">
                    <el-button
                      v-if="row.status !== 'REACHED'"
                      link
                      type="success"
                      :disabled="!canManageNode"
                      @click="achieveMilestone(row)"
                    >
                      达成
                    </el-button>
                    <el-button link type="primary" :disabled="!canManageNode" @click="openMilestone(row)">
                      编辑
                    </el-button>
                    <el-button link type="danger" :disabled="!canManageNode" @click="removeMilestone(row)">
                      删除
                    </el-button>
                  </div>
                </template>
              </el-table-column>
            </el-table>
          </el-tab-pane>

          <el-tab-pane label="风险" name="risks">
            <div class="list-head">
              <div class="seg">
                <button
                  v-for="item in RISK_TABS"
                  :key="item.key"
                  type="button"
                  :class="{ 'is-active': riskFilter === item.key }"
                  @click="riskFilter = item.key"
                >
                  {{ item.label }}<i>{{ item.count }}</i>
                </button>
              </div>
              <div class="list-side">
                <span class="list-total">未关闭 {{ openRiskCount }} 条</span>
                <el-button size="small" type="primary" :disabled="!canManageRisk" @click="openRisk()">
                  登记风险
                </el-button>
              </div>
            </div>
            <el-alert
              v-if="!canManageRisk"
              type="info"
              :closable="false"
              show-icon
              title="仅项目经理 / PMO 可登记与关闭风险，其他成员可查看"
              style="margin-bottom: 10px"
            />
            <el-table :data="filteredRisks" size="small">
              <template #empty>
                <el-empty
                  description="还没有风险或问题：登记后会计入看板「开放风险」与健康度判定"
                  :image-size="64"
                >
                  <el-button v-if="canManageRisk" size="small" type="primary" @click="openRisk()">
                    登记风险
                  </el-button>
                </el-empty>
              </template>
              <el-table-column label="标题" min-width="200">
                <template #default="{ row }">
                  <div class="cell-main">{{ row.title }}</div>
                  <div class="cell-sub">
                    {{ dictOf(RISK_TYPE, row.riskType).label }} · 概率
                    {{ Math.round(Number(row.probability || 0)) }}%
                  </div>
                </template>
              </el-table-column>
              <el-table-column label="等级" width="80">
                <template #default="{ row }">
                  <el-tag size="small" effect="plain" :type="dictOf(RISK_LEVEL, row.level).type">
                    {{ dictOf(RISK_LEVEL, row.level).label }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column label="责任人" width="100">
                <template #default="{ row }">{{ row.ownerName || userName(row.ownerId) }}</template>
              </el-table-column>
              <el-table-column label="截止日" width="118" class-name="pms-mobile-hide">
                <template #default="{ row }">{{ row.dueDate || '—' }}</template>
              </el-table-column>
              <el-table-column label="状态" width="96">
                <template #default="{ row }">
                  <el-tag size="small" effect="plain" :type="dictOf(RISK_STATUS, row.status).type">
                    {{ dictOf(RISK_STATUS, row.status).label }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column label="操作" width="150">
                <template #default="{ row }">
                  <el-button link type="primary" :disabled="!canManageRisk" @click="openRisk(row)">
                    编辑
                  </el-button>
                  <el-button
                    link
                    :type="row.status === 'CLOSED' ? 'primary' : 'success'"
                    :disabled="!canManageRisk"
                    @click="toggleRisk(row)"
                  >
                    {{ row.status === 'CLOSED' ? '重开' : '关闭' }}
                  </el-button>
                  <el-button link type="danger" :disabled="!canManageRisk" @click="removeRisk(row)">
                    删除
                  </el-button>
                </template>
              </el-table-column>
            </el-table>
          </el-tab-pane>

          <el-tab-pane v-if="store.has('change:view')" label="周期变更" name="changes" lazy>
            <ChangeBoard
              :project-id="String(detail.id || '')"
              :project-name="String(detail.projectName || '')"
              embedded
            />
          </el-tab-pane>

          <el-tab-pane label="文档" name="docs">
            <div class="list-head">
              <div class="seg">
                <button
                  v-for="item in DOC_TABS"
                  :key="item.key"
                  type="button"
                  :class="{ 'is-active': docFilter === item.key }"
                  @click="docFilter = item.key"
                >
                  {{ item.label }}<i>{{ docCountOf(item.key) }}</i>
                </button>
              </div>
              <div class="doc-head-side">
                <el-input
                  v-model="docKeyword"
                  class="doc-search"
                  size="small"
                  placeholder="搜索文件名 / 上传人"
                  clearable
                />
                <span class="list-total">
                  {{ filteredDocs.length }} 个文件 · {{ formatSize(docTotalSize) }}
                </span>
              </div>
            </div>

            <div v-if="canUploadDoc" class="upload-panel">
              <div class="upload-fields">
                <div class="field">
                  <label>归属类型</label>
                  <el-select v-model="docUploadTarget" size="small" @change="docUploadBizId = ''">
                    <el-option label="项目文档" value="PROJECT" />
                    <el-option label="阶段文档" value="STAGE" />
                    <el-option label="里程碑文档" value="MILESTONE" />
                    <el-option label="其他" value="OTHER" />
                  </el-select>
                </div>
                <div v-if="docUploadTarget === 'STAGE'" class="field">
                  <label>所属阶段 <em>*</em></label>
                  <el-select v-model="docUploadBizId" size="small" placeholder="选择阶段">
                    <el-option
                      v-for="item in stages"
                      :key="item.id"
                      :label="item.stageName"
                      :value="String(item.id)"
                    />
                  </el-select>
                  <span v-if="!stages.length" class="ops-hint">请先在「阶段」页签新增阶段</span>
                </div>
                <div v-if="docUploadTarget === 'MILESTONE'" class="field">
                  <label>所属里程碑 <em>*</em></label>
                  <el-select v-model="docUploadBizId" size="small" placeholder="选择里程碑">
                    <el-option
                      v-for="item in milestones"
                      :key="item.id"
                      :label="item.milestoneName"
                      :value="String(item.id)"
                    />
                  </el-select>
                  <span v-if="!milestones.length" class="ops-hint">请先在「里程碑」页签新增里程碑</span>
                </div>
              </div>
              <el-upload
                class="doc-drop"
                drag
                action="#"
                :show-file-list="false"
                :disabled="uploading"
                :http-request="doUpload"
              >
                <div v-loading="uploading" class="doc-drop-text">
                  <b>把文件拖到这里，或点击选择</b>
                  <span>单文件 ≤ 20MB；阶段文档是「完成阶段」的前置校验</span>
                </div>
              </el-upload>
            </div>
            <el-alert
              v-else
              type="info"
              :closable="false"
              show-icon
              title="当前账号无文档上传权限，仅可查看与下载"
            />

            <el-table :data="filteredDocs" size="small" style="margin-top: 12px">
              <template #empty>
                <el-empty
                  :description="
                    docKeyword || docFilter ? '没有匹配的文档' : '还没有文档，上传后按项目 / 阶段 / 里程碑归档'
                  "
                  :image-size="64"
                />
              </template>
              <el-table-column label="文件" min-width="260">
                <template #default="{ row }">
                  <div class="doc-cell">
                    <span class="doc-ext">{{ docExt(row.fileName) }}</span>
                    <div class="doc-meta">
                      <div class="cell-main">{{ row.fileName }}</div>
                      <div class="cell-sub">{{ formatSize(row.size) }} · {{ row.mime || '未知类型' }}</div>
                    </div>
                  </div>
                </template>
              </el-table-column>
              <el-table-column label="归属" width="190">
                <template #default="{ row }">
                  <el-tag size="small" effect="plain" :type="docTagType(row.bizType)">
                    {{ DOC_TYPE_LABEL[row.bizType] || row.bizType }}
                  </el-tag>
                  <span v-if="docScopeName(row)" class="doc-scope">{{ docScopeName(row) }}</span>
                </template>
              </el-table-column>
              <el-table-column label="上传人" width="110">
                <template #default="{ row }">{{ row.uploader || '—' }}</template>
              </el-table-column>
              <el-table-column prop="uploadTime" label="上传时间" width="170" class-name="pms-mobile-hide" />
              <el-table-column label="操作" width="120">
                <template #default="{ row }">
                  <el-button link type="primary" @click="downloadDoc(row)">下载</el-button>
                  <el-button link type="danger" :disabled="!canManageDoc" @click="removeDoc(row)">删除</el-button>
                </template>
              </el-table-column>
            </el-table>
          </el-tab-pane>
        </el-tabs>
      </div>
      <template #footer>
        <div class="drawer-footer">
          <el-button
            v-if="detail.status === 'APPROVING' && canApproveProject"
            type="danger"
            link
            @click="doReject"
          >
            驳回
          </el-button>
          <el-button
            v-if="canTerminate && canEdit"
            type="danger"
            plain
            @click="doTerminate"
          >
            终止项目
          </el-button>
          <span class="footer-spacer"></span>
          <el-button v-if="detail.status === 'DRAFT' && canCreateProject" type="primary" @click="doSubmit">
            提交审批
          </el-button>
          <el-button v-if="detail.status === 'APPROVING' && canApproveProject" type="success" @click="doApprove">
            审批通过
          </el-button>
          <el-button v-if="detail.status === 'APPROVED' && canEdit" type="primary" @click="doStatus('IN_PROGRESS')">
            启动项目
          </el-button>
          <el-button
            v-if="detail.status === 'IN_PROGRESS' && canEdit"
            type="warning"
            plain
            @click="doStatus('SUSPENDED')"
          >
            暂停
          </el-button>
          <el-button v-if="detail.status === 'SUSPENDED' && canEdit" type="primary" plain @click="doStatus('IN_PROGRESS')">
            恢复
          </el-button>
          <el-button
            v-if="detail.status === 'IN_PROGRESS' && canEdit"
            type="success"
            @click="doStatus('COMPLETED')"
          >
            完成
          </el-button>
          <el-button v-if="detail.status === 'COMPLETED' && canEdit" @click="doStatus('IN_PROGRESS')">
            重新打开
          </el-button>
          <el-button v-if="detail.status === 'COMPLETED' && canEdit" type="success" @click="doStatus('ACCEPTED')">
            验收
          </el-button>
          <el-button v-if="detail.status === 'ACCEPTED' && canEdit" type="primary" @click="doStatus('CLOSED')">
            关闭项目
          </el-button>
        </div>
      </template>
    </el-drawer>

    <el-dialog v-model="stageVisible" :title="stageForm.id ? '编辑阶段' : '新增阶段'" width="min(560px, 94vw)" align-center>
      <p v-if="stageReference" class="form-hint stage-ref">
        {{ stageReference }}
        <el-button
          v-if="!stageForm.id && lastStage?.planEnd"
          link
          type="primary"
          @click="applySuggestedStart"
        >
          使用建议日期
        </el-button>
      </p>
      <div class="form-grid">
        <div class="field span-2">
          <label>阶段名称 <em>*</em></label>
          <el-input v-model="stageForm.stageName" placeholder="如：需求 / 开发 / 测试 / 上线" />
        </div>
        <div class="field">
          <label>权重</label>
          <el-input-number v-model="stageForm.weight" :min="0" :step="0.1" />
        </div>
        <div class="field">
          <label>顺序</label>
          <el-input-number v-model="stageForm.seq" :min="1" />
        </div>
        <div class="field">
          <label>计划开始</label>
          <el-date-picker
            v-model="stageForm.planStart"
            type="date"
            value-format="YYYY-MM-DD"
            placeholder="选择日期"
            :default-value="toDate(stageForm.planStart)"
          />
        </div>
        <div class="field">
          <label>计划结束</label>
          <!-- 结束日期默认落在计划开始所在月份，省得每次手动翻月 -->
          <el-date-picker
            v-model="stageForm.planEnd"
            type="date"
            value-format="YYYY-MM-DD"
            placeholder="选择日期"
            :default-value="toDate(stageForm.planStart) || toDate(stageForm.planEnd)"
          />
        </div>
      </div>
      <template #footer>
        <el-button @click="stageVisible = false">取消</el-button>
        <el-button type="primary" @click="saveStage">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="taskVisible"
      :title="taskForm.id ? '编辑任务' : '新增任务'"
      width="min(640px, 94vw)"
      align-center
      :close-on-click-modal="false"
    >
      <div class="form-grid">
        <div class="field span-2">
          <label>任务名称 <em>*</em></label>
          <el-input v-model="taskForm.taskName" maxlength="200" show-word-limit placeholder="如：接口联调 / 回归测试" />
        </div>
        <div class="field">
          <label>所属阶段</label>
          <el-select v-model="taskForm.stageId" clearable placeholder="未分阶段">
            <el-option v-for="item in stages" :key="item.id" :label="item.stageName" :value="String(item.id)" />
          </el-select>
        </div>
        <div class="field">
          <label>负责人</label>
          <el-select v-model="taskForm.ownerId" filterable clearable placeholder="选择负责人">
            <el-option
              v-for="user in users"
              :key="user.id"
              :label="`${user.realName}（${user.username}）`"
              :value="String(user.id)"
            />
          </el-select>
        </div>
        <div class="field">
          <label>计划工时（h）</label>
          <el-input-number v-model="taskForm.planHours" :min="0" :step="0.5" />
        </div>
        <div class="field">
          <label>权重</label>
          <el-input-number v-model="taskForm.weight" :min="0" :step="0.1" />
        </div>
        <div class="field">
          <label>优先级</label>
          <el-select v-model="taskForm.priority">
            <el-option label="高" value="HIGH" />
            <el-option label="中" value="MEDIUM" />
            <el-option label="低" value="LOW" />
          </el-select>
        </div>
        <div class="field">
          <label>计划开始</label>
          <el-date-picker
            v-model="taskForm.planStart"
            type="date"
            value-format="YYYY-MM-DD"
            placeholder="选择日期"
            :default-value="toDate(taskForm.planStart)"
          />
        </div>
        <div class="field">
          <label>计划结束</label>
          <el-date-picker
            v-model="taskForm.planEnd"
            type="date"
            value-format="YYYY-MM-DD"
            placeholder="选择日期"
            :default-value="toDate(taskForm.planStart) || toDate(taskForm.planEnd)"
          />
        </div>
      </div>
      <template #footer>
        <el-button @click="taskVisible = false">取消</el-button>
        <el-button type="primary" @click="saveTask">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="milestoneVisible"
      :title="milestoneForm.id ? '编辑里程碑' : '新增里程碑'"
      width="min(560px, 94vw)"
      align-center
      :close-on-click-modal="false"
    >
      <div class="form-grid">
        <div class="field span-2">
          <label>里程碑名称 <em>*</em></label>
          <el-input v-model="milestoneForm.milestoneName" maxlength="128" placeholder="如：需求评审通过 / 提测 / 上线" />
        </div>
        <div class="field">
          <label>计划日期 <em>*</em></label>
          <el-date-picker
            v-model="milestoneForm.planDate"
            type="date"
            value-format="YYYY-MM-DD"
            placeholder="选择日期"
            :default-value="toDate(milestoneForm.planDate) || toDate(detail.planEnd)"
          />
        </div>
        <div class="field">
          <label>负责人</label>
          <el-select v-model="milestoneForm.ownerId" filterable clearable placeholder="选择负责人">
            <el-option
              v-for="user in users"
              :key="user.id"
              :label="`${user.realName}（${user.username}）`"
              :value="String(user.id)"
            />
          </el-select>
        </div>
      </div>
      <template #footer>
        <el-button @click="milestoneVisible = false">取消</el-button>
        <el-button type="primary" @click="saveMilestone">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="riskVisible"
      :title="riskForm.id ? '编辑风险' : '登记风险 / 问题'"
      width="min(680px, 94vw)"
      align-center
      :close-on-click-modal="false"
    >
      <div class="form-grid">
        <div class="field">
          <label>类型</label>
          <el-select v-model="riskForm.riskType">
            <el-option v-for="(item, code) in RISK_TYPE" :key="code" :label="item.label" :value="code" />
          </el-select>
        </div>
        <div class="field">
          <label>等级</label>
          <el-select v-model="riskForm.level">
            <el-option v-for="(item, code) in RISK_LEVEL" :key="code" :label="item.label" :value="code" />
          </el-select>
        </div>
        <div class="field span-2">
          <label>标题 <em>*</em></label>
          <el-input v-model="riskForm.title" maxlength="200" show-word-limit placeholder="如：第三方接口联调进度不可控" />
        </div>
        <div class="field">
          <label>发生概率（%）</label>
          <el-input-number v-model="riskForm.probability" :min="0" :max="100" :step="10" />
        </div>
        <div class="field">
          <label>责任人</label>
          <el-select v-model="riskForm.ownerId" filterable clearable placeholder="选择责任人">
            <el-option
              v-for="member in members"
              :key="member.userId"
              :label="member.realName || '账号已删除'"
              :value="String(member.userId)"
            />
          </el-select>
        </div>
        <div class="field">
          <label>截止日</label>
          <el-date-picker
            v-model="riskForm.dueDate"
            type="date"
            value-format="YYYY-MM-DD"
            placeholder="选择日期"
            :default-value="toDate(riskForm.dueDate)"
          />
        </div>
        <div class="field span-2">
          <label>描述</label>
          <el-input v-model="riskForm.description" type="textarea" :rows="2" maxlength="500" />
        </div>
        <div class="field span-2">
          <label>潜在影响</label>
          <el-input v-model="riskForm.impact" type="textarea" :rows="2" maxlength="500" placeholder="如：整体延期 1 周" />
        </div>
        <div class="field span-2">
          <label>应对措施</label>
          <el-input v-model="riskForm.strategy" type="textarea" :rows="2" maxlength="500" placeholder="如：安排双人对接、提前锁定测试环境" />
        </div>
      </div>
      <template #footer>
        <el-button @click="riskVisible = false">取消</el-button>
        <el-button type="primary" @click="saveRisk">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="baselineListVisible" title="项目基线" width="min(760px, 94vw)" align-center>
      <p class="form-hint">立项通过与每次变更通过各冻结一次，可查看当时的阶段 / 任务 / 进度快照。</p>
      <el-table :data="baselines" size="small">
        <template #empty>
          <el-empty description="尚未冻结基线：立项审批通过后自动生成 V1.0" :image-size="64" />
        </template>
        <el-table-column prop="version" label="版本" width="90" />
        <el-table-column prop="baselineName" label="名称" min-width="150" />
        <el-table-column label="类型" width="110">
          <template #default="{ row }">
            <el-tag size="small" effect="plain" :type="row.baselineType === 'CHANGE' ? 'warning' : 'info'">
              {{ row.baselineTypeLabel || BASELINE_TYPE[row.baselineType] || row.baselineType }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="冻结人" width="100">
          <template #default="{ row }">{{ row.frozenByName || userName(row.frozenBy) }}</template>
        </el-table-column>
        <el-table-column prop="frozenTime" label="冻结时间" width="120" />
        <el-table-column label="操作" width="110">
          <template #default="{ row }">
            <el-button link type="primary" @click="openBaseline(row)">查看快照</el-button>
          </template>
        </el-table-column>
      </el-table>
      <template #footer>
        <el-button @click="baselineListVisible = false">关闭</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="baselineVisible" :title="baselineTitle" width="min(760px, 94vw)" align-center>
      <div v-loading="baselineLoading" class="baseline-body">
        <pre v-if="baselineContent" class="json-block">{{ baselineContent }}</pre>
        <el-empty v-else description="暂无快照内容" :image-size="64" />
      </div>
      <template #footer>
        <el-button type="primary" @click="baselineVisible = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
/* ---------------- 列表 ---------------- */
.list-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 12px;
  margin-bottom: 14px;
}

/* 右侧计数 + 操作按钮：保持间距，避免文字贴到按钮上 */
.list-side {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-left: auto;
}

.seg {
  display: inline-flex;
  flex-wrap: wrap;
  gap: 2px;
  padding: 3px;
  border: 1px solid #e3e9f4;
  border-radius: 10px;
  background: #eef2f8;
}

.seg button {
  height: 30px;
  padding: 0 14px;
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
  white-space: nowrap;
}

.filter-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
  margin-bottom: 14px;
}

.filter-row :deep(.f-keyword) {
  flex: 1 1 240px;
  min-width: 180px;
}

.filter-row :deep(.f-dept) {
  flex: 0 0 170px;
}

.filter-row :deep(.f-pm) {
  flex: 0 0 180px;
}

.filter-row :deep(.f-health) {
  flex: 0 0 132px;
}

.filter-row :deep(.el-input),
.filter-row :deep(.el-select) {
  width: 100%;
}

.filter-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-left: auto;
  white-space: nowrap;
}

.cell-main {
  font-weight: 500;
  color: var(--pms-text);
}

.cell-sub {
  margin-top: 2px;
  font-size: 11.5px;
  color: var(--pms-text-3);
  font-variant-numeric: tabular-nums;
}

.health {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 12.5px;
  color: var(--pms-text-2);
}

.health i {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #2eb872;
}

.health.is-yellow i {
  background: #e6a23c;
}

.health.is-red i {
  background: #f56c6c;
}

.progress-cell {
  display: flex;
  align-items: center;
  gap: 8px;
}

.progress-track {
  position: relative;
  flex: 1;
  height: 6px;
  overflow: hidden;
  border-radius: 4px;
  background: #eef2f8;
}

.progress-fill {
  display: block;
  height: 100%;
  border-radius: 4px;
  background: linear-gradient(90deg, #7aa2ff, #3370ff);
}

.progress-cell b {
  flex: none;
  width: 38px;
  font-size: 12px;
  font-weight: 500;
  color: var(--pms-text-2);
  text-align: right;
  font-variant-numeric: tabular-nums;
}

.num-cell {
  font-variant-numeric: tabular-nums;
}

.pager {
  flex-wrap: wrap;
  row-gap: 8px;
  margin-top: 14px;
  justify-content: flex-end;
}

/* ---------------- 弹窗表单 ---------------- */
.dialog-body {
  max-height: min(64vh, 600px);
  overflow-y: auto;
  padding-right: 4px;
}

.form-hint {
  margin: 0 0 14px;
  font-size: 12.5px;
  line-height: 1.6;
  color: var(--pms-text-3);
}

.stage-ref {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 2px 6px;
  padding: 8px 10px;
  border-radius: 8px;
  background: #f7f9fd;
  color: var(--pms-text-2);
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

.drawer-footer {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  width: 100%;
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
  font-variant-numeric: tabular-nums;
}

.detail-tags {
  flex: none;
  display: flex;
  align-items: center;
  gap: 8px;
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
  min-width: 0;
  padding: 10px;
  border: 1px solid var(--pms-line);
  border-radius: 8px;
  background: #fafbfe;
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
  font-variant-numeric: tabular-nums;
}

.ops-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}

.terminate-alert {
  margin-top: 12px;
}

.pane-ops {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 10px;
}

.ops-select {
  width: 200px;
}

.ops-select.narrow {
  width: 132px;
}

.ops-select.wide {
  flex: 1 1 320px;
  width: auto;
}

.ops-hint {
  font-size: 12px;
  color: var(--pms-text-3);
}

.tag-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 10px;
}

/* ---------------- 计划：分节标题 ---------------- */
.plan-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 10px;
  padding-bottom: 8px;
  margin-bottom: 10px;
  border-bottom: 1px solid var(--pms-line-soft);
}

.plan-head-gap {
  margin-top: 20px;
}

.plan-title {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  min-width: 0;
}

.plan-title h4 {
  margin: 0;
  font-size: 13px;
  font-weight: 600;
  color: var(--pms-text);
}

.count-chip {
  min-width: 18px;
  height: 18px;
  padding: 0 5px;
  border-radius: 9px;
  background: var(--pms-primary-weak);
  color: var(--pms-primary-deep);
  font-size: 11px;
  line-height: 18px;
  text-align: center;
  font-variant-numeric: tabular-nums;
}

.plan-tip {
  font-size: 12px;
  color: var(--pms-text-3);
}

.plan-ops {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-left: auto;
}

.plan-table :deep(td.el-table__cell) {
  padding: 6px 0;
}

.date-range {
  font-size: 12.5px;
}

.date-span {
  margin-left: 6px;
  font-size: 11.5px;
  font-weight: 400;
  color: var(--pms-text-3);
}

.overdue {
  margin-left: 6px;
  font-size: 11.5px;
  color: var(--el-color-danger);
}

.row-more {
  margin-left: 2px;
  vertical-align: middle;
}

/* ---------------- 区块标题（团队内的小节） ---------------- */
.block-head {
  display: flex;
  align-items: baseline;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 8px;
}

.block-head h4 {
  margin: 0;
  font-size: 13px;
  font-weight: 600;
  color: var(--pms-text);
}

.block-tip {
  font-size: 12px;
  color: var(--pms-text-3);
}

.block-head-gap {
  margin-top: 18px;
}

/* ---------------- 计划：树形行（阶段 → 任务） ---------------- */
.plan-name {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  min-width: 0;
}

.plan-bullet {
  flex: none;
  margin-top: 7px;
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: var(--pms-primary);
  opacity: 0.6;
}

.plan-name-text {
  min-width: 0;
}

.plan-table :deep(.el-table__row--level-0) .cell-main {
  font-weight: 600;
}

.plan-table :deep(.el-table__row--level-1) .cell-main {
  font-weight: 400;
  color: var(--pms-text-2);
}

/* 阶段行浅底 + 左侧细色条，任务行纯白，层级清楚但不压视觉 */
.plan-table :deep(.plan-row-stage > td.el-table__cell) {
  background: #f5f8fd;
}

.plan-table :deep(.plan-row-stage > td.el-table__cell:first-child) {
  box-shadow: inset 2px 0 0 #cfe0f7;
}

.plan-table :deep(.plan-row-stage:hover > td.el-table__cell) {
  background: #eef4fc;
}

.plan-table :deep(.plan-row-task > td.el-table__cell) {
  background: #fff;
}

.plan-table :deep(.plan-row-task:hover > td.el-table__cell) {
  background: #fafcff;
}

/* 展开箭头：垂直居中、圆形点击区、缩小缩进 */
.plan-table :deep(td.el-table__cell:first-child .cell) {
  display: flex;
  align-items: center;
  min-width: 0;
}

.plan-table :deep(.el-table__expand-icon) {
  flex: none;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 18px;
  height: 18px;
  margin-right: 6px;
  border-radius: 50%;
  color: var(--pms-text-3);
  font-size: 11px;
  transition:
    background-color 0.16s ease,
    color 0.16s ease;
}

.plan-table :deep(.el-table__expand-icon:hover) {
  background: #e7eefb;
  color: var(--pms-primary-deep);
}

.plan-table :deep(.el-table__indent) {
  padding-left: 12px !important;
}

/* 操作列：等距排列，去掉 el-button 默认 margin 造成的前后不齐 */
.plan-table :deep(.ops-cell) {
  display: flex;
  align-items: center;
  gap: 12px;
}

.plan-table :deep(.ops-cell .el-button) {
  margin-left: 0;
  padding: 0;
}

/* 里程碑：名称与计划日期之间的呼吸感 */
.ms-sub {
  margin-top: 6px;
  line-height: 1.5;
}

.empty-tip {
  font-size: 12.5px;
  color: var(--pms-text-3);
}

/* ---------------- 文档 ---------------- */
.doc-head-side {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-left: auto;
}

.doc-head-side :deep(.doc-search) {
  width: 200px;
}

.seg button i {
  margin-left: 4px;
  font-style: normal;
  font-size: 11px;
  font-weight: 500;
  color: var(--pms-text-3);
}

.seg button.is-active i {
  color: var(--pms-primary-deep);
}

/* 左：归属字段（纵向排列）　右：拖拽区（始终撑满剩余宽高） */
.upload-panel {
  display: grid;
  grid-template-columns: 208px minmax(0, 1fr);
  align-items: stretch;
  gap: 12px;
  padding: 12px 14px;
  border: 1px dashed var(--pms-line);
  border-radius: 10px;
  background: #fafbfe;
}

.upload-fields {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-width: 0;
}

.upload-fields .field {
  width: 100%;
  gap: 4px;
}

.upload-fields .field :deep(.el-select) {
  width: 100%;
}

.doc-drop {
  display: flex;
  min-width: 0;
  /* 只有一行字段时也保留可拖拽高度 */
  min-height: 96px;
}

.doc-drop :deep(.el-upload) {
  display: flex;
  width: 100%;
  height: 100%;
}

.doc-drop :deep(.el-upload-dragger) {
  display: flex;
  flex: 1;
  align-items: center;
  justify-content: center;
  width: 100%;
  height: 100%;
  padding: 10px 16px;
  border-radius: 8px;
  background: #fff;
}

.doc-drop-text {
  display: flex;
  flex-direction: row;
  flex-wrap: wrap;
  align-items: center;
  justify-content: center;
  gap: 2px 10px;
  line-height: 1.6;
}

.doc-drop-text b {
  font-size: 13px;
  font-weight: 500;
  color: var(--pms-text);
}

.doc-drop-text span {
  font-size: 11.5px;
  color: var(--pms-text-3);
}

.doc-cell {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}

.doc-ext {
  flex: none;
  width: 38px;
  height: 38px;
  display: grid;
  place-items: center;
  border-radius: 8px;
  background: var(--pms-primary-weak);
  color: var(--pms-primary-deep);
  font-size: 10.5px;
  font-weight: 600;
  letter-spacing: 0.02em;
}

.doc-meta {
  min-width: 0;
}

.doc-scope {
  margin-left: 6px;
  font-size: 12px;
  color: var(--pms-text-3);
}

/* ---------------- 基线快照 ---------------- */
.baseline-body {
  max-height: min(62vh, 620px);
  overflow: auto;
}

.json-block {
  margin: 0;
  padding: 12px 14px;
  border: 1px solid var(--pms-line);
  border-radius: 8px;
  background: #f7f9fd;
  color: var(--pms-text-2);
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-all;
}

@media (max-width: 900px) {
  .metrics {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 768px) {
  .filter-row > * {
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

  .detail {
    padding: 4px 14px 20px;
  }

  .ops-select,
  .ops-select.wide,
  .ops-select.narrow {
    flex: 1 1 100%;
    width: 100%;
  }

  .plan-head {
    flex-direction: column;
    align-items: flex-start;
  }

  .plan-ops {
    margin-left: 0;
  }

  .list-side {
    width: 100%;
    margin-left: 0;
    justify-content: space-between;
  }

  .doc-head-side {
    width: 100%;
    margin-left: 0;
    flex-wrap: wrap;
  }

  .doc-head-side :deep(.doc-search) {
    width: 100%;
  }

  .upload-panel {
    grid-template-columns: 1fr;
  }

  .upload-fields .field {
    width: 100%;
  }

  .doc-drop {
    min-height: 84px;
  }

  .pager {
    justify-content: center;
  }
}
</style>
