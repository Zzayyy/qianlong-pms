<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus } from 'lucide-vue-next'
import {
  createProduct,
  deleteProduct,
  listProducts,
  updateProduct,
  type ProductItem
} from '@/api'
import { useUserStore } from '@/stores/user'

defineOptions({ name: 'ProductsPage' })

const store = useUserStore()
const canManage = computed(() => store.has('crm:product:manage'))

/** 产品类别（与后端 `_PRODUCT_CATEGORIES` 对齐）。 */
const CATEGORY: Record<string, string> = {
  SOFTWARE: '软件产品',
  HARDWARE: '硬件设备',
  SERVICE: '技术服务',
  SOLUTION: '解决方案',
  OTHER: '其他'
}
/** 产品状态。 */
const STATUS: Record<string, { label: string; type: 'success' | 'info' }> = {
  ACTIVE: { label: '在用', type: 'success' },
  INACTIVE: { label: '停用', type: 'info' }
}
const UNIT_OPTIONS = ['套', '个', '台', '人天', '年', '次']

const rows = ref<ProductItem[]>([])
const total = ref(0)
const page = ref({ pageNum: 1, pageSize: 10 })
const loading = ref(false)
const keyword = ref('')
const filterCategory = ref('')
const filterStatus = ref('')

const isNarrow = ref(false)
const syncWidth = () => {
  isNarrow.value = window.innerWidth <= 768
}

const editVisible = ref(false)
const saving = ref(false)
/** 产品说明字数下限（与后端 `_PRODUCT_DESC_MIN` 对齐）。 */
const DESC_MIN = 500
const DESC_MAX = 5000
const editForm = ref<any>({
  id: '',
  productName: '',
  category: 'SOFTWARE',
  spec: '',
  unit: '套',
  description: '',
  status: 'ACTIVE',
  remark: ''
})

/** 只读详情：产品说明较长，列表不展开，点「查看」看完整内容。 */
const detailVisible = ref(false)
const detailRow = ref<any>({})
const openDetail = (row: any) => {
  detailRow.value = row
  detailVisible.value = true
}

const categoryText = (value: string) => CATEGORY[value] || value || '—'
const statusMeta = (value: string) => STATUS[value] || { label: value || '—', type: 'info' as const }

const load = async () => {
  loading.value = true
  try {
    const data = await listProducts({
      pageNum: page.value.pageNum,
      pageSize: page.value.pageSize,
      keyword: keyword.value.trim() || undefined,
      category: filterCategory.value || undefined,
      status: filterStatus.value || undefined
    })
    rows.value = (data.list || []) as ProductItem[]
    total.value = Number(data.total || 0)
  } finally {
    loading.value = false
  }
}

/** 筛选条件变化后回到第一页（服务端筛选，避免分页与总数不一致）。 */
const onSearch = () => {
  page.value.pageNum = 1
  load()
}

const resetFilters = () => {
  keyword.value = ''
  filterCategory.value = ''
  filterStatus.value = ''
  onSearch()
}

const onSizeChange = () => {
  page.value.pageNum = 1
  load()
}

const openCreate = () => {
  editForm.value = {
    id: '',
    productName: '',
    category: 'SOFTWARE',
    spec: '',
    unit: '套',
    description: '',
    status: 'ACTIVE',
    remark: ''
  }
  editVisible.value = true
}

const openEdit = (row: any) => {
  editForm.value = { ...row, description: row.description || '' }
  editVisible.value = true
}

const save = async () => {
  if (!String(editForm.value.productName || '').trim()) {
    ElMessage.warning('请填写产品名称')
    return
  }
  const description = String(editForm.value.description || '').trim()
  if (description.length < DESC_MIN) {
    ElMessage.warning(`产品说明至少 ${DESC_MIN} 字（当前 ${description.length} 字）`)
    return
  }
  if (description.length > DESC_MAX) {
    ElMessage.warning(`产品说明不能超过 ${DESC_MAX} 字`)
    return
  }
  saving.value = true
  try {
    const payload = { ...editForm.value, description }
    delete payload.id
    if (editForm.value.id) {
      await updateProduct(String(editForm.value.id), payload)
      ElMessage.success('产品已更新')
    } else {
      await createProduct(payload)
      ElMessage.success('产品已新增')
    }
    editVisible.value = false
    await load()
  } catch {
    /* 错误提示由请求拦截器统一弹出 */
  } finally {
    saving.value = false
  }
}

const remove = async (row: any) => {
  try {
    await ElMessageBox.confirm(`确认删除产品「${row.productName}」？`, '删除产品', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消'
    })
  } catch {
    return
  }
  try {
    await deleteProduct(String(row.id))
    ElMessage.success('产品已删除')
    await load()
  } catch {
    /* 错误提示由请求拦截器统一弹出 */
  }
}

onMounted(() => {
  syncWidth()
  window.addEventListener('resize', syncWidth)
  load()
})

onUnmounted(() => window.removeEventListener('resize', syncWidth))
</script>

<template>
  <div v-loading="loading" class="pms-page">
    <div class="pms-card">
      <div class="toolbar">
        <div class="toolbar-filters">
          <el-input
            v-model="keyword"
            class="filter-keyword"
            placeholder="按产品名称 / 编码 / 版本搜索"
            clearable
            @keyup.enter="onSearch"
            @clear="onSearch"
          />
          <el-select
            v-model="filterCategory"
            class="filter-category"
            placeholder="全部类别"
            clearable
            @change="onSearch"
          >
            <el-option
              v-for="(label, value) in CATEGORY"
              :key="value"
              :label="label"
              :value="value"
            />
          </el-select>
          <el-select
            v-model="filterStatus"
            class="filter-status"
            placeholder="全部状态"
            clearable
            @change="onSearch"
          >
            <el-option
              v-for="(item, value) in STATUS"
              :key="value"
              :label="item.label"
              :value="value"
            />
          </el-select>
          <el-button @click="onSearch">查询</el-button>
          <el-button text @click="resetFilters">重置</el-button>
        </div>
        <div class="toolbar-actions">
          <el-button
            type="primary"
            :icon="Plus"
            class="pms-create-btn"
            :disabled="!canManage"
            :title="canManage ? '' : '仅产品总监（或系统管理员）可新增产品'"
            @click="openCreate"
          >
            新增产品
          </el-button>
        </div>
      </div>
    </div>

    <div class="pms-card">
      <el-table :data="rows" row-key="id" size="small" empty-text="暂无产品">
        <el-table-column label="产品" min-width="220">
          <template #default="{ row }">
            <div class="cell-main">{{ row.productName }}</div>
            <div class="cell-sub">{{ row.productCode }}</div>
          </template>
        </el-table-column>
        <el-table-column label="类别" width="110">
          <template #default="{ row }">
            <el-tag size="small" effect="plain">{{ categoryText(row.category) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="当前版本" min-width="140" show-overflow-tooltip>
          <template #default="{ row }">{{ row.spec || '—' }}</template>
        </el-table-column>
        <el-table-column label="单位" width="80">
          <template #default="{ row }">{{ row.unit || '—' }}</template>
        </el-table-column>
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag size="small" :type="statusMeta(row.status).type" effect="plain">
              {{ statusMeta(row.status).label }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column
          label="备注"
          min-width="180"
          show-overflow-tooltip
          class-name="pms-mobile-hide"
        >
          <template #default="{ row }">{{ row.remark || '—' }}</template>
        </el-table-column>
        <el-table-column label="操作" :width="canManage ? 150 : 80">
          <template #default="{ row }">
            <el-button link type="primary" @click="openDetail(row)">查看</el-button>
            <template v-if="canManage">
              <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
              <el-button link type="danger" @click="remove(row)">删除</el-button>
            </template>
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

    <el-dialog
      v-model="editVisible"
      :title="editForm.id ? '编辑产品' : '新增产品'"
      width="min(640px, 92vw)"
      :close-on-click-modal="false"
    >
      <el-form :model="editForm" label-width="84px" class="form-grid">
        <el-form-item label="产品名称" class="span-2">
          <el-input
            v-model="editForm.productName"
            maxlength="200"
            show-word-limit
            placeholder="如 PMS 项目管理系统"
          />
        </el-form-item>
        <el-form-item label="类别">
          <el-select v-model="editForm.category">
            <el-option
              v-for="(label, value) in CATEGORY"
              :key="value"
              :label="label"
              :value="value"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="状态">
          <el-select v-model="editForm.status">
            <el-option
              v-for="(item, value) in STATUS"
              :key="value"
              :label="item.label"
              :value="value"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="当前版本">
          <el-input v-model="editForm.spec" maxlength="200" placeholder="如 V3.2 / 标准版" />
        </el-form-item>
        <el-form-item label="单位">
          <el-select
            v-model="editForm.unit"
            filterable
            allow-create
            default-first-option
            placeholder="选择或输入单位"
          >
            <el-option v-for="unit in UNIT_OPTIONS" :key="unit" :label="unit" :value="unit" />
          </el-select>
        </el-form-item>
        <el-form-item label="产品说明" class="span-2" required>
          <el-input
            v-model="editForm.description"
            type="textarea"
            :rows="10"
            resize="vertical"
            :maxlength="DESC_MAX"
            show-word-limit
            :placeholder="`产品定位、功能范围、适用场景、交付形态等，至少 ${DESC_MIN} 字`"
          />
          <p class="desc-tip">至少 {{ DESC_MIN }} 字，用于报价与方案时快速说明产品能力</p>
        </el-form-item>
        <el-form-item label="备注" class="span-2">
          <el-input
            v-model="editForm.remark"
            type="textarea"
            :rows="3"
            maxlength="2000"
            show-word-limit
            placeholder="适用范围 / 报价说明"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存</el-button>
      </template>
    </el-dialog>

    <!-- 只读详情：产品说明较长，列表不展开，所有人可查看 -->
    <el-dialog v-model="detailVisible" title="产品详情" width="min(680px, 92vw)">
      <div class="product-detail">
        <div class="detail-head">
          <div>
            <h3>{{ detailRow.productName || '未命名产品' }}</h3>
            <p class="detail-meta">{{ detailRow.productCode }}</p>
          </div>
          <div class="detail-tags">
            <el-tag size="small" effect="plain">{{ categoryText(detailRow.category) }}</el-tag>
            <el-tag size="small" effect="plain" :type="statusMeta(detailRow.status).type">
              {{ statusMeta(detailRow.status).label }}
            </el-tag>
          </div>
        </div>
        <p class="detail-meta">
          当前版本 {{ detailRow.spec || '—' }} · 单位 {{ detailRow.unit || '—' }}
        </p>
        <h4 class="detail-title">产品说明</h4>
        <p class="detail-text">{{ detailRow.description || '暂无产品说明' }}</p>
        <template v-if="detailRow.remark">
          <h4 class="detail-title">备注</h4>
          <p class="detail-text">{{ detailRow.remark }}</p>
        </template>
      </div>
      <template #footer>
        <el-button @click="detailVisible = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.toolbar {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
}

.toolbar-filters {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  flex: 1 1 460px;
  min-width: 0;
}

.filter-keyword {
  width: 260px;
}

.filter-category,
.filter-status {
  width: 140px;
}

.toolbar-actions {
  margin-left: auto;
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
  font-size: 11.5px;
  color: var(--pms-text-3);
  font-variant-numeric: tabular-nums;
}

.form-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0 16px;
}

.form-grid .span-2 {
  grid-column: span 2;
}

.form-grid :deep(.el-form-item) {
  margin-bottom: 14px;
}

/* 只让弹窗表单内的控件占满栅格，避免把工具栏的筛选下拉也撑成整行 */
.form-grid :deep(.el-select),
.form-grid :deep(.el-input-number) {
  width: 100%;
}

.desc-tip {
  margin: 4px 0 0;
  font-size: 11.5px;
  color: var(--pms-text-3);
}

/* ---------------- 产品详情（只读） ---------------- */
.product-detail .detail-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.product-detail h3 {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
  color: var(--pms-text);
}

.product-detail .detail-meta {
  margin: 4px 0 0;
  font-size: 12px;
  color: var(--pms-text-3);
}

.product-detail .detail-tags {
  flex: none;
  display: flex;
  align-items: center;
  gap: 6px;
}

.detail-title {
  margin: 16px 0 6px;
  font-size: 13.5px;
  font-weight: 600;
  color: var(--pms-text);
}

.detail-text {
  margin: 0;
  font-size: 13px;
  line-height: 1.75;
  color: var(--pms-text-2);
  white-space: pre-wrap;
  word-break: break-word;
}

:deep(.el-pagination) {
  margin-top: 16px;
  justify-content: flex-end;
  flex-wrap: wrap;
  row-gap: 8px;
}

@media (max-width: 768px) {
  .toolbar-filters {
    flex: 1 1 100%;
  }

  .filter-keyword,
  .filter-category,
  .filter-status {
    width: 100%;
  }

  .toolbar-actions {
    width: 100%;
    margin-left: 0;
  }

  .toolbar-actions :deep(.el-button) {
    width: 100%;
  }

  .form-grid {
    grid-template-columns: 1fr;
  }

  .form-grid .span-2 {
    grid-column: auto;
  }
}
</style>
