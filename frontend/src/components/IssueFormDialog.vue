<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { CloudUpload } from 'lucide-vue-next'
import {
  createIssue,
  issueOptions,
  listMembers,
  updateIssue,
  uploadIssueFile,
  type IssueFormOptions
} from '@/api'

defineOptions({ name: 'IssueFormDialog' })

const props = defineProps<{
  /** 弹窗显隐 */
  modelValue: boolean
  /** BUG / PROD */
  issueType: string
  /** 传入表示编辑，为空表示新建 */
  issue?: Record<string, any> | null
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', value: boolean): void
  (e: 'saved', id: string): void
}>()

const SEVERITY: Record<string, string> = {
  LOW: '低',
  MEDIUM: '中',
  HIGH: '高',
  URGENT: '紧急'
}
const PRIORITY: Record<string, string> = { LOW: '低', MEDIUM: '中', HIGH: '高' }

const options = ref<IssueFormOptions>({
  projects: [],
  users: [],
  types: [],
  statuses: [],
  severities: [],
  priorities: [],
  canManage: false
})

const form = reactive({
  id: '',
  projectId: '',
  title: '',
  description: '',
  severity: 'MEDIUM',
  priority: 'MEDIUM',
  ownerId: '',
  foundDate: '',
  remark: ''
})

const saving = ref(false)
const uploading = ref(false)

const isEdit = computed(() => Boolean(form.id))
/** 编辑时按详情下发的 canUpload 判断；新建时提报人就是自己，默认可传。 */
const canUpload = computed(() => props.issue?.canUpload !== false)
const title = computed(() => {
  const label = props.issueType === 'PROD' ? '生产问题' : 'Bug'
  return isEdit.value ? `编辑${label}` : `提交${label}`
})

const nowDate = () => new Date().toISOString().slice(0, 10)

/** 新建时的描述模板，用户直接往下填。 */
const DESCRIPTION_TEMPLATE = '问题：\n\n期望：'

/** 只留模板没写内容时按空处理，避免详情页显示一版空模板。 */
const normalizeDescription = (text: string) => {
  const value = String(text || '')
  const plain = value.replace(/问题：|期望：|\s/g, '')
  return plain ? value : ''
}

const loadOptions = async () => {
  try {
    options.value = await issueOptions()
  } catch {
    /* 错误提示由请求拦截器统一弹出 */
  }
}

/* 负责人下拉：项目成员优先，其余人员放第二组 */
interface OwnerOption {
  id: string
  name: string
}

const projectMembers = ref<OwnerOption[]>([])
const memberLoading = ref(false)

const loadProjectMembers = async (projectId: string) => {
  const key = String(projectId || '')
  if (!key) {
    projectMembers.value = []
    return
  }
  memberLoading.value = true
  try {
    const rows = (await listMembers(key)) as unknown as Record<string, unknown>[]
    projectMembers.value = (Array.isArray(rows) ? rows : [])
      .filter((row) => row.userId && !row.userMissing)
      .map((row) => ({
        id: String(row.userId),
        name: String(row.realName || row.username || row.userId)
      }))
  } catch {
    projectMembers.value = []
  } finally {
    memberLoading.value = false
  }
}

const memberIds = computed(() => new Set(projectMembers.value.map((item) => item.id)))
const otherUsers = computed(() =>
  options.value.users.filter((item) => !memberIds.value.has(String(item.id)))
)

/* 图片与附件分开管理：新建时暂存，保存后上传；编辑时选完立即上传 */
interface PendingImage {
  file: File
  name: string
  url: string
}

const pendingImages = ref<PendingImage[]>([])
const pendingFiles = ref<{ file: File; name: string; size: number }[]>([])
const imageUploadRef = ref<any>()
const fileUploadRef = ref<any>()

/** 拖拽/点击选图：新建态暂存，编辑态立即上传；拖错非图片自动转附件。 */
const handleImageRequest = async (options: any) => {
  options.onSuccess?.({})
  if (looksLikeImage(options.file)) {
    await addImages([options.file])
  } else {
    ElMessage.info('非图片文件已按附件处理')
    await addFiles([options.file])
  }
  imageUploadRef.value?.clearFiles()
}

const handleFileRequest = async (options: any) => {
  options.onSuccess?.({})
  await addFiles([options.file])
  fileUploadRef.value?.clearFiles()
}

const sizeText = (size: number) => {
  if (!size) return '—'
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / 1024 / 1024).toFixed(1)} MB`
}

const clearPending = () => {
  pendingImages.value.forEach((item) => URL.revokeObjectURL(item.url))
  pendingImages.value = []
  pendingFiles.value = []
}

const uploadOne = async (issueId: string, file: File) => {
  const data = new FormData()
  data.append('file', file)
  await uploadIssueFile(issueId, data)
}

/** 编辑态已有问题 ID：选完立即上传，上传完通知父级刷新。 */
const uploadNow = async (files: File[]) => {
  if (!form.id || !files.length) return
  uploading.value = true
  try {
    for (const file of files) {
      await uploadOne(form.id, file)
    }
    ElMessage.success('已上传')
    emit('saved', form.id)
  } catch {
    /* 错误提示由请求拦截器统一弹出 */
  } finally {
    uploading.value = false
  }
}

const IMAGE_EXT = /\.(png|jpe?g|gif|webp|bmp|svg)$/i
/** 粘贴的截图有时 type 为空，按扩展名兜底。 */
const looksLikeImage = (file: File) =>
  file.type.startsWith('image/') || IMAGE_EXT.test(file.name || '')

const addImages = async (files: File[]) => {
  const images = files.filter((file) => looksLikeImage(file))
  if (!images.length) return
  if (!canUpload.value) {
    ElMessage.warning('仅项目成员、提报人或负责人可上传附件')
    return
  }
  if (form.id) {
    await uploadNow(images)
    return
  }
  for (const file of images) {
    pendingImages.value.push({
      file,
      name: file.name || '粘贴图片.png',
      url: URL.createObjectURL(file)
    })
  }
}

const addFiles = async (files: File[]) => {
  const docs = files.filter((file) => !file.type.startsWith('image/'))
  if (!docs.length) return
  if (!canUpload.value) {
    ElMessage.warning('仅项目成员、提报人或负责人可上传附件')
    return
  }
  if (form.id) {
    await uploadNow(docs)
    return
  }
  for (const file of docs) {
    pendingFiles.value.push({ file, name: file.name, size: file.size })
  }
}

const removePendingImage = (index: number) => {
  const item = pendingImages.value[index]
  if (item) URL.revokeObjectURL(item.url)
  pendingImages.value.splice(index, 1)
}

const removePendingFile = (index: number) => pendingFiles.value.splice(index, 1)

/** 描述框内直接粘贴截图：自动作为图片附件。 */
const onPaste = (event: ClipboardEvent) => {
  const items = event.clipboardData?.items
  if (!items) return
  const files: File[] = []
  for (let index = 0; index < items.length; index += 1) {
    const item = items[index]
    if (item.kind === 'file' && item.type.startsWith('image/')) {
      const file = item.getAsFile()
      if (file) files.push(file)
    }
  }
  if (!files.length) return
  event.preventDefault()
  void addImages(files)
  if (!isEdit.value) {
    ElMessage.success(`已粘贴 ${files.length} 张图片，保存时一起上传`)
  }
}

const fill = async () => {
  const row = props.issue
  Object.assign(form, {
    id: row ? String(row.id || '') : '',
    projectId: row ? String(row.projectId || '') : '',
    title: row ? String(row.title || '') : '',
    description: row ? String(row.description || '') : DESCRIPTION_TEMPLATE,
    severity: String(row?.severity || 'MEDIUM'),
    priority: String(row?.priority || 'MEDIUM'),
    ownerId: row?.ownerId ? String(row.ownerId) : '',
    foundDate: String(row?.foundDate || nowDate()),
    remark: String(row?.remark || '')
  })
  clearPending()
  await loadProjectMembers(form.projectId)
}

watch(
  () => props.modelValue,
  async (open) => {
    if (!open) {
      clearPending()
      return
    }
    await loadOptions()
    await fill()
  }
)

const save = async () => {
  if (!form.projectId) {
    ElMessage.warning('请选择项目')
    return
  }
  if (!form.title.trim()) {
    ElMessage.warning('请填写问题标题')
    return
  }
  saving.value = true
  try {
    // 雪花 ID 必须按字符串传，Number() 会丢精度
    const payload: Record<string, unknown> = {
      projectId: String(form.projectId),
      title: form.title.trim(),
      description: normalizeDescription(form.description),
      severity: form.severity,
      priority: form.priority,
      ownerId: form.ownerId ? String(form.ownerId) : 0,
      foundDate: form.foundDate || null,
      remark: form.remark || ''
    }
    let issueId = form.id
    if (issueId) {
      await updateIssue(issueId, payload)
    } else {
      const created = await createIssue({ ...payload, issueType: props.issueType })
      issueId = String(created.id)
    }
    // 新建态暂存的图片/附件在拿到问题 ID 后上传
    for (const item of pendingImages.value) {
      await uploadOne(issueId, item.file)
    }
    for (const item of pendingFiles.value) {
      await uploadOne(issueId, item.file)
    }
    clearPending()
    ElMessage.success(isEdit.value ? '问题已更新' : '已提交')
    emit('saved', issueId)
    emit('update:modelValue', false)
  } catch {
    /* 错误提示由请求拦截器统一弹出 */
  } finally {
    saving.value = false
  }
}

const close = () => emit('update:modelValue', false)
</script>

<template>
  <el-dialog
    :model-value="modelValue"
    :title="title"
    width="min(760px, 94vw)"
    class="issue-form-dialog"
    align-center
    :close-on-click-modal="false"
    @update:model-value="(value: boolean) => emit('update:modelValue', value)"
  >
    <el-form :model="form" label-width="88px">
      <el-form-item label="项目" required>
        <el-select
          v-model="form.projectId"
          filterable
          style="width: 100%"
          @change="(value: any) => loadProjectMembers(String(value || ''))"
        >
          <el-option
            v-for="item in options.projects"
            :key="String(item.id)"
            :label="`${item.projectName}（${item.projectCode}）`"
            :value="String(item.id)"
          />
        </el-select>
      </el-form-item>
      <el-form-item label="标题" required>
        <el-input
          v-model="form.title"
          maxlength="200"
          show-word-limit
          placeholder="一句话说清问题现象"
        />
      </el-form-item>
      <el-form-item label="描述">
        <el-input
          v-model="form.description"
          type="textarea"
          :rows="9"
          maxlength="2000"
          show-word-limit
          placeholder="问题：&#10;（现象、复现步骤、影响范围）&#10;&#10;期望：&#10;（期望的正确结果）&#10;可直接 Ctrl+V 粘贴截图"
          @paste="onPaste"
        />
      </el-form-item>
      <div class="form-row">
        <el-form-item label="严重程度">
          <el-select v-model="form.severity">
            <el-option
              v-for="(label, value) in SEVERITY"
              :key="value"
              :label="label"
              :value="value"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="优先级">
          <el-select v-model="form.priority">
            <el-option
              v-for="(label, value) in PRIORITY"
              :key="value"
              :label="label"
              :value="value"
            />
          </el-select>
        </el-form-item>
      </div>
      <div class="form-row">
        <el-form-item label="负责人">
          <el-select
            v-model="form.ownerId"
            clearable
            filterable
            placeholder="未指派"
            :loading="memberLoading"
          >
            <el-option-group v-if="projectMembers.length" label="项目成员">
              <el-option
                v-for="item in projectMembers"
                :key="item.id"
                :label="item.name"
                :value="item.id"
              />
            </el-option-group>
            <el-option-group v-if="otherUsers.length" label="其他人员">
              <el-option
                v-for="item in otherUsers"
                :key="String(item.id)"
                :label="item.name"
                :value="String(item.id)"
              />
            </el-option-group>
          </el-select>
        </el-form-item>
        <el-form-item label="发现日期">
          <el-date-picker
            v-model="form.foundDate"
            type="date"
            value-format="YYYY-MM-DD"
            placeholder="选择日期"
          />
        </el-form-item>
      </div>
      <el-form-item label="备注">
        <el-input v-model="form.remark" maxlength="500" show-word-limit />
      </el-form-item>

      <el-form-item label="图片">
        <div class="upload-block">
          <el-upload
            v-if="canUpload"
            ref="imageUploadRef"
            drag
            multiple
            :show-file-list="false"
            accept="image/*"
            :http-request="handleImageRequest"
            :disabled="uploading"
            class="drop-upload"
          >
            <div class="drop-inner">
              <CloudUpload :size="16" :stroke-width="1.8" />
              <span>拖拽图片到这里，或 <em>点击选择</em></span>
            </div>
          </el-upload>
          <span class="upload-tip">
            {{
              canUpload
                ? `${isEdit ? '选完立即上传' : '保存时一起上传'}；也可在描述框里 Ctrl+V 粘贴截图`
                : '仅项目成员、提报人或负责人可上传附件'
            }}
          </span>
          <div v-if="pendingImages.length" class="image-grid">
            <div v-for="(item, index) in pendingImages" :key="item.url" class="image-item">
              <img :src="item.url" :alt="item.name" />
              <button type="button" class="image-remove" @click="removePendingImage(index)">
                ×
              </button>
            </div>
          </div>
        </div>
      </el-form-item>

      <el-form-item label="附件">
        <div class="upload-block">
          <el-upload
            v-if="canUpload"
            ref="fileUploadRef"
            drag
            multiple
            :show-file-list="false"
            :http-request="handleFileRequest"
            :disabled="uploading"
            class="drop-upload"
          >
            <div class="drop-inner">
              <CloudUpload :size="16" :stroke-width="1.8" />
              <span>拖拽文件到这里，或 <em>点击选择</em></span>
            </div>
          </el-upload>
          <span class="upload-tip">
            {{
              canUpload
                ? `${isEdit ? '选完立即上传' : '保存时一起上传'}（文档类，不含图片）`
                : '仅项目成员、提报人或负责人可上传附件'
            }}
          </span>
          <ul v-if="pendingFiles.length" class="file-list">
            <li v-for="(item, index) in pendingFiles" :key="`${item.name}-${index}`">
              <span class="file-name">{{ item.name }}</span>
              <span class="file-size">{{ sizeText(item.size) }}</span>
              <el-button link type="danger" size="small" @click="removePendingFile(index)">
                移除
              </el-button>
            </li>
          </ul>
        </div>
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="close">取消</el-button>
      <el-button type="primary" :loading="saving" @click="save">保存</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.form-row {
  display: flex;
  gap: 12px;
}

.form-row :deep(.el-form-item) {
  flex: 1;
}

.upload-block {
  width: 100%;
}

.upload-head {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
}

.upload-tip {
  display: block;
  margin-top: 6px;
  font-size: 12px;
  color: var(--pms-text-3);
}

/* 拖拽上传：弹窗里用紧凑高度 */
.drop-upload {
  width: 100%;
}

.drop-upload :deep(.el-upload) {
  width: 100%;
}

.drop-upload :deep(.el-upload-dragger) {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 100%;
  height: 56px;
  padding: 0 12px;
  border: 1px dashed var(--pms-line);
  border-radius: 8px;
  background: #fafbfe;
  transition: border-color 0.15s, background 0.15s;
}

.drop-upload :deep(.el-upload-dragger:hover) {
  border-color: var(--pms-primary, #2f6bff);
  background: #f2f6ff;
}

.drop-inner {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12.5px;
  color: var(--pms-text-3);
}

.drop-inner em {
  font-style: normal;
  color: var(--pms-primary, #2f6bff);
}

.image-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 10px;
}

.image-item {
  position: relative;
  width: 78px;
  height: 78px;
  border: 1px solid var(--pms-line);
  border-radius: 8px;
  overflow: hidden;
  background: #f5f7fb;
}

.image-item img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.image-remove {
  position: absolute;
  top: 2px;
  right: 2px;
  width: 18px;
  height: 18px;
  border: none;
  border-radius: 50%;
  background: rgba(0, 0, 0, 0.55);
  color: #fff;
  font-size: 12px;
  line-height: 1;
  cursor: pointer;
}

.file-list {
  margin: 8px 0 0;
  padding: 0;
  list-style: none;
}

.file-list li {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 4px 0;
  font-size: 12.5px;
}

.file-name {
  overflow: hidden;
  max-width: 320px;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--pms-text-2);
}

.file-size {
  color: var(--pms-text-3);
  font-variant-numeric: tabular-nums;
}

@media (max-width: 768px) {
  .form-row {
    flex-direction: column;
    gap: 0;
  }
}
</style>

<style>
/* 描述框加高后弹窗内容可能超屏：body 内部滚动，底部按钮始终可见 */
.issue-form-dialog .el-dialog__body {
  max-height: calc(100vh - 220px);
  overflow-y: auto;
}
</style>
