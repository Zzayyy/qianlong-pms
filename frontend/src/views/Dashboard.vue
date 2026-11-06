<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { companyBoard } from '@/api'

const board = ref<Record<string, any>>({})
const summary = ref<Record<string, any>>({})
const topDelayed = ref<any[]>([])
const loading = ref(false)

const load = async () => {
  loading.value = true
  try {
    board.value = await companyBoard()
    summary.value = board.value.summary || {}
    topDelayed.value = (board.value.topDelayed as any[]) || []
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="pms-page" v-loading="loading">
    <div class="pms-card">
      <el-row :gutter="12">
        <el-col v-for="(value, key) in {
          项目总数: summary.projectCount,
          进行中: summary.inProgressCount,
          延期: summary.delayedCount,
          平均进度: summary.avgProgress,
          平均SPI: summary.avgSpi,
          平均CPI: summary.avgCpi,
          开放风险: summary.riskOpen,
          变更数: summary.changeCount
        }" :key="key" :xs="12" :sm="8" :md="6">
          <div class="pms-kpi">
            <div class="pms-kpi-value">{{ value ?? 0 }}</div>
            <div class="pms-kpi-label">{{ key }}</div>
          </div>
        </el-col>
      </el-row>
    </div>

    <div class="pms-card">
      <h3>健康度分布</h3>
      <el-row :gutter="12">
        <el-col v-for="(count, health) in (summary.byHealth || {})" :key="health" :xs="8" :sm="6">
          <el-tag :type="String(health) === 'RED' ? 'danger' : String(health) === 'YELLOW' ? 'warning' : 'success'" size="large">
            {{ health }}：{{ count }}
          </el-tag>
        </el-col>
      </el-row>
    </div>

    <div class="pms-card">
      <h3>延期 Top10</h3>
      <el-table :data="topDelayed" size="small">
        <el-table-column prop="projectName" label="项目" min-width="160" />
        <el-table-column prop="status" label="状态" width="120" />
        <el-table-column prop="progress" label="进度%" width="90" />
        <el-table-column prop="spi" label="SPI" width="90" class-name="pms-mobile-hide" />
        <el-table-column prop="cpi" label="CPI" width="90" class-name="pms-mobile-hide" />
        <el-table-column prop="delayDays" label="延期(天)" width="100" />
        <el-table-column prop="logFillRate" label="日志填写率%" width="120" class-name="pms-mobile-hide" />
      </el-table>
    </div>
  </div>
</template>
