<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  createRole,
  deleteRole,
  deptTree,
  listRoles,
  permissionTree,
  rolePermissionIds,
  updateRole,
  updateRolePermissions,
  type PermissionItem,
  type RoleItem
} from '@/api'
import { useUserStore } from '@/stores/user'

const store = useUserStore()
const canManage = computed(() => store.has('org:role:manage'))

const loading = ref(false)
const saving = ref(false)
const roles = ref<RoleItem[]>([])
const perms = ref<PermissionItem[]>([])
const depts = ref<{ id: string; deptName: string }[]>([])
const currentId = ref('')
const checked = ref<string[]>([])

const current = computed(() => roles.value.find((role) => role.id === currentId.value) ?? null)

const scopeLabels: Record<string, string> = {
  ALL: '全公司',
  DEPT_AND_SUB: '本部门及下级',
  DEPT: '本部门',
  PROJECT: '参与项目',
  SELF: '仅本人',
  CUSTOM: '自定义部门'
}

const moduleLabels: [string, string][] = [
  ['org', '组织与权限'],
  ['crm', '客户与商机'],
  ['project', '项目周期'],
  ['change', '变更管理'],
  ['worklog', '工作日志'],
  ['report', '统计看板'],
  ['sys', '系统设置']
]

const moduleOf = (code: string) => code.split(':')[0]

const groups = computed(() =>
  moduleLabels
    .map(([key, label]) => ({
      key,
      label,
      items: perms.value.filter((perm) => moduleOf(perm.permCode) === key)
    }))
    .filter((group) => group.items.length > 0)
)

const groupIds = (group: { items: PermissionItem[] }) => group.items.map((item) => item.id)
const groupChecked = (ids: string[]) => ids.length > 0 && ids.every((id) => checked.value.includes(id))
const groupCount = (ids: string[]) => ids.filter((id) => checked.value.includes(id)).length

const togglePerm = (id: string) => {
  const next = new Set(checked.value)
  if (next.has(id)) {
    next.delete(id)
  } else {
    next.add(id)
  }
  checked.value = [...next]
}

const toggleGroup = (ids: string[]) => {
  const next = new Set(checked.value)
  const all = groupChecked(ids)
  ids.forEach((id) => (all ? next.delete(id) : next.add(id)))
  checked.value = [...next]
}

const toDeptIds = (value: string) =>
  value
    ? value
        .split(',')
        .map((item) => item.trim())
        .filter((item) => Boolean(item))
    : []

const loadChecked = async (roleId: string) => {
  const data = await rolePermissionIds(roleId)
  checked.value = data.permIds || []
}

const load = async () => {
  loading.value = true
  try {
    roles.value = await listRoles()
    if (!perms.value.length) perms.value = await permissionTree()
    if (!depts.value.length) depts.value = (await deptTree()) as unknown as { id: string; deptName: string }[]
    if (!currentId.value && roles.value.length) currentId.value = roles.value[0].id
    if (currentId.value) await loadChecked(currentId.value)
  } finally {
    loading.value = false
  }
}

const selectRole = async (role: RoleItem) => {
  if (role.id === currentId.value) return
  currentId.value = role.id
  await loadChecked(role.id)
}

const savePermissions = async () => {
  if (!current.value || saving.value) return
  saving.value = true
  try {
    await updateRolePermissions(current.value.id, checked.value)
    ElMessage.success('角色权限已保存')
    // 可能改到自己所属角色，刷新一次当前用户权限
    await store.loadProfile()
    await load()
  } catch {
    /* 错误提示由请求拦截器统一弹出 */
  } finally {
    saving.value = false
  }
}

/* ---------------- 新增 / 编辑 ---------------- */
const createVisible = ref(false)
const createForm = reactive({
  roleCode: '',
  roleName: '',
  dataScope: 'SELF',
  customDeptIds: [] as string[],
  sort: 10
})

const openCreate = () => {
  createForm.roleCode = ''
  createForm.roleName = ''
  createForm.dataScope = 'SELF'
  createForm.customDeptIds = []
  createForm.sort = 10
  createVisible.value = true
}

const submitCreate = async () => {
  if (createForm.roleCode.trim().length < 2) {
    ElMessage.warning('角色编码至少 2 个字符')
    return
  }
  if (!createForm.roleName.trim()) {
    ElMessage.warning('请输入角色名称')
    return
  }
  try {
    const created = await createRole({
      roleCode: createForm.roleCode,
      roleName: createForm.roleName,
      dataScope: createForm.dataScope,
      customDeptIds: createForm.customDeptIds.join(','),
      sort: createForm.sort
    })
    createVisible.value = false
    ElMessage.success('角色已创建')
    await load()
    currentId.value = created.id
    await loadChecked(created.id)
  } catch {
    /* 错误提示由请求拦截器统一弹出 */
  }
}

const editVisible = ref(false)
const editForm = reactive({
  id: '',
  roleName: '',
  dataScope: 'SELF',
  customDeptIds: [] as string[],
  sort: 0,
  status: 'ENABLED',
  builtin: false
})

const openEdit = () => {
  if (!current.value) return
  editForm.id = current.value.id
  editForm.roleName = current.value.roleName
  editForm.dataScope = current.value.dataScope
  editForm.customDeptIds = toDeptIds(current.value.customDeptIds)
  editForm.sort = current.value.sort
  editForm.status = current.value.status
  editForm.builtin = Boolean(current.value.builtin)
  editVisible.value = true
}

const submitEdit = async () => {
  if (!editForm.roleName.trim()) {
    ElMessage.warning('请输入角色名称')
    return
  }
  try {
    await updateRole(editForm.id, {
      roleName: editForm.roleName,
      dataScope: editForm.builtin ? undefined : editForm.dataScope,
      customDeptIds: editForm.builtin ? undefined : editForm.customDeptIds.join(','),
      sort: editForm.sort,
      status: editForm.builtin ? undefined : editForm.status
    })
    editVisible.value = false
    ElMessage.success('角色已更新')
    await load()
  } catch {
    /* 错误提示由请求拦截器统一弹出 */
  }
}

const removeRole = async () => {
  if (!current.value) return
  try {
    await ElMessageBox.confirm(
      `确认删除角色「${current.value.roleName}」？删除后不可恢复。`,
      '删除角色',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' }
    )
  } catch {
    return
  }
  try {
    await deleteRole(current.value.id)
    ElMessage.success('角色已删除')
    currentId.value = ''
    checked.value = []
    await load()
  } catch {
    /* 错误提示由请求拦截器统一弹出 */
  }
}

onMounted(load)
</script>

<template>
  <div v-loading="loading" class="pms-page">
    <div class="role-layout">
      <aside class="pms-card role-list">
        <header class="list-head">
          <h3>角色</h3>
          <el-button v-if="canManage" type="primary" size="small" @click="openCreate">新增</el-button>
        </header>
        <div class="role-items">
          <button
            v-for="role in roles"
            :key="role.id"
            type="button"
            class="role-item"
            :class="{ 'is-active': role.id === currentId }"
            @click="selectRole(role)"
          >
            <span class="role-line">
              <span class="role-name">{{ role.roleName }}</span>
              <el-tag v-if="role.builtin" size="small" effect="plain">内置</el-tag>
              <el-tag v-if="role.status !== 'ENABLED'" type="info" size="small" effect="plain">停用</el-tag>
            </span>
            <span class="role-line role-meta">
              <span class="role-code">{{ role.roleCode }}</span>
              <span class="role-count">{{ role.userCount }} 人 / {{ role.permCount }} 项</span>
            </span>
          </button>
          <p v-if="!roles.length" class="list-empty">暂无角色</p>
        </div>
      </aside>

      <section v-if="current" class="pms-card role-detail">
        <header class="detail-head">
          <div class="detail-title">
            <h3>
              {{ current.roleName }}
              <span class="detail-code">{{ current.roleCode }}</span>
            </h3>
            <p class="detail-sub">
              数据范围：{{ scopeLabels[current.dataScope] || current.dataScope }}
              <span class="dot">·</span>{{ current.userCount }} 名用户
              <span class="dot">·</span>已选 {{ checked.length }} / {{ perms.length }} 个权限点
            </p>
          </div>
          <div class="detail-actions">
            <el-button v-if="canManage" size="small" @click="openEdit">编辑</el-button>
            <el-button
              v-if="canManage && !current.builtin"
              size="small"
              type="danger"
              plain
              @click="removeRole"
            >
              删除
            </el-button>
          </div>
        </header>

        <div class="perm-groups">
          <div v-for="group in groups" :key="group.key" class="perm-group">
            <div class="group-head">
              <span class="group-title">{{ group.label }}</span>
              <span class="group-count">{{ groupCount(groupIds(group)) }}/{{ group.items.length }}</span>
              <el-button
                link
                type="primary"
                size="small"
                :disabled="!canManage"
                @click="toggleGroup(groupIds(group))"
              >
                {{ groupChecked(groupIds(group)) ? '取消全选' : '全选' }}
              </el-button>
            </div>
            <div class="perm-items">
              <el-checkbox
                v-for="perm in group.items"
                :key="perm.id"
                :model-value="checked.includes(perm.id)"
                :disabled="!canManage"
                @change="togglePerm(perm.id)"
              >
                <span class="perm-name">{{ perm.permName }}</span>
                <span class="perm-code">{{ perm.permCode }}</span>
              </el-checkbox>
            </div>
          </div>
        </div>

        <footer class="detail-foot">
          <span class="foot-hint">保存后立即生效，该角色下用户的权限缓存会刷新</span>
          <el-button type="primary" :loading="saving" :disabled="!canManage" @click="savePermissions">
            保存权限
          </el-button>
        </footer>
      </section>

      <section v-else class="pms-card role-empty">请选择左侧角色</section>
    </div>

    <el-dialog v-model="createVisible" title="新增角色" width="90%" style="max-width: 460px">
      <el-form label-position="top">
        <el-form-item label="角色编码">
          <el-input v-model="createForm.roleCode" placeholder="如 SALES_ASSIST，保存后不可修改" />
        </el-form-item>
        <el-form-item label="角色名称">
          <el-input v-model="createForm.roleName" placeholder="如 销售助理" />
        </el-form-item>
        <el-form-item label="数据范围">
          <el-select v-model="createForm.dataScope" style="width: 100%">
            <el-option v-for="(label, key) in scopeLabels" :key="key" :label="label" :value="key" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="createForm.dataScope === 'CUSTOM'" label="自定义部门">
          <el-select v-model="createForm.customDeptIds" multiple filterable style="width: 100%">
            <el-option v-for="dept in depts" :key="dept.id" :label="dept.deptName" :value="dept.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="排序">
          <el-input-number v-model="createForm.sort" :min="0" :max="999" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createVisible = false">取消</el-button>
        <el-button type="primary" @click="submitCreate">创建</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="editVisible" title="编辑角色" width="90%" style="max-width: 460px">
      <el-form label-position="top">
        <el-form-item label="角色名称">
          <el-input v-model="editForm.roleName" />
        </el-form-item>
        <el-form-item label="数据范围">
          <el-select v-model="editForm.dataScope" :disabled="editForm.builtin" style="width: 100%">
            <el-option v-for="(label, key) in scopeLabels" :key="key" :label="label" :value="key" />
          </el-select>
        </el-form-item>
        <el-form-item
          v-if="!editForm.builtin && editForm.dataScope === 'CUSTOM'"
          label="自定义部门"
        >
          <el-select v-model="editForm.customDeptIds" multiple filterable style="width: 100%">
            <el-option v-for="dept in depts" :key="dept.id" :label="dept.deptName" :value="dept.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="排序">
          <el-input-number v-model="editForm.sort" :min="0" :max="999" />
        </el-form-item>
        <el-form-item v-if="!editForm.builtin" label="状态">
          <el-radio-group v-model="editForm.status">
            <el-radio value="ENABLED">启用</el-radio>
            <el-radio value="DISABLED">停用</el-radio>
          </el-radio-group>
        </el-form-item>
        <p v-if="editForm.builtin" class="edit-tip">内置角色的数据范围与启停状态不可修改。</p>
      </el-form>
      <template #footer>
        <el-button @click="editVisible = false">取消</el-button>
        <el-button type="primary" @click="submitEdit">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.role-layout {
  display: grid;
  grid-template-columns: 268px minmax(0, 1fr);
  gap: 14px;
  align-items: start;
}

/* ---------------- 角色列表 ---------------- */
.role-list {
  padding: 0;
  overflow: hidden;
}

.list-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 14px 16px;
  border-bottom: 1px solid var(--pms-line);
}

.list-head h3 {
  margin: 0;
  font-size: 14px;
  font-weight: 600;
  color: var(--pms-text);
}

.role-items {
  max-height: calc(100dvh - 250px);
  overflow-y: auto;
  padding: 6px;
}

.role-item {
  width: 100%;
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 9px 10px;
  border: 1px solid transparent;
  border-radius: 8px;
  background: transparent;
  text-align: left;
  cursor: pointer;
  transition:
    background-color 0.16s ease,
    border-color 0.16s ease;
}

.role-item:hover {
  background: #f6f9fe;
}

.role-item.is-active {
  background: var(--pms-primary-weak);
  border-color: #dbe7ff;
}

.role-line {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}

.role-name {
  font-size: 13.5px;
  font-weight: 500;
  color: var(--pms-text);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.role-item.is-active .role-name {
  color: var(--pms-primary-deep);
}

.role-meta {
  justify-content: space-between;
}

.role-code {
  font-size: 11.5px;
  color: var(--pms-text-3);
  letter-spacing: 0.02em;
}

.role-count {
  font-size: 11.5px;
  color: var(--pms-text-3);
}

.list-empty {
  margin: 24px 0;
  text-align: center;
  font-size: 13px;
  color: var(--pms-text-3);
}

/* ---------------- 角色详情 ---------------- */
.role-detail {
  min-height: 420px;
  display: flex;
  flex-direction: column;
}

.detail-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  padding-bottom: 14px;
  border-bottom: 1px solid var(--pms-line);
}

.detail-title h3 {
  margin: 0 0 6px;
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 16px;
  font-weight: 600;
  color: var(--pms-text);
}

.detail-code {
  padding: 1px 6px;
  border-radius: 4px;
  background: #f2f5fb;
  font-size: 11.5px;
  font-weight: 400;
  color: var(--pms-text-2);
  letter-spacing: 0.03em;
}

.detail-sub {
  margin: 0;
  font-size: 12.5px;
  color: var(--pms-text-3);
}

.detail-sub .dot {
  margin: 0 6px;
}

.detail-actions {
  display: flex;
  gap: 8px;
  flex: none;
}

/* ---------------- 权限分组 ---------------- */
.perm-groups {
  flex: 1;
  display: grid;
  gap: 18px;
  padding: 16px 0 8px;
}

.perm-group {
  border: 1px solid var(--pms-line-soft);
  border-radius: 10px;
  padding: 12px 14px;
}

.group-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
}

.group-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--pms-text);
}

.group-count {
  font-size: 11.5px;
  color: var(--pms-text-3);
  font-variant-numeric: tabular-nums;
}

.group-head .el-button {
  margin-left: auto;
}

.perm-items {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 6px 18px;
}

.perm-name {
  margin-right: 6px;
  font-size: 13px;
}

.perm-code {
  font-size: 11px;
  color: var(--pms-text-3);
  letter-spacing: 0.02em;
}

.detail-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding-top: 14px;
  border-top: 1px solid var(--pms-line);
}

.foot-hint {
  font-size: 12px;
  color: var(--pms-text-3);
}

.role-empty {
  min-height: 320px;
  display: grid;
  place-items: center;
  font-size: 13px;
  color: var(--pms-text-3);
}

.edit-tip {
  margin: 0;
  font-size: 12px;
  color: var(--pms-text-3);
}

@media (max-width: 900px) {
  .role-layout {
    grid-template-columns: 1fr;
  }

  .role-items {
    max-height: 260px;
  }

  .perm-items {
    grid-template-columns: 1fr;
  }

  .detail-foot {
    flex-direction: column;
    align-items: stretch;
  }

  .detail-foot .el-button {
    width: 100%;
  }
}
</style>
