<script setup lang="ts">
defineOptions({ name: 'PersonPicker' })
import { computed, ref } from 'vue'
import { Search } from '@element-plus/icons-vue'

const props = withDefaults(
  defineProps<{
    modelValue: string[]
    users: any[]
    depts: any[]
    title?: string
    placeholder?: string
    /** small：与同排的 size="small" 下拉、按钮等高，用于表格上方的紧凑操作条 */
    size?: 'default' | 'small'
    disabled?: boolean
  }>(),
  {
    title: '选择人员',
    placeholder: '点击选择人员',
    size: 'default',
    disabled: false,
    // 兜底空数组：调用方漏初始化时也不至于整块渲染崩溃
    modelValue: () => []
  }
)

const emit = defineEmits<{ 'update:modelValue': [value: string[]] }>()

const visible = ref(false)
const keyword = ref('')
const deptFilter = ref('')
const draft = ref<string[]>([])

const deptName = (id: string | number) =>
  props.depts.find((dept) => String(dept.id) === String(id))?.deptName || '—'

const personName = (id: string | number) => {
  const hit = props.users.find((user) => String(user.id) === String(id))
  return hit ? hit.realName : '未知人员'
}

const filteredUsers = computed(() => {
  const kw = keyword.value.trim().toLowerCase()
  return props.users.filter((user) => {
    const matchKw =
      !kw ||
      String(user.realName || '').toLowerCase().includes(kw) ||
      String(user.username || '').toLowerCase().includes(kw)
    const matchDept = !deptFilter.value || String(user.deptId) === String(deptFilter.value)
    return matchKw && matchDept
  })
})

/** 当前筛选结果里还没选的人：用来提示「选中结果」按钮还能加几个人 */
const filteredUnpicked = computed(() =>
  filteredUsers.value.filter((user) => !draft.value.includes(String(user.id)))
)

const open = () => {
  if (props.disabled) return
  draft.value = [...props.modelValue]
  keyword.value = ''
  deptFilter.value = ''
  visible.value = true
}

const toggle = (id: string) => {
  const index = draft.value.indexOf(id)
  if (index >= 0) draft.value.splice(index, 1)
  else draft.value.push(id)
}

const selectFiltered = () => {
  for (const user of filteredUsers.value) {
    const id = String(user.id)
    if (!draft.value.includes(id)) draft.value.push(id)
  }
}

const clearDraft = () => {
  draft.value = []
}

const removeDraftTag = (id: string) => {
  const index = draft.value.indexOf(id)
  if (index >= 0) draft.value.splice(index, 1)
}

const removePicked = (id: string) => {
  emit(
    'update:modelValue',
    props.modelValue.filter((item) => String(item) !== id)
  )
}

const confirm = () => {
  emit('update:modelValue', [...draft.value])
  visible.value = false
}
</script>

<template>
  <div
    class="person-picker"
    :class="{ 'is-small': size === 'small', 'is-disabled': disabled }"
    @click="open"
  >
    <div class="picker-value">
      <template v-if="modelValue.length">
        <el-tag
          v-for="id in modelValue"
          :key="id"
          size="small"
          :closable="!disabled"
          @click.stop
          @close.stop="removePicked(String(id))"
        >
          {{ personName(id) }}
        </el-tag>
      </template>
      <span v-else class="picker-placeholder">{{ placeholder }}</span>
    </div>
    <span v-if="!disabled" class="picker-action">选择</span>
  </div>

  <el-dialog
    v-model="visible"
    :title="title"
    width="min(800px, 94vw)"
    align-center
    append-to-body
    :close-on-click-modal="false"
  >
    <div class="picker-toolbar">
      <el-input v-model="keyword" placeholder="搜索姓名 / 账号" clearable class="picker-search">
        <template #prefix>
          <el-icon><Search /></el-icon>
        </template>
      </el-input>
      <el-select v-model="deptFilter" placeholder="全部部门" clearable filterable class="picker-dept">
        <el-option v-for="dept in depts" :key="dept.id" :label="dept.deptName" :value="dept.id" />
      </el-select>
      <el-button :disabled="!filteredUnpicked.length" @click="selectFiltered">
        选中结果<template v-if="filteredUnpicked.length">（{{ filteredUnpicked.length }}）</template>
      </el-button>
    </div>
    <div class="picker-columns">
      <div class="picker-list">
        <div class="picker-col-head">
          <span>人员</span>
          <span class="picker-count">{{ filteredUsers.length }}</span>
        </div>
        <div class="picker-scroll">
          <div
            v-for="user in filteredUsers"
            :key="user.id"
            class="picker-person"
            :class="{ 'is-active': draft.includes(String(user.id)) }"
            @click="toggle(String(user.id))"
          >
            <el-checkbox
              :model-value="draft.includes(String(user.id))"
              @click.stop
              @change="toggle(String(user.id))"
            />
            <div class="picker-person-main">
              <b>{{ user.realName }}</b>
              <span>{{ user.username || '—' }}</span>
            </div>
            <span class="picker-person-dept">{{ deptName(user.deptId) }}</span>
          </div>
          <el-empty v-if="!filteredUsers.length" description="没有匹配的人员" :image-size="48" />
        </div>
      </div>
      <div class="picker-selected">
        <div class="picker-col-head">
          <span>
            已选
            <b class="picker-count-num">{{ draft.length }}</b>
            人
          </span>
          <el-button link type="danger" size="small" :disabled="!draft.length" @click="clearDraft">
            清空
          </el-button>
        </div>
        <div class="picker-scroll picker-chips">
          <template v-if="draft.length">
            <el-tag
              v-for="id in draft"
              :key="id"
              closable
              @close="removeDraftTag(id)"
            >
              {{ personName(id) }}
            </el-tag>
          </template>
          <div v-else class="picker-empty">
            <span class="picker-empty-title">尚未选择人员</span>
            <span class="picker-empty-sub">点击左侧人员加入，可多选</span>
          </div>
        </div>
      </div>
    </div>
    <template #footer>
      <el-button @click="visible = false">取消</el-button>
      <el-button type="primary" @click="confirm">确定（{{ draft.length }}）</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.person-picker {
  display: flex;
  min-height: 32px;
  align-items: center;
  gap: 8px;
  padding: 4px 8px;
  border: 1px solid var(--el-border-color);
  border-radius: 6px;
  background: var(--el-fill-color-blank);
  cursor: pointer;
  transition: border-color 0.2s;
}

.person-picker:hover {
  border-color: var(--el-color-primary);
}

/* 紧凑尺寸：与 el-select / el-button 的 size="small"（24px）等高 */
.person-picker.is-small {
  min-height: 24px;
  gap: 6px;
  padding: 0 8px;
  border-radius: 4px;
}

.person-picker.is-small .picker-placeholder,
.person-picker.is-small .picker-action {
  font-size: 12px;
}

.person-picker.is-disabled {
  background: var(--el-fill-color-light);
  cursor: not-allowed;
}

.person-picker.is-disabled:hover {
  border-color: var(--el-border-color);
}

.picker-value {
  display: flex;
  flex: 1;
  flex-wrap: wrap;
  gap: 4px;
  min-width: 0;
}

.picker-placeholder {
  color: var(--el-text-color-placeholder);
  font-size: 12.5px;
}

.picker-action {
  flex: none;
  color: var(--el-color-primary);
  font-size: 12.5px;
}

.picker-toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
}

.picker-search {
  flex: 1 1 240px;
}

.picker-dept {
  flex: 0 1 180px;
}

.picker-columns {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 260px;
  gap: 12px;
  height: min(420px, 58vh);
}

.picker-list,
.picker-selected {
  display: flex;
  min-width: 0;
  flex-direction: column;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  overflow: hidden;
}

.picker-col-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 12px;
  background: var(--el-fill-color-light);
  font-size: 12.5px;
  font-weight: 600;
}

.picker-count {
  color: var(--el-text-color-secondary);
  font-weight: 400;
}

.picker-count-num {
  margin: 0 2px;
  color: var(--el-color-primary);
}

.picker-scroll {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  scrollbar-gutter: stable;
}

/* 细滚动条：避免默认滚动条压住右侧内容 */
.picker-scroll::-webkit-scrollbar {
  width: 8px;
}

.picker-scroll::-webkit-scrollbar-track {
  background: transparent;
}

.picker-scroll::-webkit-scrollbar-thumb {
  border: 2px solid transparent;
  border-radius: 4px;
  background-clip: content-box;
  background-color: var(--el-border-color);
}

.picker-scroll::-webkit-scrollbar-thumb:hover {
  background-color: var(--el-text-color-placeholder);
}

.picker-person {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 12px;
  border-bottom: 1px solid var(--el-border-color-lighter);
  cursor: pointer;
  transition: background-color 0.15s;
}

.picker-person:hover,
.picker-person.is-active {
  background: var(--el-color-primary-light-9);
}

.picker-person-main {
  display: flex;
  flex: 1;
  flex-direction: column;
  min-width: 0;
  line-height: 1.4;
}

.picker-person-main b {
  font-size: 13px;
  font-weight: 500;
}

.picker-person-main span,
.picker-person-dept {
  color: var(--el-text-color-secondary);
  font-size: 11.5px;
}

.picker-person-dept {
  flex: none;
  max-width: 40%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.picker-chips {
  display: flex;
  flex-wrap: wrap;
  align-content: flex-start;
  gap: 6px;
  padding: 10px;
}

.picker-empty {
  display: flex;
  flex: 1 1 100%;
  align-items: center;
  justify-content: center;
  flex-direction: column;
  gap: 4px;
  min-height: 120px;
  padding: 16px;
  text-align: center;
}

.picker-empty-title {
  font-size: 12.5px;
  color: var(--el-text-color-secondary);
}

.picker-empty-sub {
  font-size: 12px;
  color: var(--el-text-color-placeholder);
}

@media (max-width: 768px) {
  .picker-columns {
    grid-template-columns: 1fr;
    height: auto;
  }

  .picker-list {
    max-height: 260px;
  }

  .picker-selected {
    min-height: 120px;
    max-height: 180px;
  }
}
</style>
                                                                                                                                                                                                                            