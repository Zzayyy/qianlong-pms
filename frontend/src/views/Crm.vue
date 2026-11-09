<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  addOppFollow,
  changeCustomerStatus,
  changeOppStatus,
  convertOpp,
  createContact,
  createCustomer,
  createOpportunity,
  crmStaff,
  crmSummary,
  customerContacts,
  customerDetail,
  deleteContact,
  deleteCustomer,
  deleteOppFollow,
  deleteOpportunity,
  dictItems,
  listCustomers,
  listOpportunities,
  oppFollows,
  opportunityDetail,
  pushOppStage,
  updateContact,
  updateCustomer,
  updateOpportunity
} from '@/api'
import { useUserStore } from '@/stores/user'

const store = useUserStore()
const tab = ref('customers')
const loading = ref(false)
const canCustomer = computed(() => store.has('crm:customer:manage'))
const canOpp = computed(() => store.has('crm:opp:manage'))

/* ------------------------------ 基础数据 ------------------------------ */
const dicts = ref<Record<string, any[]>>({})
const staff = ref<any[]>([])
const summary = ref<any>({ customers: {}, opportunities: {} })
const customerOptions = ref<any[]>([])

const customerStatusFallback = [
  { value: 'POTENTIAL', label: '潜在客户' },
  { value: 'COOPERATING', label: '合作中' },
  { value: 'LOST', label: '已流失' },
  { value: 'BLACKLIST', label: '黑名单' }
]
const customerLevelFallback = [
  { value: 'A', label: 'A 类' },
  { value: 'B', label: 'B 类' },
  { value: 'C', label: 'C 类' }
]
const oppStageFallback = [
  { value: 'LEAD', label: '线索' },
  { value: 'CONTACT', label: '沟通' },
  { value: 'PROPOSAL', label: '方案' },
  { value: 'QUOTE', label: '报价' },
  { value: 'WON', label: '赢单' },
  { value: 'LOST', label: '输单' }
]
const oppStatusFallback = [
  { value: 'OPEN', label: '进行中' },
  { value: 'WON', label: '赢单' },
  { value: 'LOST', label: '输单' },
  { value: 'CLOSED', label: '已关闭' }
]
const followTypeOptions = [
  { value: 'PHONE', label: '电话' },
  { value: 'VISIT', label: '拜访' },
  { value: 'WECHAT', label: '微信' },
  { value: 'EMAIL', label: '邮件' },
  { value: 'MEETING', label: '会议' },
  { value: 'OTHER', label: '其他' }
]

const dictOptions = (code: string, fallback: any[]) =>
  dicts.value[code] && dicts.value[code].length ? dicts.value[code] : fallback
const dictLabel = (code: string, value: any, fallback: any[]) => {
  if (value === undefined || value === null || value === '') return '—'
  const hit = dictOptions(code, fallback).find((item: any) => item.value === value)
  return hit ? hit.label : String(value)
}
const customerStatusLabel = (value: any) =>
  dictLabel('dict_customer_status', value, customerStatusFallback)
const customerLevelLabel = (value: any) =>
  dictLabel('dict_customer_level', value, customerLevelFallback)
const oppStageLabel = (value: any) => dictLabel('dict_opp_stage', value, oppStageFallback)
const oppStatusLabel = (value: any) => dictLabel('dict_opp_status', value, oppStatusFallback)
const followTypeLabel = (value: any) =>
  followTypeOptions.find((item) => item.value === value)?.label || value || '—'

const statusTagType = (status: string) =>
  status === 'COOPERATING' || status === 'WON'
    ? 'success'
    : status === 'LOST' || status === 'BLACKLIST'
      ? 'danger'
      : status === 'CLOSED'
        ? 'info'
        : 'warning'
const stageTagType = (stage: string) =>
  stage === 'WON' ? 'success' : stage === 'LOST' ? 'danger' : stage === 'LEAD' ? 'info' : 'warning'

const toNumber = (value: any, fallback = 0) => {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : fallback
}
const money = (value: any) =>
  typeof value === 'number'
    ? value.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
    : String(value ?? '—')
const timeText = (value: any) => String(value || '').replace('T', ' ').slice(0, 16)
const userName = (id: any) => {
  const hit = staff.value.find((item) => Number(item.id) === Number(id))
  return hit ? hit.realName : id ? String(id) : '—'
}

/** 脱敏字段不回写（用户无字段权限时保留原值）。 */
const stripMasked = (payload: Record<string, any>) => {
  const result: Record<string, any> = {}
  Object.entries(payload).forEach(([key, value]) => {
    if (typeof value === 'string' && value.includes('****')) return
    result[key] = value
  })
  return result
}

const loadDicts = async () => {
  const codes = [
    'dict_customer_level',
    'dict_customer_status',
    'dict_opp_stage',
    'dict_opp_status'
  ]
  const rows = await Promise.all(codes.map((code) => dictItems(code).catch(() => [])))
  const map: Record<string, any[]> = {}
  codes.forEach((code, index) => {
    map[code] = (rows[index] || []) as any[]
  })
  dicts.value = map
}

const loadStaff = async () => {
  staff.value = await crmStaff().catch(() => [])
}

const loadSummary = async () => {
  summary.value = await crmSummary().catch(() => ({ customers: {}, opportunities: {} }))
}

const loadCustomerOptions = async () => {
  const data = await listCustomers({ pageNum: 1, pageSize: 200 })
  customerOptions.value = data.list || []
}

/* ------------------------------ 客户 ------------------------------ */
const customers = ref<any[]>([])
const customerTotal = ref(0)
const customerPage = ref({ pageNum: 1, pageSize: 10 })
const customerFilter = ref({ keyword: '', status: '', level: '' })

const loadCustomers = async () => {
  loading.value = true
  try {
    const params: Record<string, any> = { ...customerPage.value }
    if (customerFilter.value.keyword) params.keyword = customerFilter.value.keyword
    if (customerFilter.value.status) params.status = customerFilter.value.status
    if (customerFilter.value.level) params.level = customerFilter.value.level
    const data = await listCustomers(params)
    customers.value = data.list || []
    customerTotal.value = data.total || 0
  } finally {
    loading.value = false
  }
}

const searchCustomers = () => {
  customerPage.value.pageNum = 1
  loadCustomers()
}

const resetCustomerFilter = () => {
  customerFilter.value = { keyword: '', status: '', level: '' }
  searchCustomers()
}

const customerDialog = ref(false)
const customerEditingId = ref('')
const customerForm = ref<any>({})

const emptyCustomer = () => ({
  customerName: '',
  customerLevel: 'B',
  industry: '',
  ownerUserId: Number(store.profile?.id || 0),
  ownerDeptId: Number(store.profile?.deptId || 0),
  contactName: '',
  contactMobile: '',
  contactEmail: '',
  province: '',
  city: '',
  address: '',
  source: '',
  status: 'POTENTIAL',
  remark: ''
})

const openCustomer = async (row?: any) => {
  customerEditingId.value = row ? String(row.id) : ''
  if (row) {
    customerForm.value = { ...emptyCustomer(), ...(await customerDetail(String(row.id))) }
    customerForm.value.ownerUserId = Number(customerForm.value.ownerUserId || 0)
    customerForm.value.ownerDeptId = Number(customerForm.value.ownerDeptId || 0)
  } else {
    customerForm.value = emptyCustomer()
  }
  customerDialog.value = true
}

const syncCustomerOwner = (userId: any) => {
  const hit = staff.value.find((item) => Number(item.id) === Number(userId))
  if (hit) customerForm.value.ownerDeptId = Number(hit.deptId || 0)
}

const saveCustomer = async () => {
  if (!customerForm.value.customerName?.trim()) {
    ElMessage.warning('请填写客户名称')
    return
  }
  const payload = stripMasked({
    customerName: customerForm.value.customerName.trim(),
    customerLevel: customerForm.value.customerLevel,
    industry: customerForm.value.industry,
    ownerUserId: Number(customerForm.value.ownerUserId || 0),
    ownerDeptId: Number(customerForm.value.ownerDeptId || 0),
    contactName: customerForm.value.contactName,
    contactMobile: customerForm.value.contactMobile,
    contactEmail: customerForm.value.contactEmail,
    province: customerForm.value.province,
    city: customerForm.value.city,
    address: customerForm.value.address,
    source: customerForm.value.source,
    status: customerForm.value.status,
    remark: customerForm.value.remark
  })
  if (customerEditingId.value) {
    await updateCustomer(customerEditingId.value, payload)
    ElMessage.success('客户已更新')
  } else {
    await createCustomer(payload)
    ElMessage.success('客户已创建')
  }
  customerDialog.value = false
  await Promise.all([loadCustomers(), loadCustomerOptions(), loadSummary()])
}

const quickCustomerStatus = async (row: any, status: string) => {
  if (!status || status === row.status) return
  await changeCustomerStatus(String(row.id), status)
  ElMessage.success(`客户状态已改为 ${customerStatusLabel(status)}`)
  await Promise.all([loadCustomers(), loadSummary()])
}

const removeCustomer = async (row: any) => {
  await ElMessageBox.confirm(`确认删除客户「${row.customerName}」？`, '提示', {
    type: 'warning'
  })
  await deleteCustomer(String(row.id))
  ElMessage.success('客户已删除')
  await Promise.all([loadCustomers(), loadCustomerOptions(), loadSummary()])
}

/* ------------------------------ 联系人 ------------------------------ */
const contactDrawer = ref(false)
const contactCustomer = ref<any>({})
const contacts = ref<any[]>([])
const contactDialog = ref(false)
const contactEditingId = ref('')
const contactForm = ref<any>({})

const loadContacts = async () => {
  contacts.value = await customerContacts(String(contactCustomer.value.id))
}

const openContacts = async (row: any) => {
  contactCustomer.value = row
  contactDrawer.value = true
  await loadContacts()
}

const emptyContact = () => ({
  name: '',
  title: '',
  mobile: '',
  email: '',
  wechat: '',
  isPrimary: false,
  remark: ''
})

const openContact = (row?: any) => {
  contactEditingId.value = row ? String(row.id) : ''
  contactForm.value = row ? { ...row, isPrimary: Boolean(row.isPrimary) } : emptyContact()
  contactDialog.value = true
}

const saveContact = async () => {
  if (!contactForm.value.name?.trim()) {
    ElMessage.warning('请填写联系人姓名')
    return
  }
  const payload = stripMasked({
    name: contactForm.value.name.trim(),
    title: contactForm.value.title,
    mobile: contactForm.value.mobile,
    email: contactForm.value.email,
    wechat: contactForm.value.wechat,
    isPrimary: Boolean(contactForm.value.isPrimary),
    remark: contactForm.value.remark
  })
  if (contactEditingId.value) {
    await updateContact(contactEditingId.value, payload)
  } else {
    await createContact(String(contactCustomer.value.id), payload)
  }
  contactDialog.value = false
  ElMessage.success('联系人已保存')
  await loadContacts()
}

const setPrimaryContact = async (row: any) => {
  await updateContact(String(row.id), { isPrimary: true })
  ElMessage.success('已设为主联系人')
  await loadContacts()
}

const removeContact = async (row: any) => {
  await ElMessageBox.confirm(`确认删除联系人「${row.name}」？`, '提示', { type: 'warning' })
  await deleteContact(String(row.id))
  ElMessage.success('联系人已删除')
  await loadContacts()
}

/* ------------------------------ 商机 ------------------------------ */
const opportunities = ref<any[]>([])
const oppTotal = ref(0)
const oppPage = ref({ pageNum: 1, pageSize: 10 })
const oppFilter = ref({ keyword: '', customerId: '', stage: '', status: '' })

const loadOpps = async () => {
  loading.value = true
  try {
    const params: Record<string, any> = { ...oppPage.value }
    if (oppFilter.value.keyword) params.keyword = oppFilter.value.keyword
    if (oppFilter.value.customerId) params.customerId = oppFilter.value.customerId
    if (oppFilter.value.stage) params.stage = oppFilter.value.stage
    if (oppFilter.value.status) params.status = oppFilter.value.status
    const data = await listOpportunities(params)
    opportunities.value = data.list || []
    oppTotal.value = data.total || 0
  } finally {
    loading.value = false
  }
}

const searchOpps = () => {
  oppPage.value.pageNum = 1
  loadOpps()
}

const resetOppFilter = () => {
  oppFilter.value = { keyword: '', customerId: '', stage: '', status: '' }
  searchOpps()
}

const oppDialog = ref(false)
const oppEditingId = ref('')
const oppForm = ref<any>({})

const emptyOpp = () => ({
  oppName: '',
  customerId: null,
  expectAmount: 0,
  expectSignDate: '',
  stage: 'LEAD',
  winRate: 0,
  source: '',
  status: 'OPEN',
  lostReason: '',
  ownerUserId: Number(store.profile?.id || 0),
  ownerDeptId: Number(store.profile?.deptId || 0),
  remark: ''
})

const openOpp = async (row?: any) => {
  oppEditingId.value = row ? String(row.id) : ''
  if (row) {
    const detail = await opportunityDetail(String(row.id))
    oppForm.value = { ...emptyOpp(), ...detail }
    oppForm.value.customerId = toNumber(oppForm.value.customerId) || null
    oppForm.value.ownerUserId = toNumber(oppForm.value.ownerUserId)
    oppForm.value.ownerDeptId = toNumber(oppForm.value.ownerDeptId)
    oppForm.value.expectAmount = toNumber(oppForm.value.expectAmount)
    oppForm.value.winRate = toNumber(oppForm.value.winRate)
    oppForm.value.expectSignDate = oppForm.value.expectSignDate || ''
  } else {
    oppForm.value = emptyOpp()
  }
  oppDialog.value = true
}

const syncOppOwner = (userId: any) => {
  const hit = staff.value.find((item) => Number(item.id) === Number(userId))
  if (hit) oppForm.value.ownerDeptId = Number(hit.deptId || 0)
}

const saveOpp = async () => {
  if (!oppForm.value.oppName?.trim()) {
    ElMessage.warning('请填写商机名称')
    return
  }
  if (!oppForm.value.customerId) {
    ElMessage.warning('请选择客户')
    return
  }
  const payload = {
    oppName: oppForm.value.oppName.trim(),
    customerId: Number(oppForm.value.customerId),
    expectAmount: Number(oppForm.value.expectAmount || 0),
    expectSignDate: oppForm.value.expectSignDate || '',
    stage: oppForm.value.stage,
    winRate: Number(oppForm.value.winRate || 0),
    source: oppForm.value.source,
    ownerUserId: Number(oppForm.value.ownerUserId || 0),
    ownerDeptId: Number(oppForm.value.ownerDeptId || 0),
    remark: oppForm.value.remark
  }
  if (oppEditingId.value) {
    await updateOpportunity(oppEditingId.value, {
      ...payload,
      status: oppForm.value.status,
      lostReason: oppForm.value.lostReason
    })
    ElMessage.success('商机已更新')
  } else {
    await createOpportunity(payload)
    ElMessage.success('商机已创建')
  }
  oppDialog.value = false
  await Promise.all([loadOpps(), loadSummary()])
}

const quickOppStage = async (row: any, stage: string) => {
  if (!stage || stage === row.stage) return
  let lostReason = ''
  if (stage === 'LOST') {
    const result = await ElMessageBox.prompt('请输入输单原因（可留空）', '标记输单', {
      inputPlaceholder: '例如：价格原因 / 竞争对手'
    }).catch(() => null)
    if (!result) return
    lostReason = result.value || ''
  }
  await pushOppStage(String(row.id), stage, lostReason)
  ElMessage.success(`商机阶段已推进到 ${oppStageLabel(stage)}`)
  await Promise.all([loadOpps(), loadSummary()])
}

const quickOppStatus = async (row: any, status: string) => {
  if (!status || status === row.status) return
  let lostReason = ''
  if (status === 'LOST') {
    const result = await ElMessageBox.prompt('请输入输单原因（可留空）', '标记输单', {
      inputPlaceholder: '例如：价格原因 / 竞争对手'
    }).catch(() => null)
    if (!result) return
    lostReason = result.value || ''
  }
  await changeOppStatus(String(row.id), status, lostReason)
  ElMessage.success(`商机状态已改为 ${oppStatusLabel(status)}`)
  await Promise.all([loadOpps(), loadSummary()])
}

const removeOpp = async (row: any) => {
  await ElMessageBox.confirm(`确认删除商机「${row.oppName}」？`, '提示', { type: 'warning' })
  await deleteOpportunity(String(row.id))
  ElMessage.success('商机已删除')
  await Promise.all([loadOpps(), loadSummary()])
}

/* ------------------------------ 转项目 ------------------------------ */
const convertDialog = ref(false)
const convertRow = ref<any>({})
const convertForm = ref<any>({ projectName: '', pmId: 0, planStart: '', planEnd: '' })

const openConvert = (row: any) => {
  convertRow.value = row
  convertForm.value = {
    projectName: [row.customerName, row.oppName].filter(Boolean).join('-'),
    pmId: Number(row.ownerUserId || store.profile?.id || 0),
    planStart: '',
    planEnd: ''
  }
  convertDialog.value = true
}

const doConvert = async () => {
  const result = await convertOpp(String(convertRow.value.id), {
    projectName: convertForm.value.projectName,
    pmId: Number(convertForm.value.pmId || 0),
    planStart: convertForm.value.planStart || null,
    planEnd: convertForm.value.planEnd || null
  })
  convertDialog.value = false
  ElMessage.success(`已生成项目 ${result.projectCode || result.projectId}，可在「项目周期」完善立项`)
  await Promise.all([loadOpps(), loadCustomers(), loadSummary()])
}

/* ------------------------------ 跟进 ------------------------------ */
const followDrawer = ref(false)
const followOpp = ref<any>({})
const follows = ref<any[]>([])
const followForm = ref<any>({ content: '', followType: 'PHONE', nextPlan: '', followTime: '' })

const loadFollows = async () => {
  follows.value = await oppFollows(String(followOpp.value.id))
}

const openFollows = async (row: any) => {
  followOpp.value = row
  followForm.value = { content: '', followType: 'PHONE', nextPlan: '', followTime: '' }
  followDrawer.value = true
  await loadFollows()
}

const saveFollow = async () => {
  if (!followForm.value.content?.trim()) {
    ElMessage.warning('请填写跟进内容')
    return
  }
  await addOppFollow(String(followOpp.value.id), {
    content: followForm.value.content.trim(),
    followType: followForm.value.followType,
    nextPlan: followForm.value.nextPlan,
    followTime: followForm.value.followTime || null
  })
  ElMessage.success('跟进记录已添加')
  followForm.value = { content: '', followType: 'PHONE', nextPlan: '', followTime: '' }
  await loadFollows()
}

const removeFollow = async (row: any) => {
  await ElMessageBox.confirm('确认删除该跟进记录？', '提示', { type: 'warning' })
  await deleteOppFollow(String(row.id))
  ElMessage.success('跟进记录已删除')
  await loadFollows()
}

onMounted(async () => {
  await Promise.all([loadDicts(), loadStaff()])
  await Promise.all([loadSummary(), loadCustomers(), loadOpps(), loadCustomerOptions()])
})
</script>

<template>
  <div class="pms-page" v-loading="loading">
    <el-row :gutter="12" class="pms-card">
      <el-col :xs="12" :sm="6">
        <el-statistic title="客户总数" :value="summary.customers?.total || 0" />
      </el-col>
      <el-col :xs="12" :sm="6">
        <el-statistic title="合作中客户" :value="summary.customers?.cooperating || 0" />
      </el-col>
      <el-col :xs="12" :sm="6">
        <el-statistic title="进行中商机金额" :value="Number(summary.opportunities?.pipelineAmount || 0)" prefix="¥" />
      </el-col>
      <el-col :xs="12" :sm="6">
        <el-statistic title="赢单金额" :value="Number(summary.opportunities?.wonAmount || 0)" prefix="¥" />
      </el-col>
    </el-row>

    <el-tabs v-model="tab">
      <!-- 客户 -->
      <el-tab-pane label="客户" name="customers">
        <div class="pms-card">
          <el-row :gutter="8">
            <el-col :xs="24" :sm="6">
              <el-input v-model="customerFilter.keyword" placeholder="名称 / 编码 / 联系人 / 手机" clearable @keyup.enter="searchCustomers" />
            </el-col>
            <el-col :xs="12" :sm="4">
              <el-select v-model="customerFilter.status" placeholder="客户状态" clearable style="width: 100%">
                <el-option v-for="item in dictOptions('dict_customer_status', customerStatusFallback)" :key="item.value" :label="item.label" :value="item.value" />
              </el-select>
            </el-col>
            <el-col :xs="12" :sm="4">
              <el-select v-model="customerFilter.level" placeholder="客户等级" clearable style="width: 100%">
                <el-option v-for="item in dictOptions('dict_customer_level', customerLevelFallback)" :key="item.value" :label="item.label" :value="item.value" />
              </el-select>
            </el-col>
            <el-col :xs="24" :sm="10">
              <el-button type="primary" @click="searchCustomers">查询</el-button>
              <el-button @click="resetCustomerFilter">重置</el-button>
              <el-button v-if="canCustomer" type="success" @click="openCustomer()">新建客户</el-button>
            </el-col>
          </el-row>
        </div>

        <div class="pms-card">
          <el-table :data="customers" size="small">
            <el-table-column prop="customerCode" label="编号" width="120" />
            <el-table-column prop="customerName" label="客户名称" min-width="180" />
            <el-table-column label="等级" width="80">
              <template #default="{ row }">{{ customerLevelLabel(row.customerLevel) }}</template>
            </el-table-column>
            <el-table-column prop="industry" label="行业" width="120" class-name="pms-mobile-hide" />
            <el-table-column label="状态" width="130">
              <template #default="{ row }">
                <el-select
                  v-if="canCustomer"
                  :model-value="row.status"
                  size="small"
                  @change="quickCustomerStatus(row, $event)"
                >
                  <el-option v-for="item in dictOptions('dict_customer_status', customerStatusFallback)" :key="item.value" :label="item.label" :value="item.value" />
                </el-select>
                <el-tag v-else :type="statusTagType(row.status)">
                  {{ customerStatusLabel(row.status) }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="contactName" label="联系人" width="100" class-name="pms-mobile-hide" />
            <el-table-column prop="contactMobile" label="联系电话" width="130" class-name="pms-mobile-hide" />
            <el-table-column label="负责人" width="100" class-name="pms-mobile-hide">
              <template #default="{ row }">{{ row.ownerName || userName(row.ownerUserId) }}</template>
            </el-table-column>
            <el-table-column label="创建时间" width="140" class-name="pms-mobile-hide">
              <template #default="{ row }">{{ timeText(row.createTime) }}</template>
            </el-table-column>
            <el-table-column label="操作" width="230" fixed="right">
              <template #default="{ row }">
                <el-button size="small" @click="openContacts(row)">联系人</el-button>
                <template v-if="canCustomer">
                  <el-button size="small" type="primary" @click="openCustomer(row)">编辑</el-button>
                  <el-button size="small" type="danger" @click="removeCustomer(row)">删除</el-button>
                </template>
              </template>
            </el-table-column>
          </el-table>
          <el-pagination
            v-model:current-page="customerPage.pageNum"
            v-model:page-size="customerPage.pageSize"
            :total="customerTotal"
            layout="prev, pager, next, total"
            @current-change="loadCustomers"
            @size-change="searchCustomers"
          />
        </div>
      </el-tab-pane>

      <!-- 商机 -->
      <el-tab-pane label="商机" name="opportunities">
        <div class="pms-card">
          <el-row :gutter="8">
            <el-col :xs="24" :sm="5">
              <el-input v-model="oppFilter.keyword" placeholder="商机名称 / 编号" clearable @keyup.enter="searchOpps" />
            </el-col>
            <el-col :xs="12" :sm="4">
              <el-select v-model="oppFilter.customerId" placeholder="客户" clearable filterable style="width: 100%">
                <el-option v-for="item in customerOptions" :key="item.id" :label="item.customerName" :value="item.id" />
              </el-select>
            </el-col>
            <el-col :xs="12" :sm="3">
              <el-select v-model="oppFilter.stage" placeholder="阶段" clearable style="width: 100%">
                <el-option v-for="item in dictOptions('dict_opp_stage', oppStageFallback)" :key="item.value" :label="item.label" :value="item.value" />
              </el-select>
            </el-col>
            <el-col :xs="12" :sm="3">
              <el-select v-model="oppFilter.status" placeholder="状态" clearable style="width: 100%">
                <el-option v-for="item in dictOptions('dict_opp_status', oppStatusFallback)" :key="item.value" :label="item.label" :value="item.value" />
              </el-select>
            </el-col>
            <el-col :xs="24" :sm="9">
              <el-button type="primary" @click="searchOpps">查询</el-button>
              <el-button @click="resetOppFilter">重置</el-button>
              <el-button v-if="canOpp" type="success" @click="openOpp()">新建商机</el-button>
            </el-col>
          </el-row>
        </div>

        <div class="pms-card">
          <el-table :data="opportunities" size="small">
            <el-table-column prop="oppCode" label="编号" width="140" />
            <el-table-column prop="oppName" label="商机名称" min-width="180" />
            <el-table-column prop="customerName" label="客户" min-width="140" class-name="pms-mobile-hide" />
            <el-table-column label="阶段" width="120">
              <template #default="{ row }">
                <el-select
                  v-if="canOpp"
                  :model-value="row.stage"
                  size="small"
                  @change="quickOppStage(row, $event)"
                >
                  <el-option v-for="item in dictOptions('dict_opp_stage', oppStageFallback)" :key="item.value" :label="item.label" :value="item.value" />
                </el-select>
                <el-tag v-else :type="stageTagType(row.stage)">{{ oppStageLabel(row.stage) }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="预计金额" width="130">
              <template #default="{ row }">{{ money(row.expectAmount) }}</template>
            </el-table-column>
            <el-table-column label="赢率" width="80" class-name="pms-mobile-hide">
              <template #default="{ row }">{{ row.winRate }}%</template>
            </el-table-column>
            <el-table-column label="预计签约" width="120" class-name="pms-mobile-hide">
              <template #default="{ row }">{{ row.expectSignDate || '—' }}</template>
            </el-table-column>
            <el-table-column label="状态" width="120">
              <template #default="{ row }">
                <el-select
                  v-if="canOpp"
                  :model-value="row.status"
                  size="small"
                  @change="quickOppStatus(row, $event)"
                >
                  <el-option v-for="item in dictOptions('dict_opp_status', oppStatusFallback)" :key="item.value" :label="item.label" :value="item.value" />
                </el-select>
                <el-tag v-else :type="statusTagType(row.status)">{{ oppStatusLabel(row.status) }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="负责人" width="100" class-name="pms-mobile-hide">
              <template #default="{ row }">{{ row.ownerName || userName(row.ownerUserId) }}</template>
            </el-table-column>
            <el-table-column label="操作" width="280" fixed="right">
              <template #default="{ row }">
                <el-button size="small" @click="openFollows(row)">跟进</el-button>
                <template v-if="canOpp">
                  <el-button size="small" type="primary" @click="openOpp(row)">编辑</el-button>
                  <el-button
                    size="small"
                    type="success"
                    :disabled="row.stage !== 'WON' || Boolean(row.convertedProjectId)"
                    @click="openConvert(row)"
                  >
                    {{ row.convertedProjectId ? '已转项目' : '转项目' }}
                  </el-button>
                  <el-button size="small" type="danger" @click="removeOpp(row)">删除</el-button>
                </template>
              </template>
            </el-table-column>
          </el-table>
          <el-pagination
            v-model:current-page="oppPage.pageNum"
            v-model:page-size="oppPage.pageSize"
            :total="oppTotal"
            layout="prev, pager, next, total"
            @current-change="loadOpps"
            @size-change="searchOpps"
          />
        </div>
      </el-tab-pane>
    </el-tabs>

    <!-- 客户编辑 -->
    <el-dialog v-model="customerDialog" :title="customerEditingId ? '编辑客户' : '新建客户'" width="90%" style="max-width: 720px">
      <el-form :model="customerForm" label-width="100px">
        <el-row :gutter="8">
          <el-col :xs="24" :sm="12">
            <el-form-item label="客户名称"><el-input v-model="customerForm.customerName" /></el-form-item>
          </el-col>
          <el-col :xs="12" :sm="6">
            <el-form-item label="客户等级">
              <el-select v-model="customerForm.customerLevel" style="width: 100%">
                <el-option v-for="item in dictOptions('dict_customer_level', customerLevelFallback)" :key="item.value" :label="item.label" :value="item.value" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :xs="12" :sm="6">
            <el-form-item label="状态">
              <el-select v-model="customerForm.status" style="width: 100%">
                <el-option v-for="item in dictOptions('dict_customer_status', customerStatusFallback)" :key="item.value" :label="item.label" :value="item.value" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :xs="24" :sm="12">
            <el-form-item label="行业"><el-input v-model="customerForm.industry" /></el-form-item>
          </el-col>
          <el-col :xs="24" :sm="12">
            <el-form-item label="负责人">
              <el-select v-model="customerForm.ownerUserId" filterable style="width: 100%" @change="syncCustomerOwner">
                <el-option v-for="item in staff" :key="item.id" :label="`${item.realName}（${item.username}）`" :value="Number(item.id)" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :xs="24" :sm="12">
            <el-form-item label="联系人"><el-input v-model="customerForm.contactName" /></el-form-item>
          </el-col>
          <el-col :xs="24" :sm="12">
            <el-form-item label="联系电话"><el-input v-model="customerForm.contactMobile" /></el-form-item>
          </el-col>
          <el-col :xs="24" :sm="12">
            <el-form-item label="联系邮箱"><el-input v-model="customerForm.contactEmail" /></el-form-item>
          </el-col>
          <el-col :xs="12" :sm="6">
            <el-form-item label="省份"><el-input v-model="customerForm.province" /></el-form-item>
          </el-col>
          <el-col :xs="12" :sm="6">
            <el-form-item label="城市"><el-input v-model="customerForm.city" /></el-form-item>
          </el-col>
          <el-col :xs="24" :sm="12">
            <el-form-item label="来源"><el-input v-model="customerForm.source" placeholder="例如：官网 / 转介绍 / 展会" /></el-form-item>
          </el-col>
          <el-col :xs="24">
            <el-form-item label="详细地址"><el-input v-model="customerForm.address" /></el-form-item>
          </el-col>
          <el-col :xs="24">
            <el-form-item label="备注"><el-input v-model="customerForm.remark" type="textarea" :rows="2" /></el-form-item>
          </el-col>
        </el-row>
      </el-form>
      <template #footer>
        <el-button @click="customerDialog = false">取消</el-button>
        <el-button type="primary" @click="saveCustomer">保存</el-button>
      </template>
    </el-dialog>

    <!-- 联系人 -->
    <el-drawer v-model="contactDrawer" :title="`联系人 · ${contactCustomer.customerName || ''}`" size="70%">
      <div style="margin-bottom: 8px">
        <el-button v-if="canCustomer" type="primary" size="small" @click="openContact()">新增联系人</el-button>
      </div>
      <el-table :data="contacts" size="small">
        <el-table-column prop="name" label="姓名" width="100" />
        <el-table-column prop="title" label="职务" width="110" />
        <el-table-column prop="mobile" label="手机" width="130" />
        <el-table-column prop="email" label="邮箱" min-width="150" />
        <el-table-column prop="wechat" label="微信" width="120" class-name="pms-mobile-hide" />
        <el-table-column label="主联系人" width="90">
          <template #default="{ row }">
            <el-tag v-if="row.isPrimary" type="success" size="small">是</el-tag>
            <span v-else>—</span>
          </template>
        </el-table-column>
        <el-table-column prop="remark" label="备注" min-width="120" class-name="pms-mobile-hide" />
        <el-table-column v-if="canCustomer" label="操作" width="190">
          <template #default="{ row }">
            <el-button size="small" @click="openContact(row)">编辑</el-button>
            <el-button v-if="!row.isPrimary" size="small" @click="setPrimaryContact(row)">设为主</el-button>
            <el-button size="small" type="danger" @click="removeContact(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-drawer>

    <el-dialog v-model="contactDialog" :title="contactEditingId ? '编辑联系人' : '新增联系人'" width="90%" style="max-width: 520px">
      <el-form :model="contactForm" label-width="90px">
        <el-form-item label="姓名"><el-input v-model="contactForm.name" /></el-form-item>
        <el-form-item label="职务"><el-input v-model="contactForm.title" /></el-form-item>
        <el-form-item label="手机"><el-input v-model="contactForm.mobile" /></el-form-item>
        <el-form-item label="邮箱"><el-input v-model="contactForm.email" /></el-form-item>
        <el-form-item label="微信"><el-input v-model="contactForm.wechat" /></el-form-item>
        <el-form-item label="主联系人"><el-switch v-model="contactForm.isPrimary" /></el-form-item>
        <el-form-item label="备注"><el-input v-model="contactForm.remark" type="textarea" :rows="2" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="contactDialog = false">取消</el-button>
        <el-button type="primary" @click="saveContact">保存</el-button>
      </template>
    </el-dialog>

    <!-- 商机编辑 -->
    <el-dialog v-model="oppDialog" :title="oppEditingId ? '编辑商机' : '新建商机'" width="90%" style="max-width: 720px">
      <el-form :model="oppForm" label-width="100px">
        <el-row :gutter="8">
          <el-col :xs="24" :sm="12">
            <el-form-item label="商机名称"><el-input v-model="oppForm.oppName" /></el-form-item>
          </el-col>
          <el-col :xs="24" :sm="12">
            <el-form-item label="客户">
              <el-select v-model="oppForm.customerId" filterable style="width: 100%">
                <el-option v-for="item in customerOptions" :key="item.id" :label="item.customerName" :value="item.id" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :xs="12" :sm="8">
            <el-form-item label="预计金额">
              <el-input-number v-model="oppForm.expectAmount" :min="0" :precision="2" :step="10000" style="width: 100%" />
            </el-form-item>
          </el-col>
          <el-col :xs="12" :sm="8">
            <el-form-item label="预计签约">
              <el-date-picker v-model="oppForm.expectSignDate" type="date" value-format="YYYY-MM-DD" style="width: 100%" />
            </el-form-item>
          </el-col>
          <el-col :xs="12" :sm="8">
            <el-form-item label="赢率(%)">
              <el-input-number v-model="oppForm.winRate" :min="0" :max="100" :precision="1" style="width: 100%" />
            </el-form-item>
          </el-col>
          <el-col :xs="12" :sm="8">
            <el-form-item label="阶段">
              <el-select v-model="oppForm.stage" style="width: 100%">
                <el-option v-for="item in dictOptions('dict_opp_stage', oppStageFallback)" :key="item.value" :label="item.label" :value="item.value" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col v-if="oppEditingId" :xs="12" :sm="8">
            <el-form-item label="状态">
              <el-select v-model="oppForm.status" style="width: 100%">
                <el-option v-for="item in dictOptions('dict_opp_status', oppStatusFallback)" :key="item.value" :label="item.label" :value="item.value" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :xs="24" :sm="8">
            <el-form-item label="负责人">
              <el-select v-model="oppForm.ownerUserId" filterable style="width: 100%" @change="syncOppOwner">
                <el-option v-for="item in staff" :key="item.id" :label="`${item.realName}（${item.username}）`" :value="Number(item.id)" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :xs="24" :sm="12">
            <el-form-item label="来源"><el-input v-model="oppForm.source" placeholder="例如：官网 / 转介绍 / 展会" /></el-form-item>
          </el-col>
          <el-col v-if="oppEditingId && oppForm.status === 'LOST'" :xs="24" :sm="12">
            <el-form-item label="输单原因"><el-input v-model="oppForm.lostReason" /></el-form-item>
          </el-col>
          <el-col :xs="24">
            <el-form-item label="备注"><el-input v-model="oppForm.remark" type="textarea" :rows="2" /></el-form-item>
          </el-col>
        </el-row>
      </el-form>
      <template #footer>
        <el-button @click="oppDialog = false">取消</el-button>
        <el-button type="primary" @click="saveOpp">保存</el-button>
      </template>
    </el-dialog>

    <!-- 转项目 -->
    <el-dialog v-model="convertDialog" title="商机转项目" width="90%" style="max-width: 520px">
      <el-alert
        type="info"
        :closable="false"
        show-icon
        title="将生成项目草稿并回写商机，后续在「项目周期」提交立项审批"
        style="margin-bottom: 12px"
      />
      <el-form :model="convertForm" label-width="100px">
        <el-form-item label="项目名称"><el-input v-model="convertForm.projectName" /></el-form-item>
        <el-form-item label="项目经理">
          <el-select v-model="convertForm.pmId" filterable style="width: 100%">
            <el-option v-for="item in staff" :key="item.id" :label="`${item.realName}（${item.username}）`" :value="Number(item.id)" />
          </el-select>
        </el-form-item>
        <el-form-item label="计划开始">
          <el-date-picker v-model="convertForm.planStart" type="date" value-format="YYYY-MM-DD" style="width: 100%" />
        </el-form-item>
        <el-form-item label="计划结束">
          <el-date-picker v-model="convertForm.planEnd" type="date" value-format="YYYY-MM-DD" style="width: 100%" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="convertDialog = false">取消</el-button>
        <el-button type="primary" @click="doConvert">生成项目</el-button>
      </template>
    </el-dialog>

    <!-- 跟进 -->
    <el-drawer v-model="followDrawer" :title="`跟进 · ${followOpp.oppName || ''}`" size="70%">
      <el-form :model="followForm" label-width="90px" size="small">
        <el-row :gutter="8">
          <el-col :xs="12" :sm="6">
            <el-form-item label="方式">
              <el-select v-model="followForm.followType" style="width: 100%">
                <el-option v-for="item in followTypeOptions" :key="item.value" :label="item.label" :value="item.value" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :xs="12" :sm="6">
            <el-form-item label="跟进日期">
              <el-date-picker v-model="followForm.followTime" type="date" value-format="YYYY-MM-DD" style="width: 100%" />
            </el-form-item>
          </el-col>
          <el-col :xs="24" :sm="12">
            <el-form-item label="下一步"><el-input v-model="followForm.nextPlan" /></el-form-item>
          </el-col>
          <el-col :xs="24">
            <el-form-item label="内容">
              <el-input v-model="followForm.content" type="textarea" :rows="2" placeholder="记录沟通要点" />
            </el-form-item>
          </el-col>
        </el-row>
        <el-button v-if="canOpp" type="primary" size="small" @click="saveFollow">添加跟进</el-button>
      </el-form>

      <el-timeline style="margin-top: 16px">
        <el-timeline-item
          v-for="item in follows"
          :key="item.id"
          :timestamp="`${item.followTime || ''} ${item.creatorName || ''}`"
          placement="top"
        >
          <div>
            <el-tag size="small" type="info">{{ followTypeLabel(item.followType) }}</el-tag>
            <span style="margin-left: 8px">{{ item.content }}</span>
          </div>
          <div v-if="item.nextPlan" style="color: #909399; font-size: 12px; margin-top: 4px">
            下一步：{{ item.nextPlan }}
          </div>
          <el-button v-if="canOpp" link type="danger" size="small" @click="removeFollow(item)">删除</el-button>
        </el-timeline-item>
      </el-timeline>
      <el-empty v-if="!follows.length" description="暂无跟进记录" />
    </el-drawer>
  </div>
</template>
