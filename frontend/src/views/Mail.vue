<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { EditPen, Promotion, Search } from '@element-plus/icons-vue'
import MailEditor from '@/components/MailEditor.vue'
import {
  listChanges,
  listProjects,
  mailConfig,
  mailLogDetail,
  mailLogs,
  mailOptions,
  mailRecipients,
  mailTemplates,
  resetMailTemplate,
  resendMail,
  saveMailConfig,
  saveMailTemplate,
  sendMail,
  testMail,
  type MailDeptOption,
  type MailEstimate,
  type MailLog,
  type MailLogDetail,
  type MailOptions,
  type MailSendResult,
  type MailTemplate,
  type MailUserOption
} from '@/api'
import { useUserStore } from '@/stores/user'

const store = useUserStore()
const canManage = computed(() => store.has('sys:config'))

const tab = ref('compose')

/* ------------------------------ 写邮件 ------------------------------ */

const MAX_BODY = 15000
/** 草稿按登录人隔离，避免多人共用浏览器时串内容。 */
const draftKey = () => `pms_mail_draft_${store.profile?.id || 'anon'}`

const options = ref<MailOptions | null>(null)
const optionsLoading = ref(false)
const sending = ref(false)
const estimating = ref(false)
const estimate = ref<MailEstimate | null>(null)

const recipients = reactive({
  userIds: [] as string[],
  roleCodes: [] as string[],
  deptIds: [] as string[]
})
const compose = reactive({ subject: '', content: '' })
const sendSelf = ref(false)

const editorRef = ref<InstanceType<typeof MailEditor> | null>(null)

const deptMap = computed(() => {
  const map = new Map<string, MailDeptOption>()
  ;(options.value?.depts || []).forEach((item) => map.set(String(item.id), item))
  return map
})

const deptDepth = (dept: MailDeptOption) => {
  let depth = 0
  let current: MailDeptOption | undefined = dept
  while (current?.parentId && deptMap.value.get(String(current.parentId))) {
    depth += 1
    current = deptMap.value.get(String(current.parentId))
  }
  return depth
}

/** 部门平铺后按层级缩进，下拉里能看出上下级关系。 */
const deptView = computed(() =>
  (options.value?.depts || [])
    .filter((item) => item.userCount > 0)
    .map((item) => ({ ...item, depth: deptDepth(item) }))
)

const userMap = computed(() => {
  const map = new Map<string, string>()
  ;(options.value?.users || []).forEach((item) => {
    map.set(String(item.id), item.realName || item.username)
  })
  return map
})

const deptName = (id: string) => deptMap.value.get(String(id))?.deptName || '未分配部门'

const roleName = (code: string) =>
  options.value?.roles.find((item) => item.roleCode === code)?.roleName || code

const deptUserCount = (id: string) => deptMap.value.get(String(id))?.userCount || 0
const roleUserCount = (code: string) =>
  options.value?.roles.find((item) => item.roleCode === code)?.userCount || 0

const recipientChips = computed(() => {
  const chips: { key: string; label: string; kind: 'user' | 'role' | 'dept'; value: string }[] = []
  recipients.roleCodes.forEach((code) => {
    chips.push({
      key: `role-${code}`,
      label: `${roleName(code)}（${roleUserCount(code)} 人）`,
      kind: 'role',
      value: code
    })
  })
  recipients.deptIds.forEach((id) => {
    chips.push({
      key: `dept-${id}`,
      label: `${deptName(id)}（${deptUserCount(id)} 人）`,
      kind: 'dept',
      value: id
    })
  })
  recipients.userIds.forEach((id) => {
    chips.push({
      key: `user-${id}`,
      label: userMap.value.get(String(id)) || id,
      kind: 'user',
      value: id
    })
  })
  return chips
})

const removeChip = (chip: { kind: 'user' | 'role' | 'dept'; value: string }) => {
  const list =
    chip.kind === 'user'
      ? recipients.userIds
      : chip.kind === 'role'
        ? recipients.roleCodes
        : recipients.deptIds
  const index = list.indexOf(chip.value)
  if (index >= 0) list.splice(index, 1)
}

/** 纯文本字数：判空与提示用。 */
const contentLength = computed(() =>
  compose.content
    .replace(/<[^>]*>/g, '')
    .replace(/&nbsp;/gi, ' ')
    .trim().length
)

/** 含排版标签的字符数：后端按原始正文长度校验并入库，这里用同一口径。 */
const rawLength = computed(() => compose.content.length)

/* ------------------------------ 收件人选择 ------------------------------ */

const recipientVisible = ref(false)
const recipientTab = ref<'user' | 'role' | 'dept'>('user')
const draftSel = reactive({
  userIds: [] as string[],
  roleCodes: [] as string[],
  deptIds: [] as string[]
})
const userKeyword = ref('')
const userDeptFilter = ref('')

const openRecipient = () => {
  draftSel.userIds = [...recipients.userIds]
  draftSel.roleCodes = [...recipients.roleCodes]
  draftSel.deptIds = [...recipients.deptIds]
  recipientVisible.value = true
}

const toggleValue = (list: string[], value: string) => {
  const index = list.indexOf(value)
  if (index >= 0) list.splice(index, 1)
  else list.push(value)
}

const filteredUsers = computed(() => {
  const keyword = userKeyword.value.trim().toLowerCase()
  return (options.value?.users || []).filter((item) => {
    if (userDeptFilter.value && String(item.deptId) !== userDeptFilter.value) return false
    if (!keyword) return true
    return (
      (item.realName || '').toLowerCase().includes(keyword) ||
      (item.username || '').toLowerCase().includes(keyword)
    )
  })
})

const selectedCount = computed(
  () => draftSel.userIds.length + draftSel.roleCodes.length + draftSel.deptIds.length
)

const confirmRecipient = () => {
  recipients.userIds = [...draftSel.userIds]
  recipients.roleCodes = [...draftSel.roleCodes]
  recipients.deptIds = [...draftSel.deptIds]
  // 选过的人进入「最近联系人」，下次可以一键添加
  draftSel.userIds.forEach(rememberUser)
  recipientVisible.value = false
}

const estimateTimer = ref<number>()
const runEstimate = async () => {
  if (!recipients.userIds.length && !recipients.roleCodes.length && !recipients.deptIds.length) {
    estimate.value = null
    return
  }
  estimating.value = true
  try {
    estimate.value = await mailRecipients({
      userIds: recipients.userIds,
      roleCodes: recipients.roleCodes,
      deptIds: recipients.deptIds
    })
  } catch {
    estimate.value = null
  } finally {
    estimating.value = false
  }
}

const scheduleEstimate = () => {
  window.clearTimeout(estimateTimer.value)
  estimateTimer.value = window.setTimeout(runEstimate, 260)
}

watch(() => JSON.stringify(recipients), scheduleEstimate)

/* ------------------------------ 右侧联系人面板 ------------------------------ */

const sideKeyword = ref('')
const contactsOpen = ref(true)
const recentOpen = ref(true)
const showAllContacts = ref(false)
const recentIds = ref<string[]>([])

const userById = computed(() => {
  const map = new Map<string, MailUserOption>()
  ;(options.value?.users || []).forEach((item) => map.set(String(item.id), item))
  return map
})

const recentKey = () => `pms_mail_recent_${store.profile?.id || 'anon'}`

const loadRecent = () => {
  try {
    const raw = localStorage.getItem(recentKey())
    recentIds.value = raw ? (JSON.parse(raw) as string[]) : []
  } catch {
    recentIds.value = []
  }
}

/** 最近联系人：发送或从面板选人后记录，最多保留 10 个。 */
const rememberUser = (id: string) => {
  recentIds.value = [id, ...recentIds.value.filter((item) => item !== id)].slice(0, 10)
  localStorage.setItem(recentKey(), JSON.stringify(recentIds.value))
}

const matchKeyword = (item: MailUserOption) => {
  const keyword = sideKeyword.value.trim().toLowerCase()
  if (!keyword) return true
  return (
    (item.realName || '').toLowerCase().includes(keyword) ||
    (item.username || '').toLowerCase().includes(keyword) ||
    deptName(item.deptId).toLowerCase().includes(keyword)
  )
}

const recentContacts = computed(() =>
  recentIds.value
    .map((id) => userById.value.get(id))
    .filter((item): item is MailUserOption => Boolean(item) && matchKeyword(item as MailUserOption))
)

const sideContacts = computed(() => (options.value?.users || []).filter(matchKeyword))

const sideContactsVisible = computed(() =>
  showAllContacts.value ? sideContacts.value : sideContacts.value.slice(0, 8)
)

const addRecipient = (user: MailUserOption) => {
  const id = String(user.id)
  if (!recipients.userIds.includes(id)) recipients.userIds.push(id)
  rememberUser(id)
}

const addRoleRecipient = (code: string) => {
  if (!recipients.roleCodes.includes(code)) recipients.roleCodes.push(code)
}

/* ------------------------------ 草稿 ------------------------------ */

interface MailDraft {
  subject: string
  content: string
  userIds: string[]
  roleCodes: string[]
  deptIds: string[]
  sendSelf: boolean
  savedAt: string
}

const draftTip = ref(false)
const draftSavedAt = ref('')
let draftTimer: number | undefined

const readDraft = (): MailDraft | null => {
  try {
    const raw = localStorage.getItem(draftKey())
    return raw ? (JSON.parse(raw) as MailDraft) : null
  } catch {
    return null
  }
}

const persistDraft = () => {
  const hasContent = compose.subject.trim() || contentLength.value > 0
  if (!hasContent) return
  const draft: MailDraft = {
    subject: compose.subject,
    content: compose.content,
    userIds: recipients.userIds,
    roleCodes: recipients.roleCodes,
    deptIds: recipients.deptIds,
    sendSelf: sendSelf.value,
    savedAt: new Date().toISOString()
  }
  localStorage.setItem(draftKey(), JSON.stringify(draft))
  draftSavedAt.value = draft.savedAt
}

const scheduleDraft = () => {
  window.clearTimeout(draftTimer)
  draftTimer = window.setTimeout(persistDraft, 1000)
}

const saveDraft = () => {
  if (!compose.subject.trim() && !contentLength.value) {
    ElMessage.warning('主题与正文都为空，无需保存')
    return
  }
  persistDraft()
  ElMessage.success('草稿已保存到本机浏览器，下次进入可继续编辑')
}

const restoreDraft = () => {
  const draft = readDraft()
  if (!draft) return
  compose.subject = draft.subject || ''
  compose.content = draft.content || ''
  recipients.userIds = draft.userIds || []
  recipients.roleCodes = draft.roleCodes || []
  recipients.deptIds = draft.deptIds || []
  sendSelf.value = Boolean(draft.sendSelf)
  draftTip.value = false
  ElMessage.success('草稿已恢复')
}

const discardDraft = () => {
  localStorage.removeItem(draftKey())
  draftTip.value = false
}

const resetCompose = async () => {
  try {
    await ElMessageBox.confirm('清空当前收件人、主题与正文？', '清空写邮件', {
      type: 'warning',
      confirmButtonText: '清空',
      cancelButtonText: '取消'
    })
  } catch {
    return
  }
  compose.subject = ''
  compose.content = ''
  recipients.userIds = []
  recipients.roleCodes = []
  recipients.deptIds = []
  estimate.value = null
  sendSelf.value = false
  discardDraft()
}

watch(
  () => JSON.stringify({ s: compose.subject, c: compose.content, r: recipients, m: sendSelf.value }),
  scheduleDraft
)

/* ------------------------------ 插入系统内容 ------------------------------ */

const insertVisible = ref(false)
const insertKind = ref<'project' | 'change'>('project')
const insertKeyword = ref('')
const insertLoading = ref(false)
const insertRows = ref<Record<string, unknown>[]>([])

const loadInsertRows = async () => {
  insertLoading.value = true
  try {
    if (insertKind.value === 'project') {
      const data = await listProjects({
        pageNum: 1,
        pageSize: 20,
        keyword: insertKeyword.value.trim() || undefined
      })
      insertRows.value = data.list || []
    } else {
      const data = await listChanges({
        pageNum: 1,
        pageSize: 20,
        keyword: insertKeyword.value.trim() || undefined
      })
      insertRows.value = data.list || []
    }
  } catch {
    insertRows.value = []
  } finally {
    insertLoading.value = false
  }
}

const openInsert = async (kind: 'project' | 'change') => {
  insertKind.value = kind
  insertKeyword.value = ''
  insertVisible.value = true
  await loadInsertRows()
}

const baseUrl = () => `${location.origin}${location.pathname}`

const insertRecord = (row: Record<string, unknown>) => {
  const link = (path: string, text: string) =>
    `<a href="${baseUrl()}#${path}" target="_blank" rel="noopener">${text}</a>`
  let html = ''
  if (insertKind.value === 'project') {
    html =
      `<p><b>项目：</b>${link('/projects', `${String(row.projectName || '')}（${String(row.projectCode || '')}）`)}<br>` +
      `<b>负责人：</b>${String(row.pmName || '—')}<br>` +
      `<b>计划周期：</b>${String(row.planStart || '—')} ~ ${String(row.planEnd || '—')}</p>`
  } else {
    const projectId = String(row.projectId || '')
    const path = projectId ? `/changes?projectId=${projectId}` : '/changes'
    html =
      `<p><b>变更：</b>${link(path, `${String(row.title || '')}（${String(row.requestCode || '')}）`)}<br>` +
      `<b>所属项目：</b>${String(row.projectName || '—')}</p>`
  }
  editorRef.value?.insertHtml(html)
  insertVisible.value = false
}

const insertSignature = () => {
  const name = store.profile?.realName || store.profile?.username || '我'
  const lines = [`<p><br></p>`, `<p style="color:#5b6779;font-size:13px;">—— ${name}`]
  if (store.profile?.deptName) lines.push(`<br>${store.profile.deptName}`)
  lines.push(`<br>PMS 项目全生命周期管理系统</p>`)
  editorRef.value?.insertHtml(lines.join(''))
}

const handleInsertCommand = (command: string | number | object) => {
  if (command === 'signature') {
    insertSignature()
    return
  }
  openInsert(command === 'change' ? 'change' : 'project')
}

/* ------------------------------ 预览与发送 ------------------------------ */

const previewVisible = ref(false)

const previewDoc = computed(() => {
  const title = compose.subject.trim() || '邮件预览'
  const body = compose.content || '<p style="color:#8b95a8;">（正文为空）</p>'
  const from = options.value
    ? `${options.value.fromName} &lt;${options.value.sender || '未配置发件人'}&gt;`
    : '未配置发件人'
  return `<!DOCTYPE html><html><head><meta charset="utf-8"></head>
<body style="margin:0;padding:20px;background:#f4f6fb;font-family:-apple-system,'Segoe UI','Microsoft YaHei',sans-serif;">
  <div style="max-width:680px;margin:0 auto;">
    <div style="padding:12px 16px;background:#fff;border:1px solid #e2eaf8;border-radius:10px 10px 0 0;font-size:12px;color:#8b95a8;">
      发件人：${from}<br>主题：${title}
    </div>
    <div style="margin-top:8px;padding:16px;background:linear-gradient(120deg,#eef4ff,#f8faff);border-radius:10px 10px 0 0;border:1px solid #e2eaf8;border-bottom:0;">
      <span style="font-size:16px;font-weight:600;color:#1f4fd8;">${title}</span>
    </div>
    <div style="padding:20px;background:#fff;border:1px solid #e2eaf8;border-radius:0 0 10px 10px;font-size:14px;line-height:1.75;color:#1f2328;">
      ${body}
    </div>
    <p style="margin:14px 0 0;text-align:center;font-size:12px;color:#93a0b5;">本邮件由 PMS 项目全生命周期管理系统发送</p>
  </div>
</body></html>`
})

const openPreview = () => {
  if (!compose.subject.trim() || !contentLength.value) {
    ElMessage.warning('请先填写主题与正文')
    return
  }
  previewVisible.value = true
}

const resultVisible = ref(false)
const sendResult = ref<MailSendResult | null>(null)

const submitCompose = async () => {
  if (sending.value) return
  if (options.value && !options.value.ready) {
    ElMessage.warning('发件通道未配置，请先在「发件配置」完成 SMTP 设置')
    tab.value = 'config'
    return
  }
  if (!compose.subject.trim()) {
    ElMessage.warning('请填写邮件主题')
    return
  }
  if (!contentLength.value) {
    ElMessage.warning('请填写邮件正文')
    return
  }
  if (rawLength.value > MAX_BODY) {
    ElMessage.warning(`正文（含排版）超出 ${MAX_BODY} 字符限制，请精简后发送`)
    return
  }
  if (!recipients.userIds.length && !recipients.roleCodes.length && !recipients.deptIds.length) {
    ElMessage.warning('请至少选择一名收件人')
    return
  }
  const userIds = [...recipients.userIds]
  if (sendSelf.value && store.profile?.id && !userIds.includes(store.profile.id)) {
    userIds.push(store.profile.id)
  }
  sending.value = true
  try {
    const result = await sendMail({
      subject: compose.subject.trim(),
      content: compose.content,
      html: true,
      userIds,
      roleCodes: recipients.roleCodes,
      deptIds: recipients.deptIds
    })
    sendResult.value = result
    resultVisible.value = true
    userIds.forEach(rememberUser)
    compose.subject = ''
    compose.content = ''
    editorRef.value?.clear()
    discardDraft()
    await loadLogs()
  } catch {
    /* 错误提示由请求拦截器统一处理 */
  } finally {
    sending.value = false
  }
}

const goLogs = () => {
  resultVisible.value = false
  tab.value = 'logs'
  logPage.pageNum = 1
  loadLogs()
}

/* ------------------------------ 发件配置 ------------------------------ */
const configLoading = ref(false)
const saving = ref(false)
const testing = ref(false)
const testTo = ref('')
const form = reactive({
  enabled: true,
  smtpHost: '',
  smtpPort: 465,
  security: 'SSL',
  smtpUser: '',
  password: '',
  passwordSet: false,
  smtpFrom: '',
  fromName: 'PMS 项目管理',
  timeoutSeconds: 15,
  keepDays: 180,
  excludeOperator: true,
  testTo: ''
})

const loadConfig = async () => {
  configLoading.value = true
  try {
    const data = await mailConfig()
    Object.assign(form, {
      enabled: data.enabled,
      smtpHost: data.smtpHost,
      smtpPort: data.smtpPort || 465,
      security: data.security || 'SSL',
      smtpUser: data.smtpUser,
      password: '',
      passwordSet: data.passwordSet,
      smtpFrom: data.smtpFrom,
      fromName: data.fromName || 'PMS 项目管理',
      timeoutSeconds: data.timeoutSeconds || 15,
      keepDays: data.keepDays || 180,
      excludeOperator: data.excludeOperator,
      testTo: data.testTo
    })
    if (!testTo.value) testTo.value = data.smtpFrom || data.smtpUser
  } finally {
    configLoading.value = false
  }
}

const saveConfig = async () => {
  if (saving.value) return
  saving.value = true
  try {
    await saveMailConfig({
      enabled: form.enabled,
      smtpHost: form.smtpHost,
      smtpPort: Number(form.smtpPort),
      security: form.security,
      smtpUser: form.smtpUser,
      password: form.password,
      smtpFrom: form.smtpFrom,
      fromName: form.fromName,
      timeoutSeconds: Number(form.timeoutSeconds),
      keepDays: Number(form.keepDays),
      excludeOperator: form.excludeOperator,
      testTo: form.testTo
    })
    ElMessage.success('发件配置已保存')
    form.password = ''
    await loadConfig()
    await loadOptions()
  } finally {
    saving.value = false
  }
}

const sendTest = async () => {
  if (!testTo.value) {
    ElMessage.warning('请填写测试收件人')
    return
  }
  testing.value = true
  try {
    await testMail(testTo.value.trim())
    ElMessage.success('测试邮件已发送，请查收')
  } finally {
    testing.value = false
  }
}

/* ------------------------------ 通知模板 ------------------------------ */
const templates = ref<MailTemplate[]>([])
const templateLoading = ref(false)
const editing = ref<MailTemplate | null>(null)
const editorVisible = ref(false)
const templateSaving = ref(false)
const templateEditorRef = ref<InstanceType<typeof MailEditor> | null>(null)
const editForm = reactive({ subject: '', body: '', receiverRoles: '', enabled: true })

const TEMPLATE_VARS = [
  'project.name',
  'project.code',
  'change.code',
  'change.title',
  'operator.name',
  'reason',
  'time',
  'link'
]

const loadTemplates = async () => {
  templateLoading.value = true
  try {
    templates.value = (await mailTemplates()) || []
  } finally {
    templateLoading.value = false
  }
}

const openTemplate = (row: any) => {
  const item = row as MailTemplate
  editing.value = item
  Object.assign(editForm, {
    subject: item.subject,
    body: item.body,
    receiverRoles: item.receiverRoles,
    enabled: item.enabled
  })
  editorVisible.value = true
  nextTick(() => templateEditorRef.value?.focus())
}

const insertTemplateVar = (name: string) => {
  templateEditorRef.value?.insertHtml(`{{ ${name} }}`)
}

const submitTemplate = async () => {
  if (!editing.value) return
  if (!editForm.subject.trim() || !editForm.body.trim()) {
    ElMessage.warning('主题与正文不能为空')
    return
  }
  templateSaving.value = true
  try {
    await saveMailTemplate(editing.value.eventCode, { ...editForm })
    ElMessage.success('模板已保存')
    editorVisible.value = false
    await loadTemplates()
  } finally {
    templateSaving.value = false
  }
}

const restoreTemplate = async (row: any) => {
  try {
    await ElMessageBox.confirm(`恢复「${row.name}」的内置模板？当前修改将被清除。`, '恢复默认模板', {
      type: 'warning',
      confirmButtonText: '恢复',
      cancelButtonText: '取消'
    })
  } catch {
    return
  }
  await resetMailTemplate(row.eventCode)
  ElMessage.success('已恢复默认模板')
  await loadTemplates()
}

/* ------------------------------ 发送记录 ------------------------------ */
const logs = ref<MailLog[]>([])
const logsLoading = ref(false)
const logTotal = ref(0)
const logPage = reactive({ pageNum: 1, pageSize: 10 })
const logFilters = reactive({ status: '', eventCode: '', keyword: '' })

const logDetail = ref<MailLogDetail | null>(null)
const logDetailVisible = ref(false)

const STATUS_META: Record<string, { label: string; type: 'info' | 'success' | 'warning' | 'danger' }> = {
  PENDING: { label: '待发送', type: 'info' },
  SENT: { label: '已发送', type: 'success' },
  FAILED: { label: '发送失败', type: 'danger' },
  SKIPPED: { label: '已跳过', type: 'warning' }
}
const statusMeta = (status: string) => STATUS_META[status] || { label: status, type: 'info' }

const loadLogs = async () => {
  logsLoading.value = true
  try {
    const data = await mailLogs({
      pageNum: logPage.pageNum,
      pageSize: logPage.pageSize,
      status: logFilters.status || undefined,
      eventCode: logFilters.eventCode || undefined,
      keyword: logFilters.keyword.trim() || undefined
    })
    logs.value = data.list || []
    logTotal.value = Number(data.total || 0)
  } finally {
    logsLoading.value = false
  }
}

const searchLogs = () => {
  logPage.pageNum = 1
  loadLogs()
}

const openLogDetail = async (row: any) => {
  logDetail.value = await mailLogDetail(String(row.id))
  logDetailVisible.value = true
}

const retry = async (row: any) => {
  try {
    await resendMail(String(row.id))
    ElMessage.success('已重新发送')
    await loadLogs()
  } catch {
    await loadLogs()
  }
}

/* ------------------------------ 初始化 ------------------------------ */

const loadOptions = async () => {
  optionsLoading.value = true
  try {
    options.value = await mailOptions()
  } catch {
    options.value = null
  } finally {
    optionsLoading.value = false
  }
}

onMounted(async () => {
  loadRecent()
  const draft = readDraft()
  if (draft && (draft.subject || draft.content)) {
    draftTip.value = true
    draftSavedAt.value = draft.savedAt
  }
  await Promise.all([loadConfig(), loadTemplates(), loadLogs(), loadOptions()])
})

onBeforeUnmount(() => {
  window.clearTimeout(draftTimer)
  // 离开页面时把未落盘的编辑内容存成草稿，避免切页丢内容
  persistDraft()
  window.clearTimeout(estimateTimer.value)
})
</script>

<template>
  <div class="pms-page mail-page">
    <div class="pms-card">
      <el-tabs v-model="tab">
        <el-tab-pane label="写邮件" name="compose">
          <div v-loading="optionsLoading" class="tab-body compose-pane">
            <div class="compose-layout">
            <div class="compose-main">
            <div class="compose-actions">
              <el-button
                type="primary"
                :icon="Promotion"
                :loading="sending"
                :disabled="!canManage"
                @click="submitCompose"
              >
                发送
              </el-button>
              <el-button :icon="EditPen" :disabled="!canManage" @click="saveDraft">存草稿</el-button>
              <el-button :disabled="!canManage" @click="openPreview">预览</el-button>
              <el-dropdown :disabled="!canManage" @command="handleInsertCommand">
                <el-button :disabled="!canManage">插入系统内容</el-button>
                <template #dropdown>
                  <el-dropdown-menu>
                    <el-dropdown-item command="project">项目信息</el-dropdown-item>
                    <el-dropdown-item command="change">变更信息</el-dropdown-item>
                    <el-dropdown-item command="signature" divided>我的署名</el-dropdown-item>
                  </el-dropdown-menu>
                </template>
              </el-dropdown>
              <el-button text :disabled="!canManage" @click="resetCompose">清空</el-button>
              <div class="spacer" />
              <el-tag v-if="options && !options.ready" type="warning" effect="light" size="small">
                发件通道未配置，无法实际投递
              </el-tag>
              <span v-else-if="options" class="sub-text">
                发件人：{{ options.fromName }} &lt;{{ options.sender || '未填写' }}&gt;
              </span>
            </div>

            <el-alert
              v-if="draftTip"
              type="info"
              :closable="false"
              show-icon
              class="draft-tip"
            >
              <template #title>
                发现 {{ draftSavedAt ? draftSavedAt.replace('T', ' ').slice(0, 16) : '上次' }} 保存的草稿
                <el-button link type="primary" @click="restoreDraft">恢复继续编辑</el-button>
                <el-button link type="info" @click="discardDraft">丢弃</el-button>
              </template>
            </el-alert>

            <div class="compose-field">
              <span class="field-label">收件人</span>
              <div class="chip-area">
                <el-tag
                  v-for="chip in recipientChips"
                  :key="chip.key"
                  size="small"
                  closable
                  :type="chip.kind === 'user' ? 'primary' : 'info'"
                  effect="light"
                  @close="removeChip(chip)"
                >
                  {{ chip.label }}
                </el-tag>
                <span v-if="!recipientChips.length" class="field-placeholder">
                  支持按角色、部门或人员选择，勾选后自动合并去重
                </span>
                <button type="button" class="field-action" @click="openRecipient">选择收件人</button>
              </div>
            </div>

            <div v-if="estimate" class="estimate-line">
              <span>预计 <b>{{ estimate.recipients }}</b> 人收到</span>
              <span v-if="estimate.noEmail" class="warn">
                {{ estimate.noEmail }} 人未维护邮箱，将被跳过
              </span>
              <span v-if="estimate.testTo" class="warn">测试模式：所有通知只发往 {{ estimate.testTo }}</span>
              <span v-if="estimate.names.length" class="sub-text">
                含 {{ estimate.names.join('、') }}{{ estimate.total > estimate.names.length ? ' 等' : '' }}
              </span>
            </div>

            <div class="compose-field subject-field">
              <span class="field-label">主题</span>
              <el-input
                v-model="compose.subject"
                class="subject-input"
                maxlength="200"
                placeholder="填写邮件主题，建议带上项目/变更编号便于检索"
              />
            </div>

            <MailEditor
              ref="editorRef"
              v-model="compose.content"
              :disabled="!canManage"
              :min-height="360"
              placeholder="输入邮件正文，可粘贴表格或使用工具栏排版"
            />

            <div class="compose-foot">
              <el-checkbox v-model="sendSelf" :disabled="!canManage">抄送给我自己</el-checkbox>
              <span class="sub-text">正文 {{ contentLength }} 字（含排版 {{ rawLength }} / {{ MAX_BODY }}）</span>
              <span class="spacer" />
              <span class="sub-text">发送后可在「发送记录」查看投递状态与失败原因</span>
            </div>
            </div>

            <aside class="compose-side">
              <div class="side-search">
                <el-input v-model="sideKeyword" placeholder="搜索联系人 / 部门" clearable size="small">
                  <template #prefix>
                    <el-icon><Search /></el-icon>
                  </template>
                </el-input>
              </div>

              <div class="side-section">
                <button type="button" class="side-title" @click="recentOpen = !recentOpen">
                  <span class="side-caret" :class="{ collapsed: !recentOpen }">▾</span>
                  最近联系人
                  <span class="side-count">{{ recentContacts.length }}</span>
                </button>
                <div v-if="recentOpen" class="side-list">
                  <button
                    v-for="item in recentContacts"
                    :key="`recent-${item.id}`"
                    type="button"
                    class="side-item"
                    :title="`添加到收件人：${item.realName || item.username}`"
                    @click="addRecipient(item)"
                  >
                    <span class="side-name">{{ item.realName || item.username }}</span>
                    <span class="side-sub">{{ deptName(item.deptId) }}</span>
                  </button>
                  <p v-if="!recentContacts.length" class="side-empty">
                    发送邮件或从下方选人后，这里会记住常用联系人
                  </p>
                </div>
              </div>

              <div class="side-section">
                <button type="button" class="side-title" @click="contactsOpen = !contactsOpen">
                  <span class="side-caret" :class="{ collapsed: !contactsOpen }">▾</span>
                  系统联系人
                  <span class="side-count">{{ sideContacts.length }}</span>
                </button>
                <div v-if="contactsOpen" class="side-list">
                  <button
                    v-for="item in sideContactsVisible"
                    :key="`contact-${item.id}`"
                    type="button"
                    class="side-item"
                    :title="`添加到收件人：${item.realName || item.username}`"
                    @click="addRecipient(item)"
                  >
                    <span class="side-name">{{ item.realName || item.username }}</span>
                    <span class="side-sub">{{ deptName(item.deptId) }}</span>
                    <span v-if="!item.hasEmail" class="side-flag">无邮箱</span>
                  </button>
                  <button
                    v-if="sideContacts.length > 8"
                    type="button"
                    class="side-more"
                    @click="showAllContacts = !showAllContacts"
                  >
                    {{ showAllContacts ? '收起' : `显示更多（${sideContacts.length - 8}）` }}
                  </button>
                  <p v-if="!sideContacts.length" class="side-empty">没有匹配的联系人</p>
                </div>
              </div>

              <div class="side-section">
                <div class="side-title static">按角色添加</div>
                <div class="side-roles">
                  <el-tag
                    v-for="item in options?.roles || []"
                    :key="item.roleCode"
                    size="small"
                    effect="plain"
                    class="side-role"
                    @click="addRoleRecipient(item.roleCode)"
                  >
                    {{ item.roleName }}
                  </el-tag>
                </div>
              </div>

              <div class="side-section side-account">
                <div class="side-title static">发件账号</div>
                <p class="side-account-name">{{ options?.fromName || '未配置' }}</p>
                <p class="side-account-mail">{{ options?.sender || '未配置' }}</p>
                <p class="side-account-tip">收件人按角色 / 部门 / 人员取并集，重复自动去除</p>
              </div>
            </aside>
            </div>
          </div>
        </el-tab-pane>

        <el-tab-pane label="发送记录" name="logs">
          <div class="tab-body">
            <div class="log-filters">
              <el-select v-model="logFilters.status" placeholder="全部状态" clearable style="width: 130px">
                <el-option label="待发送" value="PENDING" />
                <el-option label="已发送" value="SENT" />
                <el-option label="发送失败" value="FAILED" />
              </el-select>
              <el-select v-model="logFilters.eventCode" placeholder="全部事件" clearable style="width: 180px">
                <el-option v-for="item in templates" :key="item.eventCode" :label="item.name" :value="item.eventCode" />
              </el-select>
              <el-input
                v-model="logFilters.keyword"
                placeholder="搜索收件人 / 主题"
                clearable
                style="width: 220px"
                @keyup.enter="searchLogs"
              />
              <el-button type="primary" @click="searchLogs">查询</el-button>
            </div>

            <el-table v-loading="logsLoading" :data="logs" size="small">
              <el-table-column prop="eventName" label="事件" width="150" />
              <el-table-column label="收件人" min-width="190">
                <template #default="{ row }">
                  <div>{{ row.recipientName || '—' }}</div>
                  <div class="sub-text">{{ row.recipient }}</div>
                </template>
              </el-table-column>
              <el-table-column label="主题" min-width="220" show-overflow-tooltip>
                <template #default="{ row }">{{ row.subject }}</template>
              </el-table-column>
              <el-table-column label="状态" width="105">
                <template #default="{ row }">
                  <el-tooltip v-if="row.error" :content="row.error" placement="top">
                    <el-tag size="small" :type="statusMeta(row.status).type">
                      {{ statusMeta(row.status).label }}
                    </el-tag>
                  </el-tooltip>
                  <el-tag v-else size="small" :type="statusMeta(row.status).type">
                    {{ statusMeta(row.status).label }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column label="失败次数" width="84" align="center">
                <template #default="{ row }">{{ row.retryCount }}</template>
              </el-table-column>
              <el-table-column label="时间" width="160">
                <template #default="{ row }">{{ row.sentAt || row.createTime }}</template>
              </el-table-column>
              <el-table-column label="操作" width="120">
                <template #default="{ row }">
                  <el-button link type="primary" @click="openLogDetail(row)">查看</el-button>
                  <el-button
                    link
                    type="primary"
                    :disabled="!canManage || row.status === 'PENDING'"
                    @click="retry(row)"
                  >
                    重发
                  </el-button>
                </template>
              </el-table-column>
            </el-table>

            <el-pagination
              v-model:current-page="logPage.pageNum"
              v-model:page-size="logPage.pageSize"
              :total="logTotal"
              :page-sizes="[10, 20, 50]"
              layout="total, sizes, prev, pager, next"
              class="pager"
              @current-change="loadLogs"
              @size-change="searchLogs"
            />
          </div>
        </el-tab-pane>

        <el-tab-pane label="通知模板" name="templates">
          <div v-loading="templateLoading" class="tab-body">
            <el-alert
              type="info"
              :closable="false"
              show-icon
              title="系统事件（立项审批、变更、任务指派等）触发时按这里配置的模板发信"
              description="主题与正文支持变量，正文可用富文本排版；修改后可通过「恢复默认」回到内置版本。"
              style="margin-bottom: 14px"
            />
            <el-table :data="templates" size="small">
              <el-table-column prop="name" label="触发事件" min-width="150" />
              <el-table-column prop="subject" label="主题" min-width="260" show-overflow-tooltip />
              <el-table-column label="收件角色" width="180" show-overflow-tooltip>
                <template #default="{ row }">{{ row.receiverRoles || '—' }}</template>
              </el-table-column>
              <el-table-column label="状态" width="90">
                <template #default="{ row }">
                  <el-tag size="small" :type="row.enabled ? 'success' : 'info'">
                    {{ row.enabled ? '启用' : '停用' }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column label="来源" width="90">
                <template #default="{ row }">
                  <el-tag size="small" effect="plain" :type="row.customized ? 'warning' : 'info'">
                    {{ row.customized ? '自定义' : '内置' }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column label="操作" width="150">
                <template #default="{ row }">
                  <el-button link type="primary" :disabled="!canManage" @click="openTemplate(row)">
                    编辑
                  </el-button>
                  <el-button
                    v-if="row.customized"
                    link
                    type="danger"
                    :disabled="!canManage"
                    @click="restoreTemplate(row)"
                  >
                    恢复默认
                  </el-button>
                </template>
              </el-table-column>
            </el-table>
          </div>
        </el-tab-pane>

        <el-tab-pane label="发件配置" name="config">
          <div v-loading="configLoading" class="tab-body">
            <el-alert
              type="warning"
              :closable="false"
              show-icon
              title="发件人邮箱建议与登录账号保持一致"
              description="QQ / 163 / 腾讯企业邮等公共邮箱会拒绝与登录账号域名不同的发件人，报错常见为「所属域名不存在」；公司内网 Exchange 则按 IT 提供的地址填写。"
              style="margin-bottom: 14px"
            />
            <el-form :model="form" label-width="120px" :disabled="!canManage">
              <div class="form-cols">
                <el-form-item label="启用邮件通知">
                  <el-switch v-model="form.enabled" />
                </el-form-item>
                <el-form-item label="加密方式">
                  <el-select v-model="form.security" style="width: 100%">
                    <el-option label="SSL（常用 465）" value="SSL" />
                    <el-option label="STARTTLS（常用 587）" value="STARTTLS" />
                    <el-option label="不加密（常用 25）" value="NONE" />
                  </el-select>
                </el-form-item>
                <el-form-item label="SMTP 服务器">
                  <el-input v-model="form.smtpHost" placeholder="如 smtp.qq.com" />
                </el-form-item>
                <el-form-item label="端口">
                  <el-input-number v-model="form.smtpPort" :min="1" :max="65535" style="width: 100%" />
                </el-form-item>
                <el-form-item label="登录账号">
                  <el-input v-model="form.smtpUser" placeholder="通常为完整邮箱地址" />
                </el-form-item>
                <el-form-item label="密码 / 授权码">
                  <el-input
                    v-model="form.password"
                    type="password"
                    show-password
                    :placeholder="form.passwordSet ? '已配置，留空表示不修改' : '请输入 SMTP 密码或授权码'"
                  />
                </el-form-item>
                <el-form-item label="发件人邮箱">
                  <el-input v-model="form.smtpFrom" placeholder="留空则使用登录账号（推荐）" />
                </el-form-item>
                <el-form-item label="发件人名称">
                  <el-input v-model="form.fromName" placeholder="如 PMS 项目管理" />
                </el-form-item>
                <el-form-item label="超时（秒）">
                  <el-input-number v-model="form.timeoutSeconds" :min="3" :max="120" style="width: 100%" />
                </el-form-item>
                <el-form-item label="记录保留（天）">
                  <el-input-number v-model="form.keepDays" :min="7" :max="3650" style="width: 100%" />
                </el-form-item>
                <el-form-item label="跳过操作人">
                  <el-switch v-model="form.excludeOperator" active-text="操作人本人不收邮件" />
                </el-form-item>
                <el-form-item label="测试模式收件人">
                  <el-input v-model="form.testTo" placeholder="非空时所有通知只发到该地址" />
                </el-form-item>
              </div>

              <div class="form-actions">
                <el-button v-if="canManage" type="primary" :loading="saving" @click="saveConfig">
                  保存配置
                </el-button>
                <el-input v-model="testTo" placeholder="测试收件邮箱" class="test-input" />
                <el-button v-if="canManage" :loading="testing" @click="sendTest">发送测试邮件</el-button>
              </div>
            </el-form>
            <el-alert
              type="info"
              :closable="false"
              show-icon
              title="关于加密方式"
              description="公司邮箱若使用 25 端口且支持 STARTTLS，请选择 STARTTLS；465 一般是 SSL。密码使用应用密钥加密后保存，接口不会回显。"
            />
          </div>
        </el-tab-pane>
      </el-tabs>
    </div>

    <!-- 选择收件人 -->
    <el-dialog v-model="recipientVisible" title="选择收件人" width="min(760px, 94vw)">
      <el-tabs v-model="recipientTab" class="recipient-tabs">
        <el-tab-pane label="按人员" name="user">
          <div class="rec-filter">
            <el-input v-model="userKeyword" placeholder="搜索姓名或账号" clearable style="width: 220px" />
            <el-select v-model="userDeptFilter" placeholder="全部部门" clearable style="width: 200px">
              <el-option
                v-for="dept in deptView"
                :key="String(dept.id)"
                :label="`${'　'.repeat(dept.depth)}${dept.deptName}（${dept.userCount}）`"
                :value="String(dept.id)"
              />
            </el-select>
            <span class="sub-text">共 {{ filteredUsers.length }} 人</span>
          </div>
          <div class="rec-list">
            <div
              v-for="item in filteredUsers"
              :key="String(item.id)"
              class="rec-row"
              @click="toggleValue(draftSel.userIds, String(item.id))"
            >
              <el-checkbox
                :model-value="draftSel.userIds.includes(String(item.id))"
                @click.stop
                @change="toggleValue(draftSel.userIds, String(item.id))"
              />
              <span class="rec-name">{{ item.realName || item.username }}</span>
              <span class="rec-account">{{ item.username }}</span>
              <span class="rec-dept">{{ deptName(item.deptId) }}</span>
              <el-tag v-if="!item.hasEmail" size="small" type="warning" effect="plain">未维护邮箱</el-tag>
            </div>
            <el-empty v-if="!filteredUsers.length" description="没有匹配的人员" :image-size="70" />
          </div>
        </el-tab-pane>

        <el-tab-pane label="按角色" name="role">
          <div class="rec-list">
            <div v-for="item in options?.roles || []" :key="item.roleCode" class="rec-row">
              <el-checkbox
                :model-value="draftSel.roleCodes.includes(item.roleCode)"
                :disabled="!item.userCount"
                @change="toggleValue(draftSel.roleCodes, item.roleCode)"
              />
              <span class="rec-name">{{ item.roleName }}</span>
              <span class="rec-dept">{{ item.userCount }} 人在岗</span>
              <span class="sub-text">{{ item.roleCode }}</span>
            </div>
            <el-empty v-if="!(options?.roles || []).length" description="暂无可用角色" :image-size="70" />
          </div>
        </el-tab-pane>

        <el-tab-pane label="按部门" name="dept">
          <div class="rec-list">
            <div v-for="item in deptView" :key="String(item.id)" class="rec-row">
              <el-checkbox
                :model-value="draftSel.deptIds.includes(String(item.id))"
                @change="toggleValue(draftSel.deptIds, String(item.id))"
              />
              <span class="rec-name">{{ '　'.repeat(item.depth) }}{{ item.deptName }}</span>
              <span class="rec-dept">{{ item.userCount }} 人在岗</span>
            </div>
            <el-empty v-if="!deptView.length" description="暂无可用部门" :image-size="70" />
          </div>
        </el-tab-pane>
      </el-tabs>
      <template #footer>
        <div class="rec-footer">
          <span class="sub-text">
            已选 {{ selectedCount }} 项（人员 {{ draftSel.userIds.length }} / 角色
            {{ draftSel.roleCodes.length }} / 部门 {{ draftSel.deptIds.length }}），确认后自动合并去重
          </span>
          <div>
            <el-button @click="recipientVisible = false">取消</el-button>
            <el-button type="primary" @click="confirmRecipient">确定</el-button>
          </div>
        </div>
      </template>
    </el-dialog>

    <!-- 插入系统内容 -->
    <el-dialog
      v-model="insertVisible"
      :title="insertKind === 'project' ? '插入项目信息' : '插入变更信息'"
      width="min(640px, 94vw)"
    >
      <div class="rec-filter">
        <el-input
          v-model="insertKeyword"
          :placeholder="insertKind === 'project' ? '搜索项目名称 / 编号' : '搜索变更标题 / 编号'"
          clearable
          style="width: 260px"
          @keyup.enter="loadInsertRows"
        />
        <el-button type="primary" @click="loadInsertRows">查询</el-button>
      </div>
      <div v-loading="insertLoading" class="rec-list short">
        <div
          v-for="row in insertRows"
          :key="String(row.id)"
          class="rec-row clickable"
          @click="insertRecord(row)"
        >
          <span class="rec-name">
            {{ insertKind === 'project' ? row.projectName : row.title }}
          </span>
          <span class="rec-account">
            {{ insertKind === 'project' ? row.projectCode : row.requestCode }}
          </span>
          <span class="rec-dept">{{ insertKind === 'project' ? row.pmName || '—' : row.projectName || '—' }}</span>
        </div>
        <el-empty v-if="!insertRows.length" description="没有匹配的数据" :image-size="70" />
      </div>
      <template #footer>
        <span class="sub-text">点击一条记录即插入带系统链接的摘要，收件人可直接打开系统查看</span>
      </template>
    </el-dialog>

    <!-- 邮件预览 -->
    <el-dialog v-model="previewVisible" title="邮件预览" width="min(820px, 96vw)" class="preview-dialog">
      <iframe class="preview-frame" :srcdoc="previewDoc" title="邮件预览" />
      <template #footer>
        <el-button @click="previewVisible = false">返回编辑</el-button>
        <el-button type="primary" :loading="sending" @click="previewVisible = false; submitCompose()">
          确认发送
        </el-button>
      </template>
    </el-dialog>

    <!-- 发送结果 -->
    <el-dialog v-model="resultVisible" title="发送结果" width="min(560px, 94vw)">
      <template v-if="sendResult">
        <div class="result-grid">
          <div class="result-item ok">
            <span class="value">{{ sendResult.sent }}</span>
            <span class="label">发送成功</span>
          </div>
          <div class="result-item warn">
            <span class="value">{{ sendResult.recipients }}</span>
            <span class="label">收件人数</span>
          </div>
          <div class="result-item danger">
            <span class="value">{{ sendResult.failed }}</span>
            <span class="label">发送失败</span>
          </div>
          <div class="result-item">
            <span class="value">{{ sendResult.skipped }}</span>
            <span class="label">无邮箱跳过</span>
          </div>
        </div>
        <el-alert
          v-if="sendResult.failures?.length"
          type="error"
          :closable="false"
          show-icon
          title="部分收件人投递失败"
          style="margin-top: 12px"
        >
          <div v-for="item in sendResult.failures" :key="item.recipient" class="failure-line">
            {{ item.name || item.recipient }}：{{ item.error }}
          </div>
        </el-alert>
        <p class="sub-text" style="margin-top: 12px">
          发送失败的邮件不会自动重试，可在「发送记录」查看原因并手动重发。
        </p>
      </template>
      <template #footer>
        <el-button @click="resultVisible = false">关闭</el-button>
        <el-button type="primary" @click="goLogs">查看发送记录</el-button>
      </template>
    </el-dialog>

    <!-- 发送记录详情 -->
    <el-dialog v-model="logDetailVisible" title="发送详情" width="min(820px, 96vw)">
      <template v-if="logDetail">
        <div class="log-meta">
          <div><span>收件人</span>{{ logDetail.recipientName }} &lt;{{ logDetail.recipient }}&gt;</div>
          <div><span>主题</span>{{ logDetail.subject }}</div>
          <div><span>状态</span>
            <el-tag size="small" :type="statusMeta(logDetail.status).type">
              {{ statusMeta(logDetail.status).label }}
            </el-tag>
            <span class="sub-text" style="margin-left: 8px">累计失败 {{ logDetail.retryCount }} 次</span>
          </div>
          <div><span>时间</span>{{ logDetail.sentAt || logDetail.createTime }}</div>
        </div>
        <el-alert
          v-if="logDetail.error"
          type="error"
          :closable="false"
          show-icon
          :title="logDetail.error"
          style="margin-bottom: 12px"
        />
        <iframe class="preview-frame" :srcdoc="logDetail.body" title="邮件内容" />
      </template>
      <template #footer>
        <el-button @click="logDetailVisible = false">关闭</el-button>
        <el-button
          type="primary"
          :disabled="!logDetail || logDetail.status === 'PENDING'"
          @click="logDetail && retry(logDetail); logDetailVisible = false"
        >
          重新发送
        </el-button>
      </template>
    </el-dialog>

    <!-- 模板编辑 -->
    <el-dialog v-model="editorVisible" :title="editing ? `编辑模板：${editing.name}` : '编辑模板'" width="min(760px, 94vw)">
      <el-form label-width="90px">
        <el-form-item label="触发说明">
          <span class="sub-text">{{ editing?.message }}</span>
        </el-form-item>
        <el-form-item label="主题">
          <el-input v-model="editForm.subject" maxlength="512" show-word-limit />
        </el-form-item>
        <el-form-item label="收件角色">
          <el-input v-model="editForm.receiverRoles" placeholder="如 PROJECT_PM,PROJECT_MEMBER,PMO" />
        </el-form-item>
        <el-form-item label="正文">
          <MailEditor
            ref="templateEditorRef"
            v-model="editForm.body"
            :min-height="240"
            placeholder="模板正文，可使用下方变量"
          />
        </el-form-item>
        <el-form-item label="启用">
          <el-switch v-model="editForm.enabled" />
        </el-form-item>
      </el-form>
      <div class="var-row">
        <span class="sub-text">插入变量：</span>
        <el-tag
          v-for="name in TEMPLATE_VARS"
          :key="name"
          size="small"
          effect="plain"
          class="var-chip"
          @click="insertTemplateVar(name)"
        >
          {{ name }}
        </el-tag>
      </div>
      <template #footer>
        <el-button @click="editorVisible = false">取消</el-button>
        <el-button type="primary" :loading="templateSaving" @click="submitTemplate">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.mail-page {
  padding-bottom: 8px;
}

.tab-body {
  padding-top: 4px;
}

/* ------------------------------ 写邮件 ------------------------------ */
.compose-pane {
  width: 100%;
}

.compose-layout {
  display: flex;
  align-items: flex-start;
  gap: 20px;
}

.compose-main {
  flex: 1 1 auto;
  min-width: 0;
}

/* 右侧联系人面板：与左侧编辑区同一屏，窄屏时自动落到下方 */
.compose-side {
  flex: 0 0 250px;
  align-self: stretch;
  padding-left: 18px;
  border-left: 1px solid var(--pms-line-soft);
}

.side-search {
  margin-bottom: 10px;
}

.side-section {
  padding: 8px 0;
  border-bottom: 1px dashed var(--pms-line-soft);
}

.side-section:last-child {
  border-bottom: 0;
}

.side-title {
  display: flex;
  align-items: center;
  gap: 6px;
  width: 100%;
  padding: 0;
  border: 0;
  background: transparent;
  color: var(--pms-text);
  font-size: 13px;
  font-weight: 600;
  text-align: left;
  cursor: pointer;
}

.side-title.static {
  cursor: default;
}

.side-caret {
  display: inline-block;
  color: var(--pms-text-3);
  font-size: 11px;
  transition: transform 0.16s ease;
}

.side-caret.collapsed {
  transform: rotate(-90deg);
}

.side-count {
  margin-left: auto;
  color: var(--pms-text-3);
  font-size: 12px;
  font-weight: 400;
}

.side-list {
  display: flex;
  flex-direction: column;
  margin-top: 6px;
  max-height: 268px;
  overflow-y: auto;
}

.side-item {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 8px;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: var(--pms-text-2);
  font-size: 13px;
  text-align: left;
  cursor: pointer;
}

.side-item:hover {
  background: #eef3ff;
  color: var(--pms-primary-deep);
}

.side-name {
  flex: 0 1 auto;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.side-sub {
  flex: 1 1 auto;
  overflow: hidden;
  color: var(--pms-text-3);
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.side-flag {
  flex: 0 0 auto;
  color: var(--pms-warn);
  font-size: 11px;
}

.side-more {
  margin-top: 2px;
  padding: 4px 8px;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: var(--pms-primary);
  font-size: 12px;
  text-align: left;
  cursor: pointer;
}

.side-more:hover {
  background: #eef3ff;
}

.side-empty {
  margin: 4px 0 0;
  padding: 4px 8px;
  color: var(--pms-text-3);
  font-size: 12px;
  line-height: 1.6;
}

.side-roles {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 8px;
}

.side-role {
  cursor: pointer;
}

.side-role:hover {
  color: var(--pms-primary-deep);
  border-color: var(--el-color-primary-light-5);
}

.side-account-name {
  margin: 6px 0 0;
  font-size: 13px;
  font-weight: 500;
  color: var(--pms-text);
}

.side-account-mail {
  margin: 2px 0 0;
  font-size: 12px;
  color: var(--pms-text-2);
  word-break: break-all;
}

.side-account-tip {
  margin: 8px 0 0;
  font-size: 12px;
  line-height: 1.6;
  color: var(--pms-text-3);
}

.compose-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 12px;
}

.compose-actions .spacer,
.compose-foot .spacer {
  flex: 1 1 auto;
}

.draft-tip {
  margin-bottom: 12px;
}

.compose-field {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 9px 0;
  border-bottom: 1px solid var(--pms-line-soft);
}

.compose-field .field-label {
  flex: 0 0 52px;
  padding-top: 3px;
  font-size: 13px;
  color: var(--pms-text-3);
}

.chip-area {
  display: flex;
  align-items: center;
  gap: 6px;
  flex: 1 1 auto;
  flex-wrap: wrap;
  min-height: 26px;
}

.field-placeholder {
  font-size: 13px;
  color: var(--pms-text-3);
}

.field-action {
  margin-left: auto;
  padding: 0;
  border: 0;
  background: transparent;
  color: var(--pms-primary);
  font-size: 13px;
  cursor: pointer;
}

.field-action:hover {
  color: var(--pms-primary-deep);
  text-decoration: underline;
}

.estimate-line {
  display: flex;
  align-items: center;
  gap: 14px;
  flex-wrap: wrap;
  padding: 7px 0 0 62px;
  font-size: 12.5px;
  color: var(--pms-text-2);
}

.estimate-line b {
  color: var(--pms-primary-deep);
}

.estimate-line .warn {
  color: var(--pms-warn);
}

.subject-field {
  align-items: center;
  border-bottom: 1px solid var(--pms-line-soft);
}

.subject-input :deep(.el-input__wrapper) {
  box-shadow: none;
  padding-left: 0;
}

.subject-input :deep(.el-input__inner) {
  font-size: 15px;
  font-weight: 500;
}

.compose-foot {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  padding-top: 10px;
}

/* ------------------------------ 收件人 / 插入 ------------------------------ */
.rec-filter {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 10px;
}

.rec-list {
  max-height: 340px;
  overflow-y: auto;
  border: 1px solid var(--pms-line-soft);
  border-radius: 8px;
}

.rec-list.short {
  max-height: 280px;
}

.rec-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 7px 12px;
  border-bottom: 1px solid var(--pms-line-soft);
  font-size: 13px;
  cursor: pointer;
}

.rec-row:last-child {
  border-bottom: 0;
}

.rec-row:hover {
  background: #f7faff;
}

.rec-row.clickable:hover {
  background: #eef3ff;
}

.rec-name {
  min-width: 120px;
  color: var(--pms-text);
  font-weight: 500;
}

.rec-account {
  min-width: 100px;
  color: var(--pms-text-2);
}

.rec-dept {
  flex: 1 1 auto;
  color: var(--pms-text-3);
}

.rec-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.recipient-tabs :deep(.el-tabs__header) {
  margin-bottom: 10px;
}

/* ------------------------------ 预览 / 结果 ------------------------------ */
.preview-frame {
  width: 100%;
  height: 460px;
  border: 1px solid var(--pms-line);
  border-radius: 10px;
  background: #f4f6fb;
}

.result-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
}

.result-item {
  padding: 12px 8px;
  text-align: center;
  background: #f7f9fd;
  border-radius: 10px;
}

.result-item .value {
  display: block;
  font-size: 22px;
  font-weight: 600;
  color: var(--pms-text);
}

.result-item .label {
  font-size: 12px;
  color: var(--pms-text-3);
}

.result-item.ok .value {
  color: var(--pms-ok);
}

.result-item.warn .value {
  color: var(--pms-warn);
}

.result-item.danger .value {
  color: var(--pms-danger);
}

.failure-line {
  font-size: 12.5px;
  line-height: 1.7;
  color: var(--pms-danger);
}

.log-meta {
  display: grid;
  gap: 6px;
  margin-bottom: 12px;
  font-size: 13px;
}

.log-meta span {
  display: inline-block;
  min-width: 60px;
  color: var(--pms-text-3);
}

/* ------------------------------ 其他 ------------------------------ */
.form-cols {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0 18px;
}

.form-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  margin: 4px 0 14px;
}

.test-input {
  width: 260px;
}

.log-filters {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 12px;
}

.sub-text {
  font-size: 12px;
  color: var(--pms-text-3);
}

.pager {
  margin-top: 12px;
  justify-content: flex-end;
}

.var-row {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.var-chip {
  cursor: pointer;
}

@media (max-width: 1100px) {
  .compose-layout {
    flex-direction: column;
  }

  .compose-side {
    flex: 0 0 auto;
    width: 100%;
    padding: 8px 0 0;
    border-left: 0;
    border-top: 1px solid var(--pms-line-soft);
  }

  .side-list {
    max-height: 220px;
  }
}

@media (max-width: 900px) {
  .form-cols {
    grid-template-columns: 1fr;
  }

  .test-input {
    width: 100%;
  }

  .result-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .estimate-line {
    padding-left: 0;
  }

  .rec-name {
    min-width: 84px;
  }

  .rec-account {
    display: none;
  }
}
</style>
