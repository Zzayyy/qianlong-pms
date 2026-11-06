<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { archiveAudit, listLoginLogs, listOperateLogs } from '@/api'

const tab = ref('operate')
const loading = ref(false)

const operateRows = ref<any[]>([])
const operateTotal = ref(0)
const operatePage = ref({ pageNum: 1, pageSize: 10 })
const filter = ref({ module: '', result: '', userId: 0 })

const loginRows = ref<any[]>([])
const loginTotal = ref(0)
const loginPage = ref({ pageNum: 1, pageSize: 10 })
const loginFilter = ref({ username: '', status: '' })

const loadOperate = async () => {
  loading.value = true
  try {
    const data = await listOperateLogs({
      pageNum: operatePage.value.pageNum,
      pageSize: operatePage.value.pageSize,
      module: filter.value.module,
      result: filter.value.result,
      user_id: filter.value.userId || undefined
    })
    operateRows.value = data.list || []
    operateTotal.value = data.total || 0
  } finally {
    loading.value = false
  }
}

const loadLogin = async () => {
  loading.value = true
  try {
    const data = await listLoginLogs({
      pageNum: loginPage.value.pageNum,
      pageSize: loginPage.value.pageSize,
      username: loginFilter.value.username,
      status: loginFilter.value.status
    })
    loginRows.value = data.list || []
    loginTotal.value = data.total || 0
  } finally {
    loading.value = false
  }
}

const archiveLoading = ref(false)
const keepMonths = ref(12)

const runArchive = async (dryRun: boolean) => {
  archiveLoading.value = true
  try {
    const data = await archiveAudit({ keepMonths: keepMonths.value, dryRun })
    const total = Number(data.total || 0)
    const tables = Object.keys((data.tables || {}) as Record<string, unknown>)
    ElMessage.success(
      dryRun
        ? `预演：${total} 行将被归档${tables.length ? '（' + tables.join('、') + '）' : ''}`
        : `已归档 ${total} 行${tables.length ? '至 ' + tables.join('、') + ' 的月份表' : ''}`
    )
  } finally {
    archiveLoading.value = false
  }
}

onMounted(loadOperate)
</script>

<template>
  <div class="pms-page" v-loading="loading">
    <div class="pms-card">
      <el-alert
        type="info"
        :closable="false"
        title="审计留痕：写操作全量记录，读操作仅记录失败与权限拒绝；口令与令牌已脱敏，不入库"
      />
      <el-divider content-position="left">按月归档</el-divider>
      <el-space wrap>
        <span>保留最近</span>
        <el-input-number v-model="keepMonths" :min="1" :max="120" size="small" />
        <span>个月（超出部分搬入 t_sys_*_YYYYMM 月份表）</span>
        <el-button size="small" :loading="archiveLoading" @click="runArchive(true)">预演</el-button>
        <el-button size="small" type="warning" :loading="archiveLoading" @click="runArchive(false)">
          执行归档
        </el-button>
      </el-space>
    </div>

    <el-tabs v-model="tab" @tab-change="tab === 'login' && !loginRows.length ? loadLogin() : null">
      <el-tab-pane label="操作审计" name="operate">
        <div class="pms-card">
          <el-row :gutter="8">
            <el-col :xs="24" :sm="8"><el-input v-model="filter.module" placeholder="模块：project/change/worklog" /></el-col>
            <el-col :xs="24" :sm="8">
              <el-select v-model="filter.result" placeholder="结果" clearable>
                <el-option label="成功" value="SUCCESS" />
                <el-option label="拒绝" value="DENIED" />
                <el-option label="失败" value="FAIL" />
                <el-option label="错误" value="ERROR" />
              </el-select>
            </el-col>
            <el-col :xs="24" :sm="8"><el-button type="primary" @click="loadOperate">查询</el-button></el-col>
          </el-row>
        </div>
        <div class="pms-card">
          <el-table :data="operateRows" size="small">
            <el-table-column prop="module" label="模块" width="100" />
            <el-table-column prop="operation" label="操作" min-width="160" />
            <el-table-column prop="result" label="结果" width="90" />
            <el-table-column prop="userId" label="用户" width="100" />
            <el-table-column prop="ip" label="IP" width="130" class-name="pms-mobile-hide" />
            <el-table-column prop="costMs" label="耗时ms" width="90" class-name="pms-mobile-hide" />
            <el-table-column prop="createTime" label="时间" width="160" class-name="pms-mobile-hide" />
          </el-table>
          <el-pagination
            v-model:current-page="operatePage.pageNum"
            v-model:page-size="operatePage.pageSize"
            :total="operateTotal"
            layout="prev, pager, next, total"
            @current-change="loadOperate"
          />
        </div>
      </el-tab-pane>

      <el-tab-pane label="登录日志" name="login">
        <div class="pms-card">
          <el-row :gutter="8">
            <el-col :xs="24" :sm="8"><el-input v-model="loginFilter.username" placeholder="账号" /></el-col>
            <el-col :xs="24" :sm="8">
              <el-select v-model="loginFilter.status" placeholder="状态" clearable>
                <el-option label="成功" value="SUCCESS" />
                <el-option label="失败" value="FAIL" />
                <el-option label="登出" value="LOGOUT" />
              </el-select>
            </el-col>
            <el-col :xs="24" :sm="8"><el-button type="primary" @click="loadLogin">查询</el-button></el-col>
          </el-row>
        </div>
        <div class="pms-card">
          <el-table :data="loginRows" size="small">
            <el-table-column prop="username" label="账号" width="140" />
            <el-table-column prop="status" label="状态" width="100" />
            <el-table-column prop="ip" label="IP" width="140" />
            <el-table-column prop="message" label="说明" min-width="160" />
            <el-table-column prop="createTime" label="时间" width="160" class-name="pms-mobile-hide" />
          </el-table>
          <el-pagination
            v-model:current-page="loginPage.pageNum"
            v-model:page-size="loginPage.pageSize"
            :total="loginTotal"
            layout="prev, pager, next, total"
            @current-change="loadLogin"
          />
        </div>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>
