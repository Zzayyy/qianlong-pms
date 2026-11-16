<script setup lang="ts">
/**
 * 轻量富文本编辑器（邮件正文 / 邮件模板共用）。
 *
 * 只依赖浏览器原生 execCommand，不引入第三方面板库，体积小且产出的是
 * 邮件客户端普遍支持的 HTML（font / span / ul / ol / blockquote / pre）。
 * 工具栏交互全部使用 mousedown.prevent，保证点击按钮时编辑区不丢失选区。
 */
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { Link as LinkIcon, Minus, RefreshLeft, RefreshRight } from '@element-plus/icons-vue'

const props = withDefaults(
  defineProps<{
    modelValue: string
    placeholder?: string
    disabled?: boolean
    minHeight?: number
  }>(),
  { placeholder: '请输入正文…', disabled: false, minHeight: 320 }
)

const emit = defineEmits<{
  'update:modelValue': [value: string]
  change: [value: string]
}>()

const editorRef = ref<HTMLDivElement | null>(null)
const savedRange = ref<Range | null>(null)

const fmt = reactive({
  bold: false,
  italic: false,
  underline: false,
  strike: false,
  ordered: false,
  unordered: false
})

const fontFamily = ref('')
const fontSize = ref('2')
const textColor = ref('#16233d')
const highlight = ref('#fff1a8')

const FONT_FAMILIES = [
  { label: '默认字体', value: '' },
  { label: '微软雅黑', value: "'Microsoft YaHei', sans-serif" },
  { label: '宋体', value: 'SimSun, serif' },
  { label: '黑体', value: "SimHei, 'Microsoft YaHei', sans-serif" },
  { label: '楷体', value: 'KaiTi, serif' },
  { label: 'Arial', value: 'Arial, Helvetica, sans-serif' },
  { label: 'Times New Roman', value: "'Times New Roman', Times, serif" },
  { label: 'Courier New', value: "'Courier New', monospace" }
]

const FONT_SIZES = [
  { label: '12px', value: '1' },
  { label: '14px', value: '2' },
  { label: '16px', value: '3' },
  { label: '18px', value: '4' },
  { label: '24px', value: '5' },
  { label: '32px', value: '6' },
  { label: '48px', value: '7' }
]

const TEXT_COLORS = [
  '#16233d',
  '#5b6779',
  '#8b95a8',
  '#cf3f3f',
  '#d68a12',
  '#2f9e5f',
  '#3370ff',
  '#7a4fd8'
]

const HIGHLIGHT_COLORS = ['#fff1a8', '#d8f5df', '#dbe9ff', '#ffe0e0', '#f0e6ff', '#e9edf5']

const LINE_HEIGHTS = ['1.5', '1.75', '2', '2.5']
const ALIGNS = [
  { label: '左对齐', value: 'justifyLeft' },
  { label: '居中', value: 'justifyCenter' },
  { label: '右对齐', value: 'justifyRight' },
  { label: '两端对齐', value: 'justifyFull' }
]

const isEmpty = computed(
  () => !props.modelValue.replace(/<[^>]*>/g, '').replace(/&nbsp;/gi, ' ').trim()
)

const textLength = computed(() =>
  props.modelValue
    .replace(/<[^>]*>/g, '')
    .replace(/&nbsp;/gi, ' ')
    .trim().length
)

const syncValue = () => {
  const html = editorRef.value?.innerHTML ?? ''
  emit('update:modelValue', html)
  emit('change', html)
}

/* ------------------------------ 选区管理 ------------------------------ */

const saveRange = () => {
  const selection = window.getSelection()
  if (!selection || !selection.rangeCount) return
  const range = selection.getRangeAt(0)
  if (editorRef.value?.contains(range.commonAncestorContainer)) {
    savedRange.value = range.cloneRange()
  }
}

const restoreRange = () => {
  editorRef.value?.focus()
  const range = savedRange.value
  if (!range) return
  const selection = window.getSelection()
  selection?.removeAllRanges()
  selection?.addRange(range)
}

const queryState = () => {
  if (!editorRef.value) return
  try {
    fmt.bold = document.queryCommandState('bold')
    fmt.italic = document.queryCommandState('italic')
    fmt.underline = document.queryCommandState('underline')
    fmt.strike = document.queryCommandState('strikeThrough')
    fmt.ordered = document.queryCommandState('insertOrderedList')
    fmt.unordered = document.queryCommandState('insertUnorderedList')
  } catch {
    /* 个别浏览器在无选区时会抛错，忽略即可 */
  }
}

const onSelectionChange = () => {
  const selection = window.getSelection()
  if (!selection || !selection.rangeCount) return
  if (!editorRef.value?.contains(selection.getRangeAt(0).commonAncestorContainer)) return
  saveRange()
  queryState()
}

/* ------------------------------ 命令执行 ------------------------------ */

const exec = (command: string, value = '') => {
  if (props.disabled) return
  restoreRange()
  document.execCommand('styleWithCSS', false, 'true')
  document.execCommand(command, false, value)
  saveRange()
  syncValue()
  queryState()
}

const applyFontFamily = (value: string) => {
  exec('fontFamily', value || 'inherit')
}

const applyFontSize = (value: string) => {
  exec('fontSize', value)
}

const applyTextColor = (color: string) => {
  textColor.value = color
  exec('foreColor', color)
}

const applyHighlight = (color: string) => {
  highlight.value = color
  exec('hiliteColor', color)
}

const applyBlock = (tag: string) => {
  exec('formatBlock', tag)
}

const applyLineHeight = (value: string) => {
  if (props.disabled) return
  restoreRange()
  const selection = window.getSelection()
  if (!selection || !selection.rangeCount) return
  const node = selection.getRangeAt(0).startContainer
  const element = node.nodeType === 1 ? (node as HTMLElement) : node.parentElement
  const block = element?.closest('p,div,li,h1,h2,h3,h4,blockquote,pre')
  if (block && editorRef.value?.contains(block)) {
    ;(block as HTMLElement).style.lineHeight = value
  } else {
    // 根节点直接排版时先包一层段落，再设置行高
    document.execCommand('formatBlock', false, 'p')
    const host = window.getSelection()?.anchorNode
    const target = host?.nodeType === 1 ? (host as HTMLElement) : host?.parentElement
    const created = target?.closest('p')
    if (created) (created as HTMLElement).style.lineHeight = value
  }
  syncValue()
}

const clearFormat = () => {
  if (props.disabled) return
  restoreRange()
  document.execCommand('styleWithCSS', false, 'true')
  document.execCommand('removeFormat', false, '')
  document.execCommand('formatBlock', false, 'p')
  document.execCommand('unlink', false, '')
  syncValue()
}

const insertHtml = (html: string) => {
  if (props.disabled || !html) return
  restoreRange()
  document.execCommand('insertHTML', false, html)
  saveRange()
  syncValue()
}

const escapeHtml = (text: string) =>
  text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')

/* ------------------------------ 插入链接 ------------------------------ */

const linkVisible = ref(false)
const linkForm = reactive({ text: '', url: '' })

const openLink = () => {
  if (props.disabled) return
  const selection = window.getSelection()
  linkForm.text = selection?.toString().slice(0, 80) || ''
  linkForm.url = ''
  linkVisible.value = true
}

const confirmLink = () => {
  const url = linkForm.url.trim()
  if (!url) return
  const text = linkForm.text.trim() || url
  insertHtml(
    `<a href="${escapeHtml(url)}" target="_blank" rel="noopener">${escapeHtml(text)}</a>`
  )
  linkVisible.value = false
}

/* ------------------------------ 粘贴净化 ------------------------------ */

const sanitize = (raw: string) => {
  const doc = new DOMParser().parseFromString(raw, 'text/html')
  doc
    .querySelectorAll('script,style,iframe,object,embed,meta,link,form,input,button')
    .forEach((node) => node.remove())
  doc.querySelectorAll('*').forEach((element) => {
    Array.from(element.attributes).forEach((attr) => {
      const name = attr.name.toLowerCase()
      if (name.startsWith('on')) {
        element.removeAttribute(attr.name)
        return
      }
      if ((name === 'href' || name === 'src') && /^\s*(javascript|vbscript):/i.test(attr.value)) {
        element.removeAttribute(attr.name)
        return
      }
      // 粘贴进来的内联图片（data:）体积巨大，邮件通道不支持，一律丢弃
      if (name === 'src' && /^data:/i.test(attr.value)) {
        element.removeAttribute(attr.name)
      }
    })
  })
  doc.querySelectorAll('img').forEach((img) => {
    if (!img.getAttribute('src')) img.remove()
  })
  return doc.body.innerHTML
}

const onPaste = (event: ClipboardEvent) => {
  if (props.disabled) return
  const data = event.clipboardData
  if (!data) return
  const rich = data.getData('text/html')
  event.preventDefault()
  if (rich) {
    document.execCommand('insertHTML', false, sanitize(rich))
  } else {
    const plain = data.getData('text/plain')
    if (!plain) return
    document.execCommand('insertHTML', false, escapeHtml(plain).replace(/\n/g, '<br>'))
  }
  saveRange()
  syncValue()
}

const onInput = () => {
  saveRange()
  syncValue()
}

const onKeydown = (event: KeyboardEvent) => {
  // Tab 默认会把焦点移出编辑区，这里改为插入四个空格
  if (event.key === 'Tab') {
    event.preventDefault()
    document.execCommand('insertHTML', false, '&nbsp;&nbsp;&nbsp;&nbsp;')
    syncValue()
  }
}

/* ------------------------------ 对外方法 ------------------------------ */

const getHtml = () => editorRef.value?.innerHTML ?? ''
const getText = () => editorRef.value?.innerText ?? ''
const focus = () => editorRef.value?.focus()
const clear = () => {
  if (editorRef.value) editorRef.value.innerHTML = ''
  syncValue()
}

defineExpose({ getHtml, getText, focus, clear, insertHtml })

/* ------------------------------ 生命周期 ------------------------------ */

watch(
  () => props.modelValue,
  (value) => {
    const element = editorRef.value
    if (!element) return
    if ((value || '') !== element.innerHTML) {
      element.innerHTML = value || ''
    }
  }
)

onMounted(() => {
  if (editorRef.value) editorRef.value.innerHTML = props.modelValue || ''
  document.addEventListener('selectionchange', onSelectionChange)
})

onBeforeUnmount(() => {
  document.removeEventListener('selectionchange', onSelectionChange)
})
</script>

<template>
  <div class="mail-editor" :class="{ 'is-disabled': disabled }">
    <div class="me-toolbar" @mousedown.prevent>
      <button
        type="button"
        class="me-btn glyph sm"
        title="清除格式"
        :disabled="disabled"
        @mousedown.prevent="clearFormat"
      >
        Tx
      </button>

      <span class="me-sep" />

      <el-select
        v-model="fontFamily"
        size="small"
        class="me-select me-font"
        :disabled="disabled"
        placeholder="默认字体"
        @change="applyFontFamily"
      >
        <el-option v-for="item in FONT_FAMILIES" :key="item.label" :label="item.label" :value="item.value" />
      </el-select>
      <el-select
        v-model="fontSize"
        size="small"
        class="me-select me-size"
        :disabled="disabled"
        placeholder="字号"
        @change="applyFontSize"
      >
        <el-option v-for="item in FONT_SIZES" :key="item.value" :label="item.label" :value="item.value" />
      </el-select>

      <span class="me-sep" />

      <button
        type="button"
        class="me-btn glyph bold"
        title="加粗（Ctrl+B）"
        :class="{ active: fmt.bold }"
        :disabled="disabled"
        @mousedown.prevent="exec('bold')"
      >
        B
      </button>
      <button
        type="button"
        class="me-btn glyph italic"
        title="斜体（Ctrl+I）"
        :class="{ active: fmt.italic }"
        :disabled="disabled"
        @mousedown.prevent="exec('italic')"
      >
        I
      </button>
      <button
        type="button"
        class="me-btn glyph underline"
        title="下划线（Ctrl+U）"
        :class="{ active: fmt.underline }"
        :disabled="disabled"
        @mousedown.prevent="exec('underline')"
      >
        U
      </button>
      <button
        type="button"
        class="me-btn glyph strike"
        title="删除线"
        :class="{ active: fmt.strike }"
        :disabled="disabled"
        @mousedown.prevent="exec('strikeThrough')"
      >
        S
      </button>

      <el-popover placement="bottom-start" :width="188" trigger="click" :disabled="disabled">
        <template #reference>
          <button type="button" class="me-btn glyph color" title="字体颜色" :disabled="disabled">
            <span>A</span>
            <i class="color-bar" :style="{ background: textColor }" />
          </button>
        </template>
        <div class="me-palette">
          <button
            v-for="color in TEXT_COLORS"
            :key="color"
            type="button"
            class="swatch"
            :style="{ background: color }"
            :title="color"
            @mousedown.prevent="applyTextColor(color)"
          />
        </div>
      </el-popover>

      <el-popover placement="bottom-start" :width="188" trigger="click" :disabled="disabled">
        <template #reference>
          <button type="button" class="me-btn glyph highlight" title="背景色" :disabled="disabled">
            <span class="marker" />
            <i class="color-bar" :style="{ background: highlight }" />
          </button>
        </template>
        <div class="me-palette">
          <button
            v-for="color in HIGHLIGHT_COLORS"
            :key="color"
            type="button"
            class="swatch"
            :style="{ background: color }"
            :title="color"
            @mousedown.prevent="applyHighlight(color)"
          />
        </div>
      </el-popover>

      <span class="me-sep" />

      <button
        type="button"
        class="me-btn"
        title="无序列表"
        :class="{ active: fmt.unordered }"
        :disabled="disabled"
        @mousedown.prevent="exec('insertUnorderedList')"
      >
        <svg viewBox="0 0 16 16" width="15" height="15" fill="currentColor">
          <circle cx="2.4" cy="4" r="1.3" />
          <circle cx="2.4" cy="8" r="1.3" />
          <circle cx="2.4" cy="12" r="1.3" />
          <rect x="6" y="3.2" width="9" height="1.5" rx="0.75" />
          <rect x="6" y="7.2" width="9" height="1.5" rx="0.75" />
          <rect x="6" y="11.2" width="9" height="1.5" rx="0.75" />
        </svg>
      </button>
      <button
        type="button"
        class="me-btn"
        title="有序列表"
        :class="{ active: fmt.ordered }"
        :disabled="disabled"
        @mousedown.prevent="exec('insertOrderedList')"
      >
        <svg viewBox="0 0 16 16" width="15" height="15" fill="currentColor">
          <text x="0" y="5.4" font-size="5" font-family="Arial">1</text>
          <text x="0" y="9.6" font-size="5" font-family="Arial">2</text>
          <text x="0" y="13.8" font-size="5" font-family="Arial">3</text>
          <rect x="6" y="3.4" width="9" height="1.5" rx="0.75" />
          <rect x="6" y="7.6" width="9" height="1.5" rx="0.75" />
          <rect x="6" y="11.8" width="9" height="1.5" rx="0.75" />
        </svg>
      </button>
      <button
        type="button"
        class="me-btn"
        title="减少缩进"
        :disabled="disabled"
        @mousedown.prevent="exec('outdent')"
      >
        <svg viewBox="0 0 16 16" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.4">
          <path d="M6.5 3.5h8M6.5 8h8M6.5 12.5h8" />
          <path d="M4 5.5 1.5 8 4 10.5" />
        </svg>
      </button>
      <button
        type="button"
        class="me-btn"
        title="增加缩进"
        :disabled="disabled"
        @mousedown.prevent="exec('indent')"
      >
        <svg viewBox="0 0 16 16" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.4">
          <path d="M6.5 3.5h8M6.5 8h8M6.5 12.5h8" />
          <path d="M1.5 5.5 4 8l-2.5 2.5" />
        </svg>
      </button>

      <span class="me-sep" />

      <el-popover placement="bottom-start" :width="132" trigger="click" :disabled="disabled">
        <template #reference>
          <button type="button" class="me-btn" title="对齐方式" :disabled="disabled">
            <svg viewBox="0 0 16 16" width="15" height="15" fill="currentColor">
              <rect x="2" y="3" width="12" height="1.5" rx="0.75" />
              <rect x="2" y="7.2" width="8" height="1.5" rx="0.75" />
              <rect x="2" y="11.4" width="12" height="1.5" rx="0.75" />
            </svg>
          </button>
        </template>
        <div class="me-menu">
          <button
            v-for="item in ALIGNS"
            :key="item.value"
            type="button"
            class="me-menu-item"
            @mousedown.prevent="exec(item.value)"
          >
            {{ item.label }}
          </button>
        </div>
      </el-popover>

      <el-popover placement="bottom-start" :width="112" trigger="click" :disabled="disabled">
        <template #reference>
          <button type="button" class="me-btn" title="行高" :disabled="disabled">
            <svg viewBox="0 0 16 16" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.4">
              <path d="M2 4h8M2 8h12M2 12h8" />
              <path d="M13.5 2.5v11" stroke-dasharray="2 2" />
            </svg>
          </button>
        </template>
        <div class="me-menu">
          <button
            v-for="value in LINE_HEIGHTS"
            :key="value"
            type="button"
            class="me-menu-item"
            @mousedown.prevent="applyLineHeight(value)"
          >
            {{ value }} 倍
          </button>
        </div>
      </el-popover>

      <button
        type="button"
        class="me-btn glyph"
        title="引用"
        :disabled="disabled"
        @mousedown.prevent="applyBlock('blockquote')"
      >
        “
      </button>
      <button
        type="button"
        class="me-btn glyph sm"
        title="代码块"
        :disabled="disabled"
        @mousedown.prevent="applyBlock('pre')"
      >
        &lt;/&gt;
      </button>

      <span class="me-sep" />

      <button type="button" class="me-btn" title="插入链接" :disabled="disabled" @mousedown.prevent="openLink">
        <el-icon :size="15"><LinkIcon /></el-icon>
      </button>
      <button
        type="button"
        class="me-btn"
        title="插入分隔线"
        :disabled="disabled"
        @mousedown.prevent="insertHtml('<hr>')"
      >
        <el-icon :size="15"><Minus /></el-icon>
      </button>

      <span class="me-sep" />

      <button type="button" class="me-btn" title="撤销" :disabled="disabled" @mousedown.prevent="exec('undo')">
        <el-icon :size="15"><RefreshLeft /></el-icon>
      </button>
      <button type="button" class="me-btn" title="重做" :disabled="disabled" @mousedown.prevent="exec('redo')">
        <el-icon :size="15"><RefreshRight /></el-icon>
      </button>
    </div>

    <div
      ref="editorRef"
      class="me-body"
      :class="{ 'is-empty': isEmpty }"
      :style="{ minHeight: `${minHeight}px` }"
      :contenteditable="!disabled"
      :data-placeholder="placeholder"
      spellcheck="false"
      @input="onInput"
      @paste="onPaste"
      @keydown="onKeydown"
      @mouseup="saveRange"
      @keyup="saveRange"
      @blur="saveRange"
    />

    <el-dialog v-model="linkVisible" title="插入链接" width="min(440px, 92vw)" append-to-body>
      <el-form label-width="64px">
        <el-form-item label="显示文字">
          <el-input v-model="linkForm.text" maxlength="80" placeholder="留空则直接显示链接地址" />
        </el-form-item>
        <el-form-item label="链接地址">
          <el-input v-model="linkForm.url" placeholder="https://" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="linkVisible = false">取消</el-button>
        <el-button type="primary" :disabled="!linkForm.url.trim()" @click="confirmLink">插入</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.mail-editor {
  border: 1px solid var(--pms-line);
  border-radius: 10px;
  background: var(--pms-surface);
  overflow: hidden;
}

.mail-editor.is-disabled {
  background: #fafbfe;
}

.me-toolbar {
  display: flex;
  align-items: center;
  gap: 2px;
  flex-wrap: wrap;
  padding: 5px 8px;
  background: #f7f9fd;
  border-bottom: 1px solid var(--pms-line);
}

.me-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  padding: 0;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: var(--pms-text-2);
  font-size: 14px;
  line-height: 1;
  cursor: pointer;
  transition: background-color 0.15s ease, color 0.15s ease;
}

.me-btn:hover {
  background: #eaeff9;
  color: var(--pms-text);
}

.me-btn.active {
  background: #e2ecff;
  color: var(--pms-primary-deep);
}

.me-btn:disabled {
  color: #c2cad8;
  cursor: not-allowed;
  background: transparent;
}

.me-btn.glyph {
  font-family: 'Times New Roman', 'Microsoft YaHei', serif;
  font-size: 15px;
  font-weight: 600;
}

.me-btn.glyph.sm {
  font-family: 'Microsoft YaHei', sans-serif;
  font-size: 12px;
  font-weight: 500;
}

.me-btn.glyph.italic {
  font-style: italic;
}

.me-btn.glyph.underline {
  text-decoration: underline;
}

.me-btn.glyph.strike {
  text-decoration: line-through;
}

.me-btn.glyph.color,
.me-btn.glyph.highlight {
  position: relative;
  flex-direction: column;
  gap: 1px;
  font-size: 13px;
}

.me-btn.glyph.color .color-bar,
.me-btn.glyph.highlight .color-bar {
  display: block;
  width: 15px;
  height: 3px;
  border-radius: 2px;
}

.me-btn.glyph.highlight .marker {
  width: 13px;
  height: 9px;
  border: 1.5px solid currentColor;
  border-radius: 2px;
}

.me-sep {
  width: 1px;
  height: 16px;
  margin: 0 5px;
  background: #dde5f2;
}

.me-select {
  flex: 0 0 auto;
}

.me-font {
  width: 104px;
}

.me-size {
  width: 76px;
}

.me-body {
  padding: 14px 16px;
  font-size: 14px;
  line-height: 1.75;
  color: var(--pms-text);
  outline: none;
  overflow-y: auto;
  max-height: 60vh;
}

.me-body:focus {
  box-shadow: inset 0 0 0 1px var(--el-color-primary-light-7);
}

.me-body.is-empty::before {
  content: attr(data-placeholder);
  color: var(--pms-text-3);
  pointer-events: none;
}

.me-body :deep(p) {
  margin: 0 0 0.6em;
}

.me-body :deep(p:last-child) {
  margin-bottom: 0;
}

.me-body :deep(ul),
.me-body :deep(ol) {
  margin: 0.3em 0 0.6em;
  padding-left: 1.6em;
}

.me-body :deep(li) {
  margin: 0.15em 0;
}

.me-body :deep(blockquote) {
  margin: 0.5em 0;
  padding: 2px 0 2px 12px;
  border-left: 3px solid #d5e3ff;
  color: var(--pms-text-2);
}

.me-body :deep(pre) {
  margin: 0.5em 0;
  padding: 10px 12px;
  background: #f6f8fc;
  border: 1px solid var(--pms-line);
  border-radius: 8px;
  font-family: 'Courier New', Consolas, monospace;
  font-size: 13px;
  white-space: pre-wrap;
}

.me-body :deep(hr) {
  margin: 12px 0;
  border: 0;
  border-top: 1px solid var(--pms-line);
}

.me-body :deep(a) {
  color: var(--pms-primary);
  text-decoration: underline;
  word-break: break-all;
}

.me-body :deep(img) {
  max-width: 100%;
}

.me-palette {
  display: grid;
  grid-template-columns: repeat(8, 1fr);
  gap: 6px;
}

.swatch {
  width: 16px;
  height: 16px;
  padding: 0;
  border: 1px solid rgba(22, 35, 61, 0.12);
  border-radius: 4px;
  cursor: pointer;
}

.swatch:hover {
  outline: 2px solid var(--el-color-primary-light-5);
}

.me-menu {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.me-menu-item {
  padding: 6px 8px;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: var(--pms-text-2);
  font-size: 13px;
  text-align: left;
  cursor: pointer;
}

.me-menu-item:hover {
  background: #eef3ff;
  color: var(--pms-primary-deep);
}

@media (max-width: 768px) {
  .me-font {
    width: 88px;
  }

  .me-body {
    max-height: none;
  }
}
</style>
