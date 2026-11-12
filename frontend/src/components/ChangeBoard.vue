<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useRoute, useRouter } from 'vue-router'
import { Plus, TriangleAlert, Undo2 } from 'lucide-vue-next'
import {
  approveChange,
  assessChange,
  changeAction,
  changeDetail,
  changeOptions,
  createChange,
  listChanges,
  listProjects,
  rejectChange,
  saveChangeSchedules,
  submitChange,
  updateChange,
  userOptions,
  type ChangeOptions,
  type ChangeSchedule
} from '@/api'
import { useUserStore } from '@/stores/user'
import { useKeepAliveRefresh } from '@/utils/keepAlive'

/**
 * 变更台账组件。
 * 独立页（跨项目台账）与项目详情内嵌（本项目周期变更）共用同一套逻辑与视觉，
 * 避免两处各写一遍导致字段口径与样式漂移。
 */
const props = withDefaults(
  defineProps<{
    /** 内嵌时锁定的项目 ID（雪花 ID，按字符串透传）。 */
    projectId?: string
    projectName?: string
    /** 内嵌模式：隐藏页头与项目筛选。 */
    embedded?: boolean
  }>(),
  { projectId: '', projectName: '', embedded: false }
)

type TagType = 'primary' | 'success' | 'warning' | 'info' | 'danger'

const store = useUserStore()
const route = useRoute()
const router = useRouter()
const rows = ref<any[]>([])
const total = ref(0)
const page = ref({ pageNum: 1, pageSize: 10 })
const loading = ref(false)
const isNarrow = ref(false)
const syncWidth = () => {
  isNarrow.value = window.innerWidth <= 768
}

const projects = ref<any[]>([])
const users = ref<any[]>([])
const scheduleRoles = ref<string[]>(['开发', '测试'])

/** 可发起变更的项目状态（后端下发 R-CHG-02 口径，前端只用于过滤下拉）。 */
const projectStatuses = ref<string[]>(['APPROVED', 'IN_PROGRESS', 'SUSPENDED'])
const changeableProjects = computed(() =>
  projects.value.filter((item) => projectStatuses.value.includes(String(item.status || '')))
)

const filters = ref({
  keyword: '',
  projectId: '',
  changeType: '',
  level: '',
  emergency: false
})

const canView = computed(() => store.has('change:view'))
const canCreate = computed(() => store.has('change:create'))
const canExecute = computed(() => store.has('change:execute'))

const typeLabels: Record<string, string> = {
  SCOPE: '范围',
  SCHEDULE: '进度',
  COST: '成本',
  TECH: '技术',
  RESOURCE: '资源',
  OTHER: '其他'
}
const statusLabels: Record<string, string> = {
  DRAFT: '草稿',
  SUBMITTED: '已提交',
  ASSESSED: '已评估',
  APPROVED: '已批准',
  EXECUTING: '执行中',
  VERIFIED: '已验证',
  CLOSED: '已关闭',
  REJECTED: '已驳回',
  WITHDRAWN: '已撤回'
}
const statusTags: Record<string, TagType> = {
  DRAFT: 'info',
  SUBMITTED: 'warning',
  ASSESSED: 'warning',
  APPROVED: 'success',
  EXECUTING: 'primary',
  VERIFIED: 'success',
  CLOSED: 'info',
  REJECTED: 'danger',
  WITHDRAWN: 'info'
}
const levelTags: Record<string, TagType> = { L1: 'info', L2: 'warning', L3: 'danger' }
const levelLabels: Record<string, string> = { L1: 'L1 一般', L2: 'L2 重要', L3: 'L3 重大' }
const nodeLabels: Record<string, string> = {
  PM: '项目经理',
  DIRECTOR: '项目总监',
  DEPT_HEAD: '部门负责人',
  PMO: 'PMO',
  EXEC: '公司领导'
}
/** 可发起变更的项目状态显示名（新建变更下拉里标注，避免选到草稿项目）。 */
const projectStatusLabels: Record<string, string> = {
  APPROVED: '已立项',
  IN_PROGRESS: '进行中',
  SUSPENDED: '已挂起'
}
const dimensionLabels: Record<string, string> = {
  SCOPE: '范围',
  SCHEDULE: '工期',
  COST: '成本',
  RESOURCE: '资源',
  RISK: '风险',
  QUALITY: '质量'
}
const approvalLabels: Record<string, string> = {
  PENDING: '待审批',
  APPROVED: '已通过',
  REJECTED: '已驳回',
  TRANSFERRED: '已转办'
}

const typeText = (value: string) => typeLabels[value] || value || '—'
const statusText = (value: string) => statusLabels[value] || value || '—'
const nodeText = (value: string) => nodeLabels[value] || value || '—'
const userName = (id: string | number) => {
  const hit = users.value.find((item) => String(item.id) === String(id))
  return hit ? hit.realName : String(id || '—')
}
const spanDays = (row: any) => {
  if (!row.planStart || !row.planEnd) return '—'
  const days = (new Date(row.planEnd).getTime() - new Date(row.planStart).getTime()) / 86400000
  return `${Math.round(days) + 1} 天`
}

/* 状态页签：分组值用逗号传给后端，一屏覆盖完整生命周期 */
const TABS = [
  { key: 'ALL', label: '全部', status: '' },
  { key: 'PENDING', label: '待审批', status: 'SUBMITTED,ASSESSED' },
  { key: 'RUNNING', label: '执行中', status: 'APPROVED,EXECUTING' },
  { key: 'DONE', label: '已结束', status: 'VERIFIED,CLOSED' },
  { key: 'CLOSED', label: '已驳回 / 撤回', status: 'REJECTED,WITHDRAWN' }
]
const tab = ref('ALL')
const activeStatus = computed(() => TABS.find((item) => item.key === tab.value)?.status || '')

/* ------------------------------ 列表 ------------------------------ */
const loadOptions = async () => {
  if (!canView.value) return
  try {
    const data: ChangeOptions = await changeOptions()
    scheduleRoles.value = data.scheduleRoles?.length ? data.scheduleRoles : scheduleRoles.value
    if (data.projectStatuses?.length) projectStatuses.value = data.projectStatuses
  } catch {
    /* 选项失败不阻断主流程，保留默认角色 */
  }
  if (!props.embedded) {
    try {
      const data = await listProjects({ pageNum: 1, pageSize: 200 })
      projects.value = data.list || []
    } catch {
      projects.value = []
    }
  }
  try {
    users.value = ((await userOptions()) || []) as any[]
  } catch {
    users.value = []
  }
}

const load = async () => {
  if (!canView.value) {
    rows.value = []
    total.value = 0
    return
  }
  const projectId = props.projectId || filters.value.projectId
  if (props.embedded && !projectId) {
    rows.value = []
    total.value = 0
    return
  }
  loading.value = true
  try {
    const data = await listChanges({
      pageNum: page.value.pageNum,
      pageSize: page.value.pageSize,
      projectId: projectId || undefined,
      keyword: filters.value.keyword.trim() || undefined,
      changeType: filters.value.changeType || undefined,
      status: activeStatus.value || undefined,
      level: filters.value.level || undefined,
      emergency: filters.value.emergency || undefined
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
  filters.value = { keyword: '', projectId: '', changeType: '', level: '', emergency: false }
  tab.value = 'ALL'
  search()
}

/* ------------------------------ 周期排期编辑 ------------------------------ */
const blankDraft = () => ({ roleName: '', ownerId: '', range: null, remark: '' })
const toDraft = (row: any) => ({
  roleName: row.roleName || '',
  ownerId: row.ownerId ? String(row.ownerId) : '',
  range: row.planStart && row.planEnd ? [String(row.planStart), String(row.planEnd)] : null,
  remark: row.remark || ''
})

const collectSchedules = (drafts: any[]): ChangeSchedule[] | null => {
  const items: ChangeSchedule[] = []
  for (const row of drafts) {
    if (!row.roleName) continue
    const range = row.range as string[] | null
    if (!range || !range[0] || !range[1]) {
      ElMessage.warning(`请选择「${row.roleName}」的日期范围`)
      return null
    }
    items.push({
      roleName: row.roleName,
      ownerId: row.ownerId || 0,
      planStart: range[0],
      planEnd: range[1],
      remark: row.remark || ''
    })
  }
  return items
}

/* ------------------------------ 新建 ------------------------------ */
const createVisible = ref(false)
const createForm = ref<any>({
  projectId: '',
  changeType: 'SCHEDULE',
  title: '',
  reason: '',
  content: '',
  expectResult: '',
  isEmergency: false
})
const createDrafts = ref<any[]>([])

const creating = ref(false)

const openCreate = () => {
  // 从项目详情/筛选带入的项目若不可变更，直接不带入，免去填完再报冲突
  const preset = String(props.projectId || filters.value.projectId || '')
  const usable =
    !preset ||
    changeableProjects.value.some((item) => String(item.id) === preset) ||
    // 项目列表尚未加载完成时不拦截，交给后端校验
    !projects.value.length
  createForm.value = {
    projectId: usable ? preset : '',
    changeType: 'SCHEDULE',
    title: '',
    reason: '',
    content: '',
    expectResult: '',
    isEmergency: false
  }
  if (preset && !usable) {
    ElMessage.warning('所选项目当前状态不可发起变更（需已立项 / 进行中 / 已挂起）')
  }
  createDrafts.value = createForm.value.changeType === 'SCHEDULE' ? [blankDraft()] : []
  createVisible.value = true
}

/** 保存草稿；`andSubmit` 为 true 时保存后立即提交，省掉「保存 → 打开详情 → 提交」两步。 */
const doCreate = async (andSubmit = false) => {
  if (creating.value) return
  if (!createForm.value.projectId) {
    ElMessage.warning('请选择所属项目')
    return
  }
  if (!createForm.value.title.trim()) {
    ElMessage.warning('请填写变更标题')
    return
  }
  const schedules = collectSchedules(createDrafts.value)
  if (schedules === null) return
  creating.value = true
  try {
    const result = await createChange({ ...createForm.value, schedules })
    if (andSubmit) {
      await submitChange(result.id)
      ElMessage.success('变更申请已提交，等待六维评估')
    } else {
      ElMessage.success('变更申请已保存为草稿，可继续提交与评估')
    }
    createVisible.value = false
    page.value.pageNum = 1
    await load()
  } catch {
    /* 错误提示由请求拦截器统一弹出 */
  } finally {
    creating.value = false
  }
}

/* ------------------------------ 详情 ------------------------------ */
const detailVisible = ref(false)
const detailLoading = ref(false)
const detail = ref<any>({})
const scheduleDrafts = ref<any[]>([])
const scheduleEditing = ref(false)
const opinion = ref('')

const status = computed(() => String(detail.value?.request?.status || ''))
const request = computed(() => detail.value?.request || {})
const canEditSchedule = computed(
  () => canCreate.value && ['DRAFT', 'SUBMITTED'].includes(status.value)
)

const assessForm = ref({
  scopeExpanded: false,
  scheduleImpactDays: 0,
  costImpactAmount: 0,
  contractCommitment: false,
  needNewResource: false,
  techArchitecture: false,
  highRisk: false,
  pmoId: ''
})

const prefillAssess = (impacts: any[]) => {
  const form = {
    scopeExpanded: false,
    scheduleImpactDays: 0,
    costImpactAmount: 0,
    contractCommitment: false,
    needNewResource: false,
    techArchitecture: false,
    highRisk: false,
    pmoId: ''
  }
  for (const item of impacts || []) {
    if (item.dimension === 'SCOPE') form.scopeExpanded = Boolean(item.scopeExpanded)
    if (item.dimension === 'SCHEDULE') form.scheduleImpactDays = Number(item.scheduleImpactDays || 0)
    if (item.dimension === 'COST') form.costImpactAmount = Number(item.costImpactAmount || 0)
    if (item.dimension === 'RESOURCE') form.needNewResource = Number(item.headcountDelta || 0) > 0
    if (item.dimension === 'RISK') form.highRisk = String(item.riskLevel || '').toUpperCase() === 'HIGH'
  }
  assessForm.value = form
}

const openDetail = async (row: any) => {
  detailVisible.value = true
  detailLoading.value = true
  try {
    detail.value = await changeDetail(String(row.id))
    scheduleDrafts.value = (detail.value.schedules || []).map(toDraft)
    scheduleEditing.value = false
    opinion.value = ''
    prefillAssess(detail.value.impacts || [])
  } catch {
    detailVisible.value = false
  } finally {
    detailLoading.value = false
  }
}

const refreshDetail = async () => {
  if (!request.value.id) return
  await openDetail({ id: request.value.id })
}

const baseVisible = ref(false)
const baseForm = ref<any>({ title: '', reason: '', content: '', expectResult: '', isEmergency: false })

const openBase = () => {
  baseForm.value = {
    title: request.value.title || '',
    reason: request.value.reason || '',
    content: request.value.content || '',
    expectResult: request.value.expectResult || '',
    isEmergency: Boolean(request.value.isEmergency)
  }
  baseVisible.value = true
}

const doEditBase = async () => {
  if (!baseForm.value.title.trim()) {
    ElMessage.warning('请填写变更标题')
    return
  }
  await updateChange(String(request.value.id), baseForm.value)
  baseVisible.value = false
  ElMessage.success('变更信息已保存')
  await refreshDetail()
  await load()
}

const doSaveSchedules = async () => {
  const items = collectSchedules(scheduleDrafts.value)
  if (items === null) return
  await saveChangeSchedules(String(request.value.id), items)
  ElMessage.success('周期排期已保存')
  scheduleEditing.value = false
  await refreshDetail()
  await load()
}

const doSubmit = async () => {
  await submitChange(String(request.value.id))
  ElMessage.success('已提交')
  await refreshDetail()
  await load()
}

const doAssess = async () => {
  const form = assessForm.value
  const result = await assessChange(String(request.value.id), {
    impacts: [
      { dimension: 'SCOPE', scopeExpanded: form.scopeExpanded },
      { dimension: 'SCHEDULE', scheduleImpactDays: Number(form.scheduleImpactDays || 0) },
      { dimension: 'COST', costImpactAmount: Number(form.costImpactAmount || 0) },
      { dimension: 'RESOURCE', headcountDelta: form.needNewResource ? 1 : 0 },
      { dimension: 'RISK', riskLevel: form.highRisk ? 'HIGH' : 'LOW' }
    ],
    items: [],
    contractCommitment: form.contractCommitment,
    techArchitecture: form.techArchitecture,
    pmoId: form.pmoId || 0
  })
  ElMessage.success(`评估完成，自动定级 ${result.level}`)
  await refreshDetail()
  await load()
}

const doApprove = async () => {
  await approveChange(String(request.value.id), opinion.value)
  ElMessage.success('审批已通过，影响项已应用并冻结新基线')
  await refreshDetail()
  await load()
}

const doReject = async () => {
  if (!opinion.value.trim()) {
    ElMessage.warning('请填写驳回意见')
    return
  }
  try {
    await ElMessageBox.confirm(
      '驳回会直接终结本次变更（状态为「已驳回」），需要重新发起。确认驳回？',
      '驳回变更',
      { confirmButtonText: '驳回', cancelButtonText: '取消', type: 'warning' }
    )
  } catch {
    return
  }
  await rejectChange(String(request.value.id), opinion.value)
  ElMessage.success('已驳回')
  await refreshDetail()
  await load()
}

const doMore = async () => {
  if (!opinion.value.trim()) {
    ElMessage.warning('请填写需要补充的评估内容')
    return
  }
  try {
    await ElMessageBox.confirm(
      '退回补充会回到「草稿」，项目经理补充材料后可重新提交并再次评估。确认退回？',
      '退回补充评估',
      { confirmButtonText: '退回', cancelButtonText: '取消', type: 'warning' }
    )
  } catch {
    return
  }
  await changeAction(String(request.value.id), 'more', { opinion: opinion.value })
  ElMessage.success('已退回补充评估')
  await refreshDetail()
  await load()
}

const doAction = async (action: string, label: string) => {
  await changeAction(String(request.value.id), action)
  ElMessage.success(`${label}成功`)
  await refreshDetail()
  await load()
}

const doWithdraw = async () => {
  try {
    await ElMessageBox.confirm(
      '撤回后本次变更申请终止（状态为「已撤回」），需重新发起。确认撤回？',
      '撤回变更',
      { confirmButtonText: '撤回', cancelButtonText: '取消', type: 'warning' }
    )
  } catch {
    return
  }
  await changeAction(String(request.value.id), 'withdraw')
  ElMessage.success('已撤回')
  await refreshDetail()
  await load()
}

const doEmergency = async () => {
  try {
    await ElMessageBox.confirm(
      '标记紧急变更后需按系统期限补办审批，逾期会进入超期提醒。确认标记？',
      '标记紧急变更',
      { confirmButtonText: '标记', cancelButtonText: '取消', type: 'warning' }
    )
  } catch {
    return
  }
  await changeAction(String(request.value.id), 'emergency')
  ElMessage.success('已标记紧急变更，请在期限内补办审批')
  await refreshDetail()
}

const currentPending = computed(() => {
  const pending = (detail.value.approvals || []).filter((item: any) => item.status === 'PENDING')
  if (!pending.length) return null
  const seq = Math.min(...pending.map((item: any) => item.seq))
  return pending.filter((item: any) => item.seq === seq)
})

const pendingText = computed(() => {
  const list = currentPending.value
  if (!list) return ''
  return `当前待审批：第 ${list[0].seq} 节点（${list.map((item: any) => nodeText(item.nodeRole)).join('、')}）`
})

const closed = computed(() => ['CLOSED', 'REJECTED', 'WITHDRAWN'].includes(status.value))

/* 三个「终止/回退类」动作的职责区分（对应后端校验）：
 * - 撤回：发起人 / 项目经理在流程任意进行中状态终止申请（WITHDRAWN，终态）
 * - 退回补充：当前节点审批人要求补充评估，ASSESSED → DRAFT，可改完重新提交
 * - 驳回：当前节点审批人否决，直接终态（REJECTED），只能重新发起
 */
const meId = computed(() => String(store.profile?.id || ''))

const canWithdraw = computed(() => {
  if (!canCreate.value || closed.value) return false
  if (!['DRAFT', 'SUBMITTED', 'ASSESSED', 'APPROVED', 'EXECUTING'].includes(status.value)) {
    return false
  }
  if (canExecute.value) return true
  return (
    meId.value === String(request.value.submitterId || '') ||
    meId.value === String(request.value.pmId || '')
  )
})

/** 当前审批节点是否轮到我（会签节点任一即可）；`change:approve` 角色（PMO/领导）可代审。 */
const canApproveNow = computed(
  () =>
    (currentPending.value || []).some(
      (item: any) => String(item.approverId || '') === meId.value
    ) || store.has('change:approve')
)

const waitApprove = computed(
  () => ['SUBMITTED', 'ASSESSED'].includes(status.value) && !canApproveNow.value
)

const canMarkEmergency = computed(
  () => !closed.value && canExecute.value && !request.value.isEmergency
)

const emergencyText = computed(() => {
  if (!request.value.isEmergency) return ''
  const due = String(request.value.emergencyDue || '')
  return due ? `已标记紧急 · 补审批期限 ${due}` : '已标记紧急'
})

/* ------------------------------ 入口与路由参数 ------------------------------ */
/** 内嵌时不提供新建入口，统一跳回变更管理（避免同一功能两个创建入口）。 */
const goCreateInChanges = () => {
  if (!props.projectId) return
  router.push({ path: '/changes', query: { projectId: props.projectId, create: '1' } })
}

const pendingCreate = ref(false)

/** 独立页支持 `?projectId=` 预筛、`?create=1` 直接打开新建（供项目详情跳转）。 */
const readQuery = () => {
  if (props.embedded) return
  const rawId = route.query.projectId
  const rawIdValue = Array.isArray(rawId) ? rawId[0] : rawId
  if (rawIdValue) filters.value.projectId = String(rawIdValue)
  const rawCreate = route.query.create
  pendingCreate.value = (Array.isArray(rawCreate) ? rawCreate[0] : rawCreate) === '1'
}

onMounted(async () => {
  syncWidth()
  window.addEventListener('resize', syncWidth)
  readQuery()
  await loadOptions()
  await load()
  if (pendingCreate.value) {
    pendingCreate.value = false
    openCreate()
    // 清掉 create 标记但保留 projectId：刷新页面不会再次弹窗
    const query = filters.value.projectId ? { projectId: filters.value.projectId } : {}
    await router.replace({ path: route.path, query })
  }
})

watch(
  () => route.query.projectId,
  (value) => {
    if (props.embedded) return
    const projectId = Array.isArray(value) ? value[0] : value
    if (!projectId) return
    filters.value.projectId = String(projectId)
    search()
  }
)

// 已在变更管理页时再次从项目跳「去新建」，路径相同不会重建组件，需单独监听 create 标记
watch(
  () => route.query.create,
  async (value) => {
    const flag = Array.isArray(value) ? value[0] : value
    if (props.embedded || flag !== '1') return
    readQuery()
    openCreate()
    const query = filters.value.projectId ? { projectId: filters.value.projectId } : {}
    await router.replace({ path: route.path, query })
  }
)

onUnmounted(() => window.removeEventListener('resize', syncWidth))

watch(
  () => props.projectId,
  async (value) => {
    if (!value) {
      rows.value = []
      total.value = 0
      return
    }
    page.value.pageNum = 1
    await load()
  }
)
</script>

<template>
  <div v-loading="loading">
    <div :class="embedded ? 'list-plain' : 'pms-card list-card'">
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
          <span class="list-total">
            <template v-if="embedded && projectName">{{ projectName }} · </template>共 {{ total }} 条
          </span>
          <el-button size="small" :loading="loading" @click="load">刷新</el-button>
          <el-button
            v-if="canCreate && !embedded"
            type="primary"
            :icon="Plus"
            class="pms-create-btn"
            @click="openCreate"
          >
            新建变更
          </el-button>
          <el-button
            v-if="canCreate && embedded"
            type="primary"
            :icon="Plus"
            class="pms-create-btn"
            @click="goCreateInChanges"
          >
            去变更管理新建
          </el-button>
        </div>
      </div>

      <div class="filter-row">
        <el-input
          v-model="filters.keyword"
          class="f-keyword"
          placeholder="变更号 / 标题"
          clearable
          @keyup.enter="search"
          @clear="search"
        />
        <el-select
          v-if="!embedded"
          v-model="filters.projectId"
          class="f-project"
          placeholder="全部项目"
          clearable
          filterable
        >
          <el-option
            v-for="item in projects"
            :key="item.id"
            :label="`${item.projectName}（${item.projectCode}）`"
            :value="item.id"
          />
        </el-select>
        <el-select v-model="filters.changeType" class="f-type" placeholder="全部类型" clearable>
          <el-option v-for="(label, value) in typeLabels" :key="value" :label="label" :value="value" />
        </el-select>
        <el-select v-model="filters.level" class="f-level" placeholder="全部级别" clearable>
          <el-option v-for="(label, value) in levelLabels" :key="value" :label="label" :value="value" />
        </el-select>
        <el-checkbox v-model="filters.emergency" class="f-emergency">仅紧急</el-checkbox>
        <div class="filter-actions">
          <el-button type="primary" :loading="loading" @click="search">查询</el-button>
          <el-button @click="resetFilters">重置</el-button>
        </div>
      </div>

      <el-table :data="rows" size="small" @row-click="openDetail">
        <el-table-column label="变更" min-width="190">
          <template #default="{ row }">
            <div class="cell-main">{{ row.title }}</div>
            <div class="cell-sub">
              {{ row.requestCode }}
              <template v-if="!embedded && row.projectName"> · {{ row.projectName }}</template>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="类型" width="84">
          <template #default="{ row }">{{ typeText(row.changeType) }}</template>
        </el-table-column>
        <el-table-column label="级别" width="92">
          <template #default="{ row }">
            <el-tag v-if="row.level" :type="levelTags[row.level] || 'info'" size="small" effect="plain">
              {{ row.level }}
            </el-tag>
            <span v-else class="muted">未定级</span>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="96">
          <template #default="{ row }">
            <el-tag :type="statusTags[row.status] || 'info'" size="small">
              {{ statusText(row.status) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="排期" width="120" class-name="pms-mobile-hide">
          <template #default="{ row }">
            <span class="muted">{{ row.scheduleRoles || '—' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="工期影响" width="96" align="right" class-name="pms-mobile-hide">
          <template #default="{ row }">
            <span class="num-cell">{{ Number(row.scheduleImpactDays || 0) }} 天</span>
          </template>
        </el-table-column>
        <el-table-column label="提交时间" width="110" class-name="pms-mobile-hide">
          <template #default="{ row }">
            <span class="muted">{{ row.submitTime || '—' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="标记" width="76">
          <template #default="{ row }">
            <el-tag v-if="row.isEmergency" type="danger" size="small" effect="plain">紧急</el-tag>
            <span v-else class="muted">—</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="80">
          <template #default="{ row }">
            <el-button link type="primary" @click.stop="openDetail(row)">详情</el-button>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty
            :description="
              embedded ? '本项目还没有变更申请，可前往变更管理发起' : '当前筛选下没有变更单'
            "
            :image-size="76"
          >
            <el-button
              v-if="embedded && canCreate"
              type="primary"
              :icon="Plus"
              class="pms-create-btn"
              @click="goCreateInChanges"
            >
              去变更管理新建
            </el-button>
          </el-empty>
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

    <el-dialog
      v-model="createVisible"
      title="新建变更申请"
      width="min(880px, 94vw)"
      align-center
      :close-on-click-modal="false"
    >
      <div class="dialog-body">
        <p class="form-hint">
          可选项目仅限「已立项 / 进行中 / 已挂起」；保存草稿可稍后补排期再提交，「保存并提交」直接进入
          六维评估 → 项目总监会签 → PMO / 公司领导审批。
        </p>
        <div class="form-grid">
          <div class="field">
            <label>所属项目 <em>*</em></label>
            <el-select
              v-model="createForm.projectId"
              filterable
              :disabled="Boolean(projectId) || !changeableProjects.length"
              placeholder="选择项目"
            >
              <el-option
                v-for="item in changeableProjects"
                :key="item.id"
                :label="`${item.projectName}（${projectStatusLabels[String(item.status || '')] || item.status}）`"
                :value="item.id"
              />
              <el-option v-if="projectId" :key="projectId" :label="projectName || projectId" :value="projectId" />
            </el-select>
            <p v-if="!changeableProjects.length" class="form-hint is-warn">
              暂无可发起变更的项目：草稿、审批中、已交付/已关闭/已终止的项目均不可发起。
            </p>
          </div>
          <div class="field">
            <label>变更类型 <em>*</em></label>
            <el-select v-model="createForm.changeType">
              <el-option v-for="(label, value) in typeLabels" :key="value" :label="label" :value="value" />
            </el-select>
          </div>
          <div class="field span-2">
            <label>标题 <em>*</em></label>
            <el-input v-model="createForm.title" maxlength="200" show-word-limit placeholder="一句话说明这次变更改什么" />
          </div>
          <div class="field span-2">
            <label>变更原因</label>
            <el-input v-model="createForm.reason" type="textarea" :rows="2" maxlength="500" placeholder="客户需求 / 技术约束 / 资源变化…" />
          </div>
          <div class="field span-2">
            <label>变更内容</label>
            <el-input v-model="createForm.content" type="textarea" :rows="3" maxlength="1000" placeholder="具体改动的范围、节点或交付物" />
          </div>
          <div class="field span-2">
            <label>期望结果</label>
            <el-input v-model="createForm.expectResult" type="textarea" :rows="2" maxlength="500" placeholder="变更完成后希望达成的状态" />
          </div>
          <div class="field">
            <label>紧急变更</label>
            <el-switch v-model="createForm.isEmergency" active-text="先执行后补审批" />
          </div>
        </div>

        <div class="schedule-block">
          <div class="schedule-head">
            <b>周期排期</b>
            <span>按角色登记负责人与日期范围（如开发、测试），评估时自动折算工期影响</span>
          </div>
          <el-table :data="createDrafts" size="small" empty-text="尚未登记排期（可在详情里补充）">
            <el-table-column label="角色" width="120">
              <template #default="{ row }">
                <el-select v-model="row.roleName" size="small" filterable allow-create default-first-option placeholder="角色">
                  <el-option v-for="role in scheduleRoles" :key="role" :label="role" :value="role" />
                </el-select>
              </template>
            </el-table-column>
            <el-table-column label="负责人" width="160">
              <template #default="{ row }">
                <el-select v-model="row.ownerId" size="small" filterable clearable placeholder="选择负责人">
                  <el-option
                    v-for="user in users"
                    :key="user.id"
                    :label="`${user.realName}（${user.username}）`"
                    :value="String(user.id)"
                  />
                </el-select>
              </template>
            </el-table-column>
            <el-table-column label="日期范围" min-width="240">
              <template #default="{ row }">
                <el-date-picker
                  v-model="row.range"
                  type="daterange"
                  size="small"
                  value-format="YYYY-MM-DD"
                  start-placeholder="开始日期"
                  end-placeholder="结束日期"
                  style="width: 100%"
                />
              </template>
            </el-table-column>
            <el-table-column label="备注" min-width="120">
              <template #default="{ row }"><el-input v-model="row.remark" size="small" /></template>
            </el-table-column>
            <el-table-column label="操作" width="64">
              <template #default="{ $index }">
                <el-button link type="danger" @click="createDrafts.splice($index, 1)">删除</el-button>
              </template>
            </el-table-column>
          </el-table>
          <el-button size="small" class="schedule-add" @click="createDrafts.push(blankDraft())">新增排期</el-button>
        </div>
      </div>
      <template #footer>
        <div class="drawer-footer">
          <span class="footer-spacer"></span>
          <el-button @click="createVisible = false">取消</el-button>
          <el-button :loading="creating" @click="doCreate(false)">保存草稿</el-button>
          <el-button type="primary" :loading="creating" @click="doCreate(true)">
            保存并提交
          </el-button>
        </div>
      </template>
    </el-dialog>

    <el-dialog v-model="baseVisible" title="编辑变更信息" width="min(720px, 94vw)" align-center>
      <div class="form-grid">
        <div class="field span-2">
          <label>标题 <em>*</em></label>
          <el-input v-model="baseForm.title" maxlength="200" show-word-limit />
        </div>
        <div class="field span-2">
          <label>变更原因</label>
          <el-input v-model="baseForm.reason" type="textarea" :rows="2" maxlength="500" />
        </div>
        <div class="field span-2">
          <label>变更内容</label>
          <el-input v-model="baseForm.content" type="textarea" :rows="3" maxlength="1000" />
        </div>
        <div class="field span-2">
          <label>期望结果</label>
          <el-input v-model="baseForm.expectResult" type="textarea" :rows="2" maxlength="500" />
        </div>
        <div class="field">
          <label>紧急变更</label>
          <el-switch v-model="baseForm.isEmergency" active-text="先执行后补审批" />
        </div>
      </div>
      <template #footer>
        <el-button @click="baseVisible = false">取消</el-button>
        <el-button type="primary" @click="doEditBase">保存</el-button>
      </template>
    </el-dialog>

    <el-drawer v-model="detailVisible" title="变更详情" size="min(920px, 96vw)">
      <div v-loading="detailLoading" class="detail">
        <template v-if="request.id">
          <div class="detail-head">
            <div class="detail-copy">
              <h3>{{ request.title || '变更详情' }}</h3>
              <p class="detail-meta">
                {{ request.requestCode }} · {{ typeText(request.changeType) }}
                <template v-if="request.projectName"> · {{ request.projectName }}</template>
                <template v-if="request.submitTime"> · 提交于 {{ request.submitTime }}</template>
              </p>
            </div>
            <div class="detail-tags">
              <el-tag v-if="request.isEmergency" type="danger" effect="plain">紧急</el-tag>
              <el-tag :type="levelTags[request.level] || 'info'" effect="plain">
                {{ levelLabels[request.level] || '未定级' }}
              </el-tag>
              <el-tag :type="statusTags[request.status] || 'info'">{{ statusText(request.status) }}</el-tag>
            </div>
          </div>

          <div class="metrics">
            <div class="metric">
              <span>工期影响</span>
              <b>{{ Number(request.scheduleImpactDays || 0) }} 天</b>
            </div>
            <div class="metric">
              <span>成本影响</span>
              <b>{{ Number(request.costImpactAmount || 0).toLocaleString() }} 元</b>
            </div>
            <div class="metric">
              <span>基线</span>
              <b>{{ request.baselineBefore || '—' }} → {{ request.baselineAfter || '—' }}</b>
            </div>
            <div class="metric">
              <span>紧急期限</span>
              <b>{{ request.emergencyDue || '—' }}</b>
            </div>
          </div>

          <el-alert v-if="pendingText" type="warning" :closable="false" show-icon :title="pendingText" />

          <section class="detail-section">
            <div class="section-head">
              <h4>基本信息</h4>
              <el-button v-if="status === 'DRAFT' && canCreate" link type="primary" @click="openBase">编辑</el-button>
            </div>
            <div class="info-grid">
              <div class="info-item">
                <span>原因</span>
                <p>{{ request.reason || '—' }}</p>
              </div>
              <div class="info-item">
                <span>变更内容</span>
                <p>{{ request.content || '—' }}</p>
              </div>
              <div class="info-item">
                <span>期望结果</span>
                <p>{{ request.expectResult || '—' }}</p>
              </div>
            </div>
          </section>

          <section class="detail-section">
            <div class="section-head">
              <h4>周期排期</h4>
              <el-button v-if="canEditSchedule" link type="primary" @click="scheduleEditing = !scheduleEditing">
                {{ scheduleEditing ? '收起' : '编辑排期' }}
              </el-button>
            </div>
            <el-table :data="detail.schedules || []" size="small" empty-text="尚未登记排期">
              <el-table-column prop="roleName" label="角色" width="96" />
              <el-table-column label="负责人" width="120">
                <template #default="{ row }">{{ row.ownerName || userName(row.ownerId) }}</template>
              </el-table-column>
              <el-table-column label="日期范围" min-width="200">
                <template #default="{ row }">{{ row.planStart || '—' }} ~ {{ row.planEnd || '—' }}</template>
              </el-table-column>
              <el-table-column label="跨度" width="88" align="right">
                <template #default="{ row }">{{ spanDays(row) }}</template>
              </el-table-column>
              <el-table-column prop="remark" label="备注" min-width="120" show-overflow-tooltip />
              <el-table-column label="已应用" width="84">
                <template #default="{ row }">
                  <el-tag v-if="row.applied" type="success" size="small" effect="plain">是</el-tag>
                  <span v-else class="muted">否</span>
                </template>
              </el-table-column>
            </el-table>
            <div v-if="scheduleEditing" class="schedule-block">
              <el-table :data="scheduleDrafts" size="small">
                <el-table-column label="角色" width="120">
                  <template #default="{ row }">
                    <el-select v-model="row.roleName" size="small" filterable allow-create default-first-option placeholder="角色">
                      <el-option v-for="role in scheduleRoles" :key="role" :label="role" :value="role" />
                    </el-select>
                  </template>
                </el-table-column>
                <el-table-column label="负责人" width="160">
                  <template #default="{ row }">
                    <el-select v-model="row.ownerId" size="small" filterable clearable placeholder="选择负责人">
                      <el-option
                        v-for="user in users"
                        :key="user.id"
                        :label="`${user.realName}（${user.username}）`"
                        :value="String(user.id)"
                      />
                    </el-select>
                  </template>
                </el-table-column>
                <el-table-column label="日期范围" min-width="240">
                  <template #default="{ row }">
                    <el-date-picker
                      v-model="row.range"
                      type="daterange"
                      size="small"
                      value-format="YYYY-MM-DD"
                      start-placeholder="开始日期"
                      end-placeholder="结束日期"
                      style="width: 100%"
                    />
                  </template>
                </el-table-column>
                <el-table-column label="备注" min-width="120">
                  <template #default="{ row }"><el-input v-model="row.remark" size="small" /></template>
                </el-table-column>
                <el-table-column label="操作" width="64">
                  <template #default="{ $index }">
                    <el-button link type="danger" @click="scheduleDrafts.splice($index, 1)">删除</el-button>
                  </template>
                </el-table-column>
              </el-table>
              <div class="schedule-ops">
                <el-button size="small" @click="scheduleDrafts.push(blankDraft())">新增排期</el-button>
                <el-button size="small" type="primary" @click="doSaveSchedules">保存排期</el-button>
              </div>
            </div>
          </section>

          <section v-if="status === 'SUBMITTED' || status === 'DRAFT'" class="detail-section">
            <div class="section-head">
              <h4>六维影响评估</h4>
            </div>
            <p class="section-hint">评估后系统按阈值自动定级（L1/L2/L3）并生成审批链；排期顺延天数会自动参与工期影响计算。</p>
            <div class="form-grid compact">
              <div class="field">
                <label>工期影响（天）</label>
                <el-input-number v-model="assessForm.scheduleImpactDays" :min="0" />
              </div>
              <div class="field">
                <label>成本影响（元）</label>
                <el-input-number v-model="assessForm.costImpactAmount" :min="0" />
              </div>
              <div class="field">
                <label>PMO 审批人</label>
                <el-select v-model="assessForm.pmoId" filterable clearable placeholder="留空按 PMO 角色">
                  <el-option
                    v-for="user in users"
                    :key="user.id"
                    :label="`${user.realName}（${user.username}）`"
                    :value="String(user.id)"
                  />
                </el-select>
              </div>
              <div class="field switch-field">
                <label>范围扩大</label>
                <el-switch v-model="assessForm.scopeExpanded" />
              </div>
              <div class="field switch-field">
                <label>涉及合同承诺</label>
                <el-switch v-model="assessForm.contractCommitment" />
              </div>
              <div class="field switch-field">
                <label>需新增资源</label>
                <el-switch v-model="assessForm.needNewResource" />
              </div>
              <div class="field switch-field">
                <label>影响技术架构</label>
                <el-switch v-model="assessForm.techArchitecture" />
              </div>
              <div class="field switch-field">
                <label>引入高风险</label>
                <el-switch v-model="assessForm.highRisk" />
              </div>
            </div>
          </section>

          <section class="detail-section">
            <div class="section-head">
              <h4>审批意见</h4>
            </div>
            <el-input
              v-model="opinion"
              type="textarea"
              :rows="2"
              maxlength="500"
              show-word-limit
              placeholder="同意 / 驳回 / 补充评估的具体意见"
            />
          </section>

          <section class="detail-section">
            <div class="section-head">
              <h4>审批链</h4>
              <span class="section-hint inline">第一节点为项目总监会签，全部通过才进入 PMO；L3 再经公司领导</span>
            </div>
            <el-table :data="detail.approvals || []" size="small" empty-text="尚未评估，暂无审批链">
              <el-table-column prop="seq" label="序号" width="64" />
              <el-table-column label="节点" width="110">
                <template #default="{ row }">{{ nodeText(row.nodeRole) }}</template>
              </el-table-column>
              <el-table-column label="审批人" width="120">
                <template #default="{ row }">{{ row.approverName || userName(row.approverId) }}</template>
              </el-table-column>
              <el-table-column label="状态" width="96">
                <template #default="{ row }">
                  <el-tag
                    size="small"
                    :type="row.status === 'APPROVED' ? 'success' : row.status === 'REJECTED' ? 'danger' : 'warning'"
                    effect="plain"
                  >
                    {{ approvalLabels[row.status] || row.status }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column prop="opinion" label="意见" min-width="120" show-overflow-tooltip />
              <el-table-column prop="approveTime" label="审批时间" width="110" class-name="pms-mobile-hide" />
              <el-table-column prop="slaDays" label="SLA" width="70" align="right" />
            </el-table>
          </section>

          <section class="detail-section">
            <div class="section-head">
              <h4>影响评估明细</h4>
            </div>
            <el-table :data="detail.impacts || []" size="small" empty-text="尚未评估">
              <el-table-column label="维度" width="90">
                <template #default="{ row }">{{ dimensionLabels[row.dimension] || row.dimension }}</template>
              </el-table-column>
              <el-table-column label="工期(天)" width="90" align="right">
                <template #default="{ row }">{{ Number(row.scheduleImpactDays || 0) }}</template>
              </el-table-column>
              <el-table-column label="成本(元)" width="110" align="right">
                <template #default="{ row }">
                  {{ Number(row.costImpactAmount || 0).toLocaleString() }}
                </template>
              </el-table-column>
              <el-table-column label="新增人数" width="90" align="right">
                <template #default="{ row }">{{ row.headcountDelta || 0 }}</template>
              </el-table-column>
              <el-table-column prop="riskLevel" label="风险" width="80" />
              <el-table-column prop="description" label="说明" min-width="140" show-overflow-tooltip />
            </el-table>
          </section>

          <section class="detail-section">
            <div class="section-head">
              <h4>影响项</h4>
              <span class="section-hint inline">审批通过后自动落库，记录前后值</span>
            </div>
            <el-table :data="detail.items || []" size="small" empty-text="无影响项">
              <el-table-column prop="itemType" label="对象" width="100" />
              <el-table-column prop="fieldName" label="字段" width="100" />
              <el-table-column prop="beforeValue" label="原值" min-width="120" />
              <el-table-column prop="afterValue" label="新值" min-width="120" />
              <el-table-column label="已应用" width="84">
                <template #default="{ row }">
                  <el-tag v-if="row.applied" type="success" size="small" effect="plain">是</el-tag>
                  <span v-else class="muted">否</span>
                </template>
              </el-table-column>
            </el-table>
          </section>
        </template>
      </div>
      <template #footer>
        <div class="drawer-footer">
          <!-- 左：申请方动作（紧急标记 / 撤回），与审批方动作分区，避免误以为重复 -->
          <div class="footer-left">
            <el-tag v-if="request.isEmergency" type="danger" effect="plain" size="small">
              {{ emergencyText }}
            </el-tag>
            <el-button v-else-if="canMarkEmergency" :icon="TriangleAlert" @click="doEmergency">
              标记紧急
            </el-button>
            <el-button
              v-if="canWithdraw"
              :icon="Undo2"
              title="撤回：终止本次申请（仅发起人 / 项目经理可操作）"
              @click="doWithdraw"
            >
              撤回申请
            </el-button>
            <span v-if="waitApprove" class="footer-note">
              {{ pendingText || '等待当前节点审批人处理' }}
            </span>
          </div>
          <!-- 右：状态推进 / 审批动作 -->
          <div class="footer-right">
            <el-button v-if="status === 'DRAFT' && canCreate" type="primary" @click="doSubmit">
              提交变更
            </el-button>
            <el-button v-if="status === 'SUBMITTED' && canCreate" type="primary" @click="doAssess">
              评估定级
            </el-button>
            <el-button
              v-if="status === 'ASSESSED'"
              :disabled="!canApproveNow"
              title="退回补充：回到草稿，补充材料后可重新提交评估"
              @click="doMore"
            >
              退回补充
            </el-button>
            <el-button
              v-if="['SUBMITTED', 'ASSESSED'].includes(status)"
              type="danger"
              plain
              :disabled="!canApproveNow"
              title="驳回：直接否决并终结本次变更（需重新发起）"
              @click="doReject"
            >
              驳回
            </el-button>
            <el-button
              v-if="status === 'ASSESSED'"
              type="success"
              :disabled="!canApproveNow"
              @click="doApprove"
            >
              审批通过
            </el-button>
            <el-button
              v-if="status === 'APPROVED' && canExecute"
              type="primary"
              @click="doAction('execute', '开始执行')"
            >
              开始执行
            </el-button>
            <el-button
              v-if="status === 'EXECUTING' && canExecute"
              type="primary"
              @click="doAction('verify', '提交验证')"
            >
              提交验证
            </el-button>
            <el-button
              v-if="status === 'VERIFIED' && canExecute"
              @click="doAction('verify-fail', '验证不通过')"
            >
              验证不通过
            </el-button>
            <el-button
              v-if="status === 'VERIFIED' && canExecute"
              type="success"
              @click="doAction('close', '关闭')"
            >
              关闭变更
            </el-button>
          </div>
        </div>
      </template>
    </el-drawer>
  </div>
</template>

<style scoped>
/* ---------------- 列表 ---------------- */
.list-plain {
  padding: 0;
}

.list-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 12px;
  margin-bottom: 14px;
}

.list-side {
  display: flex;
  align-items: center;
  gap: 8px;
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
}

.filter-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
  margin-bottom: 14px;
}

.filter-row :deep(.f-keyword) {
  flex: 1 1 220px;
  min-width: 170px;
}

.filter-row :deep(.f-project) {
  flex: 0 0 200px;
}

.filter-row :deep(.f-type) {
  flex: 0 0 120px;
}

.filter-row :deep(.f-level) {
  flex: 0 0 130px;
}

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

.cell-main {
  overflow: hidden;
  font-weight: 500;
  color: var(--pms-text);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.cell-sub {
  margin-top: 2px;
  overflow: hidden;
  font-size: 11.5px;
  color: var(--pms-text-3);
  text-overflow: ellipsis;
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
}

.muted {
  font-size: 12.5px;
  color: var(--pms-text-3);
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

/* ---------------- 表单（弹窗与抽屉复用） ---------------- */
.dialog-body {
  max-height: min(66vh, 620px);
  overflow-y: auto;
  padding-right: 4px;
}

.form-hint {
  margin: 0 0 14px;
  font-size: 12.5px;
  line-height: 1.6;
  color: var(--pms-text-3);
}

/* 字段下方的提示（如「暂无可变更项目」）：紧跟字段，弱化间距 */
.field .form-hint {
  margin: 6px 0 0;
  font-size: 11.5px;
}

.form-hint.is-warn {
  color: #ad6800;
}

.form-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px 16px;
}

.form-grid.compact {
  gap: 10px 14px;
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

.field.switch-field {
  flex-direction: row;
  align-items: center;
  justify-content: space-between;
  padding: 6px 10px;
  border: 1px solid var(--pms-line);
  border-radius: 8px;
  background: #fafbfe;
}

.field :deep(.el-date-editor),
.field :deep(.el-select),
.field :deep(.el-input-number) {
  width: 100%;
}

/* ---------------- 排期编辑块 ---------------- */
.schedule-block {
  margin-top: 16px;
  padding-top: 14px;
  border-top: 1px solid var(--pms-line-soft);
}

.schedule-head {
  display: flex;
  align-items: baseline;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 10px;
}

.schedule-head b {
  font-size: 13px;
  font-weight: 600;
  color: var(--pms-text);
}

.schedule-head span {
  font-size: 12px;
  color: var(--pms-text-3);
}

.schedule-add {
  margin-top: 8px;
}

.schedule-ops {
  display: flex;
  gap: 8px;
  margin-top: 8px;
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

.detail-copy {
  min-width: 0;
}

.detail-head h3 {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
  line-height: 1.5;
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
  gap: 6px;
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

.detail-section {
  margin-top: 18px;
}

.section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 8px;
}

.section-head h4 {
  margin: 0;
  font-size: 13px;
  font-weight: 600;
  color: var(--pms-text);
}

.section-hint {
  margin: 0 0 8px;
  font-size: 12px;
  line-height: 1.6;
  color: var(--pms-text-3);
}

.section-hint.inline {
  margin: 0;
  text-align: right;
}

.info-grid {
  display: grid;
  gap: 8px;
}

.info-item {
  display: grid;
  grid-template-columns: 72px minmax(0, 1fr);
  gap: 10px;
  padding: 10px 12px;
  border: 1px solid var(--pms-line);
  border-radius: 8px;
  background: #fafbfe;
}

.info-item span {
  font-size: 12px;
  color: var(--pms-text-3);
}

.info-item p {
  margin: 0;
  font-size: 13px;
  line-height: 1.7;
  color: var(--pms-text-2);
  white-space: pre-wrap;
  word-break: break-word;
}

.drawer-footer {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  width: 100%;
}

.footer-left,
.footer-right {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}

.footer-right {
  margin-left: auto;
}

.footer-note {
  font-size: 12px;
  color: var(--pms-text-3);
}

@media (max-width: 900px) {
  .metrics {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 768px) {
  .list-side {
    width: 100%;
    margin-left: 0;
    justify-content: space-between;
  }

  .filter-row > * {
    flex: 1 1 100%;
    min-width: 0;
  }

  .filter-row :deep(.f-keyword),
  .filter-row :deep(.f-project),
  .filter-row :deep(.f-type),
  .filter-row :deep(.f-level) {
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

  .field.switch-field {
    flex-direction: row;
  }

  .detail {
    padding: 4px 14px 20px;
  }

  .detail-head {
    flex-direction: column;
  }

  .info-item {
    grid-template-columns: 60px minmax(0, 1fr);
  }

  .pager {
    justify-content: center;
  }
}
</style>
