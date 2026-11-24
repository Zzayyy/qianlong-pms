<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { RefreshCw, Sparkles } from 'lucide-vue-next'
import {
  confirmWeekly,
  generateWeekly,
  listWeeklies,
  updateWeekly,
  weeklyDetail,
  weeklyOptions,
  weeklyPreview,
  type WeeklyItem,
  type WeeklyOptions,
  type WeeklyPreview
} from '@/api'
import { useUserStore } from '@/stores/user'
import { renderMarkdown, stripLeadingTitle } from '@/utils/markdown'
import { confirmWeeklyOverwrite, toWeekStart, weekLabelOf } from '@/utils/weekly'

defineOptions({ name: 'WeekliesPage' })

interface WeeklyStats {
  totalHours?: number
  logCount?: number
  memberCount?: number
  riskLogCount?: number
  dateFrom?: string
  dateTo?: string
  members?: { name: string; hours: number; logCount: number }[]
  byProject?: { name: string; hours: number; logCount: number }[]
}

const store = useUserStore()
/** 项目周报只对领导层（weekly:project:view）与项目经理（project:edit）开放 */
const canViewProjectWeekly = computed(
  () => store.has('weekly:project:view') || store.has('project:edit')
)

const tab = ref<'project' | 'personal'>('project')
const options = ref<WeeklyOptions>({
  weekStart: '',
  weekEnd: '',
  weekLabel: '',
  prevWeekStart: '',
  today: '',
  projects: [],
  autoEnabled: true,
  aiConfigured: false
})

const loading = ref(false)
const generating = ref(false)
const rows = ref<WeeklyItem[]>([])
const total = ref(0)
const page = reactive({ pageNum: 1, pageSize: 10 })
const projectFilters = reactive({ weekStart: '', projectId: '', status: '' })
const personalFilters = reactive({ weekStart: '' })

/** 已选项目能否生成：只有该项目的项目经理 / PMO / 管理员可以（后端下发 canGenerate） */
const selectedProject = computed(() =>
  options.value.projects.find((item) => String(item.id) === String(projectFilters.projectId))
)
const canGenerate = computed(
  () => Boolean(selectedProject.value) && selectedProject.value?.canGenerate !== false
)

const drawer = reactive({ visible: false, loading: false })
const current = ref<WeeklyItem | null>(null)
const editing = ref(false)
const saving = ref(false)
const confirming = ref(false)
const form = reactive({ title: '', content: '' })

const stats = computed<WeeklyStats>(() => (current.value?.stats as WeeklyStats) || {})
const canEdit = computed(() => current.value?.status === 'GENERATED')
const dirty = computed(
  () => !!current.value && (form.content !== (current.value.content || '') || form.title !== current.value.title)
)

const STATUS_LABEL: Record<string, string> = { GENERATED: '待确认', CONFIRMED: '已确认' }
const SOURCE_LABEL: Record<string, string> = { AUTO: '自动生成', MANUAL: '手动生成' }

/** 正文去掉首行一级标题（标题已在详情头部展示，避免重复）。 */
const bodyText = computed(() => stripLeadingTitle(current.value?.content || ''))
const rendered = computed(() => renderMarkdown(bodyText.value))

const loadOptions = async () => {
  const data = await weeklyOptions()
  options.value = data
  if (!projectFilters.weekStart) projectFilters.weekStart = data.weekStart
  if (!personalFilters.weekStart) personalFilters.weekStart = data.weekStart
}

const loadList = async () => {
  loading.value = true
  try {
    const isProject = tab.value === 'project'
    const data = await listWeeklies({
      scope: isProject ? 'PROJECT' : 'PERSONAL',
      weekStart: (isProject ? projectFilters.weekStart : personalFilters.weekStart) || undefined,
      projectId: isProject ? projectFilters.projectId || undefined : undefined,
      status: isProject ? projectFilters.status || undefined : undefined,
      pageNum: page.pageNum,
      pageSize: page.pageSize
    })
    rows.value = data.list || []
    total.value = Number(data.total || 0)
  } finally {
    loading.value = false
  }
}

const search = () => {
  page.pageNum = 1
  loadList()
}

/**
 * 周选择器拿到的值是「周日」（dayjs 未注册中文包，周首日是周日），
 * 这里统一换算成后端使用的 ISO 周一，否则按周过滤会查不到数据。
 */
const onProjectWeekChange = (value: any) => {
  projectFilters.weekStart = toWeekStart(String(value || '')) || options.value.weekStart
  search()
}

const onPersonalWeekChange = (value: any) => {
  personalFilters.weekStart = toWeekStart(String(value || '')) || options.value.weekStart
  search()
}

const reset = () => {
  projectFilters.projectId = ''
  projectFilters.status = ''
  projectFilters.weekStart = options.value.weekStart
  search()
}

const switchTab = () => {
  page.pageNum = 1
  loadList()
}

const openDetail = async (row: any) => {
  drawer.visible = true
  drawer.loading = true
  editing.value = false
  current.value = row as WeeklyItem
  try {
    const detail = await weeklyDetail(String(row.id))
    current.value = detail
    form.title = detail.title
    form.content = detail.content || ''
  } finally {
    drawer.loading = false
  }
}

/** 生成完成后收起表格刷新，并直接打开详情便于确认。 */
const afterGenerate = async (item: WeeklyItem, weekStart: string) => {
  if (tab.value === 'project') projectFilters.weekStart = weekStart
  else personalFilters.weekStart = weekStart
  await loadList()
  await openDetail(item)
}

const notifyAiHint = () => {
  if (!options.value.aiConfigured) {
    ElMessage.warning('AI 密钥未配置，将生成纯数据模板')
    return
  }
  ElMessage.info('AI 正在汇总本周日志，通常需要 10~30 秒')
}

/* ------------------------------ 依据日志预览 ------------------------------ */
const preview = reactive({
  visible: false,
  loading: false,
  data: null as WeeklyPreview | null
})

/** 生成前先看依据日志：口径与生成完全一致，避免生成完才发现数据不对。 */
const openPreview = async () => {
  if (!projectFilters.projectId) {
    ElMessage.warning('请先选择项目')
    return
  }
  preview.visible = true
  preview.loading = true
  preview.data = null
  try {
    preview.data = await weeklyPreview({
      projectId: projectFilters.projectId,
      weekStart: projectFilters.weekStart || undefined
    })
  } catch {
    preview.visible = false
  } finally {
    preview.loading = false
  }
}

const generateProject = async () => {
  if (!projectFilters.projectId) {
    ElMessage.warning('请先选择项目')
    return
  }
  if (
    !(await confirmWeeklyOverwrite({
      scope: 'PROJECT',
      projectId: projectFilters.projectId,
      weekStart: projectFilters.weekStart
    }))
  ) {
    return
  }
  notifyAiHint()
  generating.value = true
  try {
    const item = await generateWeekly({
      scope: 'PROJECT',
      projectId: projectFilters.projectId,
      weekStart: projectFilters.weekStart
    })
    ElMessage.success('项目周报已生成，请核对后确认')
    await afterGenerate(item, item.weekStart)
  } finally {
    generating.value = false
  }
}

/** 预览抽屉里直接生成：关闭抽屉后走同一套生成逻辑（含覆盖确认）。 */
const generateFromPreview = async () => {
  preview.visible = false
  await generateProject()
}

const generatePersonal = async () => {
  if (
    !(await confirmWeeklyOverwrite({
      scope: 'PERSONAL',
      weekStart: personalFilters.weekStart
    }))
  ) {
    return
  }
  notifyAiHint()
  generating.value = true
  try {
    const item = await generateWeekly({
      scope: 'PERSONAL',
      weekStart: personalFilters.weekStart
    })
    ElMessage.success('个人周总结已生成')
    await afterGenerate(item, item.weekStart)
  } finally {
    generating.value = false
  }
}

const quickConfirm = async (row: any) => {
  await openDetail(row)
  await confirm()
}

const toggleEdit = () => {
  if (editing.value && dirty.value) {
    form.title = current.value?.title || ''
    form.content = current.value?.content || ''
  }
  editing.value = !editing.value
}

const save = async () => {
  if (!current.value) return
  if (!form.content.trim()) {
    ElMessage.warning('周报正文不能为空')
    return
  }
  saving.value = true
  try {
    current.value = await updateWeekly(current.value.id, {
      title: form.title.trim(),
      content: form.content
    })
    form.title = current.value.title
    form.content = current.value.content || ''
    editing.value = false
    ElMessage.success('已保存')
    await loadList()
  } finally {
    saving.value = false
  }
}

const confirm = async () => {
  if (!current.value) return
  try {
    await ElMessageBox.confirm(
      '确认后周报归档，不再随日志自动变化，正文也不能再编辑。确认提交？',
      '确认周报',
      { type: 'warning', confirmButtonText: '确认归档', cancelButtonText: '再看看' }
    )
  } catch {
    return
  }
  confirming.value = true
  try {
    if (editing.value && dirty.value) await save()
    current.value = await confirmWeekly(current.value.id)
    editing.value = false
    ElMessage.success('周报已确认归档')
    await loadList()
  } finally {
    confirming.value = false
  }
}

const regenerate = async () => {
  if (!current.value) return
  if (
    !(await confirmWeeklyOverwrite({
      scope: current.value.scope,
      projectId: current.value.projectId,
      weekStart: current.value.weekStart
    }))
  ) {
    return
  }
  notifyAiHint()
  generating.value = true
  try {
    const item = await generateWeekly({
      scope: current.value.scope,
      projectId: current.value.scope === 'PROJECT' ? current.value.projectId : undefined,
      weekStart: current.value.weekStart
    })
    current.value = item
    form.title = item.title
    form.content = item.content || ''
    editing.value = false
    ElMessage.success('已重新生成')
    await loadList()
  } finally {
    generating.value = false
  }
}

onMounted(async () => {
  if (!canViewProjectWeekly.value) tab.value = 'personal'
  await loadOptions()
  await loadList()
})
</script>

<template>
  <div class="pms-page weekly-page">
    <div class="pms-card head-card">
      <div class="head-main">
        <span class="head-icon"><Sparkles :size="18" /></span>
        <div>
          <h2>周报总结</h2>
          <p>按周汇总工作日志，AI 生成后由项目经理确认，确认前可自由编辑</p>
        </div>
      </div>
      <div class="head-tags">
        <el-tag :type="options.aiConfigured ? 'success' : 'warning'" effect="plain" size="small">
          {{ options.aiConfigured ? 'AI 已就绪' : 'AI 未配置（降级为数据模板）' }}
        </el-tag>
        <el-tag type="info" effect="plain" size="small">
          {{ options.autoEnabled ? '每周五 12:00 自动生成项目周报' : '自动生成已关闭' }}
        </el-tag>
      </div>
    </div>

    <div class="pms-card">
      <el-tabs v-model="tab" @tab-change="switchTab">
        <el-tab-pane v-if="canViewProjectWeekly" label="项目周报" name="project">
          <div class="toolbar">
            <el-date-picker
              v-model="projectFilters.weekStart"
              type="week"
              format="YYYY 第 ww 周"
              value-format="YYYY-MM-DD"
              :first-day-of-week="1"
              :clearable="false"
              placeholder="选择周"
              style="width: 170px"
              @change="onProjectWeekChange"
            />
            <el-select
              v-model="projectFilters.projectId"
              placeholder="全部项目"
              clearable
              filterable
              style="width: 240px"
              @change="search"
            >
              <el-option
                v-for="item in options.projects"
                :key="item.id"
                :label="`${item.projectName}（${item.projectCode}）${
                  item.canGenerate === false ? ' · 仅可查看' : ''
                }`"
                :value="item.id"
              />
            </el-select>
            <el-select
              v-model="projectFilters.status"
              placeholder="全部状态"
              clearable
              style="width: 130px"
              @change="search"
            >
              <el-option label="待确认" value="GENERATED" />
              <el-option label="已确认" value="CONFIRMED" />
            </el-select>
            <el-button @click="reset">重置</el-button>
            <span class="spacer"></span>
            <el-button :icon="RefreshCw" circle :loading="loading" aria-label="刷新" @click="loadList" />
            <el-button :disabled="!projectFilters.projectId" @click="openPreview">
              依据日志
            </el-button>
            <span v-if="!projectFilters.projectId" class="gen-hint">
              {{ options.projects.length ? '请先在左侧选择项目' : '没有可生成周报的项目' }}
            </span>
            <span v-else-if="!canGenerate" class="gen-hint">
              仅该项目的项目经理 / PMO 可生成
            </span>
            <el-tooltip
              :content="`按所选周次（${weekLabelOf(projectFilters.weekStart)}）汇总所选项目日志生成周报；已有则覆盖并升版本（需该项目的项目经理）`"
              placement="top"
            >
              <el-button
                type="primary"
                :icon="Sparkles"
                :loading="generating"
                :disabled="!canGenerate"
                @click="generateProject"
              >
                生成周报
              </el-button>
            </el-tooltip>
          </div>
        </el-tab-pane>

        <el-tab-pane label="我的周总结" name="personal">
          <div class="toolbar">
            <el-date-picker
              v-model="personalFilters.weekStart"
              type="week"
              format="YYYY 第 ww 周"
              value-format="YYYY-MM-DD"
              :first-day-of-week="1"
              :clearable="false"
              placeholder="选择周"
              style="width: 170px"
              @change="onPersonalWeekChange"
            />
            <span class="hint">不限周五，任意时间都可生成本周总结；想补写上周也可切换周次</span>
            <span class="spacer"></span>
            <el-button :icon="RefreshCw" circle :loading="loading" aria-label="刷新" @click="loadList" />
            <el-tooltip
              :content="`按所选周次（${weekLabelOf(personalFilters.weekStart)}）汇总本人日志生成周总结；已有则覆盖并升版本`"
              placement="top"
            >
              <el-button type="primary" :icon="Sparkles" :loading="generating" @click="generatePersonal">
                生成我的周总结
              </el-button>
            </el-tooltip>
          </div>
        </el-tab-pane>
      </el-tabs>

      <el-table v-loading="loading" :data="rows" size="small">
        <el-table-column label="周次" width="110" prop="weekLabel" />
        <el-table-column
          v-if="tab === 'project'"
          label="项目"
          min-width="180"
          prop="projectName"
          show-overflow-tooltip
        />
        <el-table-column label="标题" min-width="240" show-overflow-tooltip>
          <template #default="{ row }">
            <el-button link type="primary" class="title-link" @click="openDetail(row)">
              {{ row.title || '未命名周报' }}
            </el-button>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="row.status === 'CONFIRMED' ? 'success' : 'warning'" size="small" effect="plain">
              {{ STATUS_LABEL[row.status] || row.status }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="生成" width="110">
          <template #default="{ row }">
            <span class="source-text">
              {{ SOURCE_LABEL[row.source] || row.source }}
              <em v-if="!row.aiUsed">（模板）</em>
            </span>
          </template>
        </el-table-column>
        <el-table-column label="版本" width="70">
          <template #default="{ row }">v{{ row.revision }}</template>
        </el-table-column>
        <el-table-column label="确认人" width="110" prop="confirmName">
          <template #default="{ row }">{{ row.confirmName || '—' }}</template>
        </el-table-column>
        <el-table-column label="生成时间" width="160" prop="createTime" />
        <el-table-column label="操作" width="150">
          <template #default="{ row }">
            <el-button link type="primary" @click="openDetail(row)">查看</el-button>
            <el-button v-if="row.status === 'GENERATED'" link type="primary" @click="quickConfirm(row)">
              确认
            </el-button>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty description="本周还没有生成周报" :image-size="72" />
        </template>
      </el-table>

      <el-pagination
        v-model:current-page="page.pageNum"
        v-model:page-size="page.pageSize"
        :total="total"
        :page-sizes="[10, 20, 50]"
        layout="total, sizes, prev, pager, next"
        class="pager"
        @current-change="loadList"
        @size-change="search"
      />
    </div>

    <el-drawer
      v-model="drawer.visible"
      title="周报详情"
      size="min(1180px, 94vw)"
      class="weekly-drawer"
      :close-on-click-modal="false"
      destroy-on-close
    >
      <div v-loading="drawer.loading" class="weekly-detail">
        <div v-if="current" class="detail-head">
          <div class="head-line">
            <h3 class="detail-title">{{ current.title }}</h3>
            <span v-if="stats.dateFrom" class="period">{{ stats.dateFrom }} ~ {{ stats.dateTo }}</span>
          </div>
          <div class="meta-row">
            <el-tag size="small" effect="plain">{{ current.weekLabel }}</el-tag>
            <el-tag size="small" effect="plain">
              {{ current.scope === 'PROJECT' ? current.projectName : '个人周总结' }}
            </el-tag>
            <el-tag :type="current.status === 'CONFIRMED' ? 'success' : 'warning'" size="small">
              {{ STATUS_LABEL[current.status] || current.status }}
            </el-tag>
            <el-tag size="small" type="info" effect="plain">
              {{ SOURCE_LABEL[current.source] || current.source }}
            </el-tag>
            <el-tag size="small" type="info" effect="plain">v{{ current.revision }}</el-tag>
            <span v-if="current.confirmTime" class="meta-text">
              {{ current.confirmName }} 于 {{ current.confirmTime }} 确认
            </span>
          </div>

          <el-alert
            v-if="!current.aiUsed"
            type="warning"
            :closable="false"
            show-icon
            :title="current.aiMessage || 'AI 生成不可用，已降级为数据模板，请人工补充'"
            class="ai-alert"
          />

          <div v-if="stats.totalHours !== undefined" class="stats-row">
            <div class="stat">
              <span class="stat-label">日志</span>
              <span class="stat-value"><b>{{ stats.logCount ?? 0 }}</b> 条</span>
            </div>
            <div class="stat">
              <span class="stat-label">工时</span>
              <span class="stat-value"><b>{{ stats.totalHours ?? 0 }}</b> h</span>
            </div>
            <div v-if="current.scope === 'PROJECT'" class="stat">
              <span class="stat-label">参与人</span>
              <span class="stat-value"><b>{{ stats.memberCount ?? 0 }}</b> 人</span>
            </div>
            <div class="stat">
              <span class="stat-label">问题 / 风险</span>
              <span class="stat-value"><b>{{ stats.riskLogCount ?? 0 }}</b> 条</span>
            </div>
          </div>

          <div v-if="stats.byProject?.length" class="project-row">
            <span v-for="item in stats.byProject.slice(0, 8)" :key="item.name" class="project-chip">
              {{ item.name }} · {{ item.hours }}h
            </span>
          </div>
        </div>

        <div class="detail-body">
          <template v-if="editing">
            <el-input v-model="form.title" maxlength="200" show-word-limit class="edit-title" />
            <el-input
              v-model="form.content"
              type="textarea"
              :rows="22"
              resize="vertical"
              placeholder="周报正文（支持 Markdown）"
            />
          </template>
          <div v-else class="markdown-body" v-html="rendered"></div>
        </div>
      </div>

      <template #footer>
        <div class="drawer-footer">
          <el-button @click="drawer.visible = false">关闭</el-button>
          <span class="spacer"></span>
          <el-button :loading="generating" @click="regenerate">重新生成</el-button>
          <el-button v-if="canEdit" @click="toggleEdit">{{ editing ? '取消编辑' : '编辑' }}</el-button>
          <el-button v-if="editing" type="primary" :loading="saving" @click="save">保存修改</el-button>
          <el-button v-if="canEdit" type="primary" :loading="confirming" @click="confirm">确认周报</el-button>
        </div>
      </template>
    </el-drawer>

    <!-- 生成前的依据日志：先核对数据，再点生成 -->
    <el-drawer
      v-model="preview.visible"
      :title="
        preview.data
          ? `依据日志 · ${preview.data.projectName} · ${preview.data.weekLabel}`
          : '依据日志'
      "
      size="min(1280px, 96vw)"
      class="weekly-drawer"
      :close-on-click-modal="false"
      destroy-on-close
    >
      <div v-loading="preview.loading" class="preview-body">
        <template v-if="preview.data">
          <div class="preview-head">
            <el-tag size="small" effect="plain">{{ preview.data.projectName }}</el-tag>
            <el-tag size="small" effect="plain">{{ preview.data.weekLabel }}</el-tag>
            <span class="preview-range">{{ preview.data.dateFrom }} ~ {{ preview.data.dateTo }}</span>
          </div>

          <div class="stats-row">
            <div class="stat">
              <span class="stat-label">日志</span>
              <span class="stat-value"><b>{{ preview.data.logCount }}</b> 条</span>
            </div>
            <div class="stat">
              <span class="stat-label">工时</span>
              <span class="stat-value"><b>{{ preview.data.totalHours }}</b> h</span>
            </div>
            <div class="stat">
              <span class="stat-label">参与人</span>
              <span class="stat-value"><b>{{ preview.data.memberCount }}</b> 人</span>
            </div>
            <div class="stat">
              <span class="stat-label">问题 / 风险</span>
              <span class="stat-value"><b>{{ preview.data.riskLogCount }}</b> 条</span>
            </div>
          </div>

          <el-alert
            type="info"
            :closable="false"
            show-icon
            class="preview-tip"
            title="只统计已生效日志（提交 / 待确认 / 已确认），草稿与已驳回不计入；多项目日志按本项目的明细工时统计。"
          />

          <el-table :data="preview.data.entries" size="small" max-height="56vh">
            <el-table-column label="日期" width="104" prop="date" />
            <el-table-column label="提交人" width="120" prop="user" show-overflow-tooltip />
            <el-table-column label="工时" width="80" align="right">
              <template #default="{ row }">{{ row.hours }}h</template>
            </el-table-column>
            <el-table-column label="工作内容" min-width="220" show-overflow-tooltip>
              <template #default="{ row }">
                <el-tag
                  v-if="row.relatedProjects?.length"
                  size="small"
                  type="warning"
                  effect="plain"
                  class="rel-tag"
                  :title="`同一条日志还涉及：${row.relatedProjects.join('、')}`"
                >
                  涉 {{ row.relatedProjects.length + 1 }} 项目
                </el-tag>
                {{ row.content || '—' }}
              </template>
            </el-table-column>
            <el-table-column label="问题与阻塞" min-width="160" show-overflow-tooltip>
              <template #default="{ row }">{{ row.problem || '—' }}</template>
            </el-table-column>
            <el-table-column label="明日计划" min-width="160" show-overflow-tooltip>
              <template #default="{ row }">{{ row.plan || '—' }}</template>
            </el-table-column>
            <template #empty>
              <el-empty
                description="该周没有已生效日志，生成会得到纯数据模板"
                :image-size="64"
              />
            </template>
          </el-table>
        </template>
      </div>

      <template #footer>
        <div class="drawer-footer">
          <el-button @click="preview.visible = false">关闭</el-button>
          <span class="spacer"></span>
          <span v-if="!canGenerate" class="gen-hint">仅该项目的项目经理 / PMO 可生成</span>
          <el-button
            v-else
            type="primary"
            :icon="Sparkles"
            :loading="generating"
            @click="generateFromPreview"
          >
            生成周报
          </el-button>
        </div>
      </template>
    </el-drawer>
  </div>
</template>

<style scoped>
.head-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
  margin-bottom: 12px;
}

.head-main {
  display: flex;
  align-items: center;
  gap: 12px;
}

.head-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  border-radius: 10px;
  background: var(--pms-primary-weak, #eef2ff);
  color: var(--pms-primary-deep, #4338ca);
}

.head-main h2 {
  margin: 0;
  font-size: 17px;
  font-weight: 600;
}

.head-main p {
  margin: 4px 0 0;
  font-size: 12px;
  color: var(--pms-text-3, #8b93a7);
}

.head-tags {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  margin: 4px 0 12px;
}

.spacer {
  flex: 1;
}

/* 生成按钮置灰的原因直接写出来，避免用户以为按钮坏了 */
.gen-hint {
  font-size: 12px;
  color: var(--pms-text-3, #8b93a7);
}

.hint {
  font-size: 12px;
  color: var(--pms-text-3, #8b93a7);
}

.title-link {
  font-weight: 500;
  text-align: left;
}

.source-text em {
  font-style: normal;
  color: var(--pms-warn, #d68a12);
}

.pager {
  margin-top: 12px;
  justify-content: flex-end;
}

/* ---------------- 周报详情抽屉（teleport 到 body，需全局选择器） ---------------- */
:global(.weekly-drawer .el-drawer__header) {
  margin-bottom: 0;
  padding: 18px 28px;
  border-bottom: 1px solid var(--pms-line, #e8edf6);
  font-size: 15px;
  font-weight: 600;
  color: var(--pms-text, #111827);
}

:global(.weekly-drawer .el-drawer__body) {
  padding: 0;
  background: var(--pms-bg, #f7f8fb);
}

:global(.weekly-drawer .el-drawer__footer) {
  padding: 12px 28px;
  border-top: 1px solid var(--pms-line, #e8edf6);
  background: #fff;
}

.weekly-detail {
  display: flex;
  flex-direction: column;
  gap: 14px;
  max-width: 1080px;
  margin: 0 auto;
  padding: 20px 32px 24px;
}

.detail-head {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 18px 22px;
  border: 1px solid var(--pms-line, #e8edf6);
  border-radius: 12px;
  background: #fff;
}

.head-line {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.detail-title {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
  line-height: 1.5;
  color: var(--pms-text, #111827);
}

.period {
  flex-shrink: 0;
  padding-top: 2px;
  font-size: 12px;
  color: var(--pms-text-3, #8b93a7);
}

.meta-row {
  display: flex;
  align-items: center;
  gap: 8px;
  row-gap: 8px;
  flex-wrap: wrap;
}

.meta-text {
  font-size: 12px;
  color: var(--pms-text-3, #8b93a7);
}

.stats-row {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
  gap: 10px;
}

/* 依据日志预览（全局把 drawer body 的 padding 归零了，这里补回来） */
.preview-body {
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding: 20px 28px;
}

.preview-head {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}

.preview-range {
  font-size: 12.5px;
  color: var(--pms-text-3, #8b93a7);
  font-variant-numeric: tabular-nums;
}

.preview-tip {
  margin: 0;
}

/* 多项目日志标记：提醒 PM 生成前核对是否串项 */
.rel-tag {
  margin-right: 6px;
}

.stat {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 10px 14px;
  border-radius: 10px;
  background: var(--pms-bg, #f4f6fa);
}

.stat-label {
  font-size: 11px;
  color: var(--pms-text-3, #8b93a7);
}

.stat-value {
  font-size: 12px;
  color: var(--pms-text-2, #4b5563);
}

.stat-value b {
  margin-right: 2px;
  font-size: 18px;
  font-weight: 600;
  color: var(--pms-text, #111827);
}

.project-row {
  display: flex;
  gap: 8px;
  row-gap: 8px;
  flex-wrap: wrap;
}

.project-chip {
  padding: 3px 12px;
  font-size: 12px;
  border-radius: 999px;
  background: var(--pms-bg, #f4f6fa);
  color: var(--pms-text-2, #4b5563);
}

.detail-body {
  padding: 10px 30px 26px;
  border: 1px solid var(--pms-line, #e8edf6);
  border-radius: 12px;
  background: #fff;
}

.edit-title {
  margin: 8px 0 10px;
}

.markdown-body {
  max-width: 960px;
  font-size: 13.5px;
  line-height: 1.95;
  color: var(--pms-text, #111827);
  word-break: break-word;
  overflow-wrap: anywhere;
}

.markdown-body :deep(h2),
.markdown-body :deep(h3),
.markdown-body :deep(h4) {
  margin: 24px 0 10px;
  padding-left: 10px;
  border-left: 3px solid var(--pms-primary, #4f46e5);
  font-size: 14.5px;
  font-weight: 600;
  line-height: 1.6;
  color: var(--pms-text, #111827);
}

.markdown-body :deep(h2:first-child),
.markdown-body :deep(h3:first-child) {
  margin-top: 12px;
}

.markdown-body :deep(p) {
  margin: 8px 0;
}

.markdown-body :deep(ul),
.markdown-body :deep(ol) {
  margin: 8px 0;
  padding-left: 22px;
}

.markdown-body :deep(li) {
  margin: 5px 0;
}

.markdown-body :deep(li::marker) {
  color: var(--pms-primary, #4f46e5);
}

.markdown-body :deep(blockquote) {
  margin: 10px 0;
  padding: 8px 14px;
  border-left: 3px solid var(--pms-primary, #4f46e5);
  border-radius: 0 8px 8px 0;
  background: var(--pms-bg, #f4f6fa);
  color: var(--pms-text-2, #4b5563);
  font-size: 12.5px;
}

.drawer-footer {
  display: flex;
  align-items: center;
  gap: 8px;
}
</style>
