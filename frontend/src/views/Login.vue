<script setup lang="ts">
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useUserStore } from '@/stores/user'

const route = useRoute()
const router = useRouter()
const store = useUserStore()

const form = ref({ username: 'admin', password: 'Pms@12345' })
const loading = ref(false)

const onSubmit = async () => {
  loading.value = true
  try {
    await store.login(form.value.username, form.value.password)
    const redirect = (route.query.redirect as string) || '/dashboard'
    router.push(redirect)
    ElMessage.success('登录成功')
  } catch {
    /* 错误提示由拦截器统一弹出 */
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="pms-login">
    <el-card class="pms-login-card">
      <template #header>
        <div class="pms-login-title">PMS 项目全周期管理与变更系统</div>
      </template>
      <el-form :model="form" label-position="top" @submit.prevent="onSubmit">
        <el-form-item label="账号">
          <el-input v-model="form.username" autocomplete="username" />
        </el-form-item>
        <el-form-item label="密码">
          <el-input v-model="form.password" type="password" show-password autocomplete="current-password" />
        </el-form-item>
        <el-button type="primary" class="pms-login-btn" :loading="loading" @click="onSubmit">登录</el-button>
      </el-form>
      <el-alert type="info" :closable="false" title="演示账号：admin / Pms@12345（以 seed.py 指定密码为准）" />
    </el-card>
  </div>
</template>

<style scoped>
.pms-login {
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #3370ff, #6ea8ff);
}

.pms-login-card {
  width: 92%;
  max-width: 380px;
}

.pms-login-title {
  font-weight: 700;
  text-align: center;
}

.pms-login-btn {
  width: 100%;
  margin-bottom: 12px;
}
</style>
