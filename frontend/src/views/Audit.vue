<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  archiveAudit,
  auditArchivePolicy,
  listAuditModules,
  listLoginLogs,
  listOperateLogs,
  type ArchiveReport
} from '@/api'
import { useUserStore } from '@/stores/user'

interface OperateLog {
  id: string
  module: string
  operation: string
  method: string
  url: string
  params: string
  result: string
  ip: string
  userId: string
  userName: string
  realName: string
  costMs: number
  traceId: string
  createTime: string
}

interface LoginLog {
  id: string
  username: string
  ip: string
  userAgent: string
  status: string
  message: string
  traceId: string
  createTime: string
}

type TagType = 'success' | 'warning' | 'info' | 'danger'

const store = useUserStore()
/** 归档会搬移并删除主表数据，需要与后端一致的 sys:config 权限。 */
const canArchive = computed(() => store.has('sys:config'))

/** 窄屏精简分页控件，避免页码与每页条数挤在一行重叠。 */
const isNarrow = ref(false)
const syncWidth = () => {
  isNarrow.value = window.innerWidth <= 768
}

const MODULE_LABELS: Record<string, string> = {
  project: '项目',
  change: '变更',
  worklog: '工作日志',
  report: '统计看板',
  crm: '客户商机',
  org: '组织权限',
  system: '系统管理',
  auth: '认证登录',
  file: '文件'
}
const moduleLabel = (code: string) => MODULE_LABELS[code] || code || 'system'

const RESULT_META: Record<string, { label: string; type: TagType }> = {
  SUCCESS: { label: '成功', type: 'success' },
  DENIED: { label: '拒绝', type: 'danger' },
  FAIL: { label: '失败', type: 'warning' },
  ERROR: { label: '错误', type: 'danger' }
}
const resultMeta = (result: string) =>
  RESULT_META[result] || { label: result || '-', type: 'info' as TagType }

const LOGIN_META: Record<string, { label: string; type: TagType }> = {
  SUCCESS: { label: '成功', type: 'success' },
  FAIL: { label: '失败', type: 'danger' },
  LOGOUT: { label: '登出', type: 'info' }
}
const loginMeta = (status: string) =>
  LOGIN_META[status] || { label: status || '-', type: 'info' as TagType }

const timeText = (value: string) => (value ? value.replace('T', ' ').slice(0, 19) : '-')

/* ------------------------------ 操作审计 ------------------------------ */
const tab = ref('operate')
const modules = ref<string[]>([])
const operateRows = ref<OperateLog[]>([])
const operateTotal = ref(0)
const operateLoading = ref(false)
const operateLoaded = ref(false)
const operatePage = reactive({ pageNum: 1, pageSize: 10 })
const operateFilter = reactive({
  module: '',
  result: '',
  userId: undefined as number | undefined,
  keyword: '',
  dateRange: [] as string[]
})

const loadOperate = async () => {
  operateLoading.value = true
  try {
    const [dateFrom, dateTo] = operateFilter.dateRange
    const data = await listOperateLogs({
      pageNum: operatePage.pageNum,
      pageSize: operatePage.pageSize,
      module: operateFilter.module || undefined,
      result: operateFilter.result || undefined,
      user_id: operateFilter.userId || undefined,
      keyword: operateFilter.keyword.trim() || undefined,
      dateFrom,
      dateTo
    })
    operateRows.value = (data.list || []) as unknown as OperateLog[]
    operateTotal.value = data.total || 0
    operateLoaded.value = true
  } catch {
    /* 错误提示由请求拦截器统一弹出 */
  } finally {
    operateLoading.value = false
  }
}

const searchOperate = () => {
  operatePage.pageNum = 1
  loadOperate()
}

const resetOperate = () => {
  operateFilter.module = ''
  operateFilter.result = ''
  operateFilter.userId = undefined
  operateFilter.keyword = ''
  operateFilter.dateRange = []
  searchOperate()
}

/* ------------------------------ 登录日志 ------------------------------ */
const loginRows = ref<LoginLog[]>([])
const loginTotal = ref(0)
const loginLoading = ref(false)
const loginLoaded = ref(false)
const loginPage = reactive({ pageNum: 1, pageSize: 10 })
const loginFilter = reactive({
  username: '',
  status: '',
  dateRange: [] as string[]
})

const loadLogin = async () => {
  loginLoading.value = true
  try {
    const [dateFrom, dateTo] = loginFilter.dateRange
    const data = await listLoginLogs({
      pageNum: loginPage.pageNum,
      pageSize: loginPage.pageSize,
      username: loginFilter.username.trim() || undefined,
      status: loginFilter.status || undefined,
      dateFrom,
      dateTo
    })
    loginRows.value = (data.list || []) as unknown as LoginLog[]
    loginTotal.value = data.total || 0
    loginLoaded.value = true
  } catch {
    /* 错误提示由请求拦截器统一弹出 */
  } finally {
    loginLoading.value = false
  }
}

const searchLogin = () => {
  loginPage.pageNum = 1
  loadLogin()
}

const resetLogin = () => {
  loginFilter.username = ''
  loginFilter.status = ''
  loginFilter.dateRange = []
  searchLogin()
}

const onTabChange = (name: string | number) => {
  if (name === 'login' && !loginLoaded.value) loadLogin()
}

const refresh = () => (tab.value === 'login' ? loadLogin() : loadOperate())

/* ------------------------------ 详情抽屉 ------------------------------ */
const operateDetailVisible = ref(false)
const operateDetail = ref<OperateLog | null>(null)
const loginDetailVisible = ref(false)
const loginDetail = ref<LoginLog | null>(null)

const openOperate = (raw: unknown) => {
  operateDetail.value = raw as OperateLog
  operateDetailVisible.value = true
}

const openLogin = (raw: unknown) => {
  loginDetail.value = raw as LoginLog
  loginDetailVisible.value = true
}

const userLabel = (raw: unknown) => {
  const row = raw as OperateLog
  if (!row.userId || row.userId === '0') return '匿名 / 系统'
  return row.realName || row.userName || `用户 ${row.userId}`
}

/** 入参统一脱敏后存库，这里尽量格式化为可读 JSON。 */
const prettyParams = computed(() => {
  const raw = operateDetail.value?.params || ''
  if (!raw) return '（无入参）'
  try {
    return JSON.stringify(JSON.parse(raw), null, 2)
  } catch {
    return raw
  }
})

/* ------------------------------ 按月归档 ------------------------------ */
const archiveVisible = ref(false)
const keepMonths = ref(12)
const previewing = ref(false)
const archiving = ref(false)
const preview = ref<ArchiveReport | null>(null)

const TABLE_LABELS: Record<string, string> = {
  t_sys_operate_log: '操作审计',
  t_sys_login_log: '登录日志'
}

const previewRows = computed(() => {
  const tables = preview.value?.tables || {}
  return Object.entries(tables).flatMap(([table, months]) =>
    Object.entries(months).map(([month, count]) => ({
      table: TABLE_LABELS[table] || table,
      month,
      count
    }))
  )
})

const canExecute = computed(
  () => !!preview.value && preview.value.dryRun && preview.value.total > 0
)

const openArchive = () => {
  preview.value = null
  archiveVisible.value = true
}

const runPreview = async () => {
  previewing.value = true
  try {
    preview.value = await archiveAudit({ keepMonths: keepMonths.value, dryRun: true })
    const total = preview.value.total || 0
    if (total) {
      ElMessage.success(`预演完成：${total} 行将被归档`)
    } else {
      ElMessage.info('当前没有超出保留期的日志')
    }
  } catch {
    /* 错误提示由请求拦截器统一弹出 */
  } finally {
    previewing.value = false
  }
}

const runArchive = async () => {
  if (!canExecute.value || !preview.value) return
  try {
    await ElMessageBox.confirm(
      `将把 ${preview.value.total} 行早于 ${preview.value.cutoff} 的日志搬入月份归档表，并从主表删除。该操作不可自动撤销，确认继续？`,
      '执行归档',
      { type: 'warning', confirmButtonText: '执行归档', cancelButtonText: '取消' }
    )
  } catch {
    return
  }
  archiving.value = true
  try {
    const report = await archiveAudit({ keepMonths: keepMonths.value, dryRun: false })
    preview.value = report
    ElMessage.success(`已归档 ${report.total} 行`)
    if (tab.value === 'login') {
      await loadLogin()
    } else {
      await loadOperate()
    }
  } catch {
    /* 错误提示由请求拦截器统一弹出 */
  } finally {
    archiving.value = false
  }
}

const loadModules = async () => {
  try {
    modules.value = (await listAuditModules()) || []
  } catch {
    /* 模块下拉加载失败不影响查询 */
  }
}

const loadPolicy = async () => {
  try {
    const policy = await auditArchivePolicy()
    keepMonths.value = policy.keepMonths || policy.defaultKeepMonths || 12
  } catch {
    /* 读取策略失败时沿用默认保留月数 */
  }
}

onMounted(() => {
  syncWidth()
  window.addEventListener('resize', syncWidth)
  loadOperate()
  loadModules()
  loadPolicy()
})

onUnmounted(() => window.removeEventListener('resize', syncWidth))
</script>

<template>
  <div class="pms-page">
    <div class="pms-card audit-head">
      <div class="head-main">
        <h3>审计留痕</h3>
        <p class="head-desc">
          写操作全量记录，读操作仅记录失败与权限拒绝；口令与令牌已脱敏，不入库。
        </p>
      </div>
      <div class="head-actions">
        <el-button v-if="canArchive" @click="openArchive">按月归档</el-button>
        <el-button @click="refresh">刷新</el-button>
      </div>
    </div>

    <el-tabs v-model="tab" @tab-change="onTabChange">
      <el-tab-pane label="操作审计" name="operate">
        <div class="pms-card">
          <div class="filter-grid">
            <el-select
              v-model="operateFilter.module"
              class="f-module"
              placeholder="全部模块"
              clearable
              filterable
              allow-create
            >
              <el-option
                v-for="item in modules"
                :key="item"
                :label="`${moduleLabel(item)}（${item}）`"
                :value="item"
              />
            </el-select>
            <el-select
              v-model="operateFilter.result"
              class="f-result"
              placeholder="全部结果"
              clearable
            >
              <el-option label="成功" value="SUCCESS" />
              <el-option label="拒绝" value="DENIED" />
              <el-option label="失败" value="FAIL" />
              <el-option label="错误" value="ERROR" />
            </el-select>
            <el-input-number
              v-model="operateFilter.userId"
              class="f-user"
              :min="1"
              :controls="false"
              placeholder="操作人 ID"
            />
            <el-input
              v-model="operateFilter.keyword"
              class="f-keyword"
              placeholder="关键字：操作 / URL / 参数 / traceId"
              clearable
              @keyup.enter="searchOperate"
            />
            <el-date-picker
              v-model="operateFilter.dateRange"
              class="f-date"
              type="daterange"
              unlink-panels
              range-separator="至"
              start-placeholder="开始日期"
              end-placeholder="结束日期"
              value-format="YYYY-MM-DD"
            />
            <div class="filter-actions">
              <el-button type="primary" :loading="operateLoading" @click="searchOperate">
                查询
              </el-button>
              <el-button @click="resetOperate">重置</el-button>
            </div>
          </div>
        </div>

        <div class="pms-card">
          <div class="table-head">
            <span>共 {{ operateTotal }} 条记录</span>
          </div>
          <el-table v-loading="operateLoading" :data="operateRows" size="small">
            <el-table-column label="时间" width="170">
              <template #default="{ row }">{{ timeText(row.createTime) }}</template>
            </el-table-column>
            <el-table-column label="模块" width="110">
              <template #default="{ row }">
                <el-tag size="small" effect="plain">{{ moduleLabel(row.module) }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="操作" min-width="240">
              <template #default="{ row }">
                <el-button link type="primary" class="op-link" @click="openOperate(row)">
                  {{ row.operation }}
                </el-button>
              </template>
            </el-table-column>
            <el-table-column label="结果" width="90">
              <template #default="{ row }">
                <el-tag size="small" :type="resultMeta(row.result).type">
                  {{ resultMeta(row.result).label }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="操作人" width="140">
              <template #default="{ row }">
                <span class="user-cell">{{ userLabel(row) }}</span>
              </template>
            </el-table-column>
            <el-table-column prop="ip" label="IP" width="130" class-name="pms-mobile-hide" />
            <el-table-column label="耗时" width="90" class-name="pms-mobile-hide">
              <template #default="{ row }">{{ row.costMs }} ms</template>
            </el-table-column>
            <el-table-column label="详情" width="72">
              <template #default="{ row }">
                <el-button link type="primary" @click="openOperate(row)">查看</el-button>
              </template>
            </el-table-column>
            <template #empty>
              <el-empty description="没有匹配的操作审计" :image-size="72" />
            </template>
          </el-table>
          <el-pagination
            v-model:current-page="operatePage.pageNum"
            v-model:page-size="operatePage.pageSize"
            :total="operateTotal"
            :page-sizes="[10, 20, 50]"
            :layout="isNarrow ? 'prev, pager, next' : 'total, sizes, prev, pager, next'"
            class="pager"
            @current-change="loadOperate"
            @size-change="searchOperate"
          />
        </div>
      </el-tab-pane>

      <el-tab-pane label="登录日志" name="login">
        <div class="pms-card">
          <div class="filter-grid">
            <el-input
              v-model="loginFilter.username"
              class="f-username"
              placeholder="账号（支持模糊）"
              clearable
              @keyup.enter="searchLogin"
            />
            <el-select
              v-model="loginFilter.status"
              class="f-result"
              placeholder="全部状态"
              clearable
            >
              <el-option label="成功" value="SUCCESS" />
              <el-option label="失败" value="FAIL" />
              <el-option label="登出" value="LOGOUT" />
            </el-select>
            <el-date-picker
              v-model="loginFilter.dateRange"
              class="f-date"
              type="daterange"
              unlink-panels
              range-separator="至"
              start-placeholder="开始日期"
              end-placeholder="结束日期"
              value-format="YYYY-MM-DD"
            />
            <div class="filter-actions">
              <el-button type="primary" :loading="loginLoading" @click="searchLogin">
                查询
              </el-button>
              <el-button @click="resetLogin">重置</el-button>
            </div>
          </div>
        </div>

        <div class="pms-card">
          <div class="table-head">
            <span>共 {{ loginTotal }} 条记录</span>
          </div>
          <el-table v-loading="loginLoading" :data="loginRows" size="small">
            <el-table-column label="时间" width="170">
              <template #default="{ row }">{{ timeText(row.createTime) }}</template>
            </el-table-column>
            <el-table-column prop="username" label="账号" width="150" />
            <el-table-column label="状态" width="90">
              <template #default="{ row }">
                <el-tag size="small" :type="loginMeta(row.status).type">
                  {{ loginMeta(row.status).label }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="ip" label="IP" width="140" />
            <el-table-column prop="message" label="说明" min-width="180" show-overflow-tooltip />
            <el-table-column label="详情" width="72">
              <template #default="{ row }">
                <el-button link type="primary" @click="openLogin(row)">查看</el-button>
              </template>
            </el-table-column>
            <template #empty>
              <el-empty description="没有匹配的登录日志" :image-size="72" />
            </template>
          </el-table>
          <el-pagination
            v-model:current-page="loginPage.pageNum"
            v-model:page-size="loginPage.pageSize"
            :total="loginTotal"
            :page-sizes="[10, 20, 50]"
            :layout="isNarrow ? 'prev, pager, next' : 'total, sizes, prev, pager, next'"
            class="pager"
            @current-change="loadLogin"
            @size-change="searchLogin"
          />
        </div>
      </el-tab-pane>
    </el-tabs>

    <el-drawer v-model="operateDetailVisible" title="操作详情" size="min(560px, 92vw)">
      <div v-if="operateDetail" class="detail">
        <el-descriptions :column="1" border size="small">
          <el-descriptions-item label="时间">
            {{ timeText(operateDetail.createTime) }}
          </el-descriptions-item>
          <el-descriptions-item label="模块">
            {{ moduleLabel(operateDetail.module) }}
          </el-descriptions-item>
          <el-descriptions-item label="操作">{{ operateDetail.operation }}</el-descriptions-item>
          <el-descriptions-item label="方法">
            <el-tag size="small" effect="plain">{{ operateDetail.method || '-' }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="结果">
            <el-tag size="small" :type="resultMeta(operateDetail.result).type">
              {{ resultMeta(operateDetail.result).label }}
            </el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="操作人">{{ userLabel(operateDetail) }}</el-descriptions-item>
          <el-descriptions-item label="IP">{{ operateDetail.ip || '-' }}</el-descriptions-item>
          <el-descriptions-item label="耗时">{{ operateDetail.costMs }} ms</el-descriptions-item>
          <el-descriptions-item label="URL">
            <span class="mono">{{ operateDetail.url || '-' }}</span>
          </el-descriptions-item>
          <el-descriptions-item label="traceId">
            <span class="mono">{{ operateDetail.traceId || '-' }}</span>
          </el-descriptions-item>
        </el-descriptions>
        <div class="params-block">
          <div class="params-title">请求入参（敏感字段已脱敏）</div>
          <pre class="params-pre">{{ prettyParams }}</pre>
        </div>
      </div>
    </el-drawer>

    <el-drawer v-model="loginDetailVisible" title="登录详情" size="min(520px, 92vw)">
      <div v-if="loginDetail" class="detail">
        <el-descriptions :column="1" border size="small">
          <el-descriptions-item label="时间">
            {{ timeText(loginDetail.createTime) }}
          </el-descriptions-item>
          <el-descriptions-item label="账号">{{ loginDetail.username || '-' }}</el-descriptions-item>
          <el-descriptions-item label="状态">
            <el-tag size="small" :type="loginMeta(loginDetail.status).type">
              {{ loginMeta(loginDetail.status).label }}
            </el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="IP">{{ loginDetail.ip || '-' }}</el-descriptions-item>
          <el-descriptions-item label="说明">{{ loginDetail.message || '-' }}</el-descriptions-item>
          <el-descriptions-item label="traceId">
            <span class="mono">{{ loginDetail.traceId || '-' }}</span>
          </el-descriptions-item>
        </el-descriptions>
        <div class="params-block">
          <div class="params-title">User-Agent</div>
          <pre class="params-pre">{{ loginDetail.userAgent || '（未记录）' }}</pre>
        </div>
      </div>
    </el-drawer>

    <el-dialog
      v-model="archiveVisible"
      title="审计表按月归档"
      width="90%"
      style="max-width: 720px"
    >
      <el-alert
        type="warning"
        :closable="false"
        show-icon
        title="归档会把超出保留期的日志搬入月份表（t_sys_*_YYYYMM），并从主表删除。建议先预演确认影响行数。"
      />
      <div class="archive-form">
        <span>保留最近</span>
        <el-input-number v-model="keepMonths" :min="1" :max="120" :disabled="archiving" />
        <span>个月（含当月），更早的数据按月归档</span>
      </div>
      <div class="archive-actions">
        <el-button :loading="previewing" :disabled="archiving" @click="runPreview">预演</el-button>
        <el-button
          type="warning"
          :loading="archiving"
          :disabled="!canExecute"
          @click="runArchive"
        >
          执行归档
        </el-button>
      </div>

      <template v-if="preview">
        <el-divider content-position="left">
          {{ preview.dryRun ? '预演结果' : '归档结果' }} · 分界 {{ preview.cutoff }}
        </el-divider>
        <el-empty v-if="!previewRows.length" description="没有需要归档的数据" :image-size="72" />
        <template v-else>
          <el-table :data="previewRows" size="small" max-height="240">
            <el-table-column prop="table" label="审计表" min-width="160" />
            <el-table-column prop="month" label="月份" width="120" />
            <el-table-column label="行数" width="100" align="right">
              <template #default="{ row }">{{ row.count }}</template>
            </el-table-column>
          </el-table>
          <p class="archive-total">合计 {{ preview.total }} 行</p>
        </template>
      </template>

      <template #footer>
        <el-button @click="archiveVisible = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.audit-head {
  display: flex;
  align-items: flex-start;
  flex-wrap: wrap;
  gap: 12px;
}

.head-main {
  flex: 1 1 360px;
  min-width: 0;
}

.head-main h3 {
  margin: 0 0 6px;
  font-size: 15px;
  font-weight: 600;
  color: var(--pms-text);
}

.head-desc {
  margin: 0;
  font-size: 12.5px;
  line-height: 1.7;
  color: var(--pms-text-3);
}

.head-actions {
  flex: none;
  display: flex;
  align-items: center;
  gap: 8px;
  margin-left: auto;
}

/* 筛选区用弹性换行布局：控件保持自身宽度，空间不足时整体换行，避免互相挤压重叠 */
.filter-grid {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
}

/* Element Plus 组件根节点不带 scoped 属性，尺寸规则需用 :deep 命中 */
.filter-grid :deep(.f-module) {
  flex: 0 0 176px;
}

.filter-grid :deep(.f-result) {
  flex: 0 0 132px;
}

.filter-grid :deep(.f-user) {
  flex: 0 0 128px;
}

.filter-grid :deep(.f-username) {
  flex: 0 0 190px;
}

.filter-grid :deep(.f-keyword) {
  flex: 1 1 240px;
  min-width: 200px;
}

.filter-grid :deep(.f-date) {
  flex: 0 0 270px;
}

.filter-grid :deep(.el-date-editor),
.filter-grid :deep(.el-input-number),
.filter-grid :deep(.el-select),
.filter-grid :deep(.el-input) {
  width: 100%;
}

.filter-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-left: auto;
  white-space: nowrap;
}

.table-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
  font-size: 12.5px;
  color: var(--pms-text-3);
}

.op-link {
  display: inline-block;
  max-width: 100%;
  overflow: hidden;
  text-align: left;
  text-overflow: ellipsis;
  white-space: nowrap;
  vertical-align: bottom;
}

.user-cell {
  display: inline-block;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.pager {
  flex-wrap: wrap;
  row-gap: 8px;
  margin-top: 14px;
  justify-content: flex-end;
}

/* ---------------- 详情抽屉 ---------------- */
.detail {
  padding: 16px 20px 24px;
}

.detail :deep(.el-descriptions__label) {
  width: 96px;
  color: var(--pms-text-3);
  white-space: nowrap;
}

.mono {
  font-family: ui-monospace, SFMono-Regular, Consolas, 'Liberation Mono', monospace;
  font-size: 12px;
  word-break: break-all;
}

.params-block {
  margin-top: 16px;
}

.params-title {
  margin-bottom: 8px;
  font-size: 12.5px;
  color: var(--pms-text-3);
}

.params-pre {
  max-height: 340px;
  margin: 0;
  padding: 12px 14px;
  overflow: auto;
  border: 1px solid var(--pms-line);
  border-radius: var(--pms-radius-sm);
  background: #fafbfe;
  color: var(--pms-text-2);
  font-family: ui-monospace, SFMono-Regular, Consolas, 'Liberation Mono', monospace;
  font-size: 12px;
  line-height: 1.65;
  white-space: pre-wrap;
  word-break: break-all;
}

/* ---------------- 归档 ---------------- */
.archive-form {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  margin: 16px 0 4px;
  font-size: 13px;
  color: var(--pms-text-2);
}

.archive-actions {
  display: flex;
  gap: 8px;
  margin-top: 10px;
}

.archive-total {
  margin: 10px 0 0;
  font-size: 12.5px;
  color: var(--pms-text-2);
  text-align: right;
}

@media (max-width: 768px) {
  .filter-grid :deep(.f-module),
  .filter-grid :deep(.f-result),
  .filter-grid :deep(.f-user),
  .filter-grid :deep(.f-username),
  .filter-grid :deep(.f-keyword),
  .filter-grid :deep(.f-date) {
    flex: 1 1 100%;
    min-width: 0;
  }

  .filter-actions {
    width: 100%;
    margin-left: 0;
    justify-content: flex-end;
  }

  .head-actions {
    width: 100%;
    margin-left: 0;
    justify-content: flex-end;
  }

  .pager {
    justify-content: center;
  }

  .pager :deep(.el-pagination__sizes) {
    margin-left: 0;
  }

  .detail {
    padding: 12px 14px 20px;
  }
}
</style>
