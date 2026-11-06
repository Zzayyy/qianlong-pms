<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  assignUserRoles,
  changeUserStatus,
  createUser,
  deptTree,
  listRoles,
  listUsers,
  resetUserPassword,
  unlockUser,
  updateUser,
  userRoleIds,
  type Page
} from '@/api'
import { useUserStore } from '@/stores/user'

const store = useUserStore()
const canManage = computed(() => store.has('org:user:manage'))

const rows = ref<any[]>([])
const depts = ref<any[]>([])
const roles = ref<any[]>([])
const total = ref(0)
const page = ref({ pageNum: 1, pageSize: 10 })
const keyword = ref('')
const filterDeptId = ref(0)
const loading = ref(false)

const editVisible = ref(false)
const editForm = ref<any>({ id: 0, realName: '', deptId: 0, managerId: null, mobile: '', email: '' })

const createVisible = ref(false)
const createForm = ref<any>({
  username: '',
  password: 'Pms@12345',
  realName: '',
  deptId: 0,
  mobile: '',
  email: '',
  roleIds: [] as number[]
})

const roleVisible = ref(false)
const roleForm = ref<any>({ id: 0, realName: '', roleIds: [] as number[] })

const pwdVisible = ref(false)
const pwdForm = ref<any>({ id: 0, realName: '', password: 'Pms@12345' })

const deptName = (id: number) => {
  const hit = depts.value.find((item) => Number(item.id) === Number(id))
  return hit ? String(hit.deptName) : String(id || '—')
}

const load = async () => {
  loading.value = true
  try {
    const data: Page<Record<string, unknown>> = await listUsers({
      pageNum: page.value.pageNum,
      pageSize: page.value.pageSize,
      keyword: keyword.value,
      deptId: filterDeptId.value || undefined
    })
    rows.value = (data.list || []) as any[]
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

/** 是否处于登录失败锁定中。 */
const isLocked = (row: any) => {
  if (!row.lockedUntil) return false
  const until = new Date(String(row.lockedUntil).replace(' ', 'T'))
  return until.getTime() > Date.now()
}

const doUnlock = async (row: any) => {
  await unlockUser(row.id)
  ElMessage.success('账号已解锁')
  await load()
}

const loadBase = async () => {
  depts.value = (await deptTree()) as any[]
  try {
    roles.value = (await listRoles()) as any[]
  } catch {
    roles.value = []
  }
}

const openEdit = (row: any) => {
  editForm.value = {
    id: row.id,
    realName: row.realName,
    deptId: row.deptId,
    managerId: row.managerId || null,
    mobile: row.mobile || '',
    email: row.email || ''
  }
  editVisible.value = true
}

const saveEdit = async () => {
  await updateUser(editForm.value.id, {
    realName: editForm.value.realName,
    deptId: editForm.value.deptId,
    managerId: editForm.value.managerId || null,
    mobile: editForm.value.mobile,
    email: editForm.value.email
  })
  editVisible.value = false
  ElMessage.success('人员信息已更新')
  await load()
}

const toggleStatus = async (row: any) => {
  const next = row.status === 'ENABLED' ? 'DISABLED' : 'ENABLED'
  await changeUserStatus(row.id, next)
  ElMessage.success(next === 'ENABLED' ? '账号已启用' : '账号已停用')
  await load()
}

const openCreate = () => {
  createForm.value = {
    username: '',
    password: 'Pms@12345',
    realName: '',
    deptId: depts.value[0]?.id || 0,
    mobile: '',
    email: '',
    roleIds: []
  }
  createVisible.value = true
}

const doCreate = async () => {
  const result = await createUser({
    username: createForm.value.username,
    password: createForm.value.password,
    realName: createForm.value.realName,
    deptId: createForm.value.deptId,
    mobile: createForm.value.mobile,
    email: createForm.value.email
  })
  if (createForm.value.roleIds?.length) {
    await assignUserRoles(result.id, createForm.value.roleIds)
  }
  createVisible.value = false
  ElMessage.success('账号已创建')
  await load()
}

const openRoles = async (row: any) => {
  const data = await userRoleIds(row.id)
  roleForm.value = { id: row.id, realName: row.realName, roleIds: data.roleIds || [] }
  roleVisible.value = true
}

const saveRoles = async () => {
  await assignUserRoles(roleForm.value.id, roleForm.value.roleIds || [])
  roleVisible.value = false
  ElMessage.success('角色已更新')
  await load()
}

const openPwd = (row: any) => {
  pwdForm.value = { id: row.id, realName: row.realName, password: 'Pms@12345' }
  pwdVisible.value = true
}

const doResetPwd = async () => {
  await ElMessageBox.confirm(`确认重置「${pwdForm.value.realName}」的密码？`, '提示', { type: 'warning' })
  await resetUserPassword(pwdForm.value.id, pwdForm.value.password)
  pwdVisible.value = false
  ElMessage.success('密码已重置并解锁')
}

onMounted(async () => {
  await loadBase()
  await load()
})
</script>

<template>
  <div class="pms-page" v-loading="loading">
    <div class="pms-card">
      <el-row :gutter="8">
        <el-col :xs="24" :sm="8" :md="6">
          <el-input
            v-model="keyword"
            placeholder="按姓名或账号搜索"
            clearable
            @keyup.enter="onSearch"
            @clear="onSearch"
          />
        </el-col>
        <el-col :xs="24" :sm="8" :md="6">
          <el-select
            v-model="filterDeptId"
            placeholder="按部门筛选"
            clearable
            style="width: 100%"
            @change="onSearch"
          >
            <el-option label="全部部门" :value="0" />
            <el-option v-for="dept in depts" :key="dept.id" :label="dept.deptName" :value="dept.id" />
          </el-select>
        </el-col>
        <el-col :xs="24" :sm="8" :md="12">
          <el-button @click="onSearch">查询</el-button>
          <el-button type="primary" :disabled="!canManage" @click="openCreate">新增人员</el-button>
        </el-col>
      </el-row>
    </div>

    <div class="pms-card">
      <el-table :data="rows" size="small">
        <el-table-column prop="username" label="账号" min-width="120" />
        <el-table-column prop="realName" label="姓名" min-width="110" />
        <el-table-column label="部门" min-width="150">
          <template #default="{ row }">{{ deptName(row.deptId) }}</template>
        </el-table-column>
        <el-table-column prop="mobile" label="手机" min-width="130" class-name="pms-mobile-hide" />
        <el-table-column prop="email" label="邮箱" min-width="180" class-name="pms-mobile-hide" />
        <el-table-column label="角色" min-width="150" class-name="pms-mobile-hide">
          <template #default="{ row }">
            <span v-if="row.roles?.length">{{ row.roles.join(' / ') }}</span>
            <span v-else class="cell-muted">未分配</span>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="150">
          <template #default="{ row }">
            <el-tag :type="row.status === 'ENABLED' ? 'success' : 'info'" size="small" effect="plain">
              {{ row.status === 'ENABLED' ? '启用' : '停用' }}
            </el-tag>
            <el-tag v-if="isLocked(row)" class="lock-tag" type="danger" size="small" effect="plain">
              已锁定
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" min-width="340">
          <template #default="{ row }">
            <el-button size="small" :disabled="!canManage" @click="openEdit(row)">编辑</el-button>
            <el-button size="small" :disabled="!canManage" @click="openRoles(row)">角色</el-button>
            <el-button size="small" :disabled="!canManage" @click="openPwd(row)">重置密码</el-button>
            <el-button
              v-if="isLocked(row)"
              size="small"
              type="warning"
              plain
              :disabled="!canManage"
              @click="doUnlock(row)"
            >
              解锁
            </el-button>
            <el-button
              size="small"
              :type="row.status === 'ENABLED' ? 'danger' : 'success'"
              :disabled="!canManage"
              @click="toggleStatus(row)"
            >
              {{ row.status === 'ENABLED' ? '停用' : '启用' }}
            </el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-pagination
        v-model:current-page="page.pageNum"
        v-model:page-size="page.pageSize"
        :total="total"
        layout="prev, pager, next, total"
        @current-change="load"
      />
    </div>

    <el-dialog v-model="createVisible" title="新增人员" width="90%">
      <el-form :model="createForm" label-width="100px">
        <el-form-item label="登录账号"><el-input v-model="createForm.username" /></el-form-item>
        <el-form-item label="初始密码"><el-input v-model="createForm.password" show-password /></el-form-item>
        <el-form-item label="姓名"><el-input v-model="createForm.realName" /></el-form-item>
        <el-form-item label="部门">
          <el-select v-model="createForm.deptId" filterable style="width: 100%">
            <el-option v-for="dept in depts" :key="dept.id" :label="dept.deptName" :value="dept.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="手机"><el-input v-model="createForm.mobile" /></el-form-item>
        <el-form-item label="邮箱"><el-input v-model="createForm.email" /></el-form-item>
        <el-form-item label="角色">
          <el-select v-model="createForm.roleIds" multiple style="width: 100%">
            <el-option v-for="role in roles" :key="role.id" :label="role.roleName" :value="role.id" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createVisible = false">取消</el-button>
        <el-button type="primary" @click="doCreate">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="editVisible" title="编辑人员" width="90%">
      <el-form :model="editForm" label-width="100px">
        <el-form-item label="姓名"><el-input v-model="editForm.realName" /></el-form-item>
        <el-form-item label="部门">
          <el-select v-model="editForm.deptId" filterable style="width: 100%">
            <el-option v-for="dept in depts" :key="dept.id" :label="dept.deptName" :value="dept.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="直属上级">
          <el-select v-model="editForm.managerId" clearable filterable style="width: 100%">
            <el-option v-for="user in rows" :key="user.id" :label="user.realName" :value="user.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="手机"><el-input v-model="editForm.mobile" /></el-form-item>
        <el-form-item label="邮箱"><el-input v-model="editForm.email" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editVisible = false">取消</el-button>
        <el-button type="primary" @click="saveEdit">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="roleVisible" :title="`角色授权 - ${roleForm.realName}`" width="90%">
      <el-checkbox-group v-model="roleForm.roleIds">
        <el-checkbox v-for="role in roles" :key="role.id" :value="role.id" :label="role.id">
          {{ role.roleName }}（{{ role.roleCode }}）
        </el-checkbox>
      </el-checkbox-group>
      <template #footer>
        <el-button @click="roleVisible = false">取消</el-button>
        <el-button type="primary" @click="saveRoles">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="pwdVisible" :title="`重置密码 - ${pwdForm.realName}`" width="90%">
      <el-form :model="pwdForm" label-width="100px">
        <el-form-item label="新密码"><el-input v-model="pwdForm.password" show-password /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="pwdVisible = false">取消</el-button>
        <el-button type="primary" @click="doResetPwd">确认重置</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.cell-muted {
  color: var(--pms-text-3);
  font-size: 12.5px;
}

.lock-tag {
  margin-left: 6px;
}

:deep(.el-pagination) {
  margin-top: 14px;
  justify-content: flex-end;
}
</style>
