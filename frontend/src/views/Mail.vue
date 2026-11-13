<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  mailConfig,
  mailLogs,
  mailTemplates,
  resetMailTemplate,
  resendMail,
  saveMailConfig,
  saveMailTemplate,
  testMail,
  type MailLog,
  type MailTemplate
} from '@/api'
import { useUserStore } from '@/stores/user'

const store = useUserStore()
const canManage = computed(() => store.has('sys:config'))

const tab = ref('config')

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
const editForm = reactive({ subject: '', body: '', receiverRoles: '', enabled: true })

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

const retry = async (row: any) => {
  try {
    await resendMail(row.id)
    ElMessage.success('已重新发送')
    await loadLogs()
  } catch {
    await loadLogs()
  }
}

onMounted(async () => {
  await Promise.all([loadConfig(), loadTemplates(), loadLogs()])
})
</script>

<template>
  <div class="pms-page mail-page">
    <div class="pms-card">
      <el-tabs v-model="tab">
        <el-tab-pane label="发件配置" name="config">
          <div v-loading="configLoading" class="tab-body">
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
                  <el-input v-model="form.smtpHost" placeholder="如 office.qianlong.com" />
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
                  <el-input v-model="form.smtpFrom" placeholder="留空则使用登录账号" />
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
                <el-form-item label="测试收件人">
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

        <el-tab-pane label="通知模板" name="templates">
          <div v-loading="templateLoading" class="tab-body">
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
              <el-table-column label="收件人" min-width="180">
                <template #default="{ row }">
                  <div>{{ row.recipientName || '—' }}</div>
                  <div class="sub-text">{{ row.recipient }}</div>
                </template>
              </el-table-column>
              <el-table-column prop="subject" label="主题" min-width="240" show-overflow-tooltip />
              <el-table-column label="状态" width="100">
                <template #default="{ row }">
                  <el-tag size="small" :type="statusMeta(row.status).type">
                    {{ statusMeta(row.status).label }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column label="重试" width="70" align="center">
                <template #default="{ row }">{{ row.retryCount }}</template>
              </el-table-column>
              <el-table-column prop="createTime" label="创建时间" width="160" />
              <el-table-column label="操作" width="90">
                <template #default="{ row }">
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
      </el-tabs>
    </div>

    <el-dialog v-model="editorVisible" :title="editing ? `编辑模板：${editing.name}` : '编辑模板'" width="min(720px, 94vw)">
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
          <el-input v-model="editForm.body" type="textarea" :rows="10" />
        </el-form-item>
        <el-form-item label="启用">
          <el-switch v-model="editForm.enabled" />
        </el-form-item>
      </el-form>
      <el-alert
        type="info"
        :closable="false"
        show-icon
        title="可用变量"
        description="{{ project.name }} {{ project.code }} {{ change.code }} {{ change.title }} {{ operator.name }} {{ reason }} {{ time }} {{ link }}"
      />
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

@media (max-width: 900px) {
  .form-cols {
    grid-template-columns: 1fr;
  }

  .test-input {
    width: 100%;
  }
}
</style>
