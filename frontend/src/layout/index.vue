<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessageBox } from 'element-plus'
import { Fold, Expand, SwitchButton } from '@element-plus/icons-vue'
import { useUserStore } from '@/stores/user'
import { logout } from '@/api'

const route = useRoute()
const router = useRouter()
const store = useUserStore()

const collapsed = ref(false)
const drawer = ref(false)
const isMobile = ref(window.innerWidth <= 768)

const onResize = () => {
  isMobile.value = window.innerWidth <= 768
  if (!isMobile.value) {
    drawer.value = false
  } else {
    collapsed.value = false
  }
}
onMounted(() => window.addEventListener('resize', onResize))
onUnmounted(() => window.removeEventListener('resize', onResize))

const title = computed(() => (route.meta.title as string) || 'PMS')
const realName = computed(() => store.profile?.realName || '')
// 菜单按「页面级权限点」过滤：无权限的入口直接不展示
const visibleMenus = computed(() =>
  menus.filter((menu) => !menu.permission || store.has(menu.permission))
)

const menus = [
  { path: '/dashboard', label: '公司看板', icon: 'DataLine', permission: 'report:view' },
  { path: '/users', label: '人员管理', icon: 'User', permission: 'org:user:view' },
  { path: '/depts', label: '部门架构', icon: 'OfficeBuilding', permission: 'org:dept:view' },
  { path: '/projects', label: '项目周期', icon: 'FolderOpened', permission: 'project:view' },
  { path: '/changes', label: '变更管理', icon: 'Refresh', permission: 'change:view' },
  { path: '/worklogs', label: '工作日志', icon: 'EditPen', permission: 'worklog:view' },
  { path: '/reports', label: '统计看板', icon: 'Histogram', permission: 'report:view' },
  { path: '/crm', label: '客户与商机', icon: 'Shop', permission: 'crm:customer:view' },
  { path: '/configs', label: '规则参数', icon: 'Setting', permission: 'sys:config' },
  { path: '/audit', label: '审计留痕', icon: 'Document', permission: 'sys:log:view' }
]

const go = (path: string) => {
  drawer.value = false
  router.push(path)
}

const onLogout = async () => {
  await ElMessageBox.confirm('确认退出登录？', '提示', { type: 'warning' })
  try {
    await logout()
  } catch {
    /* 令牌已失效也允许本地登出 */
  }
  store.logout()
  router.push('/login')
}
</script>

<template>
  <el-container class="pms-layout">
    <el-aside v-if="!isMobile" :width="collapsed ? '64px' : '200px'" class="pms-aside">
      <div class="pms-logo">{{ collapsed ? 'PMS' : 'PMS 项目管理系统' }}</div>
      <el-menu :default-active="route.path" :collapse="collapsed" router>
        <el-menu-item v-for="menu in visibleMenus" :key="menu.path" :index="menu.path" @click="go(menu.path)">
          <span>{{ menu.label }}</span>
        </el-menu-item>
      </el-menu>
    </el-aside>

    <el-drawer v-model="drawer" direction="ltr" size="200px" :with-header="false">
      <el-menu :default-active="route.path" router>
        <el-menu-item v-for="menu in visibleMenus" :key="menu.path" :index="menu.path" @click="go(menu.path)">
          <span>{{ menu.label }}</span>
        </el-menu-item>
      </el-menu>
    </el-drawer>

    <el-container>
      <el-header class="pms-header">
        <el-button text @click="isMobile ? (drawer = true) : (collapsed = !collapsed)">
          <el-icon><component :is="isMobile ? Expand : collapsed ? Expand : Fold" /></el-icon>
        </el-button>
        <span class="pms-title">{{ title }}</span>
        <div class="pms-header-right">
          <el-tag size="small">{{ realName }}</el-tag>
          <el-button text :icon="SwitchButton" @click="onLogout">退出</el-button>
        </div>
      </el-header>
      <el-main>
        <RouterView />
      </el-main>
    </el-container>
  </el-container>
</template>

<style scoped>
.pms-layout {
  height: 100%;
}

.pms-aside {
  background: #fff;
  border-right: 1px solid #ebeef5;
  transition: width 0.2s;
}

.pms-logo {
  height: 56px;
  line-height: 56px;
  text-align: center;
  font-weight: 700;
  color: #3370ff;
  border-bottom: 1px solid #ebeef5;
  overflow: hidden;
  white-space: nowrap;
}

.pms-header {
  display: flex;
  align-items: center;
  gap: 8px;
  background: #fff;
  border-bottom: 1px solid #ebeef5;
}

.pms-title {
  font-weight: 600;
}

.pms-header-right {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 8px;
}
</style>
