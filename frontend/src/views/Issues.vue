<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, RefreshCw } from 'lucide-vue-next'
import IssueFormDialog from '@/components/IssueFormDialog.vue'
import {
  changeIssueStatus,
  deleteIssue,
  issueOptions,
  listIssues,
  type IssueFormOptions,
  type IssueItem
} from '@/api'
import { useUserStore } from '@/stores/user'

defineOptions({ name: 'IssuesPage' })

const route = useRoute()
const router = useRouter()
const store = useUserStore()

/** 类型由路由 meta 决定：/bugs 与 /prod-issues 共用这一个页面。 */
const issueType = computed(() => String(route.meta.issueType || 'BUG').toUpperCase())
const isProd = computed(() => issueType.value === 'PROD')
const listPath = computed(() => (isProd.value ? '/prod-issues' : '/bugs'))
const pageTitle = computed(() => (isProd.value ? '生产问题' : 'Bug 列表'))
const pageDesc = computed(() =>
  isProd.value
    ? '项目上线或交付后在真实环境出现的问题，登记后跟进到关闭'
    : '开发、测试、验收阶段发现的功能缺陷，登记后跟进到关闭'
)

const SEVERITY: Record<string, { label: string; type: 'info' | 'success' | 'warning' | 'danger' }> = {
  LOW: { label: '低', type: 'info' },
  MEDIUM: { label: '中', type: 'warning' },
  HIGH: { label: '高', type: 'danger' },
  URGENT: { label: '紧急', type: 'danger' }
}
const PRIORITY: Record<string, string> = { LOW: '低', MEDIUM: '中', HIGH: '高' }
const STATUS: Record<string, { label: string; type: 'info' | 'success' | 'warning' | 'danger' }> = {
  OPEN: { label: '待处理', type: 'danger' },
  IN_PROGRESS: { label: '处理中', type: 'warning' },
  CLOSED: { label: '已关闭', type: 'success' }
}

const severityMeta = (value: string) => SEVERITY[value] || SEVERITY.MEDIUM
const statusMeta = (value: string) => STATUS[value] || { label: value || '—', type: 'info' as const }

const options = ref<IssueFormOptions>({
  projects: [],
  products: [],
  users: [],
  types: [],
  statuses: [],
  severities: [],
  priorities: [],
  canManage: false
})

const rows = ref<IssueItem[]>([])
const total = ref(0)
const page = ref({ pageNum: 1, pageSize: 20 })
const loading = ref(false)
const keyword = ref('')
const filterProject = ref('')
/** 产品筛选：仅生产问题有产品归属 */
const filterProduct = ref('')
const filterStatus = ref('')
const filterSeverity = ref('')
/** 列表视角：全部 / 指派给我 / 我提的 / 由我解决（后端按 ownerId / reporterId / 状态过滤）。 */
const scope = ref<'ALL' | 'MINE_OWNER' | 'MINE_REPORTER' | 'MINE_CLOSED'>('ALL')
/** 由我解决 = 负责人是我且已关闭，状态筛选固定为已关闭。 */
const statusLocked = computed(() => scope.value === 'MINE_CLOSED')

const canManage = computed(() => Boolean(options.value.canManage))
const me = computed(() => String(store.profile?.id || ''))
/** 提报人、负责人、问题管理员可编辑/流转/删除。 */
const canEditRow = (row: any) =>
  canManage.value ||
  String(row.reporterId || '') === me.value ||
  String(row.ownerId || '') === me.value

const loadOptions = async () => {
  try {
    options.value = await issueOptions()
  } catch {
    /* 错误提示由请求拦截器统一弹出 */
  }
}

const load = async () => {
  loading.value = true
  try {
    const data = await listIssues({
      issueType: issueType.value,
      pageNum: page.value.pageNum,
      pageSize: page.value.pageSize,
      keyword: keyword.value.trim() || undefined,
      projectId: filterProject.value || undefined,
      productId: filterProduct.value || undefined,
      status: statusLocked.value ? 'CLOSED' : filterStatus.value || undefined,
      severity: filterSeverity.value || undefined,
      ownerId:
        scope.value === 'MINE_OWNER' || scope.value === 'MINE_CLOSED' ? me.value : undefined,
      reporterId: scope.value === 'MINE_REPORTER' ? me.value : undefined
    })
    rows.value = (data.list || []) as IssueItem[]
    total.value = Number(data.total || 0)
  } finally {
    loading.value = false
  }
}

/** 筛选变化回到第一页（服务端筛选）。 */
const onSearch = () => {
  page.value.pageNum = 1
  load()
}

/** 切换视角：由我解决时锁定状态为已关闭，切走时把锁定值还原。 */
const onScopeChange = () => {
  if (statusLocked.value) {
    filterStatus.value = 'CLOSED'
  } else if (filterStatus.value === 'CLOSED') {
    filterStatus.value = ''
  }
  onSearch()
}

const resetFilters = () => {
  keyword.value = ''
  filterProject.value = ''
  filterProduct.value = ''
  filterStatus.value = ''
  filterSeverity.value = ''
  scope.value = 'ALL'
  onSearch()
}

const onSizeChange = () => {
  page.value.pageNum = 1
  load()
}

/* 新建 / 编辑弹窗（详情页也有独立页面） */
const formVisible = ref(false)
const editRow = ref<Record<string, any> | null>(null)

const openCreate = () => {
  editRow.value = null
  formVisible.value = true
}

const openEdit = (row: any) => {
  editRow.value = row
  formVisible.value = true
}

const onSaved = async () => {
  await load()
}

/** 查看详情：独立页面，可刷新、可分享。 */
const viewDetail = (row: any) => router.push(`${listPath.value}/${row.id}`)

/** 操作列状态按钮：待处理 → 处理中 → 已关闭，已关闭可重开。 */
const nextStatus = (row: any) =>
  row.status === 'OPEN' ? 'IN_PROGRESS' : row.status === 'IN_PROGRESS' ? 'CLOSED' : 'OPEN'
const statusActionLabel = (row: any) =>
  row.status === 'OPEN' ? '处理' : row.status === 'IN_PROGRESS' ? '关闭' : '重开'

const setStatus = async (row: any, status: string) => {
  try {
    await changeIssueStatus(String(row.id), status)
    ElMessage.success('状态已更新')
    await load()
  } catch {
    /* 错误提示由请求拦截器统一弹出 */
  }
}

const remove = async (row: any) => {
  try {
    await ElMessageBox.confirm(`确认删除「${row.title}」？`, '删除问题', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消'
    })
  } catch {
    return
  }
  try {
    await deleteIssue(String(row.id))
    ElMessage.success('问题已删除')
    await load()
  } catch {
    /* 错误提示由请求拦截器统一弹出 */
  }
}

let resizeHandler: (() => void) | null = null
const isNarrow = ref(false)
const syncWidth = () => {
  isNarrow.value = window.innerWidth <= 768
}

/** 同一个组件在两个菜单下复用，切换路由时按新类型重查。 */
watch(issueType, () => {
  page.value.pageNum = 1
  load()
})

onMounted(async () => {
  syncWidth()
  resizeHandler = syncWidth
  window.addEventListener('resize', resizeHandler)
  await loadOptions()
  await load()
})

onUnmounted(() => {
  if (resizeHandler) window.removeEventListener('resize', resizeHandler)
})
</script>

<template>
  <div v-loading="loading" class="pms-page">
    <div class="pms-card head-card">
      <div class="head-main">
        <h2>{{ pageTitle }}</h2>
        <p>{{ pageDesc }}</p>
      </div>
      <div class="head-actions">
        <el-button
          circle
          :icon="RefreshCw"
          :loading="loading"
          title="刷新列表"
          @click="load"
        />
        <el-button type="primary" :icon="Plus" @click="openCreate">
          提交{{ isProd ? '生产问题' : 'Bug' }}
        </el-button>
      </div>
    </div>

    <div class="pms-card">
      <div class="toolbar">
        <el-radio-group v-model="scope" size="small" @change="onScopeChange">
          <el-radio-button value="ALL">全部</el-radio-button>
          <el-radio-button value="MINE_OWNER">指派给我</el-radio-button>
          <el-radio-button value="MINE_REPORTER">我提的</el-radio-button>
          <el-radio-button value="MINE_CLOSED">由我解决</el-radio-button>
        </el-radio-group>
        <el-input
          v-model="keyword"
          class="filter-keyword"
          placeholder="搜索编号 / 标题 / 描述"
          clearable
          @keyup.enter="onSearch"
          @clear="onSearch"
        />
        <el-select
          v-model="filterProject"
          class="filter-project"
          placeholder="全部项目"
          clearable
          filterable
          @change="onSearch"
        >
          <el-option
            v-for="item in options.projects"
            :key="String(item.id)"
            :label="item.projectName"
            :value="String(item.id)"
          />
        </el-select>
        <el-select
          v-if="isProd"
          v-model="filterProduct"
          class="filter-product"
          placeholder="全部产品"
          clearable
          filterable
          @change="onSearch"
        >
          <el-option
            v-for="item in options.products"
            :key="String(item.id)"
            :label="item.productName"
            :value="String(item.id)"
          />
        </el-select>
        <el-select
          v-model="filterStatus"
          class="filter-status"
          placeholder="全部状态"
          clearable
          :disabled="statusLocked"
          @change="onSearch"
        >
          <el-option
            v-for="(meta, value) in STATUS"
            :key="value"
            :label="meta.label"
            :value="value"
          />
        </el-select>
        <el-select
          v-model="filterSeverity"
          class="filter-severity"
          placeholder="全部严重程度"
          clearable
          @change="onSearch"
        >
          <el-option
            v-for="(meta, value) in SEVERITY"
            :key="value"
            :label="meta.label"
            :value="value"
          />
        </el-select>
        <el-button @click="onSearch">查询</el-button>
        <el-button text @click="resetFilters">重置</el-button>
      </div>
      <el-table :data="rows" row-key="id" size="small" :empty-text="`暂无${pageTitle}`">
        <el-table-column label="编号" width="100">
          <template #default="{ row }">
            <el-button link type="primary" class="num-cell" @click="viewDetail(row)">
              {{ row.issueNo || '—' }}
            </el-button>
          </template>
        </el-table-column>
        <el-table-column label="问题" min-width="260">
          <template #default="{ row }">
            <el-button link type="primary" class="cell-title" @click="viewDetail(row)">
              {{ row.title }}
            </el-button>
            <div v-if="row.description" class="cell-sub">{{ row.description }}</div>
          </template>
        </el-table-column>
        <el-table-column label="项目" min-width="160" show-overflow-tooltip>
          <template #default="{ row }">{{ row.projectName || '—' }}</template>
        </el-table-column>
        <!-- 生产问题在项目结项后靠产品归集，Bug 不涉及产品 -->
        <el-table-column v-if="isProd" label="产品" min-width="150" show-overflow-tooltip>
          <template #default="{ row }">{{ row.productName || '—' }}</template>
        </el-table-column>
        <el-table-column label="严重程度" width="96">
          <template #default="{ row }">
            <el-tag size="small" :type="severityMeta(row.severity).type" effect="plain">
              {{ severityMeta(row.severity).label }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="优先级" width="88">
          <template #default="{ row }">{{ PRIORITY[row.priority] || row.priority || '—' }}</template>
        </el-table-column>
        <el-table-column label="状态" width="96">
          <template #default="{ row }">
            <el-tag size="small" :type="statusMeta(row.status).type" effect="plain">
              {{ statusMeta(row.status).label }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="负责人" width="110" show-overflow-tooltip>
          <template #default="{ row }">{{ row.ownerName || '未指派' }}</template>
        </el-table-column>
        <el-table-column label="提报人" width="110" show-overflow-tooltip>
          <template #default="{ row }">{{ row.reporterName || '—' }}</template>
        </el-table-column>
        <el-table-column label="发现日期" width="112">
          <template #default="{ row }">{{ row.foundDate || '—' }}</template>
        </el-table-column>
        <el-table-column label="操作" :width="canManage ? 196 : 164" fixed="right">
          <template #default="{ row }">
            <div class="row-ops">
              <el-button link type="primary" @click="viewDetail(row)">详情</el-button>
              <template v-if="canEditRow(row)">
                <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
                <el-button link type="primary" @click="setStatus(row, nextStatus(row))">
                  {{ statusActionLabel(row) }}
                </el-button>
                <el-button v-if="canManage" link type="danger" @click="remove(row)">
                  删除
                </el-button>
              </template>
            </div>
          </template>
        </el-table-column>
      </el-table>
      <el-pagination
        v-model:current-page="page.pageNum"
        v-model:page-size="page.pageSize"
        :total="total"
        :page-sizes="[10, 20, 50]"
        :layout="isNarrow ? 'prev, pager, next' : 'total, sizes, prev, pager, next'"
        @current-change="load"
        @size-change="onSizeChange"
      />
    </div>

    <IssueFormDialog
      v-model="formVisible"
      :issue-type="issueType"
      :issue="editRow"
      @saved="onSaved"
    />
  </div>
</template>

<style scoped>
.head-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.head-main h2 {
  margin: 0 0 4px;
  font-size: 16px;
  font-weight: 600;
  color: var(--pms-text);
}

.head-main p {
  margin: 0;
  font-size: 12.5px;
  color: var(--pms-text-3);
}

.head-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.toolbar {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
  margin-bottom: 12px;
}

.filter-keyword {
  width: 240px;
}

.filter-project,
.filter-product {
  width: 200px;
}

.filter-status,
.filter-severity {
  width: 140px;
}

.cell-title {
  padding: 0;
  font-size: 13px;
  font-weight: 500;
  text-align: left;
}

.cell-sub {
  overflow: hidden;
  margin-top: 2px;
  font-size: 12px;
  color: var(--pms-text-3);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.num-cell {
  padding: 0;
  font-variant-numeric: tabular-nums;
}

/* 操作列：一行排开，不再折行 */
.row-ops {
  display: flex;
  align-items: center;
  gap: 10px;
  white-space: nowrap;
}

.row-ops :deep(.el-button) {
  margin-left: 0;
  padding: 0;
  font-size: 12.5px;
}

:deep(.el-pagination) {
  margin-top: 12px;
  justify-content: flex-end;
}

@media (max-width: 768px) {
  .filter-keyword,
  .filter-project,
  .filter-product,
  .filter-status,
  .filter-severity {
    width: 100%;
  }
}
</style>
