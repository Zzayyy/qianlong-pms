<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import {
  convertOpp,
  createCustomer,
  createOpportunity,
  listCustomers,
  listOpportunities,
  pushOppStage
} from '@/api'
import { useUserStore } from '@/stores/user'

const store = useUserStore()
const tab = ref('customers')
const loading = ref(false)

const customers = ref<any[]>([])
const customerTotal = ref(0)
const customerPage = ref({ pageNum: 1, pageSize: 10 })
const customerForm = ref<any>({ customerName: '', customerLevel: 'B', industry: '', contactName: '', contactMobile: '' })

const opportunities = ref<any[]>([])
const oppTotal = ref(0)
const oppPage = ref({ pageNum: 1, pageSize: 10 })
const oppForm = ref<any>({ customerId: 0, oppName: '', amount: 0, ownerId: 0, expectedCloseDate: '' })

const loadCustomers = async () => {
  loading.value = true
  try {
    const data = await listCustomers({ pageNum: customerPage.value.pageNum, pageSize: customerPage.value.pageSize })
    customers.value = data.list || []
    customerTotal.value = data.total || 0
  } finally {
    loading.value = false
  }
}

const loadOpps = async () => {
  loading.value = true
  try {
    const data = await listOpportunities({ pageNum: oppPage.value.pageNum, pageSize: oppPage.value.pageSize })
    opportunities.value = data.list || []
    oppTotal.value = data.total || 0
  } finally {
    loading.value = false
  }
}

const doCreateCustomer = async () => {
  await createCustomer(customerForm.value)
  ElMessage.success('客户已创建')
  await loadCustomers()
}

const doCreateOpp = async () => {
  oppForm.value.ownerId = store.profile?.id || 0
  await createOpportunity(oppForm.value)
  ElMessage.success('商机已创建')
  await loadOpps()
}

const doPushStage = async (row: any, stage: string) => {
  await pushOppStage(row.id, stage)
  ElMessage.success(`阶段已推进到 ${stage}`)
  await loadOpps()
}

const doConvert = async (row: any) => {
  const result = await convertOpp(row.id, { deptId: store.profile?.deptId || 0, pmId: store.profile?.id || 0 })
  ElMessage.success(`已转项目，项目ID ${result.projectId}`)
  await loadOpps()
}

onMounted(async () => {
  await loadCustomers()
  await loadOpps()
})
</script>

<template>
  <div class="pms-page" v-loading="loading">
    <el-tabs v-model="tab">
      <el-tab-pane label="客户" name="customers">
        <div class="pms-card">
          <el-row :gutter="8">
            <el-col :xs="24" :sm="8"><el-input v-model="customerForm.customerName" placeholder="客户名称" /></el-col>
            <el-col :xs="24" :sm="8"><el-input v-model="customerForm.contactName" placeholder="联系人" /></el-col>
            <el-col :xs="24" :sm="8"><el-input v-model="customerForm.contactMobile" placeholder="联系电话" /></el-col>
          </el-row>
          <el-button style="margin-top: 8px" type="primary" @click="doCreateCustomer">新建客户</el-button>
        </div>
        <div class="pms-card">
          <el-table :data="customers" size="small">
            <el-table-column prop="customerCode" label="编号" width="130" />
            <el-table-column prop="customerName" label="客户" min-width="160" />
            <el-table-column prop="customerLevel" label="等级" width="90" />
            <el-table-column prop="customerStatus" label="状态" width="110" />
            <el-table-column prop="ownerName" label="负责人" width="110" class-name="pms-mobile-hide" />
          </el-table>
          <el-pagination
            v-model:current-page="customerPage.pageNum"
            v-model:page-size="customerPage.pageSize"
            :total="customerTotal"
            layout="prev, pager, next, total"
            @current-change="loadCustomers"
          />
        </div>
      </el-tab-pane>

      <el-tab-pane label="商机" name="opportunities">
        <div class="pms-card">
          <el-row :gutter="8">
            <el-col :xs="24" :sm="8"><el-input-number v-model="oppForm.customerId" placeholder="客户ID" /></el-col>
            <el-col :xs="24" :sm="8"><el-input v-model="oppForm.oppName" placeholder="商机名称" /></el-col>
            <el-col :xs="24" :sm="8"><el-input-number v-model="oppForm.amount" /></el-col>
          </el-row>
          <el-button style="margin-top: 8px" type="primary" @click="doCreateOpp">新建商机</el-button>
        </div>
        <div class="pms-card">
          <el-table :data="opportunities" size="small">
            <el-table-column prop="oppCode" label="编号" width="140" />
            <el-table-column prop="oppName" label="商机" min-width="150" />
            <el-table-column prop="stageCode" label="阶段" width="100" />
            <el-table-column prop="amount" label="金额" width="120" />
            <el-table-column label="操作" width="220">
              <template #default="{ row }">
                <el-button size="small" @click="doPushStage(row, 'NEGOTIATION')">推进</el-button>
                <el-button size="small" type="success" @click="doPushStage(row, 'WON')">赢单</el-button>
                <el-button size="small" type="primary" @click="doConvert(row)">转项目</el-button>
              </template>
            </el-table-column>
          </el-table>
          <el-pagination
            v-model:current-page="oppPage.pageNum"
            v-model:page-size="oppPage.pageSize"
            :total="oppTotal"
            layout="prev, pager, next, total"
            @current-change="loadOpps"
          />
        </div>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>
