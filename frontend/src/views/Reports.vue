<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { aggregateDaily, deptBoard, personalBoard } from '@/api'
import { useUserStore } from '@/stores/user'

const store = useUserStore()
const deptIds = ref('')
const board = ref<any>({})
const summary = ref<any>({})
const projects = ref<any[]>([])
const personal = ref<any>({})
const byProject = ref<any[]>([])
const loading = ref(false)

const today = new Date().toISOString().slice(0, 10)
const monthAgo = new Date(Date.now() - 30 * 86400000).toISOString().slice(0, 10)
const range = ref({ dateFrom: monthAgo, dateTo: today })

const loadDept = async () => {
  loading.value = true
  try {
    const ids = deptIds.value
      ? deptIds.value.split(',').map((item) => Number(item.trim())).filter(Boolean)
      : [store.profile?.deptId || 0]
    board.value = await deptBoard(ids)
    summary.value = board.value.summary || {}
    projects.value = (board.value.projects as any[]) || []
  } finally {
    loading.value = false
  }
}

const loadPersonal = async () => {
  personal.value = await personalBoard({ ...range.value, userId: store.profile?.id })
  byProject.value = (personal.value.byProject as any[]) || []
}

const doAggregate = async () => {
  const result = await aggregateDaily(today)
  ElMessage.success(`日聚合完成：项目 ${result.projects} 条 / 工时 ${result.worklogs} 条`)
}

onMounted(async () => {
  await loadDept()
  await loadPersonal()
})
</script>

<template>
  <div class="pms-page" v-loading="loading">
    <div class="pms-card">
      <h3>部门看板</h3>
      <el-row :gutter="8">
        <el-col :xs="24" :sm="12" :md="8">
          <el-input v-model="deptIds" placeholder="部门ID，多个用逗号分隔（空=本部门）" />
        </el-col>
        <el-col :xs="24" :sm="12" :md="16">
          <el-button @click="loadDept">查询</el-button>
          <el-button @click="doAggregate">执行日聚合</el-button>
        </el-col>
      </el-row>
      <el-row :gutter="12" style="margin-top: 12px">
        <el-col v-for="(value, key) in {
          项目数: summary.projectCount,
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
      <el-table :data="projects" size="small" style="margin-top: 12px">
        <el-table-column prop="projectName" label="项目" min-width="160" />
        <el-table-column prop="health" label="健康度" width="100" />
        <el-table-column prop="progress" label="进度%" width="90" />
        <el-table-column prop="spi" label="SPI" width="90" class-name="pms-mobile-hide" />
        <el-table-column prop="cpi" label="CPI" width="90" class-name="pms-mobile-hide" />
        <el-table-column prop="delayDays" label="延期(天)" width="100" />
      </el-table>
    </div>

    <div class="pms-card">
      <h3>个人看板</h3>
      <el-row :gutter="8">
        <el-col :xs="24" :sm="12" :md="8"><el-input v-model="range.dateFrom" placeholder="开始日期" /></el-col>
        <el-col :xs="24" :sm="12" :md="8"><el-input v-model="range.dateTo" placeholder="结束日期" /></el-col>
        <el-col :xs="24" :sm="24" :md="8"><el-button @click="loadPersonal">查询</el-button></el-col>
      </el-row>
      <el-row :gutter="12" style="margin-top: 12px">
        <el-col v-for="(value, key) in {
          填写率: personal.stats?.fillRate,
          及时率: personal.stats?.onTimeRate,
          已提交: personal.stats?.submittedDays,
          总工时: personal.stats?.totalHours
        }" :key="key" :xs="12" :sm="8" :md="6">
          <div class="pms-kpi">
            <div class="pms-kpi-value">{{ value ?? 0 }}</div>
            <div class="pms-kpi-label">{{ key }}</div>
          </div>
        </el-col>
      </el-row>
      <el-table :data="byProject" size="small" style="margin-top: 12px">
        <el-table-column prop="projectName" label="项目" min-width="160" />
        <el-table-column prop="hours" label="工时" width="100" />
        <el-table-column prop="ratio" label="占比%" width="100" />
      </el-table>
    </div>
  </div>
</template>
