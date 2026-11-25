<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowLeft, CloudUpload, Download, Paperclip, Trash2 } from 'lucide-vue-next'
import IssueFormDialog from '@/components/IssueFormDialog.vue'
import {
  changeIssueStatus,
  deleteIssue,
  deleteIssueFile,
  downloadIssueFile,
  issueAttachmentUrl,
  issueDetail,
  uploadIssueFile,
  type IssueDetailData
} from '@/api'
import { setPageTitle } from '@/utils/pageTitle'
import { useUserStore } from '@/stores/user'

defineOptions({ name: 'IssueDetailPage' })

const route = useRoute()
const router = useRouter()
const store = useUserStore()

const issueType = computed(() => String(route.meta.issueType || 'BUG').toUpperCase())
const isProd = computed(() => issueType.value === 'PROD')
const listPath = computed(() => (isProd.value ? '/prod-issues' : '/bugs'))

const SEVERITY: Record<string, { label: string; type: 'info' | 'success' | 'warning' | 'danger' }> = {
  LOW: { label: '低', type: 'info' },
  MEDIUM: { label: '中', type: 'warning' },
  HIGH: { label: '高', type: 'danger' },
  URGENT: { label: '紧急', type: 'danger' }
}
const PRIORITY: Record<string, string> = { LOW: '低', MEDIUM: '中', HIGH: '高' }
const STATUS: Record<string, { label: string; type: 'info' | 'success' | 'warning' | 'danger' }> = {
  OPEN: { label: '待处理', type: 'danger' },
  IN_PROGRESS: { label: '处理中', type: 'warning' },
  CLOSED: { label: '已关闭', type: 'success' }
}

const FIELD_LABEL: Record<string, string> = {
  title: '标题',
  description: '描述',
  severity: '严重程度',
  priority: '优先级',
  ownerId: '负责人',
  projectId: '项目',
  foundDate: '发现日期',
  remark: '备注',
  status: '状态'
}
const VALUE_LABEL: Record<string, Record<string, string>> = {
  severity: { LOW: '低', MEDIUM: '中', HIGH: '高', URGENT: '紧急' },
  priority: { LOW: '低', MEDIUM: '中', HIGH: '高' },
  status: { OPEN: '待处理', IN_PROGRESS: '处理中', CLOSED: '已关闭' }
}

const issueId = computed(() => String(route.params.id || ''))
const detail = ref<IssueDetailData | null>(null)
const loading = ref(false)
const editVisible = ref(false)

/* 图片与附件分开：图片走缩略图墙 + 大图预览，附件走表格 */
const IMAGE_EXT = /\.(png|jpe?g|gif|webp|bmp|svg)$/i
/** mime 缺失时按扩展名兜底，避免截图被归到附件。 */
const isImageAttachment = (item: { mime?: string; fileName?: string }) =>
  String(item.mime || '').startsWith('image/') || IMAGE_EXT.test(String(item.fileName || ''))

const imageAttachments = computed(() =>
  (detail.value?.attachments || []).filter((item) => isImageAttachment(item))
)
const docAttachments = computed(() =>
  (detail.value?.attachments || []).filter((item) => !isImageAttachment(item))
)

const imageUrls = ref<Record<string, string>>({})
const previewUrls = computed(() =>
  imageAttachments.value
    .map((item) => imageUrls.value[String(item.fileId)])
    .filter((url): url is string => Boolean(url))
)

const revokeImageUrls = () => {
  Object.values(imageUrls.value).forEach((url) => URL.revokeObjectURL(url))
  imageUrls.value = {}
}

/** 图片接口需要鉴权，先转 blob URL 再交给 el-image 预览。 */
const loadImageUrls = async () => {
  for (const item of imageAttachments.value) {
    const key = String(item.fileId)
    if (imageUrls.value[key]) continue
    try {
      imageUrls.value[key] = await issueAttachmentUrl(issueId.value, key)
    } catch {
      /* 单张失败不影响其他图片 */
    }
  }
}

const previewIndexOf = (row: any) =>
  Math.max(
    0,
    imageAttachments.value.findIndex((item) => String(item.fileId) === String(row.fileId))
  )

const severityMeta = (value: string) => SEVERITY[value] || SEVERITY.MEDIUM
const statusMeta = (value: string) => STATUS[value] || { label: value || '—', type: 'info' as const }

const me = computed(() => String(store.profile?.id || ''))
const canManage = computed(() => store.has('issue:manage'))
const canEdit = computed(() => {
  const row = detail.value
  if (!row) return false
  return (
    canManage.value ||
    String(row.reporterId || '') === me.value ||
    String(row.ownerId || '') === me.value
  )
})

const load = async () => {
  const id = issueId.value
  if (!id) {
    await router.replace(listPath.value)
    return
  }
  loading.value = true
  try {
    const data = await issueDetail(id)
    detail.value = data
    // 图片附件重新生成预览地址（旧的 objectURL 先释放）
    revokeImageUrls()
    await loadImageUrls()
    // 标签栏与面包屑显示问题编号，同时打开多条时能区分
    setPageTitle(route.path, `${data.issueNo} ${data.title}`)
  } catch {
    await router.replace(listPath.value)
  } finally {
    loading.value = false
  }
}

const backToList = () => router.push(listPath.value)

const timeText = (value: string) => {
  const text = String(value || '').replace('T', ' ')
  return text.length >= 19 ? text.slice(0, 19) : text || '—'
}

const valueText = (field: string, value: string) => {
  const text = String(value ?? '')
  return VALUE_LABEL[field]?.[text] ?? (text || '空')
}

/** 历史记录一句话文案：谁、什么时候、做了什么。 */
const logText = (log: IssueDetailData['logs'][number]) => {
  if (log.action === 'CREATE') return '创建了问题'
  if (log.action === 'DELETE') return '删除了问题'
  if (log.action === 'STATUS') {
    return `将状态从「${valueText('status', log.oldValue)}」改为「${valueText('status', log.newValue)}」`
  }
  const label = FIELD_LABEL[log.field] || log.field || '字段'
  if (log.field === 'ownerId') {
    return `将负责人从「${log.oldValue || '未指派'}」指派给「${log.newValue || '未指派'}」`
  }
  if (log.field === 'description') return '修改了问题描述'
  return `将${label}从「${valueText(log.field, log.oldValue)}」改为「${valueText(log.field, log.newValue)}」`
}

const setStatus = async (status: string) => {
  if (!detail.value) return
  try {
    await changeIssueStatus(String(detail.value.id), status)
    ElMessage.success('状态已更新')
    await load()
  } catch {
    /* 错误提示由请求拦截器统一弹出 */
  }
}

const remove = async () => {
  if (!detail.value) return
  try {
    await ElMessageBox.confirm(`确认删除「${detail.value.title}」？`, '删除问题', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消'
    })
  } catch {
    return
  }
  try {
    await deleteIssue(String(detail.value.id))
    ElMessage.success('问题已删除')
    await backToList()
  } catch {
    /* 错误提示由请求拦截器统一弹出 */
  }
}

const onSaved = async () => {
  await load()
}

/* 图片与附件：上传后刷新列表，下载走统一鉴权下载 */
const uploading = ref(false)
const imageUploadRef = ref<any>()

const uploadRequest = async (options: any, label = '附件') => {
  if (!detail.value) return
  uploading.value = true
  try {
    const data = new FormData()
    data.append('file', options.file)
    await uploadIssueFile(String(detail.value.id), data)
    ElMessage.success(`${label}已上传`)
    options.onSuccess?.({})
    await load()
  } catch (error) {
    options.onError?.(error)
  } finally {
    uploading.value = false
  }
}

const imageUploadRequest = async (options: any) => {
  await uploadRequest(options, '图片')
  imageUploadRef.value?.clearFiles()
}

/** 拖拽上传：图片与文档共用一个入口，按 mime 自动分流（后端存完刷新即归位）。 */
const dropRef = ref<any>()
const dropUploadRequest = async (options: any) => {
  const isImage = String(options.file?.type || '').startsWith('image/')
  await uploadRequest(options, isImage ? '图片' : '附件')
  dropRef.value?.clearFiles()
}

const removeAttachment = async (row: any) => {
  if (!detail.value) return
  try {
    await ElMessageBox.confirm(`确认删除附件「${row.fileName}」？`, '删除附件', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消'
    })
  } catch {
    return
  }
  try {
    await deleteIssueFile(String(detail.value.id), String(row.fileId))
    ElMessage.success('附件已删除')
    await load()
  } catch {
    /* 错误提示由请求拦截器统一弹出 */
  }
}

const sizeText = (size: unknown) => {
  const value = Number(size || 0)
  if (value <= 0) return '—'
  if (value < 1024) return `${value} B`
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`
  return `${(value / 1024 / 1024).toFixed(1)} MB`
}

watch(issueId, () => {
  load()
})

onMounted(load)

onBeforeUnmount(revokeImageUrls)
</script>

<template>
  <div v-loading="loading" class="pms-page">
    <!-- 顶部条：返回 + 编号 + 标题 + 状态 -->
    <div class="pms-card top-bar">
      <div class="top-main">
        <el-button link type="primary" class="back-btn" :icon="ArrowLeft" @click="backToList">
          返回
        </el-button>
        <span class="top-divider"></span>
        <span class="issue-no">{{ detail?.issueNo || '—' }}</span>
        <h2 class="issue-title">{{ detail?.title || '' }}</h2>
      </div>
      <div class="top-actions">
        <el-tag :type="statusMeta(detail?.status || '').type" effect="light">
          {{ statusMeta(detail?.status || '').label }}
        </el-tag>
        <template v-if="canEdit">
          <el-button size="small" @click="editVisible = true">编辑</el-button>
          <el-button
            v-if="detail?.status === 'OPEN'"
            type="primary"
            size="small"
            @click="setStatus('IN_PROGRESS')"
          >
            开始处理
          </el-button>
          <el-button
            v-else-if="detail?.status === 'IN_PROGRESS'"
            type="primary"
            plain
            size="small"
            @click="setStatus('CLOSED')"
          >
            关闭
          </el-button>
          <el-button v-else type="primary" plain size="small" @click="setStatus('OPEN')">
            重开
          </el-button>
          <el-button v-if="canManage" type="danger" plain size="small" @click="remove">
            删除
          </el-button>
        </template>
      </div>
    </div>

    <div class="detail-layout">
      <!-- 左栏：正文与过程记录 -->
      <div class="detail-main">
        <div class="pms-card">
          <div class="block-head">
            <h4>问题描述</h4>
            <div class="head-tools">
              <el-upload
                v-if="detail?.canUpload"
                ref="imageUploadRef"
                :show-file-list="false"
                :http-request="imageUploadRequest"
                accept="image/*"
                multiple
                :limit="9"
                :on-exceed="() => ElMessage.warning('一次最多上传 9 张图片')"
                :disabled="uploading"
              >
                <el-button size="small" :icon="Paperclip" :loading="uploading">上传图片</el-button>
              </el-upload>
              <el-button v-if="canEdit" link type="primary" @click="editVisible = true">
                编辑
              </el-button>
            </div>
          </div>
          <p class="text">{{ detail?.description || '暂无描述' }}</p>
          <!-- 图文混排：描述下方直接铺图片，点击看大图，hover 可删 -->
          <div v-if="imageAttachments.length" class="image-wall">
            <div
              v-for="item in imageAttachments"
              :key="String(item.fileId)"
              class="image-card is-manageable"
            >
              <el-image
                :src="imageUrls[String(item.fileId)]"
                :preview-src-list="previewUrls"
                :initial-index="previewIndexOf(item)"
                fit="cover"
                preview-teleported
                class="image-thumb"
              />
              <button
                v-if="canEdit"
                type="button"
                class="image-del"
                title="删除图片"
                @click="removeAttachment(item)"
              >
                ×
              </button>
              <span class="image-name">{{ item.fileName }}</span>
            </div>
          </div>
          <template v-if="detail?.remark">
            <div class="block-head is-sub">
              <h4>备注</h4>
            </div>
            <p class="text">{{ detail.remark }}</p>
          </template>

          <!-- 附件一般很少：压缩成描述卡底部的一条，没有附件时只占一行 -->
          <div class="attach-block">
            <div class="block-head">
              <h4>附件<span class="block-count">{{ docAttachments.length }}</span></h4>
              <span v-if="uploading" class="uploading-tip">上传中…</span>
            </div>
            <ul v-if="docAttachments.length" class="attach-list">
              <li v-for="item in docAttachments" :key="String(item.fileId)">
                <span class="attach-name" :title="item.fileName">{{ item.fileName }}</span>
                <span class="attach-meta">
                  {{ sizeText(item.size) }} · {{ item.uploader || '—' }} ·
                  {{ timeText(item.uploadTime) }}
                </span>
                <span class="attach-ops">
                  <el-button
                    link
                    type="primary"
                    :icon="Download"
                    @click="downloadIssueFile(String(detail?.id || ''), String(item.fileId), item.fileName)"
                  >
                    下载
                  </el-button>
                  <el-button link type="danger" :icon="Trash2" @click="removeAttachment(item)">
                    删除
                  </el-button>
                </span>
              </li>
            </ul>
            <p v-else class="empty-line">暂无附件</p>
            <el-upload
              v-if="detail?.canUpload"
              ref="dropRef"
              drag
              multiple
              :show-file-list="false"
              :http-request="dropUploadRequest"
              :disabled="uploading"
              class="drop-upload"
            >
              <div class="drop-inner">
                <CloudUpload :size="18" :stroke-width="1.8" />
                <span>拖拽图片或文件到这里，或 <em>点击选择</em></span>
              </div>
            </el-upload>
          </div>
        </div>

        <div class="pms-card">
          <div class="block-head">
            <h4>历史记录<span class="block-count">{{ detail?.logs?.length || 0 }}</span></h4>
          </div>
          <ol v-if="detail?.logs?.length" class="log-list">
            <li v-for="(log, index) in detail.logs" :key="String(log.id)">
              <span class="log-index">{{ index + 1 }}</span>
              <span class="log-line">
                {{ timeText(log.createTime) }}，由
                <b>{{ log.operatorName || '未知用户' }}</b>
                {{ logText(log) }}
              </span>
            </li>
          </ol>
          <p v-else class="empty-line">暂无历史记录</p>
        </div>
      </div>

      <!-- 右栏：基本信息与操作 -->
      <aside class="detail-side">
        <div class="pms-card">
          <div class="block-head">
            <h4>基本信息</h4>
          </div>
          <dl class="info-list">
            <div>
              <dt>项目</dt>
              <dd>{{ detail?.projectName || '—' }}</dd>
            </div>
            <div v-if="detail?.issueType === 'PROD'">
              <dt>产品</dt>
              <dd>{{ detail?.productName || '—' }}</dd>
            </div>
            <div>
              <dt>严重程度</dt>
              <dd>
                <el-tag size="small" :type="severityMeta(detail?.severity || '').type" effect="plain">
                  {{ severityMeta(detail?.severity || '').label }}
                </el-tag>
              </dd>
            </div>
            <div>
              <dt>优先级</dt>
              <dd>{{ PRIORITY[detail?.priority || ''] || '—' }}</dd>
            </div>
            <div>
              <dt>状态</dt>
              <dd>
                <el-tag size="small" :type="statusMeta(detail?.status || '').type" effect="plain">
                  {{ statusMeta(detail?.status || '').label }}
                </el-tag>
              </dd>
            </div>
            <div>
              <dt>负责人</dt>
              <dd>{{ detail?.ownerName || '未指派' }}</dd>
            </div>
            <div>
              <dt>提报人</dt>
              <dd>{{ detail?.reporterName || '—' }}</dd>
            </div>
            <div>
              <dt>发现日期</dt>
              <dd>{{ detail?.foundDate || '—' }}</dd>
            </div>
            <div>
              <dt>关闭日期</dt>
              <dd>{{ detail?.closeDate || '—' }}</dd>
            </div>
            <div>
              <dt>图片 / 附件</dt>
              <dd>{{ imageAttachments.length }} / {{ docAttachments.length }}</dd>
            </div>
          </dl>
        </div>

      </aside>
    </div>

    <IssueFormDialog
      v-model="editVisible"
      :issue-type="issueType"
      :issue="detail"
      @saved="onSaved"
    />
  </div>
</template>

<style scoped>
.top-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 10px 12px;
}

/* 状态 + 操作收在顶部条，右侧栏只放信息 */
.top-actions {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}

.top-main {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}

.back-btn {
  flex: none;
}

.top-divider {
  width: 1px;
  height: 16px;
  background: var(--pms-line);
}

.issue-no {
  flex: none;
  font-size: 12.5px;
  color: var(--pms-text-3);
  font-variant-numeric: tabular-nums;
}

.issue-title {
  overflow: hidden;
  margin: 0;
  font-size: 15.5px;
  font-weight: 600;
  color: var(--pms-text);
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 左右两栏：左正文、右属性；窄屏自动堆叠 */
.detail-layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 320px;
  align-items: start;
  gap: 0 14px;
}

.detail-main,
.detail-side {
  min-width: 0;
}

.block-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 10px;
}

.block-head.is-sub {
  margin-top: 16px;
}

.head-tools {
  display: flex;
  align-items: center;
  gap: 8px;
}

.block-head h4 {
  margin: 0;
  font-size: 13.5px;
  font-weight: 600;
  color: var(--pms-text);
}

.block-count {
  margin-left: 6px;
  font-size: 12px;
  font-weight: 400;
  color: var(--pms-text-3);
}

.text {
  margin: 0;
  font-size: 13px;
  line-height: 1.8;
  color: var(--pms-text-2);
  white-space: pre-wrap;
  word-break: break-word;
}

/* 信息栏：属性名固定宽度，值自动换行 */
.info-list {
  display: grid;
  gap: 9px;
  margin: 0;
  font-size: 12.5px;
}

.info-list > div {
  display: flex;
  align-items: baseline;
  gap: 8px;
}

.info-list dt {
  flex: none;
  width: 76px;
  color: var(--pms-text-3);
}

.info-list dd {
  flex: 1;
  min-width: 0;
  margin: 0;
  color: var(--pms-text);
  word-break: break-all;
}

/* 历史记录：编号列表，一行一条 */
.log-list {
  margin: 0;
  padding: 0;
  list-style: none;
}

.log-list li {
  display: flex;
  gap: 8px;
  padding: 9px 0;
  font-size: 12.8px;
  line-height: 1.6;
  color: var(--pms-text-2);
  border-bottom: 1px dashed var(--pms-line-soft);
}

.log-list li:last-child {
  padding-bottom: 0;
  border-bottom: none;
}

.log-index {
  flex: none;
  width: 18px;
  color: var(--pms-text-3);
  font-variant-numeric: tabular-nums;
}

.log-line b {
  color: var(--pms-text);
  font-weight: 600;
}

/* 图片墙 */
.image-wall {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-top: 12px;
}

.image-card {
  position: relative;
  width: 112px;
  overflow: hidden;
  border: 1px solid var(--pms-line);
  border-radius: 8px;
  background: #f7f9fd;
}

.image-thumb {
  display: block;
  width: 112px;
  height: 96px;
  cursor: zoom-in;
}

.image-name {
  display: block;
  overflow: hidden;
  padding: 4px 6px;
  font-size: 11.5px;
  color: var(--pms-text-3);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.image-del {
  position: absolute;
  top: 4px;
  right: 4px;
  width: 20px;
  height: 20px;
  border: none;
  border-radius: 50%;
  background: rgba(0, 0, 0, 0.55);
  color: #fff;
  font-size: 13px;
  line-height: 1;
  cursor: pointer;
  opacity: 0;
  transition: opacity 0.15s;
}

.image-card:hover .image-del {
  opacity: 1;
}

/* 附件：描述卡底部的紧凑列表，没有附件时只占一行 */
.attach-block {
  margin-top: 16px;
  padding-top: 14px;
  border-top: 1px dashed var(--pms-line-soft);
}

.attach-list {
  margin: 0;
  padding: 0;
  list-style: none;
}

.attach-list li {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 6px 0;
  font-size: 12.8px;
}

.attach-name {
  flex: 1 1 auto;
  overflow: hidden;
  min-width: 0;
  color: var(--pms-text-2);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.attach-meta {
  flex: none;
  font-size: 12px;
  color: var(--pms-text-3);
  font-variant-numeric: tabular-nums;
}

.attach-ops {
  display: flex;
  flex: none;
  align-items: center;
  gap: 2px;
}

.empty-line {
  margin: 0;
  font-size: 12.5px;
  color: var(--pms-text-3);
}

.uploading-tip {
  font-size: 12px;
  color: var(--pms-text-3);
}

/* 拖拽上传：图片与文档共用一个紧凑入口 */
.drop-upload {
  margin-top: 10px;
}

.drop-upload :deep(.el-upload) {
  width: 100%;
}

.drop-upload :deep(.el-upload-dragger) {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 100%;
  height: 62px;
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
  gap: 8px;
  font-size: 12.5px;
  color: var(--pms-text-3);
}

.drop-inner em {
  font-style: normal;
  color: var(--pms-primary, #2f6bff);
}

@media (max-width: 1100px) {
  .detail-layout {
    grid-template-columns: minmax(0, 1fr);
  }

  .detail-side {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
    gap: 14px;
  }

  .detail-side .pms-card {
    margin-bottom: 0;
  }
}

@media (max-width: 768px) {
  .issue-title {
    white-space: normal;
  }
}
</style>
