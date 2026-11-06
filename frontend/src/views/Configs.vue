<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { listConfigs, updateConfig } from '@/api'

const rows = ref<any[]>([])
const loading = ref(false)
const keyword = ref('')

const load = async () => {
  loading.value = true
  try {
    rows.value = (await listConfigs()) || []
  } finally {
    loading.value = false
  }
}

const filtered = () => {
  const text = keyword.value.trim().toLowerCase()
  if (!text) return rows.value
  return rows.value.filter((row) =>
    [row.configKey, row.groupName, row.remark]
      .map((item) => String(item || '').toLowerCase())
      .some((item) => item.includes(text))
  )
}

const editRow = async (row: any) => {
  await updateConfig(row.configKey, row.configValue)
  ElMessage.success(`${row.configKey} 已更新`)
  await load()
}

onMounted(load)
</script>

<template>
  <div class="pms-page" v-loading="loading">
    <div class="pms-card">
      <el-alert
        type="info"
        :closable="false"
        title="业务规则唯一入口：立项金额阈值、变更定级阈值、日志工时上限、健康度阈值等均在此维护，改后实时生效"
      />
      <el-input
        v-model="keyword"
        placeholder="按参数名 / 分组 / 中文含义筛选，如 变更、工时、health."
        style="margin-top: 8px"
      />
    </div>
    <div class="pms-card">
      <el-table :data="filtered()" size="small">
        <el-table-column prop="groupName" label="分组" width="110" />
        <el-table-column prop="configKey" label="参数" min-width="210" />
        <el-table-column prop="configValue" label="当前值" width="150">
          <template #default="{ row }">
            <el-input v-model="row.configValue" size="small" />
          </template>
        </el-table-column>
        <el-table-column prop="remark" label="说明（中文含义）" min-width="320" show-overflow-tooltip />
        <el-table-column label="操作" width="80">
          <template #default="{ row }">
            <el-button size="small" type="primary" @click="editRow(row)">保存</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>
  </div>
</template>
