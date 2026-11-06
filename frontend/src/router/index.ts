import { ElMessage } from 'element-plus'
import { createRouter, createWebHashHistory, type RouteRecordRaw } from 'vue-router'
import { useUserStore } from '@/stores/user'

const routes: RouteRecordRaw[] = [
  { path: '/login', name: 'login', component: () => import('@/views/Login.vue') },
  {
    path: '/',
    component: () => import('@/layout/index.vue'),
    redirect: '/dashboard',
    children: [
      { path: 'dashboard', name: 'dashboard', component: () => import('@/views/Dashboard.vue'), meta: { title: '公司看板', permission: 'report:view' } },
      { path: 'users', name: 'users', component: () => import('@/views/Users.vue'), meta: { title: '人员管理', permission: 'org:user:view' } },
      { path: 'depts', name: 'depts', component: () => import('@/views/Depts.vue'), meta: { title: '部门架构', permission: 'org:dept:view' } },
      { path: 'projects', name: 'projects', component: () => import('@/views/Projects.vue'), meta: { title: '项目周期', permission: 'project:view' } },
      { path: 'changes', name: 'changes', component: () => import('@/views/Changes.vue'), meta: { title: '变更管理', permission: 'change:view' } },
      { path: 'worklogs', name: 'worklogs', component: () => import('@/views/Worklogs.vue'), meta: { title: '工作日志', permission: 'worklog:view' } },
      { path: 'reports', name: 'reports', component: () => import('@/views/Reports.vue'), meta: { title: '统计看板', permission: 'report:view' } },
      { path: 'crm', name: 'crm', component: () => import('@/views/Crm.vue'), meta: { title: '客户与商机', permission: 'crm:customer:view' } },
      { path: 'configs', name: 'configs', component: () => import('@/views/Configs.vue'), meta: { title: '规则参数', permission: 'sys:config' } },
      { path: 'audit', name: 'audit', component: () => import('@/views/Audit.vue'), meta: { title: '审计留痕', permission: 'sys:log:view' } },
      { path: '403', name: 'forbidden', component: () => import('@/views/Forbidden.vue'), meta: { title: '无权访问' } }
    ]
  }
]

export const router = createRouter({
  history: createWebHashHistory(),
  routes
})

router.beforeEach(async (to) => {
  const store = useUserStore()
  if (to.path === '/login') {
    return true
  }
  if (!store.isLogin) {
    return { path: '/login', query: { redirect: to.fullPath } }
  }
  if (!store.profile) {
    try {
      await store.loadProfile()
    } catch {
      store.logout()
      return { path: '/login' }
    }
  }
  // 页面级权限：无对应权限点时不进该页（后端仍会二次校验）
  const required = to.meta.permission as string | undefined
  if (required && !store.has(required)) {
    ElMessage.warning('无权访问该页面')
    return { path: '/403' }
  }
  return true
})
