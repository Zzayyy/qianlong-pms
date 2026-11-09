<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { changePassword, logout as apiLogout } from '@/api'
import { useUserStore } from '@/stores/user'

const router = useRouter()
const store = useUserStore()

const formRef = ref<FormInstance>()
const form = reactive({ oldPassword: '', newPassword: '', confirmPassword: '' })
const loading = ref(false)

const validateNew = (_rule: unknown, value: string, callback: (error?: Error) => void) => {
  if (!value) {
    callback(new Error('请输入新密码'))
    return
  }
  if (value === form.oldPassword) {
    callback(new Error('新密码不能与当前密码相同'))
    return
  }
  callback()
}

const validateConfirm = (_rule: unknown, value: string, callback: (error?: Error) => void) => {
  if (!value) {
    callback(new Error('请再次输入新密码'))
    return
  }
  if (value !== form.newPassword) {
    callback(new Error('两次输入的新密码不一致'))
    return
  }
  callback()
}

const rules: FormRules = {
  oldPassword: [{ required: true, message: '请输入当前密码', trigger: 'blur' }],
  newPassword: [{ validator: validateNew, trigger: 'blur' }],
  confirmPassword: [{ validator: validateConfirm, trigger: 'blur' }]
}

const onSubmit = () => {
  if (loading.value) return
  formRef.value?.validate(async (valid) => {
    if (!valid) return
    loading.value = true
    try {
      await changePassword(form.oldPassword, form.newPassword)
      ElMessage.success('密码已修改，请使用新密码登录')
      store.logout()
      router.replace('/login')
    } catch {
      /* 错误提示由请求拦截器统一弹出 */
    } finally {
      loading.value = false
    }
  })
}

const onQuit = async () => {
  try {
    await apiLogout()
  } catch {
    /* 登出接口失败不阻塞本地退出 */
  }
  store.logout()
  router.replace('/login')
}
</script>

<template>
  <div class="cp-page">
    <section class="cp-card">
      <div class="cp-brand">
        <span class="cp-mark" aria-hidden="true"><i></i><i></i><i></i><i></i></span>
        <span class="cp-brand-text">钱龙 <b>PMS</b></span>
      </div>

      <header class="cp-head">
        <h1>修改初始密码</h1>
        <p>账号由管理员创建或密码被重置后，需要先设置新密码再进入系统。</p>
      </header>

      <div v-if="store.profile" class="cp-user">
        <span class="cp-avatar">{{ (store.profile.realName || store.profile.username || 'U').slice(0, 1) }}</span>
        <span class="cp-user-meta">
          <span class="cp-user-name">{{ store.profile.realName }}</span>
          <span class="cp-user-sub">{{ store.profile.username }} · {{ store.profile.deptName || '未分配部门' }}</span>
        </span>
      </div>

      <el-form
        ref="formRef"
        :model="form"
        :rules="rules"
        :validate-on-rule-change="false"
        label-position="top"
        @submit.prevent="onSubmit"
      >
        <el-form-item label="当前密码" prop="oldPassword">
          <el-input
            v-model="form.oldPassword"
            type="password"
            show-password
            autocomplete="current-password"
            placeholder="请输入管理员提供的初始密码"
          />
        </el-form-item>
        <el-form-item label="新密码" prop="newPassword">
          <el-input
            v-model="form.newPassword"
            type="password"
            show-password
            autocomplete="new-password"
            placeholder="设置一个新密码"
          />
        </el-form-item>
        <el-form-item label="确认新密码" prop="confirmPassword">
          <el-input
            v-model="form.confirmPassword"
            type="password"
            show-password
            autocomplete="new-password"
            placeholder="再次输入新密码"
            @keyup.enter="onSubmit"
          />
        </el-form-item>

        <el-button type="primary" class="cp-submit" :loading="loading" native-type="submit">
          保存并重新登录
        </el-button>
      </el-form>

      <footer class="cp-foot">
        <span class="cp-hint">修改成功后需要重新登录，其他设备的登录也会失效</span>
        <el-button link type="primary" @click="onQuit">退出登录</el-button>
      </footer>
    </section>
  </div>
</template>

<style scoped>
.cp-page {
  min-height: 100dvh;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px 16px;
  box-sizing: border-box;
  background:
    radial-gradient(900px 640px at 6% 4%, #d5e3ff 0%, rgba(213, 227, 255, 0) 58%),
    radial-gradient(760px 560px at 100% 98%, #dce9ff 0%, rgba(220, 233, 255, 0) 60%),
    linear-gradient(160deg, #eaf1ff 0%, #f6f9ff 52%, #ebf2fe 100%);
  color: #14161a;
}

.cp-card {
  width: 100%;
  max-width: 420px;
  padding: 28px 28px 22px;
  box-sizing: border-box;
  background: #fff;
  border: 1px solid #dbe4f3;
  border-radius: 14px;
  box-shadow:
    0 1px 2px rgba(20, 45, 90, 0.04),
    0 24px 56px -32px rgba(20, 55, 120, 0.24);
  animation: cp-in 0.4s cubic-bezier(0.16, 1, 0.3, 1) both;
}

@keyframes cp-in {
  from {
    opacity: 0;
    transform: translateY(8px);
  }
  to {
    opacity: 1;
    transform: none;
  }
}

.cp-brand {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 22px;
}

.cp-mark {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 2px;
  width: 18px;
  height: 18px;
}

.cp-mark i {
  border-radius: 1.5px;
  background: #2453cf;
}

.cp-mark i:last-child {
  background: #8ba0e7;
}

.cp-brand-text {
  font-size: 13px;
  font-weight: 500;
  letter-spacing: 0.02em;
  color: #14161a;
}

.cp-brand-text b {
  font-weight: 600;
}

.cp-head h1 {
  margin: 0 0 8px;
  font-size: 21px;
  font-weight: 600;
  letter-spacing: 0.02em;
}

.cp-head p {
  margin: 0 0 18px;
  font-size: 12.5px;
  line-height: 1.7;
  color: #6f757e;
}

.cp-user {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  margin-bottom: 18px;
  border: 1px solid #e6ebf5;
  border-radius: 10px;
  background: #f8faff;
}

.cp-avatar {
  flex: none;
  display: grid;
  place-items: center;
  width: 32px;
  height: 32px;
  border-radius: 9px;
  background: #e8efff;
  color: #2453cf;
  font-size: 14px;
  font-weight: 600;
}

.cp-user-meta {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.cp-user-name {
  font-size: 13px;
  font-weight: 500;
  color: #14161a;
}

.cp-user-sub {
  overflow: hidden;
  font-size: 11.5px;
  color: #6f757e;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.cp-card :deep(.el-form-item) {
  margin-bottom: 18px;
}

.cp-card :deep(.el-form-item__label) {
  padding-bottom: 6px;
  font-size: 12.5px;
  font-weight: 500;
  color: #4d525a;
}

.cp-card :deep(.el-input__wrapper) {
  height: 40px;
  border-radius: 7px;
}

.cp-submit {
  width: 100%;
  height: 40px;
  margin-top: 2px;
  border-radius: 7px;
}

.cp-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-top: 16px;
  padding-top: 14px;
  border-top: 1px solid #eef1f7;
}

.cp-hint {
  font-size: 11.5px;
  line-height: 1.6;
  color: #8b909a;
}

@media (max-width: 480px) {
  .cp-card {
    padding: 22px 18px 18px;
  }

  .cp-foot {
    flex-direction: column;
    align-items: flex-start;
    gap: 6px;
  }
}

@media (prefers-reduced-motion: reduce) {
  .cp-card {
    animation: none;
  }
}
</style>
