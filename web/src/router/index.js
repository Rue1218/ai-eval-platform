import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '../stores/auth'

const routes = [
  { path: '/login', component: () => import('../views/Login.vue') },
  {
    path: '/',
    component: () => import('../layouts/MainLayout.vue'),
    children: [
      { path: '', redirect: '/agent' },
      { path: 'agent', component: () => import('../views/Agent.vue'), meta: { title: 'Agent 会话' } },
      { path: 'tasks', component: () => import('../views/Tasks.vue'), meta: { title: '任务中心' } },
      { path: 'profiles', component: () => import('../views/Profiles.vue'), meta: { title: '协议档' } },
      { path: 'datasets', component: () => import('../views/Placeholder.vue'), meta: { title: '数据集' } },
      { path: 'reports', component: () => import('../views/Placeholder.vue'), meta: { title: '报告' } },
      { path: 'kb', component: () => import('../views/Placeholder.vue'), meta: { title: '知识库' } },
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
  if (to.path !== '/login' && !auth.user) {
    return '/login'
  }
  if (to.path === '/login' && auth.user) {
    return '/agent'
  }
})

export default router
