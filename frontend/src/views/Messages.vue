<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useRouter } from 'vue-router'
import {
  deleteNotice,
  listNotices,
  readAllNotices,
  readNotices,
  type NoticeItem
} from '@/api'

const router = useRouter()

const rows = ref<NoticeItem[]>([])
const loading = ref(false)
const total = ref(0)
const page = reactive({ pageNum: 1, pageSize: 10 })
const filters = reactive({ unreadOnly: false, noticeType: '', keyword: '' })
const selected = ref<NoticeItem[]>([])

const TYPE_LABEL: Record<string, string> = {
  SYSTEM: '系统',
  REMINDER: '日志催办',
  COMMENT: '评论回复'
}
const typeLabel = (type: string) => TYPE_LABEL[type] || type || '系统'

const load = async () => {
  loading.value = true
  try {
    const data = await listNotices({
      pageNum: page.pageNum,
      pageSize: page.pageSize,
      unreadOnly: filters.unreadOnly || undefined,
      noticeType: filters.noticeType || undefined,
      keyword: filters.keyword.trim() || undefined
    })
    rows.value = data.list || []
    total.value = Number(data.total || 0)
  } finally {
    loading.value = false
  }
}

const search = () => {
  page.pageNum = 1
  load()
}

const markRead = async (row: any) => {
  await readNotices([String(row.id)])
  row.readStatus = 1
}

const openNotice = async (row: any) => {
  if (!row.readStatus) await markRead(row)
  const bizType = String(row.bizType || '')
  if (bizType === 'WORKLOG' || bizType === 'WORKLOG_REMINDER') router.push('/worklogs')
  else if (bizType === 'CHANGE') router.push('/changes')
  else if (bizType === 'PROJECT') router.push('/projects')
}

const markSelected = async () => {
  if (!selected.value.length) {
    ElMessage.warning('请先选择消息')
    return
  }
  const result = await readNotices(selected.value.map((item) => String(item.id)))
  ElMessage.success(`已标记 ${result.count ?? selected.value.length} 条已读`)
  await load()
}

const markAll = async () => {
  const result = await readAllNotices()
  ElMessage.success(`已标记 ${result.count} 条已读`)
  await load()
}

const remove = async (row: any) => {
  try {
    await ElMessageBox.confirm('确认删除这条消息？', '删除消息', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消'
    })
  } catch {
    return
  }
  await deleteNotice(String(row.id))
  ElMessage.success('已删除')
  await load()
}

onMounted(load)
</script>

<template>
  <div class="pms-page message-page">
    <div class="pms-card">
      <div class="toolbar">
        <el-switch v-model="filters.unreadOnly" active-text="只看未读" @change="search" />
        <el-select
          v-model="filters.noticeType"
          placeholder="全部类型"
          clearable
          style="width: 140px"
          @change="search"
        >
          <el-option label="系统" value="SYSTEM" />
          <el-option label="日志催办" value="REMINDER" />
          <el-option label="评论回复" value="COMMENT" />
        </el-select>
        <el-input
          v-model="filters.keyword"
          placeholder="搜索标题 / 内容"
          clearable
          style="width: 220px"
          @keyup.enter="search"
        />
        <el-button type="primary" @click="search">查询</el-button>
        <span class="spacer"></span>
        <el-button link type="primary" @click="markSelected">标记已读</el-button>
        <el-button link type="primary" @click="markAll">全部已读</el-button>
      </div>

      <el-table
        v-loading="loading"
        :data="rows"
        size="small"
        @selection-change="(list: any[]) => (selected = list)"
      >
        <el-table-column type="selection" width="42" />
        <el-table-column label="标题" min-width="240">
          <template #default="{ row }">
            <span class="notice-title" :class="{ 'is-unread': !row.readStatus }" @click="openNotice(row)">
              {{ row.title }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="内容" min-width="320" show-overflow-tooltip>
          <template #default="{ row }">{{ row.content }}</template>
        </el-table-column>
        <el-table-column label="类型" width="100">
          <template #default="{ row }">
            <el-tag size="small" effect="plain">{{ typeLabel(row.noticeType) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="createTime" label="时间" width="160" />
        <el-table-column label="操作" width="130">
          <template #default="{ row }">
            <el-button v-if="!row.readStatus" link type="primary" @click="markRead(row)">标为已读</el-button>
            <el-button link type="danger" @click="remove(row)">删除</el-button>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty description="还没有收到消息" :image-size="72" />
        </template>
      </el-table>

      <el-pagination
        v-model:current-page="page.pageNum"
        v-model:page-size="page.pageSize"
        :total="total"
        :page-sizes="[10, 20, 50]"
        layout="total, sizes, prev, pager, next"
        class="pager"
        @current-change="load"
        @size-change="search"
      />
    </div>
  </div>
</template>

<style scoped>
.toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 12px;
}

.spacer {
  flex: 1;
}

.notice-title {
  cursor: pointer;
  color: var(--pms-text-2);
}

.notice-title.is-unread {
  font-weight: 600;
  color: var(--pms-text);
}

.notice-title:hover {
  color: var(--pms-primary-deep);
}

.pager {
  margin-top: 12px;
  justify-content: flex-end;
}
</style>
