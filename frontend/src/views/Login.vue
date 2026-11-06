<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { useUserStore } from '@/stores/user'

const route = useRoute()
const router = useRouter()
const store = useUserStore()

const formRef = ref<FormInstance>()
const form = reactive({ username: 'admin', password: 'Pms@12345' })
const loading = ref(false)

const rules: FormRules = {
  username: [{ required: true, message: '请输入账号', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }],
}

const onSubmit = () => {
  if (loading.value) return
  formRef.value?.validate(async (valid) => {
    if (!valid) return
    loading.value = true
    try {
      await store.login(form.username, form.password)
      const redirect = (route.query.redirect as string) || '/dashboard'
      router.push(redirect)
      ElMessage.success('登录成功')
    } catch {
      /* 错误提示由请求拦截器统一弹出，此处不再重复提示 */
    } finally {
      loading.value = false
    }
  })
}
</script>

<template>
  <div class="login-page">
    <header class="page-head">
      <div class="page-inner">
        <div class="brand">
          <span class="brand-mark" aria-hidden="true">
            <i></i><i></i><i></i><i></i>
          </span>
          <span class="brand-name">钱龙</span>
          <span class="brand-divider" aria-hidden="true"></span>
          <span class="brand-sub">项目管理系统</span>
        </div>
        <span class="head-note">仅限授权人员使用</span>
      </div>
    </header>

    <main class="page-main">
      <section class="intro">
        <h1 class="intro-title">
          <span>项目全周期管理</span>
          <span>与变更控制</span>
        </h1>
        <p class="intro-text">
          从立项、计划、执行到验收，进度、成本、风险与变更在同一条链路上留痕，责任清晰可溯。
        </p>
      </section>

      <section class="auth">
        <div class="auth-head">
          <h2>登录</h2>
          <p>使用已开通的账号进入系统</p>
        </div>

        <el-form
          ref="formRef"
          :model="form"
          :rules="rules"
          label-position="top"
          @submit.prevent="onSubmit"
        >
          <el-form-item label="账号" prop="username">
            <el-input v-model="form.username" placeholder="请输入账号" autocomplete="username" />
          </el-form-item>
          <el-form-item label="密码" prop="password">
            <el-input
              v-model="form.password"
              type="password"
              show-password
              placeholder="请输入密码"
              autocomplete="current-password"
              @keyup.enter="onSubmit"
            />
          </el-form-item>

          <el-button
            type="primary"
            class="submit"
            :loading="loading"
            native-type="submit"
          >
            登录
          </el-button>
        </el-form>

        <p class="auth-hint">演示账号 admin / Pms@12345，以 seed.py 为准</p>
      </section>
    </main>

    <footer class="page-foot">
      <div class="page-inner">
        <span>© 2026 钱龙软件</span>
        <span class="foot-note">登录异常请联系系统管理员</span>
      </div>
    </footer>
  </div>
</template>

<style scoped>
.login-page {
  /* 色彩：近白纸面 + 墨色文字 + 单一深蓝强调色 */
  --paper: #f3f7ff;
  --ink: #14161a;
  --ink-2: #4d525a;
  --ink-3: #666c75;
  --hairline: #d9e2f2;
  --accent: #2453cf;
  --accent-press: #1c40a6;

  min-height: 100dvh;
  display: flex;
  flex-direction: column;
  background:
    radial-gradient(560px 660px at 79% 46%, rgba(255, 255, 255, 0.92) 0%, rgba(255, 255, 255, 0) 68%),
    radial-gradient(1150px 800px at 2% 4%, #cfe0ff 0%, rgba(207, 224, 255, 0) 58%),
    radial-gradient(900px 640px at 99% 97%, #d7e5ff 0%, rgba(215, 229, 255, 0) 62%),
    linear-gradient(160deg, #e8f0ff 0%, #f4f8ff 52%, #e9f1fe 100%);
  color: var(--ink);
  font-family: 'PingFang SC', 'Microsoft YaHei', 'Hiragino Sans GB', system-ui, -apple-system,
    'Segoe UI', sans-serif;

  /* Element Plus 主色令牌收敛到品牌深蓝，仅作用于本页 */
  --el-color-primary: #2453cf;
  --el-color-primary-dark-2: #1c40a6;
  --el-color-primary-light-3: #526fdc;
  --el-color-primary-light-5: #8ba0e7;
  --el-color-primary-light-7: #c0ccf2;
  --el-color-primary-light-8: #d6def6;
  --el-color-primary-light-9: #ebeff9;
}

/* 全页统一内容宽度与左右边距，页头、主体、页脚严格对齐 */
.page-inner,
.page-main,
.intro,
.auth {
  box-sizing: border-box;
}

.page-inner {
  width: 100%;
  max-width: 1040px;
  margin: 0 auto;
  padding: 0 clamp(20px, 5vw, 52px);
}

/* ============ 页头：字标与使用限制 ============ */
.page-head {
  flex: none;
  border-bottom: 1px solid var(--hairline);
}

.page-head .page-inner {
  height: 64px;
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.brand {
  display: flex;
  align-items: center;
  gap: 10px;
}

.brand-mark {
  display: grid;
  grid-template-columns: repeat(2, 7px);
  grid-auto-rows: 7px;
  gap: 3px;
}

.brand-mark i {
  background: var(--ink);
  border-radius: 1px;
}

.brand-mark i:nth-child(4) {
  background: var(--accent);
}

.brand-name {
  font-size: 15px;
  font-weight: 600;
  letter-spacing: 0.06em;
}

.brand-divider {
  width: 1px;
  height: 12px;
  background: #d5d6d0;
}

.brand-sub {
  font-size: 13px;
  color: var(--ink-2);
  letter-spacing: 0.02em;
}

.head-note {
  font-size: 12px;
  color: var(--ink-3);
  letter-spacing: 0.02em;
}

/* ============ 主体：非对称栏式，一根竖线分隔 ============ */
.page-main {
  flex: 1;
  width: 100%;
  max-width: 1040px;
  margin: 0 auto;
  display: grid;
  grid-template-columns: minmax(0, 1fr) 344px;
  align-items: center;
  padding: 0 clamp(20px, 5vw, 52px);
}

.intro {
  padding-right: clamp(36px, 6vw, 72px);
}

.intro-title {
  margin: 0 0 18px;
  font-size: clamp(29px, 2.9vw, 36px);
  font-weight: 500;
  line-height: 1.46;
  letter-spacing: 0.02em;
  color: var(--ink);
}

.intro-title span {
  display: block;
}

.intro-text {
  margin: 0;
  max-width: 24.6em;
  font-size: 15px;
  line-height: 1.85;
  color: var(--ink-2);
  letter-spacing: 0.005em;
}

.auth {
  position: relative;
  align-self: stretch;
  display: flex;
  flex-direction: column;
  justify-content: center;
  padding: 40px 0 40px clamp(32px, 4.5vw, 48px);
}

/* 分隔线：两端渐隐的蓝色细线 */
.auth::before {
  content: '';
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 1px;
  background: linear-gradient(
    to bottom,
    rgba(165, 187, 226, 0) 0%,
    #c3d4ee 14%,
    #c3d4ee 86%,
    rgba(165, 187, 226, 0) 100%
  );
}

.auth-head h2 {
  margin: 0 0 7px;
  font-size: 19px;
  font-weight: 600;
  letter-spacing: 0.03em;
}

.auth-head p {
  margin: 0 0 26px;
  font-size: 12.5px;
  color: var(--ink-3);
  letter-spacing: 0.01em;
}

/* ============ 表单细节 ============ */
.auth :deep(.el-form-item) {
  margin-bottom: 22px;
}

.auth :deep(.el-form-item__label) {
  display: block;
  padding: 0 0 7px;
  font-size: 13px;
  font-weight: 500;
  line-height: 1.5;
  color: var(--ink-2);
  letter-spacing: 0.01em;
}

/* 必填星号会打破版面节奏，改为静默必填 */
.auth :deep(.el-form-item.is-required .el-form-item__label::before) {
  content: none;
}

.auth :deep(.el-form-item.is-required .el-form-item__label::after) {
  content: none;
}

.auth :deep(.el-input__wrapper) {
  height: 42px;
  padding: 0 12px;
  border-radius: 6px;
  background: #fff;
  box-shadow: 0 0 0 1px #cedaea inset;
  transition: box-shadow 0.15s ease;
}

.auth :deep(.el-input__wrapper:hover) {
  box-shadow: 0 0 0 1px #b3c3dc inset;
}

.auth :deep(.el-input__wrapper.is-focus) {
  box-shadow:
    0 0 0 1px var(--accent) inset,
    0 0 0 3px rgba(36, 83, 207, 0.12);
}

.auth :deep(.el-input__inner) {
  font-size: 14px;
  letter-spacing: 0.01em;
}

.auth :deep(.el-input__inner::placeholder) {
  color: #9aa0a9;
}

.auth :deep(.el-input__password) {
  color: var(--ink-3);
}

/* 校验提示占用独立一行，避免压住下一个字段标签 */
.auth :deep(.el-form-item__error) {
  position: static;
  width: 100%;
  padding-top: 4px;
  font-size: 11.5px;
  line-height: 1.6;
  color: #b2352b;
}

.submit {
  width: 100%;
  height: 42px;
  margin-top: 8px;
  border: 1px solid transparent;
  border-radius: 6px;
  font-size: 15px;
  font-weight: 500;
  letter-spacing: 0.08em;
  background: var(--accent);
  transition:
    background-color 0.15s ease,
    transform 0.1s ease;
}

.submit:not(:disabled):hover {
  background: #1e46b5;
}

.submit:not(:disabled):active {
  background: var(--accent-press);
  transform: translateY(1px);
}

.submit:focus-visible {
  outline: 2px solid rgba(36, 83, 207, 0.4);
  outline-offset: 2px;
}

.auth-hint {
  margin: 20px 0 0;
  font-size: 12px;
  line-height: 1.7;
  color: var(--ink-3);
}

/* ============ 页脚 ============ */
.page-foot {
  flex: none;
  border-top: 1px solid var(--hairline);
  font-size: 12px;
  color: var(--ink-3);
  letter-spacing: 0.01em;
}

.page-foot .page-inner {
  height: 48px;
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.foot-note {
  color: var(--ink-3);
}

/* ============ 入场：短距离、低幅度 ============ */
@media (prefers-reduced-motion: no-preference) {
  .page-head {
    animation: fade-down 0.4s cubic-bezier(0.22, 0.61, 0.36, 1) both;
  }

  .intro-title {
    animation: rise 0.45s cubic-bezier(0.22, 0.61, 0.36, 1) 0.04s both;
  }

  .intro-text {
    animation: rise 0.45s cubic-bezier(0.22, 0.61, 0.36, 1) 0.1s both;
  }

  .auth-head {
    animation: rise 0.45s cubic-bezier(0.22, 0.61, 0.36, 1) 0.12s both;
  }

  .auth :deep(.el-form) {
    animation: rise 0.45s cubic-bezier(0.22, 0.61, 0.36, 1) 0.16s both;
  }

  .auth-hint {
    animation: rise 0.45s cubic-bezier(0.22, 0.61, 0.36, 1) 0.2s both;
  }

  @keyframes rise {
    from {
      opacity: 0;
      transform: translateY(8px);
    }
    to {
      opacity: 1;
      transform: none;
    }
  }

  @keyframes fade-down {
    from {
      opacity: 0;
      transform: translateY(-4px);
    }
    to {
      opacity: 1;
      transform: none;
    }
  }
}

@media (prefers-reduced-motion: reduce) {
  .page-head,
  .intro-title,
  .intro-text,
  .auth-head,
  .auth :deep(.el-form),
  .auth-hint {
    animation: none;
  }
}

/* ============ 平板 ============ */
@media (max-width: 1024px) {
  .page-main {
    grid-template-columns: minmax(0, 1fr) 320px;
  }

  .intro-title {
    font-size: 30px;
  }
}

/* ============ 移动端：单列堆叠 ============ */
@media (max-width: 820px) {
  .page-head .page-inner {
    height: 56px;
  }

  .brand-sub,
  .brand-divider {
    display: none;
  }

  .head-note {
    display: none;
  }

  .page-main {
    grid-template-columns: 1fr;
    align-items: start;
    padding: 36px 20px 40px;
    gap: 26px;
  }

  .intro {
    padding-right: 0;
  }

  .intro-title {
    margin-bottom: 14px;
    font-size: 26px;
    line-height: 1.45;
  }

  .intro-text {
    max-width: none;
    font-size: 13px;
    line-height: 1.85;
  }

  .auth {
    padding-left: 0;
    padding-top: 28px;
  }

  .auth::before {
    left: 0;
    right: 0;
    top: 0;
    bottom: auto;
    width: auto;
    height: 1px;
    background: linear-gradient(
      to right,
      rgba(165, 187, 226, 0) 0%,
      #c3d4ee 12%,
      #c3d4ee 88%,
      rgba(165, 187, 226, 0) 100%
    );
  }

  .auth-head p {
    margin-bottom: 24px;
  }

  .page-foot .page-inner {
    height: 44px;
  }

  .foot-note {
    display: none;
  }
}
</style>
