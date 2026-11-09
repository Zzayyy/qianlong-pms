<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { listConfigs, resetConfigs, updateConfigs, type ConfigItem } from '@/api'
import { useUserStore } from '@/stores/user'

const store = useUserStore()
const canManage = computed(() => store.has('sys:config'))

type Row = ConfigItem & { original: string; editValue: any }

const rows = ref<Row[]>([])
const loading = ref(false)
const saving = ref(false)
const keyword = ref('')

const TYPE_LABEL: Record<string, string> = {
  BOOL: '开关',
  INT: '整数',
  FLOAT: '小数',
  STRING: '文本'
}
const typeLabel = (type: string) => TYPE_LABEL[type] || '文本'

/** 库里的字符串 → 表单控件值。 */
const parseValue = (type: string, value: string) => {
  if (type === 'BOOL') return value === 'true'
  if (type === 'INT' || type === 'FLOAT') {
    const num = Number(value)
    return Number.isFinite(num) ? num : null
  }
  return value
}

/** 表单控件值 → 落库字符串（与后端校验保持一致）。 */
const toStorage = (row: Row) => {
  if (row.valueType === 'BOOL') return row.editValue ? 'true' : 'false'
  if (row.valueType === 'INT') return String(Math.trunc(Number(row.editValue ?? 0)))
  if (row.valueType === 'FLOAT') return String(Number(row.editValue ?? 0))
  return String(row.editValue ?? '').trim()
}

const isDirty = (row: Row) => toStorage(row) !== row.original

const dirtyRows = computed(() => rows.value.filter((row) => isDirty(row)))
const dirtyCount = computed(() => dirtyRows.value.length)
const total = computed(() => rows.value.length)

const filteredRows = computed(() => {
  const text = keyword.value.trim().toLowerCase()
  if (!text) return rows.value
  return rows.value.filter((row) =>
    [row.configKey, row.groupName, row.remark]
      .map((item) => String(item || '').toLowerCase())
      .some((item) => item.includes(text))
  )
})

/** 按分组展示，保留接口返回的分组顺序。 */
const groups = computed(() => {
  const map = new Map<string, Row[]>()
  for (const row of filteredRows.value) {
    const list = map.get(row.groupName) || []
    list.push(row)
    map.set(row.groupName, list)
  }
  return [...map.entries()].map(([name, items]) => ({ name, items }))
})

const load = async () => {
  loading.value = true
  try {
    const data = (await listConfigs()) || []
    rows.value = data.map((item) => ({
      ...item,
      original: item.configValue,
      editValue: parseValue(item.valueType, item.configValue)
    }))
  } finally {
    loading.value = false
  }
}

const undo = () => {
  rows.value.forEach((row) => {
    row.editValue = parseValue(row.valueType, row.original)
  })
}

const restoreOne = (row: Row) => {
  row.editValue = parseValue(row.valueType, row.defaultValue)
}

const save = async () => {
  if (!canManage.value || !dirtyRows.value.length) return
  const invalid = dirtyRows.value.some(
    (row) =>
      (row.valueType === 'INT' || row.valueType === 'FLOAT') &&
      (row.editValue === null || row.editValue === undefined || row.editValue === '')
  )
  if (invalid) {
    ElMessage.warning('数字参数不能为空')
    return
  }
  saving.value = true
  try {
    const result = await updateConfigs(
      dirtyRows.value.map((row) => ({
        configKey: row.configKey,
        configValue: toStorage(row)
      }))
    )
    ElMessage.success(`已保存 ${result.updated} 项参数`)
    await load()
  } catch {
    /* 错误提示由请求拦截器统一弹出 */
  } finally {
    saving.value = false
  }
}

const restoreAll = async () => {
  if (!canManage.value || !rows.value.length) return
  try {
    await ElMessageBox.confirm(
      `将把全部 ${rows.value.length} 项参数恢复为代码默认值，可能影响审批阈值、日志规则等业务行为。`,
      '恢复默认参数',
      { type: 'warning', confirmButtonText: '恢复默认', cancelButtonText: '取消' }
    )
  } catch {
    return
  }
  try {
    const result = await resetConfigs(rows.value.map((row) => row.configKey))
    ElMessage.success(`已恢复 ${result.reset} 项默认值`)
    await load()
  } catch {
    /* 错误提示由请求拦截器统一弹出 */
  }
}

onMounted(load)
</script>

<template>
  <div class="pms-page" v-loading="loading">
    <div class="pms-card config-head">
      <div class="head-filters">
        <el-input
          v-model="keyword"
          class="config-search"
          placeholder="搜索参数名、分组或含义，如 工时、health."
          clearable
        />
        <span class="config-stats">
          共 {{ total }} 项
          <template v-if="dirtyCount">
            · <b class="dirty-count">{{ dirtyCount }} 项未保存</b>
          </template>
        </span>
      </div>
      <div class="head-actions">
        <el-button link type="danger" :disabled="!canManage" @click="restoreAll">
          恢复默认
        </el-button>
        <el-button :disabled="!dirtyCount" @click="undo">撤销修改</el-button>
        <el-button
          type="primary"
          :disabled="!canManage || !dirtyCount"
          :loading="saving"
          @click="save"
        >
          保存修改
        </el-button>
      </div>
    </div>

    <el-empty v-if="!groups.length" description="没有匹配的参数" />

    <div v-for="group in groups" :key="group.name" class="pms-card config-group">
      <div class="group-head">
        <h3>{{ group.name }}</h3>
        <span class="group-count">{{ group.items.length }} 项</span>
      </div>

      <div class="config-list">
        <div
          v-for="row in group.items"
          :key="row.configKey"
          class="config-row"
          :class="{ 'is-dirty': isDirty(row) }"
        >
          <div class="config-meta">
            <div class="config-key">
              <span>{{ row.configKey }}</span>
              <el-tag size="small" effect="plain" class="type-tag">
                {{ typeLabel(row.valueType) }}
              </el-tag>
              <el-tag v-if="isDirty(row)" size="small" type="warning" effect="plain">
                未保存
              </el-tag>
            </div>
            <div class="config-remark">{{ row.remark || '未登记说明' }}</div>
          </div>

          <div class="config-value">
            <el-switch
              v-if="row.valueType === 'BOOL'"
              v-model="row.editValue"
              :disabled="!canManage"
            />
            <el-input-number
              v-else-if="row.valueType === 'INT'"
              v-model="row.editValue"
              :min="0"
              :step="1"
              :controls="false"
              :disabled="!canManage"
            />
            <el-input-number
              v-else-if="row.valueType === 'FLOAT'"
              v-model="row.editValue"
              :min="0"
              :step="0.1"
              :controls="false"
              :disabled="!canManage"
            />
            <el-input v-else v-model="row.editValue" :disabled="!canManage" />
          </div>

          <div class="config-default">
            <span class="default-label">默认</span>
            <span class="default-value">{{ row.defaultValue || '—' }}</span>
          </div>

          <div class="config-action">
            <el-button
              link
              type="primary"
              size="small"
              :disabled="
                !canManage || row.editValue === parseValue(row.valueType, row.defaultValue)
              "
              @click="restoreOne(row)"
            >
              恢复默认
            </el-button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.config-head {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
}

.head-filters {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
  flex: 1 1 420px;
  min-width: 0;
}

.config-search {
  width: 320px;
}

.config-stats {
  font-size: 12.5px;
  color: var(--pms-text-3);
  font-variant-numeric: tabular-nums;
}

.dirty-count {
  color: #c47f17;
  font-weight: 500;
}

.head-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-left: auto;
}

/* ---------------- 分组 ---------------- */
.group-head {
  display: flex;
  align-items: baseline;
  gap: 8px;
  margin-bottom: 6px;
  padding-bottom: 10px;
  border-bottom: 1px solid var(--pms-line);
}

.group-head h3 {
  margin: 0;
  font-size: 14px;
  font-weight: 600;
  color: var(--pms-text);
}

.group-count {
  font-size: 12px;
  color: var(--pms-text-3);
}

.config-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 180px 110px 84px;
  align-items: center;
  gap: 16px;
  padding: 12px 8px;
  border-bottom: 1px solid #f2f4f8;
  transition: background-color 0.15s ease;
}

.config-row:last-child {
  border-bottom: 0;
}

.config-row:hover {
  background: #fafbfe;
}

.config-row.is-dirty {
  background: #fffdf5;
}

.config-meta {
  min-width: 0;
}

.config-key {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  font-family: ui-monospace, SFMono-Regular, Consolas, 'Liberation Mono', monospace;
  font-size: 12.5px;
  color: var(--pms-text);
}

.type-tag {
  font-family: inherit;
}

.config-remark {
  margin-top: 4px;
  overflow: hidden;
  font-size: 12px;
  line-height: 1.6;
  color: var(--pms-text-3);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.config-value :deep(.el-input-number),
.config-value :deep(.el-input) {
  width: 100%;
}

.config-value :deep(.el-input-number .el-input__inner) {
  text-align: left;
}

.config-default {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.default-label {
  font-size: 11px;
  color: var(--pms-text-3);
}

.default-value {
  overflow: hidden;
  font-size: 12.5px;
  color: var(--pms-text-2);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.config-action {
  text-align: right;
}

.config-action :deep(.el-button) {
  padding: 0;
}

@media (max-width: 768px) {
  .config-search {
    width: 100%;
  }

  .head-filters {
    flex: 1 1 100%;
  }

  .head-actions {
    width: 100%;
    margin-left: 0;
    justify-content: flex-end;
  }

  .config-row {
    grid-template-columns: 1fr;
    gap: 8px;
    padding: 12px 4px;
  }

  .config-remark {
    white-space: normal;
  }

  .config-default {
    flex-direction: row;
    align-items: baseline;
    gap: 8px;
  }

  .config-action {
    text-align: left;
  }
}
</style>
