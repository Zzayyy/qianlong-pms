<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { createDept, deleteDept, deptTree, listUsers, updateDept, type Page } from '@/api'
import { useUserStore } from '@/stores/user'

const store = useUserStore()
const canManage = computed(() => store.has('org:dept:manage'))

const rows = ref<any[]>([])
const users = ref<any[]>([])
const loading = ref(false)
const dialogVisible = ref(false)
const form = ref<any>({
  id: 0,
  deptCode: '',
  deptName: '',
  parentId: 0,
  leaderId: null as number | null,
  sort: 0
})

/** 扁平列表按 parentId 组装成树（后端返回全量，前端自行挂载）。 */
const buildTree = (list: any[]): any[] => {
  const nodes = new Map<number, any>()
  list.forEach((item) => nodes.set(Number(item.id), { ...item, children: [] as any[] }))
  const roots: any[] = []
  nodes.forEach((node) => {
    const parent = nodes.get(Number(node.parentId))
    if (parent && Number(node.parentId) !== Number(node.id)) {
      parent.children.push(node)
    } else {
      roots.push(node)
    }
  })
  return roots
}

const load = async () => {
  loading.value = true
  try {
    rows.value = buildTree(await deptTree())
  } finally {
    loading.value = false
  }
}

const loadUsers = async () => {
  try {
    const data: Page<Record<string, unknown>> = await listUsers({ pageNum: 1, pageSize: 200 })
    users.value = (data.list || []) as any[]
  } catch {
    users.value = []
  }
}

const userName = (id: number | null) => {
  if (!id) {
    return '—'
  }
  const hit = users.value.find((item) => Number(item.id) === Number(id))
  return hit ? `${hit.realName}（${hit.username}）` : String(id)
}

const openCreate = (parentId = 0) => {
  form.value = { id: 0, deptCode: '', deptName: '', parentId, leaderId: null, sort: 0 }
  dialogVisible.value = true
}

const openEdit = (row: any) => {
  form.value = {
    id: row.id,
    deptCode: row.deptCode,
    deptName: row.deptName,
    parentId: row.parentId,
    leaderId: row.leaderId || null,
    sort: row.sort || 0
  }
  dialogVisible.value = true
}

const save = async () => {
  if (!form.value.deptCode || !form.value.deptName) {
    ElMessage.warning('部门编码与名称必填')
    return
  }
  const payload: Record<string, unknown> = {
    deptName: form.value.deptName,
    deptCode: form.value.deptCode,
    parentId: form.value.parentId || 0,
    leaderId: form.value.leaderId || null,
    sort: form.value.sort || 0
  }
  if (form.value.id) {
    delete payload.deptCode
    await updateDept(form.value.id, payload)
    ElMessage.success('部门已更新')
  } else {
    await createDept(payload)
    ElMessage.success('部门已新增')
  }
  dialogVisible.value = false
  await load()
}

const remove = async (row: any) => {
  await ElMessageBox.confirm(`确认删除部门「${row.deptName}」？有下级或在职人员时会被拒绝`, '提示', {
    type: 'warning'
  })
  await deleteDept(row.id)
  ElMessage.success('部门已删除')
  await load()
}

onMounted(async () => {
  await load()
  await loadUsers()
})
</script>

<template>
  <div class="pms-page" v-loading="loading">
    <div class="pms-card">
      <el-alert
        type="info"
        :closable="false"
        title="公司组织架构：管理员可新增部门、指定负责人、调整上下级；有下级或在职人员的部门不可删除"
      />
      <el-button type="primary" size="small" style="margin-top: 8px" @click="openCreate(0)">
        新增顶级部门
      </el-button>
    </div>

    <div class="pms-card">
      <el-table :data="rows" size="small" row-key="id" default-expand-all :tree-props="{ children: 'children' }">
        <el-table-column prop="deptName" label="部门" min-width="180" />
        <el-table-column prop="deptCode" label="编码" width="120" />
        <el-table-column prop="level" label="层级" width="80" />
        <el-table-column label="负责人" min-width="150" class-name="pms-mobile-hide">
          <template #default="{ row }">{{ userName(row.leaderId) }}</template>
        </el-table-column>
        <el-table-column label="人数" width="80">
          <template #default="{ row }">{{ row.userCount ?? 0 }}</template>
        </el-table-column>
        <el-table-column prop="status" label="状态" width="100" />
        <el-table-column label="操作" min-width="220">
          <template #default="{ row }">
            <el-button size="small" @click="openCreate(row.id)">加子部门</el-button>
            <el-button size="small" type="primary" @click="openEdit(row)" :disabled="!canManage">编辑</el-button>
            <el-button size="small" type="danger" @click="remove(row)" :disabled="!canManage">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <el-dialog v-model="dialogVisible" :title="form.id ? '编辑部门' : '新增部门'" width="90%">
      <el-form :model="form" label-width="100px">
        <el-form-item label="部门名称"><el-input v-model="form.deptName" /></el-form-item>
        <el-form-item label="部门编码">
          <el-input v-model="form.deptCode" :disabled="!!form.id" placeholder="如 SALES_EAST" />
        </el-form-item>
        <el-form-item label="上级部门">
          <el-input-number v-model="form.parentId" :min="0" />
          <span style="margin-left: 8px; color: #909399">0 表示顶级部门</span>
        </el-form-item>
        <el-form-item label="负责人">
          <el-select v-model="form.leaderId" clearable filterable style="width: 100%">
            <el-option v-for="user in users" :key="user.id" :label="user.realName" :value="user.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="排序"><el-input-number v-model="form.sort" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="save">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>
