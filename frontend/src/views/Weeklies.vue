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
  type WeeklyItem,
  type WeeklyOptions
} from '@/api'

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

const escapeHtml = (text: string) =>
  text.replace(/[&<>"']/g, (char) => {
    const map: Record<string, string> = {
      '&': '&amp;',
      '<': '&lt;',
      '>': '&gt;',
      '"': '&quot;',
      "'": '&#39;'
    }
    return map[char] ?? char
  })

/** 极简 Markdown 渲染（标题 / 有序无序列表 / 引用 / 加粗），先转义再格式化，避免 XSS。 */
const renderMarkdown = (raw: string) => {
  const lines = escapeHtml(raw || '').split(/\r?\n/)
  const html: string[] = []
  let listTag: 'ul' | 'ol' | '' = ''
  const closeList = () => {
    if (listTag) {
      html.push(`</${listTag}>`)
      listTag = ''
    }
  }
  const openList = (tag: 'ul' | 'ol') => {
    if (listTag !== tag) {
      closeList()
      html.push(`<${tag}>`)
      listTag = tag
    }
  }
  for (const line of lines) {
    const text = line.replace(/\*\*(.+?)\*\*/g, '<b>$1</b>')
    if (!text.trim()) {
      closeList()
      continue
    }
    const heading = /^(#{1,4})\s+(.*)$/.exec(text)
    if (heading) {
      closeList()
      const level = Math.min(heading[1].length + 1, 5)
      html.push(`<h${level}>${heading[2]}</h${level}>`)
      continue
    }
    if (/^\s*\d+[.、)]\s+/.test(text)) {
      openList('ol')
      html.push(`<li>${text.replace(/^\s*\d+[.、)]\s+/, '')}</li>`)
      continue
    }
    if (/^\s*[-*]\s+/.test(text)) {
      openList('ul')
      html.push(`<li>${text.replace(/^\s*[-*]\s+/, '')}</li>`)
      continue
    }
    if (/^&gt;\s?/.test(text)) {
      closeList()
      html.push(`<blockquote>${text.replace(/^&gt;\s?/, '')}</blockquote>`)
      continue
    }
    closeList()
    html.push(`<p>${text}</p>`)
  }
  closeList()
  return html.join('')
}

/** 正文去掉首行一级标题（标题已在详情头部展示，避免重复）。 */
const bodyText = computed(() => (current.value?.content || '').replace(/^\s*#\s+.*(?:\r?\n)+/, ''))
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

const generateProject = async () => {
  if (!projectFilters.projectId) {
    ElMessage.warning('请先选择项目')
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

const generatePersonal = async () => {
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
  if (current.value.status === 'CONFIRMED') {
    try {
      await ElMessageBox.confirm(
        '重新生成会覆盖已确认的正文并回到「待确认」，需要重新确认。继续？',
        '重新生成',
        { type: 'warning', confirmButtonText: '重新生成', cancelButtonText: '取消' }
      )
    } catch {
      return
    }
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
        <el-tab-pane label="项目周报" name="project">
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
              @change="search"
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
                :label="`${item.projectName}（${item.projectCode}）`"
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
            <el-tooltip content="为所选项目生成本周周报（项目经理）" placement="top">
              <el-button
                type="primary"
                :icon="Sparkles"
                :loading="generating"
                :disabled="!projectFilters.projectId"
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
              @change="search"
            />
            <span class="hint">不限周五，任意时间都可生成本周总结；想补写上周也可切换周次</span>
            <span class="spacer"></span>
            <el-button :icon="RefreshCw" circle :loading="loading" aria-label="刷新" @click="loadList" />
            <el-button type="primary" :icon="Sparkles" :loading="generating" @click="generatePersonal">
              生成我的周总结
            </el-button>
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
