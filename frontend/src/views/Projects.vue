<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
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
  updateStage,
  uploadProjectFile,
  type Page
} from '@/api'
import { useUserStore } from '@/stores/user'

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

/** 雪花 ID 超出 JS 安全整数（后端以字符串返回），一律按字符串比较与透传。 */
const userName = (id: string | number) => {
  const hit = users.value.find((item) => String(item.id) === String(id))
  return hit ? `${hit.realName}（${hit.username}）` : String(id || '—')
}

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
const stages = ref<any[]>([])
const tasks = ref<any[]>([])
const milestones = ref<any[]>([])
const members = ref<any[]>([])
const newPmId = ref('')
const addMemberId = ref<string | null>(null)

/* 项目节点与文档 */
const canManageStage = computed(() => store.has('project:stage:edit'))
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
    const data = await listProjects({ pageNum: page.value.pageNum, pageSize: page.value.pageSize, keyword: keyword.value })
    rows.value = data.list || []
    total.value = data.total || 0
  } finally {
    loading.value = false
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
  await load()
}

const openDetail = async (row: any) => {
  detail.value = await projectDetail(row.id)
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
  ElMessage.success(`状态已变更为 ${status}`)
  await refreshDetail()
  await load()
}

const addTask = async () => {
  await createTask(detail.value.id, {
    taskName: '新任务',
    stageId: stages.value[0]?.id || 0,
    ownerId: store.profile?.id || 0,
    planHours: 8,
    weight: 1
  })
  tasks.value = await listTasks(detail.value.id)
}

const addMilestone = async () => {
  await createMilestone(detail.value.id, { milestoneName: '新里程碑', planDate: detail.value.planEnd })
  milestones.value = await listMilestones(detail.value.id)
}

onMounted(async () => {
  await loadBase()
  await load()
})
</script>

<template>
  <div class="pms-page" v-loading="loading">
    <div class="pms-card">
      <el-row :gutter="8">
        <el-col :xs="24" :sm="10" :md="8">
          <el-input v-model="keyword" placeholder="项目名/编号" clearable />
        </el-col>
        <el-col :xs="24" :sm="14" :md="16">
          <el-button @click="load">查询</el-button>
          <el-button type="primary" @click="openCreate">新建项目</el-button>
        </el-col>
      </el-row>
    </div>

    <div class="pms-card">
      <el-table :data="rows" size="small" @row-click="openDetail">
        <el-table-column prop="projectCode" label="编号" width="140" />
        <el-table-column prop="projectName" label="项目" min-width="160" />
        <el-table-column prop="status" label="状态" width="110" />
        <el-table-column prop="health" label="健康度" width="100" />
        <el-table-column prop="progress" label="进度%" width="90" />
        <el-table-column prop="contractAmount" label="合同额" width="120" class-name="pms-mobile-hide" />
        <el-table-column prop="planEnd" label="计划结束" width="120" class-name="pms-mobile-hide" />
      </el-table>
      <el-pagination
        v-model:current-page="page.pageNum"
        v-model:page-size="page.pageSize"
        :total="total"
        layout="prev, pager, next, total"
        @current-change="load"
      />
    </div>

    <el-dialog v-model="createVisible" title="新建项目" width="90%">
      <el-form :model="createForm" label-width="100px">
        <el-form-item label="项目名称"><el-input v-model="createForm.projectName" /></el-form-item>
        <el-form-item label="所属部门">
          <el-select v-model="createForm.deptId" filterable style="width: 100%">
            <el-option v-for="dept in depts" :key="dept.id" :label="dept.deptName" :value="dept.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="负责人">
          <el-select v-model="createForm.pmId" filterable style="width: 100%">
            <el-option v-for="user in users" :key="user.id" :label="user.realName" :value="user.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="项目组成员">
          <el-select v-model="createForm.memberIds" multiple filterable style="width: 100%">
            <el-option v-for="user in users" :key="user.id" :label="user.realName" :value="user.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="合同金额"><el-input-number v-model="createForm.contractAmount" /></el-form-item>
        <el-form-item label="计划开始"><el-input v-model="createForm.planStart" placeholder="2026-11-01" /></el-form-item>
        <el-form-item label="计划结束"><el-input v-model="createForm.planEnd" placeholder="2026-12-31" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createVisible = false">取消</el-button>
        <el-button type="primary" @click="doCreate">保存</el-button>
      </template>
    </el-dialog>

    <el-drawer v-model="detailVisible" :title="detail.projectName || '项目详情'" size="70%">
      <el-descriptions :column="1" border size="small">
        <el-descriptions-item label="编号">{{ detail.projectCode }}</el-descriptions-item>
        <el-descriptions-item label="状态">{{ detail.status }}</el-descriptions-item>
        <el-descriptions-item label="负责人">{{ userName(detail.pmId) }}</el-descriptions-item>
        <el-descriptions-item label="健康度">{{ detail.health }}</el-descriptions-item>
        <el-descriptions-item label="进度">{{ detail.progress }}%</el-descriptions-item>
        <el-descriptions-item label="计划">{{ detail.planStart }} ~ {{ detail.planEnd }}</el-descriptions-item>
      </el-descriptions>

      <div class="pms-card" style="margin-top: 12px">
        <el-row :gutter="8" align="middle">
          <el-col :xs="24" :sm="12">
            <el-select v-model="newPmId" filterable size="small" style="width: 100%">
              <el-option v-for="user in users" :key="user.id" :label="user.realName" :value="user.id" />
            </el-select>
          </el-col>
          <el-col :xs="24" :sm="12">
            <el-button size="small" type="primary" @click="doChangePm">设为负责人</el-button>
            <el-button size="small" @click="claimProject">认领给我</el-button>
          </el-col>
        </el-row>
      </div>

      <el-row :gutter="8" style="margin-top: 12px">
        <el-button size="small" @click="doSubmit">提交审批</el-button>
        <el-button size="small" type="success" @click="doApprove">审批通过</el-button>
        <el-button size="small" type="danger" @click="doReject">驳回</el-button>
        <el-button size="small" @click="doStatus('IN_PROGRESS')">启动</el-button>
        <el-button size="small" @click="doStatus('SUSPENDED')">暂停</el-button>
        <el-button size="small" @click="doStatus('COMPLETED')">完成</el-button>
      </el-row>

      <el-tabs style="margin-top: 12px">
        <el-tab-pane label="成员">
          <el-row :gutter="8">
            <el-col :xs="24" :sm="12">
              <el-select v-model="addMemberId" filterable clearable size="small" placeholder="选择要加入的人员" style="width: 100%">
                <el-option v-for="user in users" :key="user.id" :label="user.realName" :value="user.id" />
              </el-select>
            </el-col>
            <el-col :xs="24" :sm="12">
              <el-button size="small" type="primary" :disabled="!canEdit" @click="doAddMember">添加成员</el-button>
            </el-col>
          </el-row>
          <el-table :data="members" size="small" style="margin-top: 8px">
            <el-table-column label="姓名" min-width="130">
              <template #default="{ row }">{{ row.realName || row.userId }}</template>
            </el-table-column>
            <el-table-column prop="username" label="账号" min-width="120" class-name="pms-mobile-hide" />
            <el-table-column prop="roleInProject" label="组内角色" width="120" />
            <el-table-column prop="joinDate" label="加入日期" width="120" class-name="pms-mobile-hide" />
            <el-table-column label="操作" width="90">
              <template #default="{ row }">
                <el-button size="small" type="danger" :disabled="!canEdit" @click="doRemoveMember(row)">移出</el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-tab-pane>
        <el-tab-pane label="项目总监">
          <el-alert
            type="info"
            :closable="false"
            show-icon
            title="项目总监是项目级授权（可多人），不是岗位；被指派者自动入组并取得本项目变更的会签审核权"
          />
          <el-select
            v-model="directorIds"
            multiple
            filterable
            size="small"
            style="width: 100%; margin-top: 8px"
            :disabled="!canEdit"
          >
            <el-option
              v-for="user in users"
              :key="user.id"
              :label="`${user.realName}（${user.username}）`"
              :value="user.id"
            />
          </el-select>
          <el-button size="small" type="primary" style="margin-top: 8px" :disabled="!canEdit" @click="saveDirectors">
            保存总监
          </el-button>
          <div style="margin-top: 8px">
            <el-tag v-for="item in directors" :key="item.userId" style="margin: 0 6px 6px 0">
              {{ item.realName || item.userId }}
            </el-tag>
          </div>
        </el-tab-pane>
        <el-tab-pane label="阶段">
          <el-button size="small" type="primary" :disabled="!canManageStage" @click="openStage()">新增阶段</el-button>
          <el-table :data="stages" size="small">
            <el-table-column prop="stageName" label="阶段" />
            <el-table-column prop="weight" label="权重" width="80" />
            <el-table-column prop="progress" label="进度%" width="90" />
            <el-table-column prop="status" label="状态" width="110" />
            <el-table-column label="文档" width="80">
              <template #default="{ row }">{{ docCount(row.id) }}</template>
            </el-table-column>
            <el-table-column label="操作" width="280">
              <template #default="{ row }">
                <el-button size="small" :disabled="!canManageStage" @click="openStage(row)">编辑</el-button>
                <el-button size="small" :disabled="!canManageStage" @click="startStage(row)">开始</el-button>
                <el-button size="small" type="success" :disabled="!canManageStage" @click="finishStage(row)">完成</el-button>
                <el-button size="small" type="danger" :disabled="!canManageStage" @click="removeStage(row)">删除</el-button>
              </template>
            </el-table-column>
          </el-table>
          <el-alert
            type="info"
            :closable="false"
            show-icon
            style="margin-top: 8px"
            title="完成阶段前需在该节点的「文档」页签上传交付文档（参数 project.stage.docRequired 可关闭校验）"
          />
        </el-tab-pane>
        <el-tab-pane label="任务">
          <el-button size="small" @click="addTask">新增任务</el-button>
          <el-table :data="tasks" size="small">
            <el-table-column prop="taskName" label="任务" />
            <el-table-column prop="planHours" label="计划工时" width="100" />
            <el-table-column prop="actualHours" label="实际工时" width="100" />
            <el-table-column prop="progress" label="进度%" width="90" />
          </el-table>
        </el-tab-pane>
        <el-tab-pane label="里程碑">
          <el-button size="small" type="primary" :disabled="!canManageStage" @click="addMilestone">新增里程碑</el-button>
          <el-table :data="milestones" size="small">
            <el-table-column prop="milestoneName" label="名称" />
            <el-table-column prop="planDate" label="计划日期" width="120" />
            <el-table-column prop="actualDate" label="实际日期" width="120" />
            <el-table-column prop="status" label="状态" width="100" />
            <el-table-column label="操作" width="160">
              <template #default="{ row }">
                <el-button size="small" type="success" :disabled="!canManageStage" @click="achieveMilestone(row)">达成</el-button>
                <el-button size="small" type="danger" :disabled="!canManageStage" @click="removeMilestone(row)">删除</el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-tab-pane>
        <el-tab-pane label="文档">
          <el-row :gutter="8" align="middle">
            <el-col :xs="24" :sm="5">
              <el-select v-model="docBizType" size="small" style="width: 100%">
                <el-option label="项目文档" value="PROJECT" />
                <el-option label="阶段文档" value="STAGE" />
                <el-option label="里程碑文档" value="MILESTONE" />
              </el-select>
            </el-col>
            <el-col v-if="docBizType === 'STAGE'" :xs="24" :sm="5">
              <el-select v-model="docBizId" size="small" placeholder="选择阶段" style="width: 100%">
                <el-option v-for="item in stages" :key="item.id" :label="item.stageName" :value="item.id" />
              </el-select>
            </el-col>
            <el-col v-if="docBizType === 'MILESTONE'" :xs="24" :sm="5">
              <el-select v-model="docBizId" size="small" placeholder="选择里程碑" style="width: 100%">
                <el-option v-for="item in milestones" :key="item.id" :label="item.milestoneName" :value="item.id" />
              </el-select>
            </el-col>
            <el-col :xs="24" :sm="8">
              <input ref="fileInput" type="file" />
            </el-col>
            <el-col :xs="24" :sm="4">
              <el-button size="small" type="primary" @click="uploadDoc">上传文档</el-button>
            </el-col>
          </el-row>
          <el-table :data="docs" size="small" style="margin-top: 8px">
            <el-table-column prop="fileName" label="文件名" min-width="200" />
            <el-table-column prop="bizType" label="归属" width="110" />
            <el-table-column prop="uploader" label="上传人" width="120" />
            <el-table-column prop="uploadTime" label="上传时间" width="170" class-name="pms-mobile-hide" />
            <el-table-column label="操作" width="150">
              <template #default="{ row }">
                <el-button size="small" @click="downloadDoc(row)">下载</el-button>
                <el-button size="small" type="danger" @click="removeDoc(row)">删除</el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-tab-pane>
      </el-tabs>
    </el-drawer>

    <el-dialog v-model="stageVisible" :title="stageForm.id ? '编辑阶段' : '新增阶段'" width="90%">
      <el-form :model="stageForm" label-width="90px">
        <el-form-item label="阶段名称"><el-input v-model="stageForm.stageName" /></el-form-item>
        <el-form-item label="权重"><el-input-number v-model="stageForm.weight" :min="0" :step="0.1" /></el-form-item>
        <el-form-item label="顺序"><el-input-number v-model="stageForm.seq" :min="1" /></el-form-item>
        <el-form-item label="计划开始"><el-input v-model="stageForm.planStart" placeholder="2026-11-01" /></el-form-item>
        <el-form-item label="计划结束"><el-input v-model="stageForm.planEnd" placeholder="2026-11-30" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="stageVisible = false">取消</el-button>
        <el-button type="primary" @click="saveStage">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>
