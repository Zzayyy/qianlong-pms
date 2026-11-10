<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  addMember,
  approveProject,
  changeProjectPm,
  changeProjectStatus,
  createMilestone,
  createProject,
  createStage,
  createTask,
  deleteMilestone,
  deleteProjectFile,
  deleteStage,
  deleteTask,
  deptTree,
  downloadProjectFile,
  listMembers,
  listMilestones,
  listProjects,
  listStages,
  listTasks,
  listUsers,
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
  updateStage,
  updateTask,
  updateTaskProgress,
  uploadProjectFile,
  type Page
} from '@/api'
import ChangeBoard from '@/components/ChangeBoard.vue'
import { useUserStore } from '@/stores/user'

type TagType = 'primary' | 'success' | 'warning' | 'info' | 'danger'

const store = useUserStore()
const rows = ref<any[]>([])
const total = ref(0)
const page = ref({ pageNum: 1, pageSize: 10 })
const keyword = ref('')
const loading = ref(false)

/* 组织基础数据：部门与人员（用于下拉选择） */
const depts = ref<any[]>([])
const users = ref<any[]>([])
const canEdit = computed(() => store.has('project:edit'))
const canCreateProject = computed(() => store.has('project:create'))
const canApproveProject = computed(() => store.has('project:approve'))
const canUploadDoc = computed(() => store.has('project:doc:upload'))
const canManageDoc = computed(() => store.has('project:doc:manage'))
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

const STATUS_META: Record<string, { label: string; type: TagType }> = {
  DRAFT: { label: '草稿', type: 'info' },
  APPROVING: { label: '审批中', type: 'warning' },
  APPROVED: { label: '已立项', type: 'success' },
  IN_PROGRESS: { label: '进行中', type: 'primary' },
  SUSPENDED: { label: '已暂停', type: 'warning' },
  COMPLETED: { label: '已完成', type: 'success' },
  ACCEPTED: { label: '已验收', type: 'success' },
  TERMINATED: { label: '已终止', type: 'danger' },
  CLOSED: { label: '已关闭', type: 'info' }
}
const statusMeta = (status: string) =>
  STATUS_META[status] || { label: status || '—', type: 'info' as TagType }

const HEALTH_META: Record<string, { label: string; key: string }> = {
  GREEN: { label: '健康', key: 'green' },
  YELLOW: { label: '预警', key: 'yellow' },
  RED: { label: '风险', key: 'red' }
}
const healthMeta = (health: string) =>
  HEALTH_META[health] || { label: health || '—', key: 'green' }

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
const activeTab = ref('members')
const stages = ref<any[]>([])
const tasks = ref<any[]>([])
const milestones = ref<any[]>([])
const members = ref<any[]>([])
const newPmId = ref('')
const addMemberId = ref<string | null>(null)

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
const docBizType = ref<'PROJECT' | 'STAGE' | 'MILESTONE'>('PROJECT')
const docBizId = ref('')
const fileInput = ref<HTMLInputElement | null>(null)
const stageVisible = ref(false)
const stageForm = ref<any>({ id: '', stageName: '', weight: 1, seq: 1, planStart: '', planEnd: '' })

const loadNodeData = async () => {
  directors.value = await projectDirectors(detail.value.id)
  directorIds.value = directors.value.map((item: any) => String(item.userId))
  docs.value = await projectAttachments(detail.value.id)
}

const docCount = (stageId: string | number) =>
  docs.value.filter(
    (item) => item.bizType === 'STAGE' && String(item.bizId) === String(stageId)
  ).length

const openStage = (row?: any) => {
  stageForm.value = row
    ? {
        id: row.id,
        stageName: row.stageName,
        weight: Number(row.weight || 1),
        seq: Number(row.seq || 1),
        planStart: row.planStart || '',
        planEnd: row.planEnd || ''
      }
    : {
        id: '',
        stageName: '',
        weight: 1,
        seq: stages.value.length + 1,
        planStart: detail.value.planStart || '',
        planEnd: detail.value.planEnd || ''
      }
  stageVisible.value = true
}

const saveStage = async () => {
  if (!stageForm.value.stageName.trim()) {
    ElMessage.warning('请填写阶段名称')
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
  await setProjectDirectors(detail.value.id, directorIds.value)
  ElMessage.success('项目总监已更新（变更审批将由其会签）')
  await loadNodeData()
}

const uploadDoc = async () => {
  const file = fileInput.value?.files?.[0]
  if (!file) {
    ElMessage.warning('请先选择文件')
    return
  }
  const form = new FormData()
  form.append('file', file)
  form.append('projectId', String(detail.value.id))
  form.append('bizType', docBizType.value)
  form.append('bizId', String(docBizId.value || 0))
  await uploadProjectFile(form)
  ElMessage.success('文档已上传')
  if (fileInput.value) fileInput.value.value = ''
  docs.value = await projectAttachments(detail.value.id)
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
      status: activeStatus.value || undefined
    })
    rows.value = data.list || []
    total.value = data.total || 0
  } finally {
    loading.value = false
  }
}

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
  }
}

const loadBase = async () => {
  depts.value = (await deptTree()) as any[]
  try {
    const data: Page<Record<string, unknown>> = await listUsers({ pageNum: 1, pageSize: 200 })
    users.value = (data.list || []) as any[]
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
  activeTab.value = 'members'
  newPmId.value = String(detail.value.pmId || '')
  addMemberId.value = null
  stages.value = await listStages(row.id)
  tasks.value = await listTasks(row.id)
  milestones.value = await listMilestones(row.id)
  members.value = await listMembers(row.id)
  await loadNodeData()
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
    roleInProject: 'MEMBER'
  })
  addMemberId.value = null
  ElMessage.success('成员已添加')
  await refreshDetail()
}

const doRemoveMember = async (row: any) => {
  await removeMember(detail.value.id, row.id)
  ElMessage.success('成员已移出')
  await refreshDetail()
}

const doSubmit = async () => {
  await submitProject(detail.value.id)
  ElMessage.success('已提交立项审批')
  detailVisible.value = false
  await load()
}

const doApprove = async () => {
  await approveProject(detail.value.id)
  ElMessage.success('立项已通过并冻结基线')
  detailVisible.value = false
  await load()
}

const doReject = async () => {
  await rejectProject(detail.value.id, '前端驳回')
  ElMessage.success('已驳回')
  detailVisible.value = false
  await load()
}

const doStatus = async (status: string) => {
  await changeProjectStatus(detail.value.id, status)
  ElMessage.success(`状态已变更为 ${statusMeta(status).label}`)
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

const stageName = (stageId: string | number) =>
  stages.value.find((item) => String(item.id) === String(stageId))?.stageName || '未分阶段'

const openTask = (row?: any) => {
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
        stageId: stages.value[0] ? String(stages.value[0].id) : '',
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
  tasks.value = await listTasks(detail.value.id)
}

const removeTask = async (row: any) => {
  await ElMessageBox.confirm(`确认删除任务「${row.taskName}」？`, '提示', { type: 'warning' })
  await deleteTask(detail.value.id, String(row.id))
  ElMessage.success('任务已删除')
  tasks.value = await listTasks(detail.value.id)
  detail.value = await projectDetail(detail.value.id)
}

const setTaskProgress = async (row: any, value: number) => {
  if (Number(row.progress || 0) === value) return
  await updateTaskProgress(detail.value.id, String(row.id), value)
  tasks.value = await listTasks(detail.value.id)
  detail.value = await projectDetail(detail.value.id)
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
    <div class="pms-card page-head">
      <div class="head-copy">
        <h2>项目周期</h2>
        <p>从立项审批到阶段、任务、里程碑与交付文档按周期推进，关键节点冻结基线；周期或范围调整走详情里的「周期变更」。</p>
      </div>
      <div class="head-ops">
        <el-button :loading="loading" @click="refreshAll">刷新</el-button>
        <el-button v-if="canCreateProject" type="primary" @click="openCreate">新建项目</el-button>
      </div>
    </div>

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
        <span class="list-total">共 {{ total }} 个项目</span>
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
          <template #default="{ row }">{{ userName(row.pmId) }}</template>
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
            <el-select v-model="createForm.memberIds" multiple filterable collapse-tags collapse-tags-tooltip placeholder="可选，负责人会自动入组">
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
              {{ detail.projectCode }} · 负责人 {{ userName(detail.pmId) }}
            </p>
          </div>
          <div class="detail-tags">
            <el-tag :type="statusMeta(detail.status).type">{{ statusMeta(detail.status).label }}</el-tag>
            <span class="health" :class="`is-${healthMeta(detail.health).key}`">
              <i></i>{{ healthMeta(detail.health).label }}
            </span>
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
          <el-select v-model="newPmId" class="ops-select" filterable size="small" placeholder="选择新的负责人">
            <el-option
              v-for="user in users"
              :key="user.id"
              :label="`${user.realName}（${user.username}）`"
              :value="user.id"
            />
          </el-select>
          <el-button size="small" :disabled="!canEdit" @click="doChangePm">设为负责人</el-button>
          <el-button size="small" :disabled="!canEdit && Boolean(detail.pmId)" @click="claimProject">认领给我</el-button>
          <span v-if="!canManage && !isOwner" class="ops-hint">
            仅项目经理、PMO 或管理员可维护成员、节点与文档状态
          </span>
        </div>

        <el-tabs v-model="activeTab" style="margin-top: 14px">
          <el-tab-pane label="成员" name="members">
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
              <el-button size="small" type="primary" :disabled="!canEdit" @click="doAddMember">添加成员</el-button>
            </div>
            <el-table :data="members" size="small" empty-text="暂无成员">
              <el-table-column label="姓名" min-width="130">
                <template #default="{ row }">{{ row.realName || row.userId }}</template>
              </el-table-column>
              <el-table-column prop="username" label="账号" min-width="120" class-name="pms-mobile-hide" />
              <el-table-column prop="roleInProject" label="组内角色" width="120" />
              <el-table-column prop="joinDate" label="加入日期" width="120" class-name="pms-mobile-hide" />
              <el-table-column label="操作" width="90">
                <template #default="{ row }">
                  <el-button link type="danger" :disabled="!canEdit" @click="doRemoveMember(row)">移出</el-button>
                </template>
              </el-table-column>
            </el-table>
          </el-tab-pane>

          <el-tab-pane label="项目总监" name="directors">
            <el-alert
              type="info"
              :closable="false"
              show-icon
              title="项目总监是项目级授权（可多人），不是岗位；被指派者自动入组并取得本项目变更的会签审核权"
            />
            <div class="pane-ops">
              <el-select
                v-model="directorIds"
                class="ops-select wide"
                multiple
                filterable
                collapse-tags
                collapse-tags-tooltip
                size="small"
                placeholder="选择项目总监（可多人）"
                :disabled="!canEdit || !canManage"
              >
                <el-option
                  v-for="user in users"
                  :key="user.id"
                  :label="`${user.realName}（${user.username}）`"
                  :value="user.id"
                />
              </el-select>
              <el-button size="small" type="primary" :disabled="!canEdit || !canManage" @click="saveDirectors">
                保存总监
              </el-button>
            </div>
            <div class="tag-list">
              <el-tag v-for="item in directors" :key="item.userId" effect="plain">
                {{ item.realName || item.userId }}
              </el-tag>
              <span v-if="!directors.length" class="empty-tip">尚未指派项目总监</span>
            </div>
          </el-tab-pane>

          <el-tab-pane label="阶段" name="stages">
            <div class="pane-ops">
              <el-button size="small" type="primary" :disabled="!canManageNode" @click="openStage()">新增阶段</el-button>
              <span class="ops-hint">完成阶段前需在该节点的「文档」页签上传交付文档</span>
            </div>
            <el-table :data="stages" size="small">
              <template #empty>
                <el-empty description="还没有阶段，建议按「需求 / 开发 / 测试 / 上线」拆分" :image-size="64">
                  <el-button v-if="canManageNode" size="small" type="primary" @click="openStage()">新增阶段</el-button>
                </el-empty>
              </template>
              <el-table-column prop="stageName" label="阶段" min-width="140" />
              <el-table-column prop="weight" label="权重" width="80" />
              <el-table-column label="进度" width="90">
                <template #default="{ row }">{{ Math.round(Number(row.progress || 0)) }}%</template>
              </el-table-column>
              <el-table-column prop="status" label="状态" width="110" />
              <el-table-column label="文档" width="70">
                <template #default="{ row }">{{ docCount(row.id) }}</template>
              </el-table-column>
              <el-table-column label="操作" width="240">
                <template #default="{ row }">
                  <el-button link type="primary" :disabled="!canManageNode" @click="openStage(row)">编辑</el-button>
                  <el-button link type="primary" :disabled="!canManageNode" @click="startStage(row)">开始</el-button>
                  <el-button link type="success" :disabled="!canManageNode" @click="finishStage(row)">完成</el-button>
                  <el-button link type="danger" :disabled="!canManageNode" @click="removeStage(row)">删除</el-button>
                </template>
              </el-table-column>
            </el-table>
          </el-tab-pane>

          <el-tab-pane label="任务" name="tasks">
            <div class="pane-ops">
              <el-button size="small" type="primary" :disabled="!canEdit" @click="openTask()">新增任务</el-button>
              <span class="ops-hint">进度可在表格内直接调整，改动会级联重算项目进度</span>
            </div>
            <el-table :data="tasks" size="small">
              <template #empty>
                <el-empty description="还没有任务，拆到阶段后便于按人跟踪进度" :image-size="64">
                  <el-button v-if="canEdit" size="small" type="primary" @click="openTask()">新增任务</el-button>
                </el-empty>
              </template>
              <el-table-column label="任务" min-width="180">
                <template #default="{ row }">
                  <div class="cell-main">{{ row.taskName }}</div>
                  <div class="cell-sub">{{ row.taskCode || '—' }}</div>
                </template>
              </el-table-column>
              <el-table-column label="阶段" width="110">
                <template #default="{ row }">{{ stageName(row.stageId) }}</template>
              </el-table-column>
              <el-table-column label="负责人" width="100" class-name="pms-mobile-hide">
                <template #default="{ row }">{{ userName(row.ownerId) }}</template>
              </el-table-column>
              <el-table-column label="计划工时" width="96" align="right">
                <template #default="{ row }">{{ Number(row.planHours || 0) }}h</template>
              </el-table-column>
              <el-table-column label="实际工时" width="96" align="right" class-name="pms-mobile-hide">
                <template #default="{ row }">{{ Number(row.actualHours || 0) }}h</template>
              </el-table-column>
              <el-table-column label="进度" width="132">
                <template #default="{ row }">
                  <el-input-number
                    size="small"
                    :min="0"
                    :max="100"
                    :step="5"
                    controls-position="right"
                    :disabled="!canEdit"
                    :model-value="Number(row.progress || 0)"
                    @change="(value: any) => setTaskProgress(row, Number(value || 0))"
                  />
                </template>
              </el-table-column>
              <el-table-column label="计划起止" width="190" class-name="pms-mobile-hide">
                <template #default="{ row }">{{ row.planStart || '—' }} ~ {{ row.planEnd || '—' }}</template>
              </el-table-column>
              <el-table-column label="操作" width="110">
                <template #default="{ row }">
                  <el-button link type="primary" :disabled="!canEdit" @click="openTask(row)">编辑</el-button>
                  <el-button link type="danger" :disabled="!canEdit" @click="removeTask(row)">删除</el-button>
                </template>
              </el-table-column>
            </el-table>
          </el-tab-pane>

          <el-tab-pane label="里程碑" name="milestones">
            <div class="pane-ops">
              <el-button size="small" type="primary" :disabled="!canManageNode" @click="openMilestone()">
                新增里程碑
              </el-button>
              <span class="ops-hint">里程碑用于标注关键交付节点，达成后记录实际日期</span>
            </div>
            <el-table :data="milestones" size="small">
              <template #empty>
                <el-empty description="还没有里程碑，用来标注关键交付节点" :image-size="64">
                  <el-button v-if="canManageNode" size="small" type="primary" @click="openMilestone()">
                    新增里程碑
                  </el-button>
                </el-empty>
              </template>
              <el-table-column prop="milestoneName" label="名称" min-width="150" />
              <el-table-column label="负责人" width="100">
                <template #default="{ row }">{{ userName(row.ownerId) }}</template>
              </el-table-column>
              <el-table-column prop="planDate" label="计划日期" width="120" />
              <el-table-column prop="actualDate" label="实际日期" width="120" class-name="pms-mobile-hide" />
              <el-table-column prop="status" label="状态" width="100" />
              <el-table-column label="操作" width="190">
                <template #default="{ row }">
                  <el-button link type="success" :disabled="!canManageNode" @click="achieveMilestone(row)">达成</el-button>
                  <el-button link type="primary" :disabled="!canManageNode" @click="openMilestone(row)">编辑</el-button>
                  <el-button link type="danger" :disabled="!canManageNode" @click="removeMilestone(row)">删除</el-button>
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
            <div class="pane-ops">
              <el-select v-model="docBizType" size="small" class="ops-select">
                <el-option label="项目文档" value="PROJECT" />
                <el-option label="阶段文档" value="STAGE" />
                <el-option label="里程碑文档" value="MILESTONE" />
              </el-select>
              <el-select v-if="docBizType === 'STAGE'" v-model="docBizId" size="small" class="ops-select" placeholder="选择阶段">
                <el-option v-for="item in stages" :key="item.id" :label="item.stageName" :value="item.id" />
              </el-select>
              <el-select v-if="docBizType === 'MILESTONE'" v-model="docBizId" size="small" class="ops-select" placeholder="选择里程碑">
                <el-option v-for="item in milestones" :key="item.id" :label="item.milestoneName" :value="item.id" />
              </el-select>
              <input ref="fileInput" class="file-input" type="file" />
              <el-button size="small" type="primary" :disabled="!canUploadDoc" @click="uploadDoc">上传文档</el-button>
              <span v-if="!canUploadDoc" class="ops-hint">无文档上传权限</span>
            </div>
            <el-table :data="docs" size="small">
              <template #empty>
                <el-empty description="还没有文档：选择归属与文件后点「上传文档」" :image-size="64" />
              </template>
              <el-table-column prop="fileName" label="文件名" min-width="200" show-overflow-tooltip />
              <el-table-column prop="bizType" label="归属" width="110" />
              <el-table-column prop="uploader" label="上传人" width="120" class-name="pms-mobile-hide" />
              <el-table-column prop="uploadTime" label="上传时间" width="170" class-name="pms-mobile-hide" />
              <el-table-column label="操作" width="130">
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
          <span class="footer-spacer"></span>
          <el-button @click="detailVisible = false">关闭</el-button>
          <el-button v-if="detail.status === 'DRAFT' && canCreateProject" type="primary" @click="doSubmit">
            提交审批
          </el-button>
          <el-button v-if="detail.status === 'APPROVING' && canApproveProject" type="success" @click="doApprove">
            审批通过
          </el-button>
          <el-button v-if="detail.status === 'APPROVED' && canEdit" type="primary" @click="doStatus('IN_PROGRESS')">
            启动项目
          </el-button>
          <el-button v-if="detail.status === 'IN_PROGRESS' && canEdit" @click="doStatus('SUSPENDED')">暂停</el-button>
          <el-button v-if="detail.status === 'SUSPENDED' && canEdit" @click="doStatus('IN_PROGRESS')">恢复</el-button>
          <el-button
            v-if="['IN_PROGRESS', 'COMPLETED'].includes(detail.status) && canEdit"
            @click="doStatus('COMPLETED')"
          >
            完成
          </el-button>
          <el-button v-if="detail.status === 'COMPLETED' && canEdit" type="success" @click="doStatus('ACCEPTED')">
            验收
          </el-button>
        </div>
      </template>
    </el-drawer>

    <el-dialog v-model="stageVisible" :title="stageForm.id ? '编辑阶段' : '新增阶段'" width="min(560px, 94vw)" align-center>
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
          <el-date-picker v-model="stageForm.planStart" type="date" value-format="YYYY-MM-DD" placeholder="选择日期" />
        </div>
        <div class="field">
          <label>计划结束</label>
          <el-date-picker v-model="stageForm.planEnd" type="date" value-format="YYYY-MM-DD" placeholder="选择日期" />
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
          <el-date-picker v-model="taskForm.planStart" type="date" value-format="YYYY-MM-DD" placeholder="选择日期" />
        </div>
        <div class="field">
          <label>计划结束</label>
          <el-date-picker v-model="taskForm.planEnd" type="date" value-format="YYYY-MM-DD" placeholder="选择日期" />
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
          <el-date-picker v-model="milestoneForm.planDate" type="date" value-format="YYYY-MM-DD" placeholder="选择日期" />
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
  </div>
</template>

<style scoped>
/* ---------------- 页头 ---------------- */
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

/* ---------------- 列表 ---------------- */
.list-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 12px;
  margin-bottom: 14px;
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
  flex: 1 1 240px;
  min-width: 180px;
}

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

.empty-tip {
  font-size: 12.5px;
  color: var(--pms-text-3);
}

.file-input {
  max-width: 260px;
  font-size: 12px;
}

@media (max-width: 900px) {
  .metrics {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 768px) {
  .page-head .head-ops {
    width: 100%;
    margin-left: 0;
    justify-content: flex-end;
  }

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
  .ops-select.wide {
    flex: 1 1 100%;
    width: 100%;
  }

  .pager {
    justify-content: center;
  }
}
</style>
