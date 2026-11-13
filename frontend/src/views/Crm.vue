<script setup lang="ts">
defineOptions({ name: 'CrmPage' })
import { computed, nextTick, onMounted, onUnmounted, ref, type Component } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Building2, CircleDollarSign, Handshake, Plus, TrendingUp } from 'lucide-vue-next'
import {
  addOppFollow,
  changeCustomerStatus,
  changeOppStatus,
  convertOpp,
  createContact,
  createCustomer,
  createOpportunity,
  crmOptions,
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
import { useKeepAliveRefresh } from '@/utils/keepAlive'

type TabKey = 'customers' | 'opportunities'
type TagType = 'primary' | 'success' | 'info' | 'warning' | 'danger'

interface KpiItem {
  key: string
  label: string
  icon: Component
  tone?: string
  value: string
  title: string
}

const store = useUserStore()
const tab = ref<TabKey>('customers')
const canCustomer = computed(() => store.has('crm:customer:manage'))
const canOpp = computed(() => store.has('crm:opp:manage'))

const customerLoading = ref(false)
const oppLoading = ref(false)
const summaryLoading = ref(false)

/** 窄屏把行内操作收进下拉，避免按钮堆叠导致行高失控。 */
const isNarrow = ref(false)
const syncWidth = () => {
  isNarrow.value = window.innerWidth <= 768
}

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

const statusTagType = (status: string): TagType =>
  status === 'COOPERATING' || status === 'WON'
    ? 'success'
    : status === 'LOST' || status === 'BLACKLIST'
      ? 'danger'
      : status === 'CLOSED'
        ? 'info'
        : 'warning'
const stageTagType = (stage: string): TagType =>
  stage === 'WON' ? 'success' : stage === 'LOST' ? 'danger' : stage === 'LEAD' ? 'info' : 'warning'
const levelTagType = (level: string): TagType =>
  level === 'A' ? 'primary' : level === 'B' ? 'success' : 'info'

const toNumber = (value: any, fallback = 0) => {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : fallback
}
/** 雪花 ID 超出 JS 安全整数（后端以字符串返回），只能用字符串透传，`Number()` 会改写末位。 */
const idText = (value: any) => (value === null || value === undefined ? '' : String(value))
/** 提交给后端的 ID 字段：空值用 `'0'` 表示「未指定」，避免空串触发类型校验失败。 */
const idOrZero = (value: any) => {
  const text = idText(value).trim()
  return text === '' || text === '0' ? '0' : text
}
const money = (value: any) =>
  typeof value === 'number'
    ? value.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
    : String(value ?? '—')
const fullAmount = (value: any) => `¥${money(Number(value || 0))}`
/** 概览卡片金额过大时不展示完整数字，详细信息放到 title 里。 */
const amountText = (value: any) => {
  const num = Number(value || 0)
  if (!num) return '¥0'
  if (num >= 100000000) return `¥${(num / 100000000).toFixed(2)} 亿`
  if (num >= 10000) return `¥${(num / 10000).toFixed(1)} 万`
  return `¥${num.toFixed(0)}`
}
const timeText = (value: any) => String(value || '').replace('T', ' ').slice(0, 16)
const userName = (id: any) => {
  const key = idText(id)
  if (!key || key === '0') return '—'
  const hit = staff.value.find((item) => String(item.id) === key)
  // 用户已停用、删除或不在数据范围时不回退雪花 ID，展示可读占位
  return hit ? hit.realName || hit.username || '未知用户' : '未知用户'
}

const kpis = computed<KpiItem[]>(() => {
  const customers = summary.value.customers || {}
  const opps = summary.value.opportunities || {}
  return [
    {
      key: 'total',
      label: '客户总数',
      icon: Building2,
      value: String(customers.total ?? 0),
      title: `潜在 ${customers.potential ?? 0} · 合作中 ${customers.cooperating ?? 0}`
    },
    {
      key: 'cooperating',
      label: '合作中客户',
      icon: Handshake,
      tone: 'primary',
      value: String(customers.cooperating ?? 0),
      title: `已流失 ${customers.lost ?? 0} · 黑名单 ${customers.blacklist ?? 0}`
    },
    {
      key: 'pipeline',
      label: '进行中商机金额',
      icon: TrendingUp,
      tone: 'warning',
      value: amountText(opps.pipelineAmount),
      title: `${opps.open ?? 0} 个进行中商机 · ${fullAmount(opps.pipelineAmount)}`
    },
    {
      key: 'won',
      label: '赢单金额',
      icon: CircleDollarSign,
      tone: 'success',
      value: amountText(opps.wonAmount),
      title: `${opps.won ?? 0} 个赢单商机 · ${fullAmount(opps.wonAmount)}`
    }
  ]
})

/** 脱敏字段不回写（用户无字段权限时保留原值）。 */
const stripMasked = (payload: Record<string, any>) => {
  const result: Record<string, any> = {}
  Object.entries(payload).forEach(([key, value]) => {
    if (typeof value === 'string' && value.includes('****')) return
    result[key] = value
  })
  return result
}

const confirmAction = async (message: string, title = '提示') => {
  try {
    await ElMessageBox.confirm(message, title, {
      type: 'warning',
      confirmButtonText: '确定',
      cancelButtonText: '取消'
    })
    return true
  } catch {
    return false
  }
}

/** 输单原因可留空，返回 null 表示用户取消。 */
const askLostReason = async () => {
  try {
    const result = await ElMessageBox.prompt('请输入输单原因（可留空）', '标记输单', {
      inputPlaceholder: '例如：价格原因 / 竞争对手',
      confirmButtonText: '确定',
      cancelButtonText: '取消'
    })
    return String(result.value ?? '')
  } catch {
    return null
  }
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

/** 赢单阶段由后台参数 `crm.opp.winStage` 决定，前端不再硬编码。 */
const winStage = ref('WON')
const canConvert = (row: any) =>
  Boolean(row) && row.stage === winStage.value && !row.convertedProjectId

const loadOptions = async () => {
  try {
    const data = await crmOptions()
    winStage.value = data.winStage || 'WON'
  } catch {
    winStage.value = 'WON'
  }
}

const loadSummary = async () => {
  summaryLoading.value = true
  try {
    summary.value = await crmSummary()
  } catch {
    summary.value = { customers: {}, opportunities: {} }
  } finally {
    summaryLoading.value = false
  }
}

const loadCustomerOptions = async () => {
  try {
    const data = await listCustomers({ pageNum: 1, pageSize: 200 })
    customerOptions.value = data.list || []
  } catch {
    customerOptions.value = []
  }
}

/** 虚拟化下拉选项：客户可达 200+、人员可达 500，避免一次性渲染全部 DOM。 */
const customerSelectOptions = computed(() =>
  customerOptions.value.map((item: any) => ({
    value: idText(item.id),
    label: item.customerName
  }))
)
const staffSelectOptions = computed(() =>
  staff.value.map((item: any) => ({
    value: idText(item.id),
    label: `${item.realName}（${item.username}）`
  }))
)

/* ------------------------------ 客户 ------------------------------ */
const customers = ref<any[]>([])
const customerTableRef = ref<any>()
const oppTableRef = ref<any>()
const customerTotal = ref(0)
const customerPage = ref({ pageNum: 1, pageSize: 10 })
const customerFilter = ref({ keyword: '', status: '', level: '' })

const loadCustomers = async () => {
  customerLoading.value = true
  try {
    const params: Record<string, any> = { ...customerPage.value }
    if (customerFilter.value.keyword) params.keyword = customerFilter.value.keyword
    if (customerFilter.value.status) params.status = customerFilter.value.status
    if (customerFilter.value.level) params.level = customerFilter.value.level
    const data = await listCustomers(params)
    customers.value = data.list || []
    customerTotal.value = data.total || 0
  } catch {
    /* 错误提示由请求拦截器统一弹出 */
  } finally {
    customerLoading.value = false
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

/** 每页条数变化：回到第一页。 */
const onCustomerSizeChange = () => {
  customerPage.value.pageNum = 1
  loadCustomers()
}

const customerDialog = ref(false)
const customerEditingId = ref('')
const customerForm = ref<any>({})

const emptyCustomer = () => ({
  customerName: '',
  customerLevel: 'B',
  industry: '',
  ownerUserId: idText(store.profile?.id),
  ownerName: store.profile?.realName || '',
  ownerDeptId: idText(store.profile?.deptId),
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
  } else {
    customerForm.value = emptyCustomer()
  }
  customerDialog.value = true
}

const syncCustomerOwner = (userId: any) => {
  const hit = staff.value.find((item) => String(item.id) === String(userId))
  if (hit) customerForm.value.ownerDeptId = idText(hit.deptId)
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
    ownerUserId: idOrZero(customerForm.value.ownerUserId),
    ownerDeptId: idOrZero(customerForm.value.ownerDeptId),
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
  if (!(await confirmAction(`确认删除客户「${row.customerName}」？删除后联系人一并移除。`, '删除客户'))) {
    return
  }
  await deleteCustomer(String(row.id))
  ElMessage.success('客户已删除')
  await Promise.all([loadCustomers(), loadCustomerOptions(), loadSummary()])
}

/* ------------------------------ 联系人 ------------------------------ */
const contactDrawer = ref(false)
const contactCustomer = ref<any>({})
const contactLoading = ref(false)
const contacts = ref<any[]>([])
const contactDialog = ref(false)
const contactEditingId = ref('')
const contactForm = ref<any>({})

const loadContacts = async () => {
  contactLoading.value = true
  try {
    contacts.value = await customerContacts(String(contactCustomer.value.id))
  } catch {
    contacts.value = []
  } finally {
    contactLoading.value = false
  }
}

const openContacts = async (row: any) => {
  contactCustomer.value = row
  contacts.value = []
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
  if (!(await confirmAction(`确认删除联系人「${row.name}」？`, '删除联系人'))) return
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
  oppLoading.value = true
  try {
    const params: Record<string, any> = { ...oppPage.value }
    if (oppFilter.value.keyword) params.keyword = oppFilter.value.keyword
    if (oppFilter.value.customerId) params.customerId = oppFilter.value.customerId
    if (oppFilter.value.stage) params.stage = oppFilter.value.stage
    if (oppFilter.value.status) params.status = oppFilter.value.status
    const data = await listOpportunities(params)
    opportunities.value = data.list || []
    oppTotal.value = data.total || 0
  } catch {
    /* 错误提示由请求拦截器统一弹出 */
  } finally {
    oppLoading.value = false
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

/** 每页条数变化：回到第一页。 */
const onOppSizeChange = () => {
  oppPage.value.pageNum = 1
  loadOpps()
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
  ownerUserId: idText(store.profile?.id),
  ownerName: store.profile?.realName || '',
  ownerDeptId: idText(store.profile?.deptId),
  remark: ''
})

const openOpp = async (row?: any) => {
  oppEditingId.value = row ? String(row.id) : ''
  if (row) {
    const detail = await opportunityDetail(String(row.id))
    oppForm.value = { ...emptyOpp(), ...detail }
    // 客户 / 负责人 ID 保持字符串（雪花 ID 转数字会改写末位）
    const customerId = idText(oppForm.value.customerId)
    oppForm.value.customerId = customerId && customerId !== '0' ? customerId : null
    oppForm.value.ownerUserId = idText(oppForm.value.ownerUserId)
    oppForm.value.ownerDeptId = idText(oppForm.value.ownerDeptId)
    oppForm.value.expectAmount = toNumber(oppForm.value.expectAmount)
    oppForm.value.winRate = toNumber(oppForm.value.winRate)
    oppForm.value.expectSignDate = oppForm.value.expectSignDate || ''
  } else {
    oppForm.value = emptyOpp()
  }
  oppDialog.value = true
}

const syncOppOwner = (userId: any) => {
  const hit = staff.value.find((item) => String(item.id) === String(userId))
  if (hit) oppForm.value.ownerDeptId = idText(hit.deptId)
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
    customerId: idText(oppForm.value.customerId),
    expectAmount: Number(oppForm.value.expectAmount || 0),
    expectSignDate: oppForm.value.expectSignDate || '',
    stage: oppForm.value.stage,
    winRate: Number(oppForm.value.winRate || 0),
    source: oppForm.value.source,
    ownerUserId: idOrZero(oppForm.value.ownerUserId),
    ownerDeptId: idOrZero(oppForm.value.ownerDeptId),
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
    const reason = await askLostReason()
    if (reason === null) return
    lostReason = reason
  }
  await pushOppStage(String(row.id), stage, lostReason)
  ElMessage.success(`商机阶段已推进到 ${oppStageLabel(stage)}`)
  await Promise.all([loadOpps(), loadSummary()])
}

const quickOppStatus = async (row: any, status: string) => {
  if (!status || status === row.status) return
  let lostReason = ''
  if (status === 'LOST') {
    const reason = await askLostReason()
    if (reason === null) return
    lostReason = reason
  }
  await changeOppStatus(String(row.id), status, lostReason)
  ElMessage.success(`商机状态已改为 ${oppStatusLabel(status)}`)
  await Promise.all([loadOpps(), loadSummary()])
}

const removeOpp = async (row: any) => {
  if (!(await confirmAction(`确认删除商机「${row.oppName}」？`, '删除商机'))) return
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
    pmId: idText(row.ownerUserId || store.profile?.id),
    planStart: '',
    planEnd: ''
  }
  convertDialog.value = true
}

/**
 * 历史数据的负责人/客户可能已停用或不在当前数据范围，补一个回显项，
 * 避免虚拟下拉找不到选项时直接展示雪花 ID。
 */
const withSelectedOption = (
  options: { value: string; label: string }[],
  value: unknown,
  label?: string,
  fallbackLabel = '未知用户'
) => {
  const key = idText(value)
  if (!key || key === '0' || options.some((item) => item.value === key)) return options
  return [{ value: key, label: label || fallbackLabel }, ...options]
}

const customerOwnerOptions = computed(() =>
  withSelectedOption(
    staffSelectOptions.value,
    customerForm.value.ownerUserId,
    customerForm.value.ownerName
  )
)
const oppOwnerOptions = computed(() =>
  withSelectedOption(staffSelectOptions.value, oppForm.value.ownerUserId, oppForm.value.ownerName)
)
const oppCustomerOptions = computed(() =>
  withSelectedOption(
    customerSelectOptions.value,
    oppForm.value.customerId,
    oppForm.value.customerName,
    '未知客户'
  )
)
const convertPmOptions = computed(() =>
  withSelectedOption(staffSelectOptions.value, convertForm.value.pmId, convertRow.value.ownerName)
)

const doConvert = async () => {
  const result = await convertOpp(String(convertRow.value.id), {
    projectName: convertForm.value.projectName,
    pmId: idOrZero(convertForm.value.pmId),
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
const followLoading = ref(false)
const followSaving = ref(false)
const followForm = ref<any>({ content: '', followType: 'PHONE', nextPlan: '', followTime: '' })

const loadFollows = async () => {
  followLoading.value = true
  try {
    follows.value = await oppFollows(String(followOpp.value.id))
  } catch {
    follows.value = []
  } finally {
    followLoading.value = false
  }
}

const openFollows = async (row: any) => {
  followOpp.value = row
  followForm.value = { content: '', followType: 'PHONE', nextPlan: '', followTime: '' }
  follows.value = []
  followDrawer.value = true
  await loadFollows()
}

const saveFollow = async () => {
  if (!followForm.value.content?.trim()) {
    ElMessage.warning('请填写跟进内容')
    return
  }
  followSaving.value = true
  try {
    await addOppFollow(String(followOpp.value.id), {
      content: followForm.value.content.trim(),
      followType: followForm.value.followType,
      nextPlan: followForm.value.nextPlan,
      followTime: followForm.value.followTime || null
    })
    ElMessage.success('跟进记录已添加')
    followForm.value = { content: '', followType: 'PHONE', nextPlan: '', followTime: '' }
    await loadFollows()
  } catch {
    /* 错误提示由请求拦截器统一弹出 */
  } finally {
    followSaving.value = false
  }
}

const removeFollow = async (row: any) => {
  if (!(await confirmAction('确认删除该跟进记录？', '删除跟进'))) return
  await deleteOppFollow(String(row.id))
  ElMessage.success('跟进记录已删除')
  await loadFollows()
}

/* ------------------------------ 交互 ------------------------------ */
const switchTab = (key: TabKey) => {
  if (tab.value === key) return
  tab.value = key
  // 两个表格常驻后用 v-show 切换，显示时需要重算列宽
  nextTick(() => {
    const table = key === 'customers' ? customerTableRef.value : oppTableRef.value
    table?.doLayout?.()
  })
}

const refreshAll = async () => {
  await Promise.all([loadSummary(), loadCustomers(), loadOpps(), loadCustomerOptions()])
  markLoaded()
}

const { markLoaded } = useKeepAliveRefresh(refreshAll)

const onCustomerCommand = (command: string, row: any) => {
  if (command === 'edit') openCustomer(row)
  else if (command === 'contacts') openContacts(row)
  else if (command === 'delete') removeCustomer(row)
}

const onOppCommand = (command: string, row: any) => {
  if (command === 'edit') openOpp(row)
  else if (command === 'follows') openFollows(row)
  else if (command === 'convert') openConvert(row)
  else if (command === 'delete') removeOpp(row)
}

onMounted(async () => {
  syncWidth()
  window.addEventListener('resize', syncWidth)
  await Promise.all([loadDicts(), loadStaff(), loadOptions()])
  await refreshAll()
})

onUnmounted(() => window.removeEventListener('resize', syncWidth))
</script>

<template>
  <div class="pms-page">
    <section class="kpi-board" v-loading="summaryLoading">
      <article
        v-for="item in kpis"
        :key="item.key"
        class="kpi"
        :class="`tone-${item.tone || 'default'}`"
        :title="item.title"
      >
        <span class="kpi-icon">
          <component :is="item.icon" :size="16" :stroke-width="1.75" />
        </span>
        <span class="kpi-value">{{ item.value }}</span>
        <span class="kpi-label">{{ item.label }}</span>
      </article>
    </section>

    <div class="pms-card list-card">
      <div class="list-head">
        <div class="seg">
          <button
            type="button"
            :class="{ 'is-active': tab === 'customers' }"
            @click="switchTab('customers')"
          >
            客户
          </button>
          <button
            type="button"
            :class="{ 'is-active': tab === 'opportunities' }"
            @click="switchTab('opportunities')"
          >
            商机
          </button>
        </div>
        <div class="list-side">
          <span class="list-total">
            共 {{ tab === 'customers' ? customerTotal : oppTotal }} 条
          </span>
          <el-button
            size="small"
            :loading="customerLoading || oppLoading || summaryLoading"
            @click="refreshAll"
          >
            刷新
          </el-button>
          <el-button
            v-if="tab === 'customers' && canCustomer"
            type="primary"
            :icon="Plus"
            class="pms-create-btn"
            @click="openCustomer()"
          >
            新增客户
          </el-button>
          <el-button
            v-if="tab === 'opportunities' && canOpp"
            type="primary"
            :icon="Plus"
            class="pms-create-btn"
            @click="openOpp()"
          >
            新增商机
          </el-button>
        </div>
      </div>

      <!-- 客户筛选 -->
      <div v-if="tab === 'customers'" class="filter-row">
        <el-input
          v-model="customerFilter.keyword"
          class="f-keyword"
          placeholder="名称 / 编码 / 联系人 / 手机"
          clearable
          @keyup.enter="searchCustomers"
          @clear="searchCustomers"
        />
        <el-select
          v-model="customerFilter.status"
          class="f-status"
          placeholder="客户状态"
          clearable
          @change="searchCustomers"
        >
          <el-option
            v-for="item in dictOptions('dict_customer_status', customerStatusFallback)"
            :key="item.value"
            :label="item.label"
            :value="item.value"
          />
        </el-select>
        <el-select
          v-model="customerFilter.level"
          class="f-level"
          placeholder="客户等级"
          clearable
          @change="searchCustomers"
        >
          <el-option
            v-for="item in dictOptions('dict_customer_level', customerLevelFallback)"
            :key="item.value"
            :label="item.label"
            :value="item.value"
          />
        </el-select>
        <div class="filter-actions">
          <el-button type="primary" :loading="customerLoading" @click="searchCustomers">
            查询
          </el-button>
          <el-button @click="resetCustomerFilter">重置</el-button>
        </div>
      </div>

      <!-- 商机筛选 -->
      <div v-else class="filter-row">
        <el-input
          v-model="oppFilter.keyword"
          class="f-keyword"
          placeholder="商机名称 / 编号"
          clearable
          @keyup.enter="searchOpps"
          @clear="searchOpps"
        />
        <el-select-v2
          v-model="oppFilter.customerId"
          class="f-customer"
          :options="customerSelectOptions"
          placeholder="全部客户"
          clearable
          filterable
          @change="searchOpps"
        />
        <el-select
          v-model="oppFilter.stage"
          class="f-status"
          placeholder="全部阶段"
          clearable
          @change="searchOpps"
        >
          <el-option
            v-for="item in dictOptions('dict_opp_stage', oppStageFallback)"
            :key="item.value"
            :label="item.label"
            :value="item.value"
          />
        </el-select>
        <el-select
          v-model="oppFilter.status"
          class="f-status"
          placeholder="全部状态"
          clearable
          @change="searchOpps"
        >
          <el-option
            v-for="item in dictOptions('dict_opp_status', oppStatusFallback)"
            :key="item.value"
            :label="item.label"
            :value="item.value"
          />
        </el-select>
        <div class="filter-actions">
          <el-button type="primary" :loading="oppLoading" @click="searchOpps">查询</el-button>
          <el-button @click="resetOppFilter">重置</el-button>
        </div>
      </div>

      <!-- 客户列表 -->
      <el-table
        v-show="tab === 'customers'"
        ref="customerTableRef"
        v-loading="customerLoading"
        :data="customers"
        size="small"
        empty-text="暂无客户"
      >
        <el-table-column label="客户名称" min-width="200">
          <template #default="{ row }">
            <div class="cell-stack">
              <span class="cell-main" :title="row.customerName">{{ row.customerName }}</span>
              <span class="cell-sub">{{ row.customerCode || '—' }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="等级" width="86">
          <template #default="{ row }">
            <el-tag :type="levelTagType(row.customerLevel)" size="small" effect="plain">
              {{ customerLevelLabel(row.customerLevel) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="行业" min-width="110" class-name="pms-mobile-hide">
          <template #default="{ row }">
            <span :class="{ 'cell-muted': !row.industry }">{{ row.industry || '—' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="116">
          <template #default="{ row }">
            <el-dropdown
              v-if="canCustomer"
              trigger="click"
              placement="bottom-start"
              @command="(value) => quickCustomerStatus(row, value)"
            >
              <el-tag
                :type="statusTagType(row.status)"
                size="small"
                effect="plain"
                class="tag-trigger"
                title="点击切换客户状态"
              >
                {{ customerStatusLabel(row.status) }}
              </el-tag>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item
                    v-for="item in dictOptions('dict_customer_status', customerStatusFallback)"
                    :key="item.value"
                    :command="item.value"
                    :disabled="item.value === row.status"
                  >
                    {{ item.label }}
                  </el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
            <el-tag v-else :type="statusTagType(row.status)" size="small" effect="plain">
              {{ customerStatusLabel(row.status) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="联系人" min-width="150" class-name="pms-mobile-hide">
          <template #default="{ row }">
            <div class="cell-stack">
              <span class="cell-main">{{ row.contactName || '—' }}</span>
              <span v-if="row.contactMobile" class="cell-sub">{{ row.contactMobile }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="负责人" width="96" class-name="pms-mobile-hide">
          <template #default="{ row }">{{ row.ownerName || userName(row.ownerUserId) }}</template>
        </el-table-column>
        <el-table-column label="创建时间" width="140" class-name="pms-mobile-hide">
          <template #default="{ row }">
            <span class="cell-muted">{{ timeText(row.createTime) || '—' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" :width="isNarrow ? 92 : 186" fixed="right">
          <template #default="{ row }">
            <el-dropdown
              v-if="isNarrow"
              trigger="click"
              placement="bottom-end"
              @command="(command) => onCustomerCommand(command, row)"
            >
              <el-button size="small">操作</el-button>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item command="contacts">联系人</el-dropdown-item>
                  <el-dropdown-item command="edit" :disabled="!canCustomer">编辑客户</el-dropdown-item>
                  <el-dropdown-item v-if="canCustomer" command="delete" divided>
                    删除客户
                  </el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
            <div v-else class="op-actions">
              <el-button size="small" :disabled="!canCustomer" @click="openCustomer(row)">
                编辑
              </el-button>
              <el-button link type="primary" size="small" @click="openContacts(row)">
                联系人
              </el-button>
              <el-button
                v-if="canCustomer"
                link
                type="danger"
                size="small"
                @click="removeCustomer(row)"
              >
                删除
              </el-button>
            </div>
          </template>
        </el-table-column>
      </el-table>

      <!-- 商机列表 -->
      <el-table
        v-show="tab !== 'customers'"
        ref="oppTableRef"
        v-loading="oppLoading"
        :data="opportunities"
        size="small"
        empty-text="暂无商机"
      >
        <el-table-column label="商机名称" min-width="200">
          <template #default="{ row }">
            <div class="cell-stack">
              <span class="cell-main" :title="row.oppName">{{ row.oppName }}</span>
              <span class="cell-sub">{{ row.oppCode || '—' }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="客户" min-width="140" class-name="pms-mobile-hide">
          <template #default="{ row }">
            <span class="cell-ellipsis" :title="row.customerName">{{ row.customerName || '—' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="阶段" width="110">
          <template #default="{ row }">
            <el-dropdown
              v-if="canOpp"
              trigger="click"
              placement="bottom-start"
              @command="(value) => quickOppStage(row, value)"
            >
              <el-tag
                :type="stageTagType(row.stage)"
                size="small"
                effect="plain"
                class="tag-trigger"
                title="点击推进商机阶段"
              >
                {{ oppStageLabel(row.stage) }}
              </el-tag>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item
                    v-for="item in dictOptions('dict_opp_stage', oppStageFallback)"
                    :key="item.value"
                    :command="item.value"
                    :disabled="item.value === row.stage"
                  >
                    {{ item.label }}
                  </el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
            <el-tag v-else :type="stageTagType(row.stage)" size="small" effect="plain">
              {{ oppStageLabel(row.stage) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="预计金额" width="132" align="right">
          <template #default="{ row }">
            <span class="amount-cell">¥{{ money(row.expectAmount) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="赢率" width="82" align="right" class-name="pms-mobile-hide">
          <template #default="{ row }">
            <span class="cell-muted">{{ Number(row.winRate || 0) }}%</span>
          </template>
        </el-table-column>
        <el-table-column label="预计签约" width="116" class-name="pms-mobile-hide">
          <template #default="{ row }">
            <span :class="{ 'cell-muted': !row.expectSignDate }">
              {{ row.expectSignDate || '—' }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="116">
          <template #default="{ row }">
            <el-dropdown
              v-if="canOpp"
              trigger="click"
              placement="bottom-start"
              @command="(value) => quickOppStatus(row, value)"
            >
              <el-tag
                :type="statusTagType(row.status)"
                size="small"
                effect="plain"
                class="tag-trigger"
                title="点击切换商机状态"
              >
                {{ oppStatusLabel(row.status) }}
              </el-tag>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item
                    v-for="item in dictOptions('dict_opp_status', oppStatusFallback)"
                    :key="item.value"
                    :command="item.value"
                    :disabled="item.value === row.status"
                  >
                    {{ item.label }}
                  </el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
            <el-tag v-else :type="statusTagType(row.status)" size="small" effect="plain">
              {{ oppStatusLabel(row.status) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="负责人" width="96" class-name="pms-mobile-hide">
          <template #default="{ row }">{{ row.ownerName || userName(row.ownerUserId) }}</template>
        </el-table-column>
        <el-table-column label="操作" :width="isNarrow ? 92 : 238" fixed="right">
          <template #default="{ row }">
            <el-dropdown
              v-if="isNarrow"
              trigger="click"
              placement="bottom-end"
              @command="(command) => onOppCommand(command, row)"
            >
              <el-button size="small">操作</el-button>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item command="follows">跟进记录</el-dropdown-item>
                  <el-dropdown-item command="edit" :disabled="!canOpp">编辑商机</el-dropdown-item>
                  <el-dropdown-item command="convert" :disabled="!canConvert(row)">
                    {{ row.convertedProjectId ? '已转项目' : '转为项目' }}
                  </el-dropdown-item>
                  <el-dropdown-item v-if="canOpp" command="delete" divided>删除商机</el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
            <div v-else class="op-actions">
              <el-button size="small" :disabled="!canOpp" @click="openOpp(row)">编辑</el-button>
              <el-button link type="primary" size="small" @click="openFollows(row)">
                跟进
              </el-button>
              <el-button
                v-if="canOpp"
                link
                type="success"
                size="small"
                :disabled="!canConvert(row)"
                @click="openConvert(row)"
              >
                {{ row.convertedProjectId ? '已转项目' : '转项目' }}
              </el-button>
              <el-button v-if="canOpp" link type="danger" size="small" @click="removeOpp(row)">
                删除
              </el-button>
            </div>
          </template>
        </el-table-column>
      </el-table>

      <el-pagination
        v-if="tab === 'customers'"
        v-model:current-page="customerPage.pageNum"
        v-model:page-size="customerPage.pageSize"
        :total="customerTotal"
        :page-sizes="[10, 20, 50]"
        :layout="isNarrow ? 'prev, pager, next' : 'total, sizes, prev, pager, next'"
        class="pager"
        @current-change="loadCustomers"
        @size-change="onCustomerSizeChange"
      />
      <el-pagination
        v-else
        v-model:current-page="oppPage.pageNum"
        v-model:page-size="oppPage.pageSize"
        :total="oppTotal"
        :page-sizes="[10, 20, 50]"
        :layout="isNarrow ? 'prev, pager, next' : 'total, sizes, prev, pager, next'"
        class="pager"
        @current-change="loadOpps"
        @size-change="onOppSizeChange"
      />
    </div>

    <!-- 客户编辑 -->
    <el-dialog
      v-model="customerDialog"
      :title="customerEditingId ? '编辑客户' : '新增客户'"
      width="min(720px, 94vw)"
      :close-on-click-modal="false"
    >
      <div v-if="customerEditingId" class="dialog-id">
        <span class="dialog-avatar" aria-hidden="true">
          {{ (customerForm.customerName || '客').slice(0, 1) }}
        </span>
        <div class="dialog-id-meta">
          <div class="dialog-id-line">
            <span class="dialog-id-name">{{ customerForm.customerName || '未命名' }}</span>
            <el-tag :type="statusTagType(customerForm.status)" size="small" effect="plain">
              {{ customerStatusLabel(customerForm.status) }}
            </el-tag>
          </div>
          <div class="dialog-id-sub">
            {{ customerForm.customerCode || '暂无编码' }}
            <span class="dot">·</span>{{ customerLevelLabel(customerForm.customerLevel) }}
            <span class="dot">·</span>{{ userName(customerForm.ownerUserId) }}
          </div>
        </div>
      </div>

      <div class="form-section-title">基本信息</div>
      <el-form :model="customerForm" label-width="92px" class="form-grid">
        <el-form-item label="客户名称">
          <el-input v-model="customerForm.customerName" placeholder="公司全称" />
        </el-form-item>
        <el-form-item label="行业">
          <el-input v-model="customerForm.industry" placeholder="如 制造业 / 互联网" />
        </el-form-item>
        <el-form-item label="客户等级">
          <el-select v-model="customerForm.customerLevel" placeholder="选择等级">
            <el-option
              v-for="item in dictOptions('dict_customer_level', customerLevelFallback)"
              :key="item.value"
              :label="item.label"
              :value="item.value"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="客户状态">
          <el-select v-model="customerForm.status" placeholder="选择状态">
            <el-option
              v-for="item in dictOptions('dict_customer_status', customerStatusFallback)"
              :key="item.value"
              :label="item.label"
              :value="item.value"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="负责人">
          <el-select-v2
            v-model="customerForm.ownerUserId"
            :options="customerOwnerOptions"
            filterable
            @change="syncCustomerOwner"
          />
        </el-form-item>
        <el-form-item label="来源">
          <el-input v-model="customerForm.source" placeholder="如 官网 / 转介绍 / 展会" />
        </el-form-item>
      </el-form>

      <div class="form-section-title">联系方式</div>
      <el-form :model="customerForm" label-width="92px" class="form-grid">
        <el-form-item label="联系人">
          <el-input v-model="customerForm.contactName" placeholder="选填" />
        </el-form-item>
        <el-form-item label="联系电话">
          <el-input v-model="customerForm.contactMobile" placeholder="选填" />
        </el-form-item>
        <el-form-item label="邮箱" class="span-2">
          <el-input v-model="customerForm.contactEmail" placeholder="选填" />
        </el-form-item>
        <el-form-item label="省份">
          <el-input v-model="customerForm.province" placeholder="选填" />
        </el-form-item>
        <el-form-item label="城市">
          <el-input v-model="customerForm.city" placeholder="选填" />
        </el-form-item>
        <el-form-item label="详细地址" class="span-2">
          <el-input v-model="customerForm.address" placeholder="选填" />
        </el-form-item>
        <el-form-item label="备注" class="span-2">
          <el-input v-model="customerForm.remark" type="textarea" :rows="2" maxlength="500" />
        </el-form-item>
      </el-form>

      <template #footer>
        <div class="dialog-footer">
          <span class="form-tip">客户名称必填；负责人决定该客户的数据可见范围。</span>
          <div class="dialog-actions">
            <el-button @click="customerDialog = false">取消</el-button>
            <el-button type="primary" @click="saveCustomer">保存</el-button>
          </div>
        </div>
      </template>
    </el-dialog>

    <!-- 联系人 -->
    <el-drawer
      v-model="contactDrawer"
      :title="`联系人 · ${contactCustomer.customerName || ''}`"
      size="min(1080px, 96vw)"
    >
      <div class="detail">
        <div class="detail-head">
          <div>
            <h3>{{ contactCustomer.customerName || '未命名客户' }}</h3>
            <p class="detail-meta">
              {{ contactCustomer.customerCode || '暂无编码' }}
              <span class="dot">·</span>{{ customerLevelLabel(contactCustomer.customerLevel) }}
              <span class="dot">·</span>负责人
              {{ contactCustomer.ownerName || userName(contactCustomer.ownerUserId) }}
            </p>
          </div>
          <div class="detail-tags">
            <el-tag :type="statusTagType(contactCustomer.status)" size="small" effect="plain">
              {{ customerStatusLabel(contactCustomer.status) }}
            </el-tag>
          </div>
        </div>

        <div class="list-head">
          <span class="list-total">共 {{ contacts.length }} 位联系人</span>
          <el-button
            v-if="canCustomer"
            type="primary"
            :icon="Plus"
            class="pms-create-btn"
            @click="openContact()"
          >
            新增联系人
          </el-button>
        </div>

        <el-table
          v-loading="contactLoading"
          :data="contacts"
          size="small"
          empty-text="暂无联系人"
        >
          <el-table-column label="姓名" width="110">
            <template #default="{ row }">
              <div class="cell-stack">
                <span class="cell-main">{{ row.name }}</span>
                <span v-if="row.title" class="cell-sub">{{ row.title }}</span>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="手机" width="124">
            <template #default="{ row }">
              <span :class="{ 'cell-muted': !row.mobile }">{{ row.mobile || '—' }}</span>
            </template>
          </el-table-column>
          <el-table-column label="邮箱" min-width="150">
            <template #default="{ row }">
              <span class="cell-ellipsis" :class="{ 'cell-muted': !row.email }">
                {{ row.email || '—' }}
              </span>
            </template>
          </el-table-column>
          <el-table-column label="微信" width="110" class-name="pms-mobile-hide">
            <template #default="{ row }">
              <span :class="{ 'cell-muted': !row.wechat }">{{ row.wechat || '—' }}</span>
            </template>
          </el-table-column>
          <el-table-column label="主联系人" width="84">
            <template #default="{ row }">
              <el-tag v-if="row.isPrimary" type="success" size="small" effect="plain">是</el-tag>
              <span v-else class="cell-muted">—</span>
            </template>
          </el-table-column>
          <el-table-column label="备注" min-width="120" class-name="pms-mobile-hide">
            <template #default="{ row }">
              <span class="cell-ellipsis" :class="{ 'cell-muted': !row.remark }">
                {{ row.remark || '—' }}
              </span>
            </template>
          </el-table-column>
          <el-table-column
            v-if="canCustomer"
            label="操作"
            :width="isNarrow ? 92 : 168"
            fixed="right"
          >
            <template #default="{ row }">
              <el-dropdown
                v-if="isNarrow"
                trigger="click"
                placement="bottom-end"
                @command="(command) => command === 'edit' ? openContact(row) : removeContact(row)"
              >
                <el-button size="small">操作</el-button>
                <template #dropdown>
                  <el-dropdown-menu>
                    <el-dropdown-item command="edit">编辑</el-dropdown-item>
                    <el-dropdown-item command="delete" divided>删除</el-dropdown-item>
                  </el-dropdown-menu>
                </template>
              </el-dropdown>
              <div v-else class="op-actions">
                <el-button size="small" @click="openContact(row)">编辑</el-button>
                <el-button v-if="!row.isPrimary" link type="primary" size="small" @click="setPrimaryContact(row)">
                  设为主
                </el-button>
                <el-button link type="danger" size="small" @click="removeContact(row)">删除</el-button>
              </div>
            </template>
          </el-table-column>
        </el-table>
      </div>
      <template #footer>
        <div class="drawer-footer">
          <span class="footer-tip">主联系人默认用于合同与通知送达</span>
          <span class="footer-spacer"></span>
          <el-button @click="contactDrawer = false">关闭</el-button>
        </div>
      </template>
    </el-drawer>

    <el-dialog
      v-model="contactDialog"
      :title="contactEditingId ? '编辑联系人' : '新增联系人'"
      width="min(520px, 94vw)"
      :close-on-click-modal="false"
    >
      <el-form :model="contactForm" label-width="80px">
        <el-form-item label="姓名">
          <el-input v-model="contactForm.name" placeholder="联系人姓名" />
        </el-form-item>
        <el-form-item label="职务">
          <el-input v-model="contactForm.title" placeholder="选填" />
        </el-form-item>
        <el-form-item label="手机">
          <el-input v-model="contactForm.mobile" placeholder="选填" />
        </el-form-item>
        <el-form-item label="邮箱">
          <el-input v-model="contactForm.email" placeholder="选填" />
        </el-form-item>
        <el-form-item label="微信">
          <el-input v-model="contactForm.wechat" placeholder="选填" />
        </el-form-item>
        <el-form-item label="主联系人">
          <el-switch v-model="contactForm.isPrimary" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="contactForm.remark" type="textarea" :rows="2" maxlength="200" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="contactDialog = false">取消</el-button>
        <el-button type="primary" @click="saveContact">保存</el-button>
      </template>
    </el-dialog>

    <!-- 商机编辑 -->
    <el-dialog
      v-model="oppDialog"
      :title="oppEditingId ? '编辑商机' : '新增商机'"
      width="min(720px, 94vw)"
      :close-on-click-modal="false"
    >
      <div v-if="oppEditingId" class="dialog-id">
        <span class="dialog-avatar" aria-hidden="true">
          {{ (oppForm.oppName || '商').slice(0, 1) }}
        </span>
        <div class="dialog-id-meta">
          <div class="dialog-id-line">
            <span class="dialog-id-name">{{ oppForm.oppName || '未命名' }}</span>
            <el-tag :type="stageTagType(oppForm.stage)" size="small" effect="plain">
              {{ oppStageLabel(oppForm.stage) }}
            </el-tag>
            <el-tag :type="statusTagType(oppForm.status)" size="small" effect="plain">
              {{ oppStatusLabel(oppForm.status) }}
            </el-tag>
          </div>
          <div class="dialog-id-sub">
            {{ oppForm.oppCode || '暂无编码' }}
            <span class="dot">·</span>{{ userName(oppForm.ownerUserId) }}
          </div>
        </div>
      </div>

      <div class="form-section-title">基本信息</div>
      <el-form :model="oppForm" label-width="92px" class="form-grid">
        <el-form-item label="商机名称">
          <el-input v-model="oppForm.oppName" placeholder="如 XX 公司 PMS 实施" />
        </el-form-item>
        <el-form-item label="所属客户">
          <el-select-v2
            v-model="oppForm.customerId"
            :options="oppCustomerOptions"
            filterable
            placeholder="选择客户"
          />
        </el-form-item>
        <el-form-item label="负责人">
          <el-select-v2
            v-model="oppForm.ownerUserId"
            :options="oppOwnerOptions"
            filterable
            @change="syncOppOwner"
          />
        </el-form-item>
        <el-form-item label="来源">
          <el-input v-model="oppForm.source" placeholder="如 官网 / 转介绍 / 展会" />
        </el-form-item>
      </el-form>

      <div class="form-section-title">金额与阶段</div>
      <el-form :model="oppForm" label-width="92px" class="form-grid">
        <el-form-item label="预计金额">
          <el-input-number
            v-model="oppForm.expectAmount"
            :min="0"
            :precision="2"
            :step="10000"
            controls-position="right"
          />
        </el-form-item>
        <el-form-item label="预计签约">
          <el-date-picker
            v-model="oppForm.expectSignDate"
            type="date"
            value-format="YYYY-MM-DD"
            placeholder="选择日期"
          />
        </el-form-item>
        <el-form-item label="赢率(%)">
          <el-input-number
            v-model="oppForm.winRate"
            :min="0"
            :max="100"
            :precision="1"
            controls-position="right"
          />
        </el-form-item>
        <el-form-item label="当前阶段">
          <el-select v-model="oppForm.stage" placeholder="选择阶段">
            <el-option
              v-for="item in dictOptions('dict_opp_stage', oppStageFallback)"
              :key="item.value"
              :label="item.label"
              :value="item.value"
            />
          </el-select>
        </el-form-item>
        <el-form-item v-if="oppEditingId" label="当前状态">
          <el-select v-model="oppForm.status" placeholder="选择状态">
            <el-option
              v-for="item in dictOptions('dict_opp_status', oppStatusFallback)"
              :key="item.value"
              :label="item.label"
              :value="item.value"
            />
          </el-select>
        </el-form-item>
        <el-form-item v-if="oppEditingId && oppForm.status === 'LOST'" label="输单原因">
          <el-input v-model="oppForm.lostReason" placeholder="记录丢单原因，便于复盘" />
        </el-form-item>
        <el-form-item label="备注" class="span-2">
          <el-input v-model="oppForm.remark" type="textarea" :rows="2" maxlength="500" />
        </el-form-item>
      </el-form>

      <template #footer>
        <div class="dialog-footer">
          <span class="form-tip">
            商机进入「{{ oppStageLabel(winStage) }}」阶段后，可在列表中转为项目。
          </span>
          <div class="dialog-actions">
            <el-button @click="oppDialog = false">取消</el-button>
            <el-button type="primary" @click="saveOpp">保存</el-button>
          </div>
        </div>
      </template>
    </el-dialog>

    <!-- 转项目 -->
    <el-dialog
      v-model="convertDialog"
      title="商机转项目"
      width="min(540px, 94vw)"
      :close-on-click-modal="false"
    >
      <el-alert
        type="info"
        :closable="false"
        show-icon
        title="将生成项目草稿并回写商机，后续在「项目周期」提交立项审批"
        style="margin-bottom: 16px"
      />
      <el-form :model="convertForm" label-width="88px" class="form-grid">
        <el-form-item label="项目名称" class="span-2">
          <el-input v-model="convertForm.projectName" />
        </el-form-item>
        <el-form-item label="项目经理" class="span-2">
          <el-select-v2
            v-model="convertForm.pmId"
            :options="convertPmOptions"
            filterable
            placeholder="选择项目经理"
          />
        </el-form-item>
        <el-form-item label="计划开始">
          <el-date-picker
            v-model="convertForm.planStart"
            type="date"
            value-format="YYYY-MM-DD"
            placeholder="选择日期"
          />
        </el-form-item>
        <el-form-item label="计划结束">
          <el-date-picker
            v-model="convertForm.planEnd"
            type="date"
            value-format="YYYY-MM-DD"
            placeholder="选择日期"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="convertDialog = false">取消</el-button>
        <el-button type="primary" @click="doConvert">生成项目</el-button>
      </template>
    </el-dialog>

    <!-- 跟进 -->
    <el-drawer
      v-model="followDrawer"
      :title="`跟进 · ${followOpp.oppName || ''}`"
      size="min(620px, 94vw)"
    >
      <div class="detail">
        <div class="detail-head">
          <div>
            <h3>{{ followOpp.oppName || '未命名商机' }}</h3>
            <p class="detail-meta">
              {{ followOpp.oppCode || '暂无编码' }}
              <span class="dot">·</span>{{ followOpp.customerName || '未关联客户' }}
            </p>
          </div>
          <div class="detail-tags">
            <el-tag :type="stageTagType(followOpp.stage)" size="small" effect="plain">
              {{ oppStageLabel(followOpp.stage) }}
            </el-tag>
            <el-tag :type="statusTagType(followOpp.status)" size="small" effect="plain">
              {{ oppStatusLabel(followOpp.status) }}
            </el-tag>
          </div>
        </div>

        <div class="metrics">
          <div class="metric">
            <span>预计金额</span>
            <b>¥{{ money(followOpp.expectAmount) }}</b>
          </div>
          <div class="metric">
            <span>赢率</span>
            <b>{{ Number(followOpp.winRate || 0) }}%</b>
          </div>
          <div class="metric">
            <span>预计签约</span>
            <b>{{ followOpp.expectSignDate || '未设置' }}</b>
          </div>
          <div class="metric">
            <span>负责人</span>
            <b>{{ followOpp.ownerName || userName(followOpp.ownerUserId) }}</b>
          </div>
        </div>

        <section v-if="canOpp" class="detail-section">
          <h4>记录跟进</h4>
          <div class="field-grid">
            <div class="field">
              <label>跟进方式</label>
              <el-select v-model="followForm.followType" placeholder="选择方式">
                <el-option
                  v-for="item in followTypeOptions"
                  :key="item.value"
                  :label="item.label"
                  :value="item.value"
                />
              </el-select>
            </div>
            <div class="field">
              <label>跟进日期</label>
              <el-date-picker
                v-model="followForm.followTime"
                type="date"
                value-format="YYYY-MM-DD"
                placeholder="选择日期"
              />
            </div>
            <div class="field span-2">
              <label>下一步计划</label>
              <el-input v-model="followForm.nextPlan" placeholder="选填，例如：下周发送报价" />
            </div>
            <div class="field span-2">
              <label>跟进内容 <em>*</em></label>
              <el-input
                v-model="followForm.content"
                type="textarea"
                :rows="3"
                maxlength="500"
                show-word-limit
                placeholder="记录沟通要点、客户反馈与关键结论"
              />
            </div>
          </div>
          <div class="follow-actions">
            <el-button type="primary" :loading="followSaving" @click="saveFollow">
              添加跟进
            </el-button>
          </div>
        </section>

        <section class="detail-section">
          <h4>跟进记录</h4>
          <div v-loading="followLoading" class="timeline">
            <el-timeline v-if="follows.length">
              <el-timeline-item
                v-for="item in follows"
                :key="item.id"
                :timestamp="`${item.followTime || ''} ${item.creatorName || ''}`"
                placement="top"
              >
                <div class="follow-item">
                  <el-tag size="small" type="info" effect="plain">
                    {{ followTypeLabel(item.followType) }}
                  </el-tag>
                  <span class="follow-text">{{ item.content }}</span>
                </div>
                <div v-if="item.nextPlan" class="follow-next">下一步：{{ item.nextPlan }}</div>
                <el-button
                  v-if="canOpp"
                  link
                  type="danger"
                  size="small"
                  @click="removeFollow(item)"
                >
                  删除
                </el-button>
              </el-timeline-item>
            </el-timeline>
            <el-empty v-else description="暂无跟进记录" :image-size="64" />
          </div>
        </section>
      </div>
      <template #footer>
        <div class="drawer-footer">
          <span class="footer-spacer"></span>
          <el-button @click="followDrawer = false">关闭</el-button>
        </div>
      </template>
    </el-drawer>
  </div>
</template>

<style scoped>
/* ---------------- 概览 ---------------- */
.kpi-board {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 1px;
  margin-bottom: 14px;
  overflow: hidden;
  background: var(--pms-line);
  border: 1px solid var(--pms-line);
  border-radius: var(--pms-radius);
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

.tone-success .kpi-icon {
  background: #eaf7ee;
  color: #3a9e5f;
}

/* ---------------- 列表 ---------------- */
/* 列表右上角：计数 + 刷新 + 新增（随页签切换） */
.list-side {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-left: auto;
}

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
.filter-row :deep(.f-keyword) {
  flex: 1 1 240px;
  min-width: 180px;
}

.filter-row :deep(.f-customer) {
  flex: 0 0 200px;
}

.filter-row :deep(.f-status) {
  flex: 0 0 140px;
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

.pager {
  flex-wrap: wrap;
  row-gap: 8px;
  margin-top: 14px;
  justify-content: flex-end;
}

/* ---------------- 表格单元格 ---------------- */
.cell-stack {
  display: flex;
  flex-direction: column;
  gap: 1px;
  min-width: 0;
}

.cell-main {
  overflow: hidden;
  font-size: 13px;
  line-height: 1.45;
  color: var(--pms-text);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.cell-sub {
  overflow: hidden;
  font-size: 11.5px;
  color: var(--pms-text-3);
  text-overflow: ellipsis;
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
}

.cell-muted {
  color: var(--pms-text-3);
  font-size: 12.5px;
}

.cell-ellipsis {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.amount-cell {
  font-variant-numeric: tabular-nums;
  font-weight: 500;
}

/* 状态标签可点开下拉直接切换 */
.tag-trigger {
  cursor: pointer;
}

.tag-trigger:hover {
  filter: brightness(0.96);
}

/* ---------------- 行内操作：一个实心主操作 + 文本次级操作 ---------------- */
.op-actions {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 2px 6px;
}

.op-actions :deep(.el-button) {
  margin-left: 0;
}

.op-actions :deep(.el-button.is-link) {
  height: 24px;
  padding: 0 4px;
  /* 文字按钮不加任何投影/描边，避免出现淡淡的“轮廓” */
  box-shadow: none;
  background: transparent;
  border-color: transparent;
}

/* 表格里字号小，危险/成功色需要比默认再深一档才够清晰 */
.op-actions :deep(.el-button.is-link.el-button--danger:not(.is-disabled)) {
  color: #d64545;
}

.op-actions :deep(.el-button.is-link.el-button--success:not(.is-disabled)) {
  color: #3a9e5f;
}

/* 禁用态统一收敛为灰色，比淡粉更易读，也不会误认为可点 */
.op-actions :deep(.el-button.is-link.is-disabled) {
  color: #b6bcc6;
}

/* ---------------- 弹窗表单 ---------------- */
.form-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0 18px;
}

.form-grid .span-2 {
  grid-column: 1 / -1;
}

.form-grid :deep(.el-form-item) {
  margin-bottom: 18px;
}

.form-grid :deep(.el-select),
.form-grid :deep(.el-input-number),
.form-grid :deep(.el-date-editor) {
  width: 100%;
}

.form-tip {
  margin: 2px 0 0;
  font-size: 12px;
  line-height: 1.7;
  color: var(--pms-text-3);
}

.form-section-title {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 0 0 14px;
  font-size: 12.5px;
  font-weight: 600;
  letter-spacing: 0.04em;
  color: var(--pms-text-2);
}

.form-section-title::after {
  content: '';
  flex: 1;
  height: 1px;
  background: var(--pms-line);
}

.dialog-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.dialog-actions {
  display: flex;
  gap: 8px;
}

/* 编辑弹窗：顶部身份摘要 */
.dialog-id {
  display: flex;
  align-items: center;
  gap: 12px;
  padding-bottom: 16px;
  margin-bottom: 18px;
  border-bottom: 1px dashed var(--pms-line);
}

.dialog-avatar {
  flex: none;
  display: grid;
  place-items: center;
  width: 44px;
  height: 44px;
  border-radius: 12px;
  background: var(--pms-primary-weak);
  color: var(--pms-primary-deep);
  font-size: 17px;
  font-weight: 600;
}

.dialog-id-meta {
  min-width: 0;
}

.dialog-id-line {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}

.dialog-id-name {
  font-size: 15px;
  font-weight: 600;
  color: var(--pms-text);
}

.dialog-id-sub {
  margin-top: 3px;
  overflow: hidden;
  font-size: 12px;
  color: var(--pms-text-3);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.dialog-id-sub .dot {
  margin: 0 5px;
  color: #c3c9d4;
}

/* ---------------- 抽屉 ---------------- */
.detail {
  padding: 4px 20px 24px;
}

.detail-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 16px;
}

.detail-head h3 {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
  color: var(--pms-text);
}

.detail-meta {
  margin: 5px 0 0;
  font-size: 12px;
  color: var(--pms-text-3);
}

.detail-meta .dot {
  margin: 0 6px;
  color: #c3c9d4;
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
  margin: 0 0 18px;
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
}

.detail-section {
  margin-top: 18px;
}

.detail-section h4 {
  margin: 0 0 10px;
  font-size: 13px;
  font-weight: 600;
  color: var(--pms-text);
}

.field-grid {
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

.field.span-2 {
  grid-column: span 2;
}

.field > label {
  font-size: 12.5px;
  font-weight: 500;
  color: var(--pms-text-2);
}

.field > label em {
  margin-left: 2px;
  font-style: normal;
  color: var(--el-color-danger);
}

.field :deep(.el-select),
.field :deep(.el-date-editor) {
  width: 100%;
}

.follow-actions {
  display: flex;
  justify-content: flex-end;
  margin-top: 14px;
}

.timeline {
  min-height: 80px;
}

.follow-item {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  font-size: 13px;
  line-height: 1.65;
  color: var(--pms-text-2);
}

.follow-text {
  word-break: break-word;
}

.follow-next {
  margin-top: 4px;
  font-size: 12px;
  color: var(--pms-text-3);
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

@media (max-width: 900px) {
  .kpi-board {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 768px) {
  .list-side {
    width: 100%;
    margin-left: 0;
    flex-wrap: wrap;
  }

  .filter-row > * {
    flex: 1 1 100%;
    min-width: 0;
  }

  .filter-row :deep(.f-keyword),
  .filter-row :deep(.f-customer),
  .filter-row :deep(.f-status),
  .filter-row :deep(.f-level) {
    flex: 1 1 100%;
    min-width: 0;
  }

  .filter-actions {
    width: 100%;
    margin-left: 0;
    justify-content: flex-end;
  }

  .form-grid,
  .field-grid {
    grid-template-columns: 1fr;
  }

  .form-grid .span-2,
  .field.span-2 {
    grid-column: auto;
  }

  .metrics {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .detail {
    padding: 4px 14px 20px;
  }

  .detail-head {
    flex-direction: column;
  }

  .dialog-footer {
    flex-direction: column;
    align-items: stretch;
    gap: 10px;
  }

  .dialog-actions {
    justify-content: flex-end;
  }

  .pager {
    justify-content: center;
  }
}
</style>
