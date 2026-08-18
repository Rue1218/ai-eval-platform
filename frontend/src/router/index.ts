import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'
import { useAuthStore, type Role } from '../stores/auth'

declare module 'vue-router' {
  interface RouteMeta {
    title?: string
    minRole?: Role
    public?: boolean
  }
}

const ROLE_LEVEL: Record<Role, number> = { readonly: 0, engineer: 1, admin: 2 }

// 路由表 = PRD 5.8（不得增减业务路由）
const routes: RouteRecordRaw[] = [
  {
    path: '/login',
    component: () => import('../views/Login.vue'),
    meta: { public: true, title: '登录' },
  },
  {
    path: '/',
    component: () => import('../layouts/MainLayout.vue'),
    children: [
      { path: '', redirect: '/agent' },
      { path: 'agent', component: () => import('../views/Agent.vue'), meta: { title: '智能体', minRole: 'engineer' } },
      { path: 'tasks', component: () => import('../views/Tasks.vue'), meta: { title: '任务中心', minRole: 'readonly' } },
      { path: 'reports/:id', component: () => import('../views/Report.vue'), meta: { title: '报告', minRole: 'readonly' } },
      { path: 'datasets', component: () => import('../views/Datasets.vue'), meta: { title: '数据集', minRole: 'engineer' } },
      { path: 'cases', component: () => import('../views/Cases.vue'), meta: { title: '用例', minRole: 'engineer' } },
      { path: 'kb', component: () => import('../views/Kb.vue'), meta: { title: '知识库', minRole: 'engineer' } },
      { path: 'admin/profiles', component: () => import('../views/AdminProfiles.vue'), meta: { title: '协议档', minRole: 'admin' } },
      { path: 'admin/stress', component: () => import('../views/AdminStress.vue'), meta: { title: '压测治理', minRole: 'admin' } },
      { path: 'admin/users', component: () => import('../views/AdminUsers.vue'), meta: { title: '账号', minRole: 'admin' } },
    ],
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

function canAccess(role: Role | undefined, minRole?: Role): boolean {
  if (!minRole) return true
  if (!role) return false
  return ROLE_LEVEL[role] >= ROLE_LEVEL[minRole]
}

router.beforeEach(async (to) => {
  const auth = useAuthStore()
  if (!auth.loaded) {
    await auth.fetchMe()
  }
  // 公开页（仅 /login）
  if (to.meta.public) {
    if (to.path === '/login' && auth.user) {
      return auth.user.role === 'readonly' ? '/tasks' : '/agent'
    }
    return true
  }
  // 未登录
  if (!auth.user) {
    return '/login'
  }
  // 越权：只读回 /tasks，其余回 /agent
  if (!canAccess(auth.user.role, to.meta.minRole)) {
    return auth.user.role === 'readonly' ? '/tasks' : '/agent'
  }
  return true
})

export default router
