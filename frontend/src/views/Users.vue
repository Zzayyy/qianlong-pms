<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  assignUserRoles,
  batchDeleteUsers,
  batchUserStatus,
  changeUserStatus,
  createUser,
  deleteUser,
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
const canDelete = computed(() => store.has('org:user:delete'))

const rows = ref<any[]>([])
const depts = ref<any[]>([])
const roles = ref<any[]>([])
const total = ref(0)
const page = ref({ pageNum: 1, pageSize: 10 })
const keyword = ref('')
const filterDeptId = ref(0)
const loading = ref(false)

const editVisible = ref(false)
const editForm = ref<any>({
  id: 0,
  username: '',
  realName: '',
  deptId: 0,
  managerId: null,
  mobile: '',
  email: '',
  status: 'ENABLED',
  roles: [] as string[]
})

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

const tableRef = ref<any>()
const selection = ref<any[]>([])

/** 窄屏把行内操作收进下拉，避免按钮堆叠导致行高失控。 */
const isNarrow = ref(false)
const syncWidth = () => {
  isNarrow.value = window.innerWidth <= 768
}
const onSelectionChange = (rows: any[]) => {
  selection.value = rows
}
const clearSelection = () => tableRef.value?.clearSelection()
const isSelf = (row: any) => String(row.id) === String(store.profile?.id || '')
const selectionIds = () => selection.value.map((row) => String(row.id))

/** 雪花 ID 超出 JS 安全整数，按字符串比较，避免 Number() 改写末位。 */
const deptName = (id: string | number) => {
  const hit = depts.value.find((item) => String(item.id) === String(id))
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

/** 清空筛选条件并重新查询。 */
const resetFilters = () => {
  keyword.value = ''
  filterDeptId.value = 0
  page.value.pageNum = 1
  load()
}

/** 每页条数变化：回到第一页。 */
const onSizeChange = () => {
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
  try {
    await unlockUser(row.id)
    ElMessage.success('账号已解锁')
    await load()
  } catch {
    /* 错误提示由请求拦截器统一弹出 */
  }
}

const loadBase = async () => {
  depts.value = (await deptTree()) as any[]
  try {
    roles.value = (await listRoles()) as any[]
  } catch {
    roles.value = []
  }
}

/** 直属上级下拉的候选（全量用户，避免只在本页里选）。 */
const managerOptions = ref<any[]>([])
const loadManagerOptions = async () => {
  try {
    const data: Page<Record<string, unknown>> = await listUsers({ pageNum: 1, pageSize: 200 })
    managerOptions.value = (data.list || []) as any[]
  } catch {
    managerOptions.value = []
  }
}

const openEdit = async (row: any) => {
  editForm.value = {
    id: row.id,
    username: row.username || '',
    realName: row.realName,
    deptId: row.deptId,
    managerId: row.managerId || null,
    mobile: row.mobile || '',
    email: row.email || '',
    status: row.status || 'ENABLED',
    roles: (row.roles || []) as string[]
  }
  editVisible.value = true
  await loadManagerOptions()
}

const saveEdit = async () => {
  if (!String(editForm.value.realName || '').trim()) {
    ElMessage.warning('请输入姓名')
    return
  }
  try {
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
  } catch {
    /* 错误提示由请求拦截器统一弹出 */
  }
}

const toggleStatus = async (row: any) => {
  const next = row.status === 'ENABLED' ? 'DISABLED' : 'ENABLED'
  try {
    await changeUserStatus(row.id, next)
    ElMessage.success(next === 'ENABLED' ? '账号已启用' : '账号已停用')
    await load()
  } catch {
    /* 错误提示由请求拦截器统一弹出 */
  }
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
  try {
    await createUser({
      username: createForm.value.username,
      password: createForm.value.password,
      realName: createForm.value.realName,
      deptId: createForm.value.deptId,
      mobile: createForm.value.mobile,
      email: createForm.value.email,
      roleIds: createForm.value.roleIds || []
    })
    createVisible.value = false
    ElMessage.success('账号已创建')
    await load()
  } catch {
    /* 错误提示由请求拦截器统一弹出 */
  }
}

/** 单个删除（不可删除自己）。 */
const removeUser = async (row: any) => {
  if (isSelf(row)) {
    ElMessage.warning('不能删除当前登录账号')
    return
  }
  try {
    await ElMessageBox.confirm(
      `确认删除「${row.realName}」？删除后无法登录，角色关联一并解除。`,
      '删除用户',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' }
    )
  } catch {
    return
  }
  try {
    await deleteUser(row.id)
    ElMessage.success('用户已删除')
    clearSelection()
    await load()
  } catch {
    /* 错误提示由请求拦截器统一弹出 */
  }
}

/** 批量启用 / 停用。 */
const batchStatus = async (status: 'ENABLED' | 'DISABLED') => {
  if (!selection.value.length) return
  if (status === 'DISABLED') {
    try {
      await ElMessageBox.confirm(
        `确认停用选中的 ${selection.value.length} 个账号？停用后立即失效。`,
        '批量停用',
        { type: 'warning', confirmButtonText: '停用', cancelButtonText: '取消' }
      )
    } catch {
      return
    }
  }
  try {
    const result = await batchUserStatus(selectionIds(), status)
    ElMessage.success(`已${status === 'ENABLED' ? '启用' : '停用'} ${result.count} 个账号`)
    clearSelection()
    await load()
  } catch {
    /* 错误提示由请求拦截器统一弹出 */
  }
}

/** 批量删除。 */
const removeSelected = async () => {
  if (!selection.value.length) return
  try {
    await ElMessageBox.confirm(
      `确认删除选中的 ${selection.value.length} 个用户？删除后无法登录。`,
      '批量删除',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' }
    )
  } catch {
    return
  }
  try {
    const result = await batchDeleteUsers(selectionIds())
    ElMessage.success(`已删除 ${result.count} 个用户`)
    clearSelection()
    await load()
  } catch {
    /* 错误提示由请求拦截器统一弹出 */
  }
}

const openRoles = async (row: any) => {
  try {
    const data = await userRoleIds(row.id)
    roleForm.value = { id: row.id, realName: row.realName, roleIds: data.roleIds || [] }
    roleVisible.value = true
  } catch {
    /* 错误提示由请求拦截器统一弹出 */
  }
}

const saveRoles = async () => {
  try {
    await assignUserRoles(roleForm.value.id, roleForm.value.roleIds || [])
    roleVisible.value = false
    ElMessage.success('角色已更新')
    await load()
  } catch {
    /* 错误提示由请求拦截器统一弹出 */
  }
}

const openPwd = (row: any) => {
  pwdForm.value = { id: row.id, realName: row.realName, password: 'Pms@12345' }
  pwdVisible.value = true
}

const doResetPwd = async () => {
  try {
    await ElMessageBox.confirm(`确认重置「${pwdForm.value.realName}」的密码？`, '提示', {
      type: 'warning'
    })
  } catch {
    return
  }
  try {
    await resetUserPassword(pwdForm.value.id, pwdForm.value.password)
    pwdVisible.value = false
    ElMessage.success('密码已重置并解锁')
  } catch {
    /* 错误提示由请求拦截器统一弹出 */
  }
}

/** 窄屏下拉菜单的操作分发。 */
const onRowCommand = (command: string, row: any) => {
  switch (command) {
    case 'edit':
      openEdit(row)
      break
    case 'roles':
      openRoles(row)
      break
    case 'password':
      openPwd(row)
      break
    case 'unlock':
      doUnlock(row)
      break
    case 'status':
      toggleStatus(row)
      break
    case 'delete':
      removeUser(row)
      break
  }
}

onMounted(async () => {
  syncWidth()
  window.addEventListener('resize', syncWidth)
  await loadBase()
  await load()
})

onUnmounted(() => window.removeEventListener('resize', syncWidth))
</script>

<template>
  <div class="pms-page" v-loading="loading">
    <div class="pms-card">
      <div class="toolbar">
        <div class="toolbar-filters">
          <el-input
            v-model="keyword"
            class="filter-keyword"
            placeholder="按姓名或账号搜索"
            clearable
            @keyup.enter="onSearch"
            @clear="onSearch"
          />
          <el-select
            v-model="filterDeptId"
            class="filter-dept"
            placeholder="全部部门"
            clearable
            @change="onSearch"
          >
            <el-option label="全部部门" :value="0" />
            <el-option v-for="dept in depts" :key="dept.id" :label="dept.deptName" :value="dept.id" />
          </el-select>
          <el-button @click="onSearch">查询</el-button>
          <el-button text @click="resetFilters">重置</el-button>
        </div>
        <div class="toolbar-actions">
          <el-button type="primary" :disabled="!canManage" @click="openCreate">新增人员</el-button>
        </div>
      </div>
    </div>

    <div class="pms-card">
      <div v-if="selection.length" class="batch-bar">
        <span class="batch-count">已选 {{ selection.length }} 人</span>
        <el-button size="small" :disabled="!canManage" @click="batchStatus('ENABLED')">批量启用</el-button>
        <el-button size="small" :disabled="!canManage" @click="batchStatus('DISABLED')">批量停用</el-button>
        <el-button size="small" type="danger" plain :disabled="!canDelete" @click="removeSelected">
          批量删除
        </el-button>
        <el-button size="small" link @click="clearSelection">取消选择</el-button>
      </div>

      <el-table
        ref="tableRef"
        :data="rows"
        row-key="id"
        size="small"
        empty-text="暂无人员"
        @selection-change="onSelectionChange"
      >
        <el-table-column type="selection" width="40" :selectable="(row) => !isSelf(row)" />
        <el-table-column label="账号" min-width="100">
          <template #default="{ row }">
            <span class="account-cell">
              <span
                v-if="isNarrow"
                class="status-dot"
                :class="row.status === 'ENABLED' ? 'is-on' : 'is-off'"
              />
              {{ row.username }}
            </span>
          </template>
        </el-table-column>
        <el-table-column prop="realName" label="姓名" :min-width="isNarrow ? 110 : 90" />
        <el-table-column label="部门" min-width="130" class-name="pms-mobile-hide">
          <template #default="{ row }">{{ deptName(row.deptId) }}</template>
        </el-table-column>
        <el-table-column label="直属上级" min-width="90" class-name="pms-mobile-hide">
          <template #default="{ row }">
            <span :class="{ 'cell-muted': !row.managerName }">{{ row.managerName || '—' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="联系方式" min-width="170" class-name="pms-mobile-hide">
          <template #default="{ row }">
            <div class="contact-cell">
              <span class="contact-main">{{ row.mobile || '—' }}</span>
              <span v-if="row.email" class="contact-sub" :title="row.email">{{ row.email }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="角色" min-width="130" class-name="pms-mobile-hide">
          <template #default="{ row }">
            <span v-if="row.roles?.length" class="cell-ellipsis" :title="row.roles.join(' / ')">
              {{ row.roles.join(' / ') }}
            </span>
            <span v-else class="cell-muted">未分配</span>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="140" class-name="pms-mobile-hide">
          <template #default="{ row }">
            <span class="status-tags">
              <el-tag :type="row.status === 'ENABLED' ? 'success' : 'info'" size="small" effect="plain">
                {{ row.status === 'ENABLED' ? '启用' : '停用' }}
              </el-tag>
              <el-tag v-if="row.mustChangePassword" type="warning" size="small" effect="plain">
                待改密
              </el-tag>
              <el-tag v-if="isLocked(row)" type="danger" size="small" effect="plain">已锁定</el-tag>
            </span>
          </template>
        </el-table-column>
        <el-table-column label="操作" :width="isNarrow ? 96 : 262" fixed="right">
          <template #default="{ row }">
            <el-dropdown
              v-if="isNarrow"
              trigger="click"
              placement="bottom-end"
              @command="(command) => onRowCommand(command, row)"
            >
              <el-button size="small">操作</el-button>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item command="edit" :disabled="!canManage">编辑资料</el-dropdown-item>
                  <el-dropdown-item command="roles" :disabled="!canManage">角色授权</el-dropdown-item>
                  <el-dropdown-item command="password" :disabled="!canManage">重置密码</el-dropdown-item>
                  <el-dropdown-item v-if="isLocked(row)" command="unlock" :disabled="!canManage">
                    解除锁定
                  </el-dropdown-item>
                  <el-dropdown-item
                    command="status"
                    :disabled="!canManage || (row.status === 'ENABLED' && isSelf(row))"
                  >
                    {{ row.status === 'ENABLED' ? '停用账号' : '启用账号' }}
                  </el-dropdown-item>
                  <el-dropdown-item
                    v-if="canDelete"
                    command="delete"
                    :disabled="isSelf(row)"
                    divided
                  >
                    删除账号
                  </el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
            <div v-else class="op-actions">
              <el-button size="small" :disabled="!canManage" @click="openEdit(row)">编辑</el-button>
              <el-button
                link
                type="primary"
                size="small"
                :disabled="!canManage"
                @click="openRoles(row)"
              >
                角色
              </el-button>
              <el-button
                link
                type="primary"
                size="small"
                :disabled="!canManage"
                @click="openPwd(row)"
              >
                重置密码
              </el-button>
              <el-button
                v-if="isLocked(row)"
                link
                type="warning"
                size="small"
                :disabled="!canManage"
                @click="doUnlock(row)"
              >
                解锁
              </el-button>
              <el-button
                link
                :type="row.status === 'ENABLED' ? 'danger' : 'success'"
                size="small"
                :disabled="!canManage || (row.status === 'ENABLED' && isSelf(row))"
                @click="toggleStatus(row)"
              >
                {{ row.status === 'ENABLED' ? '停用' : '启用' }}
              </el-button>
              <el-button
                v-if="canDelete"
                link
                type="danger"
                size="small"
                :disabled="isSelf(row)"
                @click="removeUser(row)"
              >
                删除
              </el-button>
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

    <el-dialog
      v-model="createVisible"
      title="新增人员"
      width="min(600px, 92vw)"
      :close-on-click-modal="false"
    >
      <el-form :model="createForm" label-width="84px" class="form-grid">
        <el-form-item label="登录账号">
          <el-input v-model="createForm.username" placeholder="用于登录，创建后不可修改" />
        </el-form-item>
        <el-form-item label="姓名">
          <el-input v-model="createForm.realName" placeholder="真实姓名" />
        </el-form-item>
        <el-form-item label="初始密码">
          <el-input v-model="createForm.password" show-password placeholder="输入初始密码" />
        </el-form-item>
        <el-form-item label="部门">
          <el-select v-model="createForm.deptId" filterable placeholder="选择部门">
            <el-option v-for="dept in depts" :key="dept.id" :label="dept.deptName" :value="dept.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="角色" class="span-2">
          <el-select
            v-model="createForm.roleIds"
            multiple
            collapse-tags
            collapse-tags-tooltip
            :max-collapse-tags="3"
            placeholder="可稍后在角色授权中调整"
          >
            <el-option v-for="role in roles" :key="role.id" :label="role.roleName" :value="role.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="手机">
          <el-input v-model="createForm.mobile" placeholder="选填" />
        </el-form-item>
        <el-form-item label="邮箱">
          <el-input v-model="createForm.email" placeholder="选填" />
        </el-form-item>
      </el-form>
      <p class="form-tip">新账号首次登录时会被要求修改初始密码。</p>
      <template #footer>
        <el-button @click="createVisible = false">取消</el-button>
        <el-button type="primary" @click="doCreate">创建</el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="editVisible"
      title="编辑人员"
      width="min(620px, 92vw)"
      :close-on-click-modal="false"
    >
      <div class="edit-profile">
        <span class="edit-avatar" aria-hidden="true">
          {{ (editForm.realName || editForm.username || 'U').slice(0, 1) }}
        </span>
        <div class="edit-meta">
          <div class="edit-line">
            <span class="edit-name">{{ editForm.realName || '未命名' }}</span>
            <el-tag
              :type="editForm.status === 'ENABLED' ? 'success' : 'info'"
              size="small"
              effect="plain"
            >
              {{ editForm.status === 'ENABLED' ? '启用' : '停用' }}
            </el-tag>
          </div>
          <div class="edit-sub">
            {{ editForm.username }}
            <span class="dot">·</span>{{ deptName(editForm.deptId) }}
            <template v-if="editForm.roles?.length">
              <span class="dot">·</span>{{ editForm.roles.join(' / ') }}
            </template>
          </div>
        </div>
      </div>

      <div class="form-section-title">基本信息</div>
      <el-form :model="editForm" label-width="84px" class="form-grid">
        <el-form-item label="姓名">
          <el-input v-model="editForm.realName" maxlength="64" />
        </el-form-item>
        <el-form-item label="部门">
          <el-select v-model="editForm.deptId" filterable placeholder="选择部门">
            <el-option v-for="dept in depts" :key="dept.id" :label="dept.deptName" :value="dept.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="手机">
          <el-input v-model="editForm.mobile" placeholder="选填" />
        </el-form-item>
        <el-form-item label="邮箱">
          <el-input v-model="editForm.email" placeholder="选填" />
        </el-form-item>
        <el-form-item label="直属上级" class="span-2">
          <el-select
            v-model="editForm.managerId"
            clearable
            filterable
            placeholder="不设置则仅按部门归属计算数据范围"
          >
            <el-option
              v-for="user in managerOptions"
              :key="user.id"
              :label="`${user.realName}（${user.username}）`"
              :value="user.id"
            />
          </el-select>
        </el-form-item>
      </el-form>

      <template #footer>
        <div class="dialog-footer">
          <span class="form-tip">修改部门或直属上级后，该用户需重新登录</span>
          <div class="dialog-actions">
            <el-button @click="editVisible = false">取消</el-button>
            <el-button type="primary" @click="saveEdit">保存</el-button>
          </div>
        </div>
      </template>
    </el-dialog>

    <el-dialog
      v-model="roleVisible"
      :title="`角色授权 · ${roleForm.realName}`"
      width="min(520px, 92vw)"
      :close-on-click-modal="false"
    >
      <el-checkbox-group v-model="roleForm.roleIds" class="role-grid">
        <el-checkbox v-for="role in roles" :key="role.id" :value="role.id" border class="role-option">
          <span class="role-name">{{ role.roleName }}</span>
          <span class="role-code">{{ role.roleCode }}</span>
        </el-checkbox>
      </el-checkbox-group>
      <p class="form-tip">角色决定功能权限与数据范围，可多选；保存后该用户需重新登录生效。</p>
      <template #footer>
        <el-button @click="roleVisible = false">取消</el-button>
        <el-button type="primary" @click="saveRoles">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="pwdVisible"
      :title="`重置密码 · ${pwdForm.realName}`"
      width="min(440px, 92vw)"
      :close-on-click-modal="false"
    >
      <el-form :model="pwdForm" label-width="72px">
        <el-form-item label="新密码">
          <el-input v-model="pwdForm.password" show-password placeholder="输入新密码" />
        </el-form-item>
      </el-form>
      <p class="form-tip">
        重置后该账号所有登录状态立即失效；使用新密码首次登录时，还需再设置一次自己的密码。
      </p>
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

.batch-bar {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 12px;
  padding: 8px 12px;
  background: #f4f8ff;
  border: 1px solid #dbe7ff;
  border-radius: 8px;
}

.batch-count {
  margin-right: 4px;
  font-size: 12.5px;
  font-weight: 500;
  color: var(--pms-primary-deep);
}

.cell-ellipsis {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.status-tags {
  display: inline-flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
}

/* 窄屏用状态圆点替代独立状态列 */
.account-cell {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.status-dot {
  flex: none;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--pms-text-3);
}

.status-dot.is-on {
  background: var(--el-color-success);
}

/* 手机与邮箱合并为一列，避免表格过宽 */
.contact-cell {
  display: flex;
  flex-direction: column;
  gap: 1px;
  min-width: 0;
}

.contact-main {
  font-size: 13px;
  color: var(--pms-text);
  line-height: 1.45;
}

.contact-sub {
  overflow: hidden;
  font-size: 11.5px;
  color: var(--pms-text-3);
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* ---------------- 工具栏 ---------------- */
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
  width: 240px;
}

.filter-dept {
  width: 180px;
}

.toolbar-actions {
  margin-left: auto;
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

/* ---------------- 弹窗表单栅格 ---------------- */
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

.form-grid :deep(.el-select) {
  width: 100%;
}

.form-tip {
  margin: 2px 0 0;
  font-size: 12px;
  line-height: 1.7;
  color: var(--pms-text-3);
}

/* ---------------- 编辑弹窗：顶部身份摘要 ---------------- */
.edit-profile {
  display: flex;
  align-items: center;
  gap: 12px;
  padding-bottom: 16px;
  margin-bottom: 18px;
  border-bottom: 1px dashed var(--pms-line);
}

.edit-avatar {
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

.edit-meta {
  min-width: 0;
}

.edit-line {
  display: flex;
  align-items: center;
  gap: 8px;
}

.edit-name {
  font-size: 15px;
  font-weight: 600;
  color: var(--pms-text);
}

.edit-sub {
  margin-top: 3px;
  overflow: hidden;
  font-size: 12px;
  color: var(--pms-text-3);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.edit-sub .dot {
  margin: 0 5px;
  color: #c3c9d4;
}

/* ---------------- 表单分区标题 ---------------- */
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

/* ---------------- 弹窗底部：说明 + 操作 ---------------- */
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

/* ---------------- 角色勾选 ---------------- */
.role-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}

.role-option {
  width: 100%;
  height: auto;
  min-height: 50px;
  margin-right: 0;
  padding: 8px 10px;
  border-radius: 8px;
}

.role-option :deep(.el-checkbox__label) {
  display: flex;
  flex-direction: column;
  gap: 2px;
  line-height: 1.4;
}

.role-name {
  font-size: 13px;
  color: var(--pms-text);
}

.role-code {
  font-size: 11.5px;
  color: var(--pms-text-3);
  letter-spacing: 0.02em;
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
  .filter-dept {
    width: 100%;
  }

  .toolbar-actions {
    width: 100%;
    margin-left: 0;
  }

  .toolbar-actions :deep(.el-button) {
    width: 100%;
  }

  .form-grid,
  .role-grid {
    grid-template-columns: 1fr;
  }

  .form-grid .span-2 {
    grid-column: auto;
  }

  .role-option {
    min-height: 0;
  }

  .dialog-footer {
    flex-direction: column;
    align-items: stretch;
    gap: 10px;
  }

  .dialog-actions {
    justify-content: flex-end;
  }

  :deep(.el-pagination) {
    justify-content: center;
  }
}
</style>
