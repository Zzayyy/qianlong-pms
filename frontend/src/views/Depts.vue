<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus } from 'lucide-vue-next'
import { createDept, deleteDept, deptTree, updateDept, userOptions } from '@/api'
import { useUserStore } from '@/stores/user'

const store = useUserStore()
const canManage = computed(() => store.has('org:dept:manage'))

/** 窄屏收紧列宽 */
const isNarrow = ref(false)
const syncWidth = () => {
  isNarrow.value = window.innerWidth <= 768
}

const flat = ref<any[]>([])
const tree = ref<any[]>([])
const users = ref<any[]>([])
const loading = ref(false)
const keyword = ref('')

/** 扁平列表按 parentId 组装成树（ID 一律用字符串，避免雪花 ID 丢精度）。 */
const buildTree = (list: any[]): any[] => {
  const nodes = new Map<string, any>()
  list.forEach((item) => nodes.set(String(item.id), { ...item, children: [] as any[] }))
  const roots: any[] = []
  nodes.forEach((node) => {
    const parent = nodes.get(String(node.parentId))
    if (parent && String(node.parentId) !== String(node.id)) {
      parent.children.push(node)
    } else {
      roots.push(node)
    }
  })
  return roots
}

/** 搜索时保留命中节点及其祖先链。 */
const visibleTree = computed(() => {
  const kw = keyword.value.trim().toLowerCase()
  if (!kw) return tree.value
  const filter = (nodes: any[]): any[] =>
    nodes
      .map((node) => {
        const children = filter(node.children || [])
        const hit =
          String(node.deptName).toLowerCase().includes(kw) ||
          String(node.deptCode).toLowerCase().includes(kw)
        return hit || children.length ? { ...node, children } : null
      })
      .filter((node): node is any => node !== null)
  return filter(tree.value)
})

const deptCount = computed(() => flat.value.length)
const userTotal = computed(() =>
  flat.value.reduce((sum, dept) => sum + Number(dept.userCount || 0), 0)
)

const load = async () => {
  loading.value = true
  try {
    flat.value = (await deptTree()) as any[]
    tree.value = buildTree(flat.value)
  } finally {
    loading.value = false
  }
}

const loadUsers = async () => {
  try {
    users.value = ((await userOptions()) || []) as any[]
  } catch {
    users.value = []
  }
}

/**
 * 负责人姓名兜底：部门树接口已下发 `leaderName`；
 * 这里只用于「编辑时不显示别人部门负责人」等场景，查不到就显示占位符，不暴露雪花 ID。
 */
const userName = (id: string | null) => {
  if (!id) return '—'
  const hit = users.value.find((item) => String(item.id) === String(id))
  return hit ? `${hit.realName}（${hit.username}）` : '—'
}

/* ---------------- 上级部门候选（编辑时排除自身及下级，防止成环） ---------------- */
const form = ref<any>({
  id: '',
  deptCode: '',
  deptName: '',
  parentId: null as string | null,
  leaderId: null as string | null,
  sort: 0,
  status: 'ENABLED'
})

const subtreeIds = (id: string): Set<string> => {
  const ids = new Set<string>([String(id)])
  let changed = true
  while (changed) {
    changed = false
    for (const dept of flat.value) {
      if (!ids.has(String(dept.id)) && ids.has(String(dept.parentId))) {
        ids.add(String(dept.id))
        changed = true
      }
    }
  }
  return ids
}

const parentOptions = computed(() => {
  const exclude = form.value.id ? subtreeIds(String(form.value.id)) : new Set<string>()
  const nodes = flat.value.filter((dept) => !exclude.has(String(dept.id)))
  const build = (parentId: string): any[] =>
    nodes
      .filter((dept) => String(dept.parentId) === parentId)
      .sort((a, b) => Number(a.sort || 0) - Number(b.sort || 0))
      .map((dept) => ({
        value: String(dept.id),
        label: dept.deptName,
        children: build(String(dept.id))
      }))
  return build('0')
})

/* ---------------- 新增 / 编辑 ---------------- */
const dialogVisible = ref(false)

const openCreate = (parentId: string | number = '') => {
  form.value = {
    id: '',
    deptCode: '',
    deptName: '',
    parentId: parentId ? String(parentId) : null,
    leaderId: null,
    sort: 0,
    status: 'ENABLED'
  }
  dialogVisible.value = true
}

const openEdit = (row: any) => {
  form.value = {
    id: String(row.id),
    deptCode: row.deptCode,
    deptName: row.deptName,
    parentId: row.parentId ? String(row.parentId) : null,
    leaderId: row.leaderId ? String(row.leaderId) : null,
    sort: Number(row.sort || 0),
    status: row.status || 'ENABLED'
  }
  dialogVisible.value = true
}

const save = async () => {
  if (!form.value.deptName?.trim()) {
    ElMessage.warning('请输入部门名称')
    return
  }
  if (!form.value.id && !form.value.deptCode?.trim()) {
    ElMessage.warning('请输入部门编码')
    return
  }
  // ID 以字符串提交，由后端转 int；前端 Number() 会丢雪花 ID 精度
  const payload: Record<string, unknown> = {
    deptName: form.value.deptName.trim(),
    parentId: form.value.parentId ? String(form.value.parentId) : 0,
    leaderId: form.value.leaderId ?? null,
    sort: Number(form.value.sort) || 0,
    status: form.value.status
  }
  try {
    if (form.value.id) {
      await updateDept(form.value.id, payload)
      ElMessage.success('部门已更新')
    } else {
      await createDept({ ...payload, deptCode: form.value.deptCode.trim().toUpperCase() })
      ElMessage.success('部门已新增')
    }
    dialogVisible.value = false
    await load()
  } catch {
    /* 错误提示由请求拦截器统一弹出 */
  }
}

const remove = async (row: any) => {
  try {
    await ElMessageBox.confirm(
      `确认删除部门「${row.deptName}」？存在下级或在职人员时会被拒绝。`,
      '删除部门',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' }
    )
  } catch {
    return
  }
  try {
    await deleteDept(row.id)
    ElMessage.success('部门已删除')
    await load()
  } catch {
    /* 错误提示由请求拦截器统一弹出 */
  }
}

onMounted(async () => {
  syncWidth()
  window.addEventListener('resize', syncWidth)
  await load()
  await loadUsers()
})

onUnmounted(() => window.removeEventListener('resize', syncWidth))
</script>

<template>
  <div class="pms-page" v-loading="loading">
    <div class="pms-card">
      <div class="dept-toolbar">
        <div class="dept-filters">
          <el-input
            v-model="keyword"
            class="dept-search"
            placeholder="按部门名称或编码搜索"
            clearable
          />
          <span class="dept-stats">共 {{ deptCount }} 个部门 · {{ userTotal }} 名人员</span>
        </div>
        <el-button
          type="primary"
          :icon="Plus"
          class="pms-create-btn"
          :disabled="!canManage"
          @click="openCreate(0)"
        >
          新增顶级部门
        </el-button>
      </div>
    </div>

    <div class="pms-card">
      <el-table
        :key="keyword"
        :data="visibleTree"
        row-key="id"
        size="small"
        default-expand-all
        :tree-props="{ children: 'children' }"
        empty-text="暂无部门"
      >
        <el-table-column label="部门" :min-width="isNarrow ? 132 : 220">
          <template #default="{ row }">
            <span class="dept-name">{{ row.deptName }}</span>
            <el-tag
              v-if="row.deptType === 'COMPANY'"
              class="dept-type"
              size="small"
              effect="plain"
            >
              公司
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="deptCode" label="编码" width="130" class-name="pms-mobile-hide" />
        <el-table-column label="负责人" min-width="150" class-name="pms-mobile-hide">
          <template #default="{ row }">
            {{ row.leaderName || userName(row.leaderId) }}
          </template>
        </el-table-column>
        <el-table-column label="人数" width="64" align="right">
          <template #default="{ row }">{{ row.userCount ?? 0 }}</template>
        </el-table-column>
        <el-table-column label="状态" width="96" class-name="pms-mobile-hide">
          <template #default="{ row }">
            <el-tag :type="row.status === 'ENABLED' ? 'success' : 'info'" size="small" effect="plain">
              {{ row.status === 'ENABLED' ? '启用' : '停用' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="排序" width="70" align="center" class-name="pms-mobile-hide">
          <template #default="{ row }">{{ row.sort ?? 0 }}</template>
        </el-table-column>
        <el-table-column label="操作" :width="isNarrow ? 178 : 220" fixed="right">
          <template #default="{ row }">
            <div class="op-actions">
              <el-button size="small" :disabled="!canManage" @click="openCreate(row.id)">
                加子部门
              </el-button>
              <el-button
                link
                type="primary"
                size="small"
                :disabled="!canManage"
                @click="openEdit(row)"
              >
                编辑
              </el-button>
              <el-button link type="danger" size="small" :disabled="!canManage" @click="remove(row)">
                删除
              </el-button>
            </div>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <el-dialog
      v-model="dialogVisible"
      :title="form.id ? '编辑部门' : '新增部门'"
      width="min(560px, 92vw)"
      :close-on-click-modal="false"
    >
      <el-form :model="form" label-width="84px" class="form-grid">
        <el-form-item label="部门名称">
          <el-input v-model="form.deptName" maxlength="128" placeholder="如 华东销售部" />
        </el-form-item>
        <el-form-item label="部门编码">
          <el-input
            v-model="form.deptCode"
            :disabled="Boolean(form.id)"
            maxlength="64"
            placeholder="如 SALES_EAST"
          />
        </el-form-item>
        <el-form-item label="上级部门" class="span-2">
          <el-tree-select
            v-model="form.parentId"
            :data="parentOptions"
            check-strictly
            clearable
            default-expand-all
            filterable
            :render-after-expand="false"
            placeholder="不选则为顶级部门"
          />
        </el-form-item>
        <el-form-item label="负责人">
          <el-select v-model="form.leaderId" clearable filterable placeholder="不指定">
            <el-option
              v-for="user in users"
              :key="user.id"
              :label="user.realName"
              :value="user.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="排序">
          <el-input-number v-model="form.sort" :min="0" :max="999" controls-position="right" />
        </el-form-item>
        <el-form-item v-if="form.id" label="状态" class="span-2">
          <el-radio-group v-model="form.status">
            <el-radio value="ENABLED">启用</el-radio>
            <el-radio value="DISABLED">停用</el-radio>
          </el-radio-group>
        </el-form-item>
      </el-form>
      <p class="form-tip">
        调整上级会同步重算下级层级；部门编码创建后不可修改，有下级或在职人员时不可删除。
      </p>
      <template #footer>
        <div class="dialog-footer">
          <div class="dialog-actions">
            <el-button @click="dialogVisible = false">取消</el-button>
            <el-button type="primary" @click="save">保存</el-button>
          </div>
        </div>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
/* ---------------- 工具栏 ---------------- */
.dept-toolbar {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
}

.dept-filters {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
  flex: 1 1 420px;
  min-width: 0;
}

.dept-search {
  width: 260px;
}

.dept-stats {
  font-size: 12.5px;
  color: var(--pms-text-3);
  font-variant-numeric: tabular-nums;
}

/* ---------------- 表格 ---------------- */
.dept-name {
  font-size: 13px;
  color: var(--pms-text);
}

.dept-type {
  margin-left: 6px;
}

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
  box-shadow: none;
  background: transparent;
  border-color: transparent;
}

.op-actions :deep(.el-button.is-link.el-button--danger:not(.is-disabled)) {
  color: #d64545;
}

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
.form-grid :deep(.el-tree-select) {
  width: 100%;
}

.form-grid :deep(.el-input-number) {
  width: 100%;
}

.form-tip {
  margin: 2px 0 0;
  font-size: 12px;
  line-height: 1.7;
  color: var(--pms-text-3);
}

.dialog-footer {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 12px;
}

.dialog-actions {
  display: flex;
  gap: 8px;
}

@media (max-width: 768px) {
  .dept-search {
    width: 100%;
  }

  .dept-filters {
    flex: 1 1 100%;
  }

  .dept-toolbar > .el-button {
    width: 100%;
  }

  .form-grid {
    grid-template-columns: 1fr;
  }

  .form-grid .span-2 {
    grid-column: auto;
  }

  .dialog-footer {
    flex-direction: column;
    align-items: stretch;
    gap: 10px;
  }

  .dialog-actions {
    justify-content: flex-end;
  }
}
</style>
