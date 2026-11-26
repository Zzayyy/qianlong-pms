<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  copyWeeklyPrompt,
  createWeeklyPrompt,
  deleteWeeklyPrompt,
  deptOptions,
  listWeeklyPrompts,
  updateWeeklyPrompt,
  weeklyPromptVariables,
  type DeptOption,
  type WeeklyPromptItem
} from '@/api'

/** 提示词管理页：个人周总结 / 项目周报各一套全公司默认，部门可覆盖自己那套。 */

const SCOPES = [
  { value: 'PERSONAL', label: '个人周总结' },
  { value: 'PROJECT', label: '项目周报' }
] as const

const loading = ref(false)
const saving = ref(false)
const scopeFilter = ref('')
const items = ref<WeeklyPromptItem[]>([])
const canManageGlobal = ref(false)
const myDeptId = ref('')
const depts = ref<DeptOption[]>([])
const variables = ref<{ key: string; remark: string }[]>([])

const drawerVisible = ref(false)
const editing = ref<WeeklyPromptItem | null>(null)
const form = reactive({
  scope: 'PERSONAL' as 'PROJECT' | 'PERSONAL',
  deptId: '0',
  name: '',
  systemPrompt: '',
  userPrompt: '',
  enabled: true,
  remark: ''
})

const copyVisible = ref(false)
const copySource = ref<WeeklyPromptItem | null>(null)
const copyForm = reactive({ deptId: '', name: '' })

/** 可选的部门：管理员可选全公司默认或任意部门，部门领导只能选本部门。 */
const deptChoices = computed(() => {
  const list = depts.value.map((item) => ({ id: String(item.id), name: item.deptName }))
  if (canManageGlobal.value) {
    return [{ id: '0', name: '全公司默认' }, ...list]
  }
  return list.filter((item) => item.id === myDeptId.value)
})

const filtered = computed(() =>
  scopeFilter.value ? items.value.filter((item) => item.scope === scopeFilter.value) : items.value
)

const targetDeptId = computed(() => {
  if (canManageGlobal.value) return form.deptId || '0'
  return myDeptId.value
})

const load = async () => {
  loading.value = true
  try {
    const data = await listWeeklyPrompts()
    items.value = data.items || []
    canManageGlobal.value = !!data.canManageGlobal
    myDeptId.value = String(data.deptId || '')
  } catch {
    /* 错误提示由请求拦截器统一弹出 */
  } finally {
    loading.value = false
  }
}

const loadOptions = async () => {
  const [deptList, variableList] = await Promise.all([
    deptOptions().catch(() => [] as DeptOption[]),
    weeklyPromptVariables().catch(() => [] as { key: string; remark: string }[])
  ])
  depts.value = deptList || []
  variables.value = variableList || []
}

const openCreate = () => {
  editing.value = null
  form.scope = (scopeFilter.value || 'PERSONAL') as 'PROJECT' | 'PERSONAL'
  form.deptId = canManageGlobal.value ? '0' : myDeptId.value
  form.name = ''
  form.systemPrompt = ''
  form.userPrompt = ''
  form.enabled = true
  form.remark = ''
  drawerVisible.value = true
}

const openEdit = (row: any) => {
  const item = row as WeeklyPromptItem
  editing.value = item
  form.scope = item.scope
  form.deptId = String(item.deptId)
  form.name = item.name
  form.systemPrompt = item.systemPrompt
  form.userPrompt = item.userPrompt
  form.enabled = item.enabled === 1
  form.remark = item.remark
  drawerVisible.value = true
}

const submit = async () => {
  if (!form.name.trim()) {
    ElMessage.warning('请填写模板名称')
    return
  }
  if (!form.userPrompt.trim()) {
    ElMessage.warning('请填写用户提示词')
    return
  }
  if (!editing.value) {
    const duplicated = items.value.some(
      (item) =>
        item.scope === form.scope &&
        String(item.deptId) === String(Number(targetDeptId.value || 0))
    )
    if (duplicated) {
      ElMessage.warning('该部门已有同范围提示词，请直接编辑原模板或换一个范围')
      return
    }
  }
  saving.value = true
  try {
    if (editing.value) {
      await updateWeeklyPrompt(editing.value.id, {
        name: form.name.trim(),
        systemPrompt: form.systemPrompt,
        userPrompt: form.userPrompt,
        enabled: form.enabled ? 1 : 0,
        remark: form.remark
      })
      ElMessage.success('已保存，后续生成的周报立即生效')
    } else {
      await createWeeklyPrompt({
        scope: form.scope,
        deptId: targetDeptId.value,
        name: form.name.trim(),
        systemPrompt: form.systemPrompt,
        userPrompt: form.userPrompt,
        enabled: form.enabled ? 1 : 0,
        remark: form.remark
      })
      ElMessage.success('已新建提示词模板')
    }
    drawerVisible.value = false
    await load()
  } catch {
    /* 错误提示由请求拦截器统一弹出 */
  } finally {
    saving.value = false
  }
}

const openCopy = (row: any) => {
  copySource.value = row as WeeklyPromptItem
  copyForm.deptId = canManageGlobal.value ? myDeptId.value || '0' : myDeptId.value
  copyForm.name = ''
  copyVisible.value = true
}

const submitCopy = async () => {
  if (!copySource.value) return
  if (!copyForm.deptId) {
    ElMessage.warning('请选择目标部门')
    return
  }
  saving.value = true
  try {
    await copyWeeklyPrompt(copySource.value.id, {
      deptId: copyForm.deptId,
      name: copyForm.name.trim()
    })
    copyVisible.value = false
    ElMessage.success('已复制，可继续编辑成部门专用提示词')
    await load()
  } catch {
    /* 错误提示由请求拦截器统一弹出 */
  } finally {
    saving.value = false
  }
}

const remove = async (row: any) => {
  const item = row as WeeklyPromptItem
  try {
    await ElMessageBox.confirm(
      `删除后「${item.deptName}」将回落到上一级或全公司默认提示词，确认删除「${item.name}」？`,
      '删除提示词模板',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' }
    )
  } catch {
    return
  }
  try {
    await deleteWeeklyPrompt(item.id)
    ElMessage.success('已删除')
    await load()
  } catch {
    /* 错误提示由请求拦截器统一弹出 */
  }
}

const toggleEnabled = async (row: any, value: string | number | boolean) => {
  const item = row as WeeklyPromptItem
  const enabled = value === true
  try {
    await updateWeeklyPrompt(item.id, {
      name: item.name,
      systemPrompt: item.systemPrompt,
      userPrompt: item.userPrompt,
      enabled: enabled ? 1 : 0,
      remark: item.remark
    })
    ElMessage.success(enabled ? '已启用' : '已停用，将回落到上一级模板')
    await load()
  } catch {
    /* 错误提示由请求拦截器统一弹出 */
  }
}

/** 占位符展示文案：花括号在模板里直接写会被 Vue 解析成插值，统一在 JS 里拼。 */
const varLabel = (key: string) => `{{${key}}}`

const copyVariable = async (key: string) => {
  const label = varLabel(key)
  try {
    await navigator.clipboard.writeText(label)
    ElMessage.success(`已复制 ${label}`)
  } catch {
    ElMessage.warning(`占位符：${label}`)
  }
}

onMounted(async () => {
  await load()
  await loadOptions()
})
</script>

<template>
  <div class="pms-page" v-loading="loading">
    <div class="pms-card">
      <div class="card-head">
        <div class="head-main">
          <h2 class="head-title">周报提示词</h2>
          <p class="head-desc">
            个人周总结按填报人部门匹配，项目周报按项目归属部门匹配；逐级回退到上级部门、
            全公司默认，最后使用系统内置提示词。同一范围同一部门只保留一套。
          </p>
        </div>
        <div class="head-actions">
          <el-radio-group v-model="scopeFilter">
            <el-radio-button value="">全部</el-radio-button>
            <el-radio-button v-for="item in SCOPES" :key="item.value" :value="item.value">
              {{ item.label }}
            </el-radio-button>
          </el-radio-group>
          <el-button type="primary" @click="openCreate">新建部门模板</el-button>
        </div>
      </div>

      <el-empty
        v-if="!filtered.length"
        description="还没有提示词模板，先新建一套"
        :image-size="72"
      />

      <el-table v-else :data="filtered" size="small">
        <el-table-column label="模板" min-width="300">
          <template #default="{ row }">
            <div class="name-cell">
              <el-tag size="small" effect="plain" class="scope-tag">{{ row.scopeLabel }}</el-tag>
              <span class="name-text">{{ row.name }}</span>
              <el-tag v-if="row.builtin" size="small" effect="plain">内置</el-tag>
              <el-tag v-if="row.effective" size="small" type="success" effect="plain">
                当前在用
              </el-tag>
            </div>
            <div v-if="row.remark" class="name-remark">{{ row.remark }}</div>
          </template>
        </el-table-column>
        <el-table-column label="适用部门" width="160">
          <template #default="{ row }">
            <span :class="{ 'global-dept': Number(row.deptId) === 0 }">{{ row.deptName }}</span>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="80">
          <template #default="{ row }">
            <el-switch
              :model-value="row.enabled === 1"
              :disabled="!row.canEdit"
              @change="(value: string | number | boolean) => toggleEnabled(row, value)"
            />
          </template>
        </el-table-column>
        <el-table-column label="更新时间" width="160">
          <template #default="{ row }">{{ row.updateTime || '—' }}</template>
        </el-table-column>
        <el-table-column label="操作" width="140" align="right">
          <template #default="{ row }">
            <el-button
              link
              type="primary"
              size="small"
              :disabled="!row.canEdit"
              @click="openEdit(row)"
            >
              编辑
            </el-button>
            <el-button link type="primary" size="small" @click="openCopy(row)">复制</el-button>
            <el-button
              link
              type="danger"
              size="small"
              :disabled="!!row.builtin || !row.canEdit"
              @click="remove(row)"
            >
              删除
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <el-drawer
      v-model="drawerVisible"
      :title="editing ? '编辑提示词模板' : '新建提示词模板'"
      size="680px"
      class="prompt-drawer"
    >
      <el-form class="prompt-form" label-position="top">
        <el-form-item label="模板名称">
          <el-input v-model="form.name" maxlength="100" show-word-limit placeholder="如：研发部-个人周总结" />
        </el-form-item>
        <div class="form-row">
          <el-form-item label="适用范围" class="form-half">
            <el-select v-model="form.scope" :disabled="!!editing">
              <el-option
                v-for="item in SCOPES"
                :key="item.value"
                :label="item.label"
                :value="item.value"
              />
            </el-select>
          </el-form-item>
          <el-form-item label="适用部门" class="form-half">
            <el-select v-model="form.deptId" :disabled="!!editing || !canManageGlobal">
              <el-option
                v-for="item in deptChoices"
                :key="item.id"
                :label="item.name"
                :value="item.id"
              />
            </el-select>
          </el-form-item>
        </div>
        <el-form-item label="系统提示词（角色设定）">
          <el-input
            v-model="form.systemPrompt"
            type="textarea"
            :rows="3"
            maxlength="4000"
            placeholder="留空使用系统默认：你是资深项目管理助理……"
          />
        </el-form-item>
        <el-form-item label="用户提示词（模板正文）">
          <el-input
            v-model="form.userPrompt"
            type="textarea"
            :rows="9"
            maxlength="20000"
            class="prompt-input"
            placeholder="用中文描述报告结构和要求，数据用占位符引用"
          />
          <div class="field-tip">
            未写 <code>{{ varLabel('stats') }}</code> 或
            <code>{{ varLabel('entries') }}</code> 时，系统会自动把统计数据与日志明细追加到末尾，不会让 AI 缺数据。
          </div>
        </el-form-item>
        <el-collapse class="var-collapse">
          <el-collapse-item name="vars">
            <template #title>
              <span class="var-title">可用占位符（点击复制）</span>
            </template>
            <div class="var-list">
              <el-tag
                v-for="item in variables"
                :key="item.key"
                size="small"
                effect="plain"
                class="var-tag"
                @click="copyVariable(item.key)"
              >
                {{ varLabel(item.key) }}
                <span class="var-remark">{{ item.remark }}</span>
              </el-tag>
            </div>
          </el-collapse-item>
        </el-collapse>
        <div class="form-row">
          <el-form-item label="启用" class="form-half">
            <el-switch v-model="form.enabled" />
          </el-form-item>
          <el-form-item label="备注" class="form-half">
            <el-input v-model="form.remark" maxlength="200" placeholder="选填，说明用途" />
          </el-form-item>
        </div>
      </el-form>
      <template #footer>
        <el-button @click="drawerVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="submit">保存</el-button>
      </template>
    </el-drawer>

    <el-dialog v-model="copyVisible" title="复制提示词模板" width="520px">
      <el-form label-width="86px">
        <el-form-item label="源模板">
          <span>{{ copySource?.name }}（{{ copySource?.deptName }}）</span>
        </el-form-item>
        <el-form-item label="目标部门">
          <el-select v-model="copyForm.deptId" placeholder="选择部门" style="width: 100%">
            <el-option
              v-for="item in deptChoices"
              :key="item.id"
              :label="item.name"
              :value="item.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="模板名称">
          <el-input v-model="copyForm.name" maxlength="100" placeholder="留空自动命名为「xxx（部门版）」" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="copyVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="submitCopy">复制</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
/* ---------------- 卡片头部（与列表同一张卡片） ---------------- */
.card-head {
  display: flex;
  align-items: flex-start;
  flex-wrap: wrap;
  gap: 12px 16px;
  margin-bottom: 14px;
}

.head-main {
  flex: 1 1 420px;
  min-width: 0;
}

.head-title {
  margin: 0;
  font-size: 14.5px;
  font-weight: 600;
  letter-spacing: 0.01em;
  color: var(--pms-text);
}

.head-desc {
  margin: 6px 0 0;
  font-size: 12.5px;
  line-height: 1.7;
  color: var(--pms-text-3);
  text-wrap: pretty;
}

.head-actions {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  margin-left: auto;
}

.name-cell {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}

.name-cell .el-tag {
  flex: none;
}

.name-text {
  overflow: hidden;
  font-weight: 500;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.name-remark {
  margin-top: 2px;
  overflow: hidden;
  font-size: 12px;
  color: var(--pms-text-3);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.global-dept {
  color: var(--pms-text-2);
  font-weight: 500;
}

/* ---------------- 编辑抽屉 ---------------- */
/* 全局把 drawer body 的 padding 清成了 0，这里补回内边距 */
:global(.prompt-drawer .el-drawer__header) {
  margin-bottom: 0;
  padding: 18px 24px;
  border-bottom: 1px solid var(--pms-line, #e8edf6);
  font-size: 15px;
  font-weight: 600;
  color: var(--pms-text, #111827);
}

:global(.prompt-drawer .el-drawer__body) {
  padding: 20px 24px 8px;
}

:global(.prompt-drawer .el-drawer__footer) {
  padding: 12px 24px;
  border-top: 1px solid var(--pms-line, #e8edf6);
}

.prompt-form :deep(.el-form-item) {
  margin-bottom: 18px;
}

.prompt-form :deep(.el-form-item__label) {
  padding-bottom: 6px;
  font-size: 12.5px;
  line-height: 1.4;
  color: var(--pms-text-2, #4b5563);
}

.form-row {
  display: flex;
  gap: 16px;
}

.form-half {
  flex: 1 1 0;
  min-width: 0;
}

.form-half :deep(.el-select) {
  width: 100%;
}

.prompt-input :deep(textarea) {
  font-family: ui-monospace, SFMono-Regular, Consolas, 'Liberation Mono', monospace;
  font-size: 12.5px;
  line-height: 1.6;
}

.field-tip {
  margin-top: 6px;
  font-size: 12px;
  line-height: 1.6;
  color: var(--pms-text-3, #8b93a7);
}

.field-tip code {
  padding: 1px 4px;
  border-radius: 4px;
  background: #f2f4f8;
  font-family: ui-monospace, SFMono-Regular, Consolas, 'Liberation Mono', monospace;
}

.var-collapse {
  margin-bottom: 18px;
  border-top: 0;
  border-bottom: 1px solid var(--pms-line, #e8edf6);
}

.var-collapse :deep(.el-collapse-item__header) {
  height: 38px;
  border-bottom: 0;
  font-size: 12.5px;
  color: var(--pms-text-2, #4b5563);
}

.var-collapse :deep(.el-collapse-item__wrap) {
  border-bottom: 0;
}

.var-title {
  font-size: 12.5px;
}

.var-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  padding-bottom: 8px;
}

.var-tag {
  cursor: pointer;
}

.var-remark {
  margin-left: 4px;
  color: var(--pms-text-3);
}

@media (max-width: 768px) {
  .head-actions {
    width: 100%;
    margin-left: 0;
  }

  .form-row {
    flex-direction: column;
    gap: 0;
  }
}
</style>
