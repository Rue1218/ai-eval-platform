/**
 * AI 测试与评估平台 — 路由配置
 * 依据：docs/AI测试与评估平台-PRD.md (PRD 5.8 路由表，禁止增减业务路由)
 */
import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'
import { useAuthStore } from '../stores/auth'

declare module 'vue-router' {
  interface RouteMeta {
    title?: string
    public?: boolean
  }
}

// 路由表 = PRD 5.8
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
      { path: 'agent', component: () => import('../views/Agent.vue'), meta: { title: '智能体' } },
      { path: 'dispatch', component: () => import('../views/Dispatch.vue'), meta: { title: '调度中心' } },
      { path: 'tasks', component: () => import('../views/Tasks.vue'), meta: { title: '任务中心' } },
      { path: 'reports', component: () => import('../views/Report.vue'), meta: { title: '评测报告' } },
      { path: 'reports/:id', component: () => import('../views/Report.vue'), meta: { title: '评测报告' } },
      { path: 'datasets', component: () => import('../views/Datasets.vue'), meta: { title: '数据集' } },
      { path: 'cases', component: () => import('../views/Cases.vue'), meta: { title: '用例' } },
      { path: 'kb', component: () => import('../views/Kb.vue'), meta: { title: '知识库' } },
      { path: 'admin/profiles', component: () => import('../views/AdminProfiles.vue'), meta: { title: '协议档' } },
      { path: 'admin/stress', component: () => import('../views/AdminStress.vue'), meta: { title: '压测治理' } },
      { path: 'admin/users', component: () => import('../views/AdminUsers.vue'), meta: { title: '账号' } },
    ],
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.beforeEach(async (to) => {
  const auth = useAuthStore()
  if (!auth.loaded) {
    await auth.fetchMe()
  }

  // 报告分享链接免登录支持 (?share=...)
  if (to.path.startsWith('/reports/') && to.query.share) {
    return true
  }

  // 公开页（/login）
  if (to.meta.public) {
    if (to.path === '/login' && auth.user) {
      return '/agent'
    }
    return true
  }

  // 受保护路由：未登录跳 /login
  if (!auth.user) {
    return '/login'
  }

  return true
})

export default router
