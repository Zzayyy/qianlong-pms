<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, reactive, ref, watch, type Component } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  BarChart3,
  Briefcase,
  Building2,
  ChevronDown,
  ChevronRight,
  ClipboardList,
  FolderKanban,
  GitPullRequest,
  House,
  KeyRound,
  LayoutDashboard,
  LogOut,
  Menu,
  Network,
  NotebookPen,
  PanelLeftClose,
  PanelLeftOpen,
  ScrollText,
  Settings2,
  ShieldAlert,
  ShieldCheck,
  SlidersHorizontal,
  Users,
  X
} from 'lucide-vue-next'
import { changePassword, logout } from '@/api'
import { firstAccessiblePath } from '@/router'
import { useUserStore } from '@/stores/user'

interface NavLeaf {
  path: string
  label: string
  icon: Component
  permission: string
}

interface NavSection {
  key: string
  label: string
  items: NavLeaf[]
}

interface TabItem {
  path: string
  label: string
  icon: Component
}

const route = useRoute()
const router = useRouter()
const store = useUserStore()

/* ---------------- 侧边导航结构 ---------------- */
const navSections: NavSection[] = [
  {
    key: 'overview',
    label: '概览',
    items: [{ path: '/dashboard', label: '公司看板', icon: LayoutDashboard, permission: 'report:view' }]
  },
  {
    key: 'project',
    label: '项目',
    items: [
      { path: '/projects', label: '项目周期', icon: FolderKanban, permission: 'project:view' },
      { path: '/changes', label: '变更管理', icon: GitPullRequest, permission: 'change:view' }
    ]
  },
  {
    key: 'crm',
    label: '客户',
    items: [{ path: '/crm', label: '客户与商机', icon: Briefcase, permission: 'crm:customer:view' }]
  },
  {
    key: 'collab',
    label: '协同',
    items: [
      { path: '/worklogs', label: '工作日志', icon: NotebookPen, permission: 'worklog:view' },
      { path: '/reports', label: '统计看板', icon: BarChart3, permission: 'report:view' }
    ]
  },
  {
    key: 'org',
    label: '组织',
    items: [
      { path: '/users', label: '人员管理', icon: Users, permission: 'org:user:view' },
      { path: '/depts', label: '部门架构', icon: Network, permission: 'org:dept:view' }
    ]
  },
  {
    key: 'system',
    label: '系统',
    items: [
      { path: '/roles', label: '角色权限', icon: ShieldCheck, permission: 'org:role:view' },
      { path: '/configs', label: '规则参数', icon: SlidersHorizontal, permission: 'sys:config' },
      { path: '/audit', label: '审计留痕', icon: ScrollText, permission: 'sys:log:view' }
    ]
  }
]

const visibleSections = computed(() =>
  navSections
    .map((section) => ({
      ...section,
      items: section.items.filter((item) => store.has(item.permission))
    }))
    .filter((section) => section.items.length > 0)
)

const flatNav = computed(() =>
  visibleSections.value.flatMap((section) =>
    section.items.map((item) => ({ ...item, section: section.label, total: section.items.length }))
  )
)

/* ---------------- 断点与侧栏折叠 ---------------- */
const width = ref(window.innerWidth)
const onResize = () => {
  width.value = window.innerWidth
  if (width.value > 920) drawer.value = false
}
onMounted(() => window.addEventListener('resize', onResize))
onUnmounted(() => window.removeEventListener('resize', onResize))

const isCompact = computed(() => width.value <= 920)
const isMobile = computed(() => width.value <= 768)
const collapsed = ref(false)
const drawer = ref(false)

const go = (path: string) => {
  drawer.value = false
  if (route.path !== path) router.push(path)
}

/* ---------------- 面包屑 ---------------- */
const crumbs = computed(() => {
  const items: { label: string; path?: string }[] = [{ label: '首页', path: '/dashboard' }]
  const section = flatNav.value.find((item) => item.path === route.path)
  if (section && section.total > 1) {
    const first = visibleSections.value.find((entry) => entry.label === section.section)?.items[0]
    items.push({ label: section.section, path: first?.path })
  }
  const title = (route.meta.title as string) || ''
  if (title) items.push({ label: title })
  return items
})

/* ---------------- 标签栏 ---------------- */
const tabs = ref<TabItem[]>([])
const tabbar = ref<HTMLElement | null>(null)

const iconOf = (path: string) => {
  if (path === '/403') return ShieldAlert
  return flatNav.value.find((item) => item.path === path)?.icon ?? LayoutDashboard
}

if (store.has('report:view')) {
  tabs.value.push({ path: '/dashboard', label: '公司看板', icon: LayoutDashboard })
}

const scrollActiveTab = () => {
  const el = tabbar.value?.querySelector<HTMLElement>('.tab.is-active')
  if (!el) return
  const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches
  el.scrollIntoView({ inline: 'nearest', block: 'nearest', behavior: reduce ? 'auto' : 'smooth' })
}

const addTab = () => {
  if (!route.meta.title) return
  if (!tabs.value.some((tab) => tab.path === route.path)) {
    if (tabs.value.length >= 12) tabs.value.splice(1, 1)
    tabs.value.push({
      path: route.path,
      label: route.meta.title as string,
      icon: iconOf(route.path)
    })
  }
  nextTick(scrollActiveTab)
}

watch(() => route.path, addTab, { immediate: true })

const closeTab = (tab: TabItem) => {
  const index = tabs.value.findIndex((item) => item.path === tab.path)
  if (index < 0) return
  const isActive = route.path === tab.path
  tabs.value.splice(index, 1)
  if (isActive) {
    const next = tabs.value[index] ?? tabs.value[index - 1]
    go(next ? next.path : '/dashboard')
  }
}

/* ---------------- 用户 ---------------- */
const realName = computed(() => store.profile?.realName || '未登录')
const username = computed(() => store.profile?.username || '')
const initial = computed(() => (realName.value || username.value || 'U').slice(0, 1).toUpperCase())
const homePath = computed(() => firstAccessiblePath((code) => store.has(code)))
const userSubtitle = computed(() => {
  const parts = [username.value, store.profile?.deptName].filter(Boolean)
  return parts.length ? parts.join(' · ') : '系统用户'
})

const pwdVisible = ref(false)
const pwdSaving = ref(false)
const pwdForm = reactive({ oldPassword: '', newPassword: '', confirmPassword: '' })

const openPassword = () => {
  pwdForm.oldPassword = ''
  pwdForm.newPassword = ''
  pwdForm.confirmPassword = ''
  pwdVisible.value = true
}

const savePassword = async () => {
  if (pwdSaving.value) return
  if (!pwdForm.oldPassword) {
    ElMessage.warning('请输入原密码')
    return
  }
  if (pwdForm.newPassword.length < 8) {
    ElMessage.warning('新密码长度至少 8 位')
    return
  }
  if (pwdForm.newPassword !== pwdForm.confirmPassword) {
    ElMessage.warning('两次输入的新密码不一致')
    return
  }
  pwdSaving.value = true
  try {
    await changePassword(pwdForm.oldPassword, pwdForm.newPassword)
    pwdVisible.value = false
    ElMessage.success('密码已修改，请重新登录')
    store.logout()
    tabs.value = []
    router.push('/login')
  } catch {
    /* 错误提示由请求拦截器统一弹出，避免未处理的 Promise 拒绝 */
  } finally {
    pwdSaving.value = false
  }
}

const onUserCommand = async (command: string) => {
  if (command === 'password') {
    openPassword()
    return
  }
  if (command !== 'logout') return
  try {
    await ElMessageBox.confirm('确认退出当前账号？', '退出登录', {
      confirmButtonText: '退出',
      cancelButtonText: '取消',
      type: 'warning'
    })
  } catch {
    return
  }
  try {
    await logout()
  } catch {
    /* 令牌已失效也允许本地登出 */
  }
  store.logout()
  tabs.value = []
  router.push('/login')
}
</script>

<template>
  <div class="app">
    <aside v-if="!isCompact" class="app-side" :class="{ 'is-collapsed': collapsed }">
      <button class="side-brand" type="button" @click="go(homePath)">
        <span class="brand-mark" aria-hidden="true"><i></i><i></i><i></i><i></i></span>
        <span v-if="!collapsed" class="brand-text">
          <span class="brand-name">钱龙 PMS</span>
          <span class="brand-sub">项目管理系统</span>
        </span>
      </button>

      <nav class="side-nav">
        <div v-for="section in visibleSections" :key="section.key" class="side-section">
          <div v-if="!collapsed" class="side-label">{{ section.label }}</div>
          <div v-else class="side-divider" aria-hidden="true"></div>
          <button
            v-for="item in section.items"
            :key="item.path"
            type="button"
            class="side-item"
            :class="{ 'is-active': route.path === item.path }"
            :title="item.label"
            @click="go(item.path)"
          >
            <component :is="item.icon" :size="16" :stroke-width="1.75" />
            <span v-if="!collapsed" class="side-text">{{ item.label }}</span>
          </button>
        </div>
      </nav>
    </aside>

    <div class="app-body">
      <header class="app-header">
        <button
          v-if="isCompact"
          type="button"
          class="icon-btn"
          aria-label="打开导航"
          @click="drawer = true"
        >
          <Menu :size="18" :stroke-width="1.75" />
        </button>
        <button
          v-else
          type="button"
          class="icon-btn"
          :aria-label="collapsed ? '展开侧边栏' : '收起侧边栏'"
          @click="collapsed = !collapsed"
        >
          <component :is="collapsed ? PanelLeftOpen : PanelLeftClose" :size="17" :stroke-width="1.75" />
        </button>

        <span v-if="isCompact" class="compact-brand">
          <span class="brand-mark" aria-hidden="true"><i></i><i></i><i></i><i></i></span>
          <span class="brand-name">钱龙</span>
        </span>

        <nav v-if="!isMobile" class="crumbs" aria-label="面包屑">
          <template v-for="(crumb, index) in crumbs" :key="crumb.label + index">
            <ChevronRight v-if="index > 0" class="crumb-sep" :size="12" :stroke-width="2" />
            <button v-if="crumb.path && index < crumbs.length - 1" type="button" class="crumb-link" @click="go(crumb.path)">
              <House v-if="index === 0" :size="13" :stroke-width="1.9" />
              <span>{{ crumb.label }}</span>
            </button>
            <span v-else class="crumb-current">{{ crumb.label }}</span>
          </template>
        </nav>

        <div class="header-actions">
          <el-dropdown trigger="click" placement="bottom-end" popper-class="pms-nav-popper" @command="onUserCommand">
            <button type="button" class="user-btn">
              <span class="avatar">{{ initial }}</span>
              <span v-if="!isMobile" class="user-name">{{ realName }}</span>
              <ChevronDown v-if="!isMobile" class="user-caret" :size="13" :stroke-width="1.9" />
            </button>
            <template #dropdown>
              <el-dropdown-menu>
                <div class="popper-user">
                  <span class="pu-avatar">{{ initial }}</span>
                  <span class="pu-text">
                    <span class="pu-name">{{ realName }}</span>
                    <span class="pu-sub">{{ userSubtitle }}</span>
                    </span>
                    </div>
                    <el-dropdown-item command="password">
                    <KeyRound :size="15" :stroke-width="1.75" class="dd-icon" />
                    <span>修改密码</span>
                    </el-dropdown-item>
                    <el-dropdown-item divided command="logout">
                    <LogOut :size="15" :stroke-width="1.75" class="dd-icon" />
                    <span>退出登录</span>
                    </el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </header>

      <div class="tabs-bar">
        <div ref="tabbar" class="tabs" role="tablist">
          <div
            v-for="tab in tabs"
            :key="tab.path"
            class="tab"
            :class="{ 'is-active': route.path === tab.path }"
            role="tab"
            :aria-selected="route.path === tab.path"
            tabindex="0"
            @click="go(tab.path)"
            @keydown.enter.prevent="go(tab.path)"
          >
            <component :is="tab.icon" class="tab-icon" :size="14" :stroke-width="1.75" />
            <span class="tab-label">{{ tab.label }}</span>
            <span class="tab-close" role="button" aria-label="关闭标签" @click.stop="closeTab(tab)">
              <X :size="12" :stroke-width="2" />
            </span>
          </div>
        </div>
      </div>

      <main class="app-main">
        <RouterView v-slot="{ Component: viewComponent }">
          <transition name="page" mode="out-in">
            <component :is="viewComponent" :key="route.path" />
          </transition>
        </RouterView>
      </main>
    </div>

    <el-dialog v-model="pwdVisible" title="修改密码" width="90%" style="max-width: 420px">
      <el-form label-position="top" @submit.prevent="savePassword">
        <el-form-item label="原密码">
          <el-input
            v-model="pwdForm.oldPassword"
            type="password"
            show-password
            autocomplete="current-password"
            placeholder="请输入当前密码"
          />
        </el-form-item>
        <el-form-item label="新密码">
          <el-input
            v-model="pwdForm.newPassword"
            type="password"
            show-password
            autocomplete="new-password"
            placeholder="至少 8 位"
          />
        </el-form-item>
        <el-form-item label="确认新密码">
          <el-input
            v-model="pwdForm.confirmPassword"
            type="password"
            show-password
            autocomplete="new-password"
            placeholder="再次输入新密码"
            @keyup.enter="savePassword"
          />
        </el-form-item>
      </el-form>
      <p class="pwd-tip">修改后需要重新登录，其他设备的登录状态也会失效。</p>
      <template #footer>
        <el-button @click="pwdVisible = false">取消</el-button>
        <el-button type="primary" :loading="pwdSaving" @click="savePassword">保存</el-button>
      </template>
    </el-dialog>

    <el-drawer v-model="drawer" direction="ltr" size="264px" :with-header="false">
      <div class="drawer-head">
        <span class="brand-mark" aria-hidden="true"><i></i><i></i><i></i><i></i></span>
        <span class="brand-text">
          <span class="brand-name">钱龙 PMS</span>
          <span class="brand-sub">项目管理系统</span>
        </span>
      </div>
      <div class="drawer-body">
        <div v-for="section in visibleSections" :key="section.key" class="drawer-section">
          <div class="drawer-label">{{ section.label }}</div>
          <button
            v-for="item in section.items"
            :key="item.path"
            type="button"
            class="drawer-item"
            :class="{ 'is-active': route.path === item.path }"
            @click="go(item.path)"
          >
            <component :is="item.icon" :size="16" :stroke-width="1.75" />
            <span>{{ item.label }}</span>
          </button>
        </div>
      </div>
    </el-drawer>
  </div>
</template>

<style scoped>
.app {
  height: 100%;
  display: flex;
  background: var(--pms-bg);
}

/* ---------------- 左侧导航 ---------------- */
.app-side {
  flex: none;
  width: 224px;
  display: flex;
  flex-direction: column;
  background: var(--pms-surface);
  border-right: 1px solid var(--pms-line);
  overflow: hidden;
  transition: width 0.2s cubic-bezier(0.16, 1, 0.3, 1);
}

.app-side.is-collapsed {
  width: 68px;
}

.side-brand {
  flex: none;
  height: 56px;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 0 16px;
  border: 0;
  border-bottom: 1px solid var(--pms-line);
  background: transparent;
  text-align: left;
  cursor: pointer;
}

.is-collapsed .side-brand {
  justify-content: center;
  padding: 0;
}

.brand-mark {
  flex: none;
  display: grid;
  grid-template-columns: repeat(2, 6px);
  grid-auto-rows: 6px;
  gap: 2px;
}

.brand-mark i {
  background: var(--pms-text);
  border-radius: 1px;
}

.brand-mark i:nth-child(4) {
  background: var(--pms-primary);
}

.brand-text {
  display: flex;
  flex-direction: column;
  gap: 1px;
  white-space: nowrap;
}

.brand-name {
  font-size: 14px;
  font-weight: 600;
  letter-spacing: 0.02em;
  color: var(--pms-text);
}

.brand-sub {
  font-size: 11px;
  color: var(--pms-text-3);
  letter-spacing: 0.02em;
}

.side-nav {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 10px 10px 16px;
}

.side-section + .side-section {
  margin-top: 4px;
}

.side-label {
  padding: 9px 10px 5px;
  font-size: 11px;
  letter-spacing: 0.06em;
  color: var(--pms-text-3);
}

.side-divider {
  height: 1px;
  margin: 8px 6px;
  background: var(--pms-line-soft);
}

.side-item {
  position: relative;
  width: 100%;
  height: 36px;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 0 10px;
  border: 0;
  border-radius: var(--pms-radius-sm);
  background: transparent;
  color: var(--pms-text-2);
  font-size: 13.5px;
  text-align: left;
  white-space: nowrap;
  cursor: pointer;
  transition:
    background-color 0.16s ease,
    color 0.16s ease;
}

.side-item:hover {
  background: #f4f7fd;
  color: var(--pms-text);
}

.side-item.is-active {
  background: var(--pms-primary-weak);
  color: var(--pms-primary-deep);
  font-weight: 500;
}

.side-item.is-active::before {
  content: '';
  position: absolute;
  left: -10px;
  top: 9px;
  bottom: 9px;
  width: 2px;
  border-radius: 0 2px 2px 0;
  background: var(--pms-primary);
}

.is-collapsed .side-item {
  justify-content: center;
  padding: 0;
  gap: 0;
}

/* ---------------- 内容外壳 ---------------- */
.app-body {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
}

.app-header {
  flex: none;
  height: 56px;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 0 16px;
  background: var(--pms-surface);
  border-bottom: 1px solid var(--pms-line);
}

.icon-btn {
  flex: none;
  width: 32px;
  height: 32px;
  display: grid;
  place-items: center;
  border: 0;
  border-radius: var(--pms-radius-sm);
  background: transparent;
  color: var(--pms-text-3);
  cursor: pointer;
  transition:
    background-color 0.16s ease,
    color 0.16s ease;
}

.icon-btn:hover {
  background: #f4f7fd;
  color: var(--pms-text);
}

.compact-brand {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-right: 4px;
}

.compact-brand .brand-name {
  font-size: 13.5px;
}

/* ---------------- 面包屑 ---------------- */
.crumbs {
  flex: 1;
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 2px;
  overflow: hidden;
  font-size: 12.5px;
}

.crumb-link {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 3px 5px;
  border: 0;
  border-radius: 5px;
  background: transparent;
  color: var(--pms-text-3);
  font-size: 12.5px;
  white-space: nowrap;
  cursor: pointer;
  transition:
    color 0.16s ease,
    background-color 0.16s ease;
}

.crumb-link:hover {
  background: #f1f6ff;
  color: var(--pms-primary-deep);
}

.crumb-sep {
  flex: none;
  color: #c3ccdb;
}

.crumb-current {
  padding: 3px 5px;
  color: var(--pms-text);
  font-weight: 500;
  white-space: nowrap;
}

/* ---------------- 用户 ---------------- */
.header-actions {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 6px;
}

.user-btn {
  display: flex;
  align-items: center;
  gap: 8px;
  height: 32px;
  padding: 0 8px 0 5px;
  border: 0;
  border-radius: var(--pms-radius-sm);
  background: transparent;
  color: var(--pms-text-2);
  font-size: 13px;
  cursor: pointer;
  transition: background-color 0.16s ease;
}

.user-btn:hover {
  background: #f4f7fd;
}

.avatar {
  width: 25px;
  height: 25px;
  display: grid;
  place-items: center;
  border-radius: 50%;
  background: var(--pms-primary-weak);
  color: var(--pms-primary-deep);
  font-size: 12px;
  font-weight: 600;
}

.user-caret {
  color: #a8b1c1;
}

/* ---------------- 标签栏 ---------------- */
.tabs-bar {
  flex: none;
  height: 42px;
  display: flex;
  align-items: center;
  padding: 0 12px;
  background: var(--pms-surface);
  border-bottom: 1px solid var(--pms-line);
}

.tabs {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 6px 0;
  overflow-x: auto;
  scrollbar-width: none;
}

.tabs::-webkit-scrollbar {
  display: none;
}

.tab {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 28px;
  padding: 0 8px 0 10px;
  border: 1px solid transparent;
  border-radius: 7px;
  color: var(--pms-text-2);
  font-size: 12.5px;
  white-space: nowrap;
  cursor: pointer;
  outline: none;
  transition:
    background-color 0.16s ease,
    color 0.16s ease,
    border-color 0.16s ease;
}

.tab:hover {
  background: #f4f7fd;
  color: var(--pms-text);
}

.tab:focus-visible {
  border-color: var(--el-color-primary-light-5);
}

.tab.is-active {
  background: var(--pms-primary-weak);
  border-color: #dbe7ff;
  color: var(--pms-primary-deep);
  font-weight: 500;
}

.tab-icon {
  opacity: 0.85;
}

.tab-close {
  display: grid;
  place-items: center;
  width: 16px;
  height: 16px;
  margin-left: 2px;
  border-radius: 4px;
  opacity: 0;
  transition:
    opacity 0.15s ease,
    background-color 0.15s ease;
}

.tab:hover .tab-close,
.tab.is-active .tab-close {
  opacity: 0.6;
}

.tab-close:hover {
  opacity: 1;
  background: rgba(22, 35, 61, 0.08);
}

/* ---------------- 内容区 ---------------- */
.app-main {
  flex: 1;
  min-height: 0;
  overflow: auto;
  background: var(--pms-bg);
}

.page-enter-active,
.page-leave-active {
  transition:
    opacity 0.16s ease,
    transform 0.16s ease;
}

.page-enter-from {
  opacity: 0;
  transform: translateY(6px);
}

.page-leave-to {
  opacity: 0;
  transform: translateY(-4px);
}

/* ---------------- 抽屉导航 ---------------- */
.pwd-tip {
  margin: 2px 0 0;
  font-size: 12px;
  line-height: 1.6;
  color: var(--pms-text-3);
}

.drawer-head {
  height: 56px;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 0 16px;
  border-bottom: 1px solid var(--pms-line);
}

.drawer-body {
  padding: 10px;
  overflow-y: auto;
}

.drawer-section + .drawer-section {
  margin-top: 4px;
}

.drawer-label {
  padding: 9px 10px 5px;
  font-size: 11px;
  letter-spacing: 0.06em;
  color: var(--pms-text-3);
}

.drawer-item {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 9px 10px;
  border: 0;
  border-radius: var(--pms-radius-sm);
  background: transparent;
  color: var(--pms-text-2);
  font-size: 13.5px;
  text-align: left;
  cursor: pointer;
  transition:
    background-color 0.16s ease,
    color 0.16s ease;
}

.drawer-item:hover {
  background: #f4f7fd;
  color: var(--pms-text);
}

.drawer-item.is-active {
  background: var(--pms-primary-weak);
  color: var(--pms-primary-deep);
  font-weight: 500;
}

@media (max-width: 768px) {
  .app-header {
    height: 52px;
    padding: 0 12px;
  }

  .tabs-bar {
    height: 40px;
    padding: 0 8px;
  }
}

@media (prefers-reduced-motion: reduce) {
  .app-side,
  .page-enter-active,
  .page-leave-active {
    transition: none;
  }
}
</style>

<style>
/* 下拉面板需全局样式（挂载在 body 下） */
.pms-nav-popper.el-popper {
  border-radius: 10px;
  border-color: var(--pms-line);
  box-shadow: 0 12px 32px -12px rgba(16, 35, 70, 0.22);
}

.pms-nav-popper.el-popper .el-popper__arrow::before {
  border-color: var(--pms-line);
}

.pms-nav-popper .el-dropdown-menu {
  padding: 6px;
}

.pms-nav-popper .el-dropdown-menu__item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  border-radius: 7px;
  font-size: 13px;
  color: var(--pms-text-2);
}

.pms-nav-popper .el-dropdown-menu__item:not(.is-disabled):focus,
.pms-nav-popper .el-dropdown-menu__item:not(.is-disabled):hover {
  background: #f4f7fd;
  color: var(--pms-primary-deep);
}

.pms-nav-popper .dd-icon {
  color: var(--pms-text-3);
}

.pms-nav-popper .el-dropdown-menu__item:hover .dd-icon {
  color: var(--pms-primary-deep);
}

.pms-nav-popper .popper-user {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 10px 10px;
}

.pms-nav-popper .pu-avatar {
  width: 30px;
  height: 30px;
  display: grid;
  place-items: center;
  border-radius: 50%;
  background: var(--pms-primary-weak);
  color: var(--pms-primary-deep);
  font-size: 13px;
  font-weight: 600;
}

.pms-nav-popper .pu-text {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.pms-nav-popper .pu-name {
  font-size: 13px;
  font-weight: 600;
  color: var(--pms-text);
}

.pms-nav-popper .pu-sub {
  font-size: 11.5px;
  color: var(--pms-text-3);
}
</style>
