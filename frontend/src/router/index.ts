import { ElMessage } from 'element-plus'
import { createRouter, createWebHashHistory, type RouteRecordRaw } from 'vue-router'
import { useUserStore } from '@/stores/user'

const routes: RouteRecordRaw[] = [
  { path: '/login', name: 'login', component: () => import('@/views/Login.vue') },
  {
    path: '/change-password',
    name: 'change-password',
    component: () => import('@/views/ChangePassword.vue'),
    meta: { title: '修改初始密码' }
  },
  {
    path: '/',
    component: () => import('@/layout/index.vue'),
    redirect: '/dashboard',
    children: [
      { path: 'dashboard', name: 'dashboard', component: () => import('@/views/Dashboard.vue'), meta: { title: '公司看板', permission: 'report:company:view' } },
      { path: 'users', name: 'users', component: () => import('@/views/Users.vue'), meta: { title: '人员管理', permission: 'org:user:view' } },
      { path: 'depts', name: 'depts', component: () => import('@/views/Depts.vue'), meta: { title: '部门架构', permission: 'org:dept:view' } },
      { path: 'roles', name: 'roles', component: () => import('@/views/Roles.vue'), meta: { title: '角色权限', permission: 'org:role:view' } },
      { path: 'projects', name: 'projects', component: () => import('@/views/Projects.vue'), meta: { title: '项目周期', permission: 'project:view' } },
      // 项目详情独立成页：可刷新、可分享、可多标签并存；面包屑回挂到项目周期
      {
        path: 'projects/:id',
        name: 'project-detail',
        component: () => import('@/views/Projects.vue'),
        meta: { title: '项目详情', permission: 'project:view', parentPath: '/projects' }
      },
      { path: 'changes', name: 'changes', component: () => import('@/views/Changes.vue'), meta: { title: '变更记录', permission: 'change:view' } },
      // Bug 与生产问题共用一个页面，靠 meta.issueType 区分
      { path: 'bugs', name: 'bugs', component: () => import('@/views/Issues.vue'), meta: { title: 'Bug 列表', permission: 'issue:view', issueType: 'BUG' } },
      { path: 'prod-issues', name: 'prod-issues', component: () => import('@/views/Issues.vue'), meta: { title: '生产问题', permission: 'issue:view', issueType: 'PROD' } },
      // 问题详情独立成页：可刷新、可分享，面包屑回挂到对应列表
      {
        path: 'bugs/:id',
        name: 'bug-detail',
        component: () => import('@/views/IssueDetail.vue'),
        meta: { title: 'Bug 详情', permission: 'issue:view', issueType: 'BUG', parentPath: '/bugs' }
      },
      {
        path: 'prod-issues/:id',
        name: 'prod-issue-detail',
        component: () => import('@/views/IssueDetail.vue'),
        meta: { title: '生产问题详情', permission: 'issue:view', issueType: 'PROD', parentPath: '/prod-issues' }
      },
      { path: 'worklogs', name: 'worklogs', component: () => import('@/views/Worklogs.vue'), meta: { title: '工作日志', permission: 'worklog:view' } },
      { path: 'weeklies', name: 'weeklies', component: () => import('@/views/Weeklies.vue'), meta: { title: '周报总结', permission: 'worklog:view' } },
      { path: 'dept-board', name: 'dept-board', component: () => import('@/views/Reports.vue'), meta: { title: '部门看板', permission: 'report:dept:view' } },
      { path: 'reports', redirect: '/dept-board' },
      { path: 'crm', name: 'crm', component: () => import('@/views/Crm.vue'), meta: { title: '客户与商机', permission: 'crm:customer:view' } },
      { path: 'products', name: 'products', component: () => import('@/views/Products.vue'), meta: { title: '产品列表', permission: 'crm:product:view' } },
      { path: 'configs', name: 'configs', component: () => import('@/views/Configs.vue'), meta: { title: '规则参数', permission: 'sys:config' } },
      { path: 'messages', name: 'messages', component: () => import('@/views/Messages.vue'), meta: { title: '我的消息' } },
      { path: 'mail', name: 'mail', component: () => import('@/views/Mail.vue'), meta: { title: '邮件中心', permission: 'sys:config' } },
      { path: 'audit', name: 'audit', component: () => import('@/views/Audit.vue'), meta: { title: '审计留痕', permission: 'sys:log:view' } },
      { path: '403', name: 'forbidden', component: () => import('@/views/Forbidden.vue'), meta: { title: '无权访问' } }
    ]
  }
]

const layoutRoute = routes.find((route) => route.path === '/')

/** 按权限点找到第一个可访问的页面（登录落地页 / 403 兜底）。 */
export const firstAccessiblePath = (has: (code: string) => boolean): string => {
  for (const child of layoutRoute?.children ?? []) {
    // 兼容旧地址的重定向路由、带参数的详情路由不作为落地页候选
    if ('redirect' in child || String(child.path).includes(':')) continue
    const permission = child.meta?.permission as string | undefined
    if (!permission || has(permission)) {
      return `/${String(child.path)}`
    }
  }
  return '/403'
}

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
  // 初始密码未修改：强制留在改密页，其余页面一律拦回
  if (store.mustChangePassword) {
    return to.path === '/change-password' ? true : { path: '/change-password' }
  }
  if (to.path === '/change-password') {
    return { path: firstAccessiblePath((code) => store.has(code)) }
  }

  // 页面级权限：无对应权限点时不进该页（后端仍会二次校验）
  const required = to.meta.permission as string | undefined
  if (required && !store.has(required)) {
    const fallback = firstAccessiblePath((code) => store.has(code))
    ElMessage.warning('无权访问该页面')
    return { path: fallback === to.path ? '/403' : fallback }
  }
  return true
})
