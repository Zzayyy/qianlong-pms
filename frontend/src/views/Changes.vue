<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import {
  approveChange,
  assessChange,
  changeAction,
  changeDetail,
  createChange,
  listChanges,
  listProjects,
  listUsers,
  rejectChange,
  submitChange,
  type Page
} from '@/api'

const rows = ref<any[]>([])
const total = ref(0)
const page = ref({ pageNum: 1, pageSize: 10 })
const loading = ref(false)

/** 雪花 ID 超出 JS 安全整数，选择框与入参一律用字符串，禁止 Number() 转换。 */
const projects = ref<any[]>([])
const users = ref<any[]>([])

const loadOptions = async () => {
  try {
    const data = await listProjects({ pageNum: 1, pageSize: 200 })
    projects.value = data.list || []
  } catch {
    projects.value = []
  }
  try {
    const data: Page<Record<string, unknown>> = await listUsers({ pageNum: 1, pageSize: 200 })
    users.value = (data.list || []) as any[]
  } catch {
    users.value = []
  }
}

const createVisible = ref(false)
const createForm = ref<any>({ projectId: '', changeType: 'SCHEDULE', title: '', reason: '', isEmergency: false })

const detailVisible = ref(false)
const detail = ref<any>({})
const impacts = ref<any[]>([])
const items = ref<any[]>([])
const approvals = ref<any[]>([])

const assessForm = ref<any>({
  scopeExpanded: false,
  scheduleImpactDays: 0,
  costImpactAmount: 0,
  contractCommitment: false,
  needNewResource: false,
  techArchitecture: false,
  highRisk: false,
  deptLeaderId: '',
  pmoId: ''
})

const load = async () => {
  loading.value = true
  try {
    const data = await listChanges({ pageNum: page.value.pageNum, pageSize: page.value.pageSize })
    rows.value = data.list || []
    total.value = data.total || 0
  } finally {
    loading.value = false
  }
}

const doCreate = async () => {
  if (!createForm.value.projectId) {
    ElMessage.warning('请选择所属项目')
    return
  }
  await createChange({ ...createForm.value, projectId: String(createForm.value.projectId) })
  createVisible.value = false
  ElMessage.success('变更申请已创建')
  await load()
}

const openDetail = async (row: any) => {
  detail.value = await changeDetail(row.id)
  impacts.value = detail.value.impacts || []
  items.value = detail.value.items || []
  approvals.value = detail.value.approvals || []
  detailVisible.value = true
}

const doSubmit = async () => {
  await submitChange(detail.value.id)
  ElMessage.success('已提交')
  await openDetail(detail.value)
  await load()
}

const doAssess = async () => {
  const result = await assessChange(detail.value.id, {
    impacts: [
      { dimension: 'SCOPE', scopeExpanded: assessForm.value.scopeExpanded },
      { dimension: 'SCHEDULE', scheduleImpactDays: assessForm.value.scheduleImpactDays },
      { dimension: 'COST', costImpactAmount: assessForm.value.costImpactAmount },
      { dimension: 'CONTRACT', contractCommitment: assessForm.value.contractCommitment },
      { dimension: 'RESOURCE', needNewResource: assessForm.value.needNewResource },
      { dimension: 'RISK', highRisk: assessForm.value.highRisk }
    ],
    items: [],
    deptLeaderId: assessForm.value.deptLeaderId || 0,
    pmoId: assessForm.value.pmoId || 0
  })
  ElMessage.success(`评估完成，定级 ${result.level}`)
  await openDetail(detail.value)
  await load()
}

const doApprove = async () => {
  await approveChange(detail.value.id, '同意')
  ElMessage.success('审批已通过，影响项已应用并冻结新基线')
  detailVisible.value = false
  await load()
}

const doReject = async () => {
  await rejectChange(detail.value.id, '不同意')
  ElMessage.success('已驳回')
  detailVisible.value = false
  await load()
}

const doAction = async (action: string) => {
  await changeAction(detail.value.id, action)
  ElMessage.success(`已执行 ${action}`)
  await openDetail(detail.value)
  await load()
}

onMounted(async () => {
  await loadOptions()
  await load()
})
</script>

<template>
  <div class="pms-page" v-loading="loading">
    <div class="pms-card">
      <el-button type="primary" @click="createVisible = true">新建变更</el-button>
      <el-button @click="load">刷新</el-button>
    </div>

    <div class="pms-card">
      <el-table :data="rows" size="small" @row-click="openDetail">
        <el-table-column prop="requestCode" label="变更号" width="150" />
        <el-table-column prop="title" label="标题" min-width="160" />
        <el-table-column prop="changeType" label="类型" width="110" />
        <el-table-column prop="level" label="级别" width="80" />
        <el-table-column prop="status" label="状态" width="120" />
        <el-table-column prop="isEmergency" label="紧急" width="80" class-name="pms-mobile-hide" />
      </el-table>
      <el-pagination
        v-model:current-page="page.pageNum"
        v-model:page-size="page.pageSize"
        :total="total"
        layout="prev, pager, next, total"
        @current-change="load"
      />
    </div>

    <el-dialog v-model="createVisible" title="新建变更申请" width="90%">
      <el-form :model="createForm" label-width="110px">
        <el-form-item label="所属项目">
          <el-select v-model="createForm.projectId" filterable placeholder="选择项目">
            <el-option
              v-for="item in projects"
              :key="item.id"
              :label="`${item.projectName}（${item.projectCode}）`"
              :value="item.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="变更类型">
          <el-select v-model="createForm.changeType">
            <el-option label="范围" value="SCOPE" />
            <el-option label="进度" value="SCHEDULE" />
            <el-option label="成本" value="COST" />
            <el-option label="技术" value="TECH" />
            <el-option label="资源" value="RESOURCE" />
            <el-option label="其他" value="OTHER" />
          </el-select>
        </el-form-item>
        <el-form-item label="标题"><el-input v-model="createForm.title" /></el-form-item>
        <el-form-item label="原因"><el-input v-model="createForm.reason" type="textarea" /></el-form-item>
        <el-form-item label="紧急变更"><el-switch v-model="createForm.isEmergency" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createVisible = false">取消</el-button>
        <el-button type="primary" @click="doCreate">保存</el-button>
      </template>
    </el-dialog>

    <el-drawer v-model="detailVisible" :title="detail.request?.requestCode || '变更详情'" size="70%">
      <el-descriptions :column="1" border size="small">
        <el-descriptions-item label="标题">{{ detail.request?.title }}</el-descriptions-item>
        <el-descriptions-item label="级别">{{ detail.request?.level }}</el-descriptions-item>
        <el-descriptions-item label="状态">{{ detail.request?.status }}</el-descriptions-item>
        <el-descriptions-item label="基线">{{ detail.request?.baselineBefore }} → {{ detail.request?.baselineAfter }}</el-descriptions-item>
      </el-descriptions>

      <h4>六维影响评估（自动生成级别与审批链）</h4>
      <el-form :model="assessForm" label-width="130px" size="small">
        <el-form-item label="范围扩大"><el-switch v-model="assessForm.scopeExpanded" /></el-form-item>
        <el-form-item label="工期影响(天)"><el-input-number v-model="assessForm.scheduleImpactDays" /></el-form-item>
        <el-form-item label="成本影响(元)"><el-input-number v-model="assessForm.costImpactAmount" /></el-form-item>
        <el-form-item label="涉及合同承诺"><el-switch v-model="assessForm.contractCommitment" /></el-form-item>
        <el-form-item label="需新增资源"><el-switch v-model="assessForm.needNewResource" /></el-form-item>
        <el-form-item label="影响技术架构"><el-switch v-model="assessForm.techArchitecture" /></el-form-item>
        <el-form-item label="引入高风险"><el-switch v-model="assessForm.highRisk" /></el-form-item>
        <el-form-item label="部门领导">
          <el-select v-model="assessForm.deptLeaderId" filterable clearable placeholder="留空则按部门负责人">
            <el-option
              v-for="user in users"
              :key="user.id"
              :label="`${user.realName}（${user.username}）`"
              :value="user.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="PMO">
          <el-select v-model="assessForm.pmoId" filterable clearable placeholder="留空则按 PMO 角色">
            <el-option
              v-for="user in users"
              :key="user.id"
              :label="`${user.realName}（${user.username}）`"
              :value="user.id"
            />
          </el-select>
        </el-form-item>
      </el-form>

      <el-row :gutter="8">
        <el-button size="small" @click="doSubmit">提交</el-button>
        <el-button size="small" type="primary" @click="doAssess">评估定级</el-button>
        <el-button size="small" type="success" @click="doApprove">审批通过</el-button>
        <el-button size="small" type="danger" @click="doReject">驳回</el-button>
        <el-button size="small" @click="doAction('execute')">执行</el-button>
        <el-button size="small" @click="doAction('verify')">提交验证</el-button>
        <el-button size="small" @click="doAction('close')">关闭</el-button>
        <el-button size="small" @click="doAction('emergency')">标记紧急</el-button>
      </el-row>

      <h4>审批链</h4>
      <el-alert
        type="info"
        :closable="false"
        show-icon
        title="第一节点为项目总监会签（同序号多人，全部通过才进入 PMO；L3 再经公司领导）"
        style="margin-bottom: 8px"
      />
      <el-table :data="approvals" size="small">
        <el-table-column prop="seq" label="序号" width="70" />
        <el-table-column prop="nodeRole" label="节点" width="110" />
        <el-table-column label="审批人" width="130">
          <template #default="{ row }">{{ row.approverName || row.approverId }}</template>
        </el-table-column>
        <el-table-column prop="status" label="状态" width="100" />
        <el-table-column prop="opinion" label="意见" min-width="120" />
        <el-table-column prop="approveTime" label="审批时间" width="120" />
        <el-table-column prop="slaDays" label="SLA(天)" width="90" />
      </el-table>

      <h4>影响评估明细</h4>
      <el-table :data="impacts" size="small">
        <el-table-column prop="dimension" label="维度" width="110" />
        <el-table-column prop="scheduleImpactDays" label="工期(天)" width="100" />
        <el-table-column prop="costImpactAmount" label="成本(元)" width="120" />
        <el-table-column prop="riskLevel" label="风险" width="100" />
      </el-table>

      <h4>影响项</h4>
      <el-table :data="items" size="small">
        <el-table-column prop="itemType" label="类型" width="110" />
        <el-table-column prop="action" label="动作" width="90" />
        <el-table-column prop="beforeValue" label="原值" />
        <el-table-column prop="afterValue" label="新值" />
        <el-table-column prop="applied" label="已应用" width="90" />
      </el-table>
    </el-drawer>
  </div>
</template>
