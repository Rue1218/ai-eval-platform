<template>
  <div class="app" :class="{ folded: theme.collapsed }">
    <!-- 侧边栏 -->
    <button v-if="mobileNavOpen" class="mobile-nav-backdrop" aria-label="关闭导航菜单" @click="closeMobileNavigation"></button>
    <aside class="sidebar" :class="{ 'mobile-open': mobileNavOpen }">
      <div class="brand" @click="theme.toggleCollapsed()" title="点击折叠/展开侧栏">
        <div class="brand-mark">A</div>
        <div class="brand-text">
          <div class="brand-name">AI Eval</div>
          <div class="brand-sub">TEST & EVAL</div>
        </div>
      </div>

      <nav class="nav">
        <!-- 评测组 -->
        <div class="nav-group">评测</div>
        <router-link
          v-for="item in evalRoutes"
          :key="item.path"
          :to="item.path"
          class="nav-item"
          :class="{ active: currentPath === item.path }"
          :style="currentPath === item.path ? { '--t': item.t, '--c': item.c } : {}"
          @click="closeMobileNavigation"
        >
          <span class="nav-ico">
            <component :is="item.icon" />
          </span>
          <span class="nav-label">{{ item.label }}</span>
        </router-link>

        <!-- 管理组 -->
        <div class="nav-group">管理</div>
        <router-link
          v-for="item in adminRoutes"
          :key="item.path"
          :to="item.path"
          class="nav-item"
          :class="{ active: currentPath === item.path }"
          :style="currentPath === item.path ? { '--t': item.t, '--c': item.c } : {}"
          @click="closeMobileNavigation"
        >
          <span class="nav-ico">
            <component :is="item.icon" />
          </span>
          <span class="nav-label">{{ item.label }}</span>
        </router-link>
      </nav>

      <!-- 侧边栏底部用户信息 -->
      <div class="sidebar-foot">
        <div class="user-card">
          <div class="avatar">{{ userInitial }}</div>
          <div class="user-meta">
            <div class="user-name">{{ auth.user?.username || 'admin' }}</div>
            <div class="user-role">平台成员</div>
          </div>
          <button class="logout-btn" @click="handleLogout" title="退出登录">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"></path>
              <polyline points="16 17 21 12 16 7"></polyline>
              <line x1="21" y1="12" x2="9" y2="12"></line>
            </svg>
          </button>
        </div>
      </div>
    </aside>

    <!-- 主视口卡片 -->
    <main class="main">
      <!-- 顶栏 -->
      <header class="topbar">
        <button class="mobile-nav-toggle" title="打开导航菜单" @click="toggleMobileNavigation">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
            <line x1="4" y1="6" x2="20" y2="6" />
            <line x1="4" y1="12" x2="20" y2="12" />
            <line x1="4" y1="18" x2="20" y2="18" />
          </svg>
        </button>
        <div class="topbar-title">
          <span>{{ currentTitle }}</span>
        </div>

        <!-- 居中测试对象模式切换 -->
        <div class="mode-switch" role="tablist">
          <button
            class="mode-opt"
            :class="{ on: modeStore.mode === 'llm' }"
            data-mode="llm"
            @click="modeStore.setMode('llm')"
            title="基础模型 / 对比评测 / 模型压测"
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" width="13" height="13">
              <rect x="6" y="6" width="12" height="12" rx="2"/><rect x="10" y="10" width="4" height="4"/>
              <path d="M9 3v3M15 3v3M9 18v3M15 18v3M3 9h3M3 15h3M18 9h3M18 15h3"/>
            </svg>
            <span class="mode-label">大模型</span>
            <i class="mode-dot"></i>
          </button>
          <button
            class="mode-opt"
            :class="{ on: modeStore.mode === 'rag' }"
            data-mode="rag"
            @click="modeStore.setMode('rag')"
            title="LightRAG / 外部 RAG / 知识库 / 黄金 QA"
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" width="13" height="13">
              <path d="M5 5.5A2.5 2.5 0 0 1 7.5 3H19v15H7.5A2.5 2.5 0 0 0 5 20.5Z"/><path d="M5 18.5V5.5"/><path d="M9 7.5h6"/>
            </svg>
            <span class="mode-label">RAG</span>
            <i class="mode-dot"></i>
          </button>
        </div>

        <!-- 右侧操作栏 -->
        <div class="topbar-actions">
          <!-- 数据源标记 -->
          <span
            class="data-source-badge"
            :class="api.isMock() ? 'mock' : 'live'"
            :title="api.isMock() ? 'Mock 模式：使用本地数据' : '实时模式：真实连接后端 API'"
          >
            {{ api.isMock() ? '◆ 示例 Mock' : '● 实时 API' }}
          </span>

          <!-- 主题切换 -->
          <button class="topbar-icon-btn" @click="theme.toggle()" :title="theme.mode === 'light' ? '切换深色模式' : '切换浅色模式'">
            <svg v-if="theme.mode === 'light'" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"></path>
            </svg>
            <svg v-else width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <circle cx="12" cy="12" r="5"></circle>
              <line x1="12" y1="1" x2="12" y2="3"></line>
              <line x1="12" y1="21" x2="12" y2="23"></line>
              <line x1="4.22" y1="4.22" x2="5.64" y2="5.64"></line>
              <line x1="18.36" y1="18.36" x2="19.78" y2="19.78"></line>
              <line x1="1" y1="12" x2="3" y2="12"></line>
              <line x1="21" y1="12" x2="23" y2="12"></line>
              <line x1="4.22" y1="19.78" x2="5.64" y2="18.36"></line>
              <line x1="18.36" y1="5.64" x2="19.78" y2="4.22"></line>
            </svg>
          </button>

          <!-- 改密入口 -->
          <button class="topbar-icon-btn" @click="showChangePwd = true" title="修改密码">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <rect x="3" y="11" width="18" height="11" rx="2" ry="2"></rect>
              <path d="M7 11V7a5 5 0 0 1 10 0v4"></path>
            </svg>
          </button>
        </div>
      </header>

      <!-- 视图呈现区 -->
      <section class="content" :class="{ flush: isFlushView }">
        <router-view />
      </section>
    </main>

    <!-- 首次改密 / 修改密码弹窗 -->
    <n-modal
      v-model:show="showChangePwd"
      preset="card"
      title="修改登录密码"
      style="width: 440px"
      :closable="!auth.mustChangePassword"
      :mask-closable="!auth.mustChangePassword"
    >
      <n-form ref="pwdFormRef" :model="pwdForm" label-placement="left" label-width="80">
        <n-form-item label="原密码" v-if="!auth.mustChangePassword">
          <n-input v-model:value="pwdForm.oldPassword" type="password" show-password-on="click" placeholder="输入当前密码" />
        </n-form-item>
        <n-form-item label="新密码">
          <n-input v-model:value="pwdForm.newPassword" type="password" show-password-on="click" placeholder="至少 8 位，包含字母与数字" />
        </n-form-item>
        <n-form-item label="确认密码">
          <n-input v-model:value="pwdForm.confirmPassword" type="password" show-password-on="click" placeholder="再次输入新密码" />
        </n-form-item>
      </n-form>
      <template #footer>
        <div style="display: flex; justify-content: flex-end; gap: 8px">
          <n-button v-if="!auth.mustChangePassword" @click="showChangePwd = false">取消</n-button>
          <n-button type="primary" :loading="pwdLoading" @click="submitChangePassword">确认修改</n-button>
        </div>
      </template>
    </n-modal>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, h } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useMessage, useDialog } from 'naive-ui'
import { useAuthStore } from '../stores/auth'
import { useThemeStore } from '../stores/theme'
import { useModeStore } from '../stores/mode'
import { api } from '../api/http'

const route = useRoute()
const router = useRouter()
const message = useMessage()
const dialog = useDialog()
const auth = useAuthStore()
const theme = useThemeStore()
const modeStore = useModeStore()

const showChangePwd = ref(auth.mustChangePassword)
const pwdLoading = ref(false)
const mobileNavOpen = ref(false)
const pwdForm = ref({
  oldPassword: '',
  newPassword: '',
  confirmPassword: '',
})

// 图标简易渲染
const IconAgent = () =>
  h('svg', { viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', strokeWidth: 2, strokeLinecap: 'round', strokeLinejoin: 'round' }, [
    h('path', { d: 'M12 2a2 2 0 0 1 2 2v2a2 2 0 0 1-2 2 2 2 0 0 1-2-2V4a2 2 0 0 1 2-2z' }),
    h('rect', { x: '4', y: '8', width: '16', height: '12', rx: '2' }),
    h('line', { x1: '9', y1: '13', x2: '9', y2: '13' }),
    h('line', { x1: '15', y1: '13', x2: '15', y2: '13' }),
  ])

const IconTasks = () =>
  h('svg', { viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', strokeWidth: 2, strokeLinecap: 'round', strokeLinejoin: 'round' }, [
    h('polyline', { points: '9 11 12 14 22 4' }),
    h('path', { d: 'M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11' }),
  ])

const IconDatasets = () =>
  h('svg', { viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', strokeWidth: 2, strokeLinecap: 'round', strokeLinejoin: 'round' }, [
    h('ellipse', { cx: '12', cy: '5', rx: '9', ry: '3' }),
    h('path', { d: 'M21 12c0 1.66-4 3-9 3s-9-1.34-9-3' }),
    h('path', { d: 'M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5' }),
  ])

const IconCases = () =>
  h('svg', { viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', strokeWidth: 2, strokeLinecap: 'round', strokeLinejoin: 'round' }, [
    h('path', { d: 'M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z' }),
    h('polyline', { points: '14 2 14 8 20 8' }),
    h('line', { x1: '16', y1: '13', x2: '8', y2: '13' }),
    h('line', { x1: '16', y1: '17', x2: '8', y2: '17' }),
    h('polyline', { points: '10 9 9 9 8 9' }),
  ])

const IconKb = () =>
  h('svg', { viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', strokeWidth: 2, strokeLinecap: 'round', strokeLinejoin: 'round' }, [
    h('path', { d: 'M4 19.5A2.5 2.5 0 0 1 6.5 17H20' }),
    h('path', { d: 'M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z' }),
  ])

const IconProfiles = () =>
  h('svg', { viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', strokeWidth: 2, strokeLinecap: 'round', strokeLinejoin: 'round' }, [
    h('rect', { x: '2', y: '2', width: '20', height: '8', rx: '2', ry: '2' }),
    h('rect', { x: '2', y: '14', width: '20', height: '8', rx: '2', ry: '2' }),
    h('line', { x1: '6', y1: '6', x2: '6.01', y2: '6' }),
    h('line', { x1: '6', y1: '18', x2: '6.01', y2: '18' }),
  ])

const IconStress = () =>
  h('svg', { viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', strokeWidth: 2, strokeLinecap: 'round', strokeLinejoin: 'round' }, [
    h('polygon', { points: '13 2 3 14 12 14 11 22 21 10 12 10 13 2' }),
  ])

const IconUsers = () =>
  h('svg', { viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', strokeWidth: 2, strokeLinecap: 'round', strokeLinejoin: 'round' }, [
    h('path', { d: 'M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2' }),
    h('circle', { cx: '9', cy: '7', r: '4' }),
    h('path', { d: 'M23 21v-2a4 4 0 0 0-3-3.87' }),
    h('path', { d: 'M16 3.13a4 4 0 0 1 0 7.75' }),
  ])

const evalRoutes = [
  { path: '/agent', label: '智能体', icon: IconAgent, t: 'var(--t-agent)', c: 'var(--c-agent)' },
  { path: '/tasks', label: '任务中心', icon: IconTasks, t: 'var(--t-tasks)', c: 'var(--c-tasks)' },
  { path: '/datasets', label: '数据集', icon: IconDatasets, t: 'var(--t-datasets)', c: 'var(--c-datasets)' },
  { path: '/cases', label: '用例', icon: IconCases, t: 'var(--t-cases)', c: 'var(--c-cases)' },
  { path: '/kb', label: '知识库', icon: IconKb, t: 'var(--t-kb)', c: 'var(--c-kb)' },
]

const adminRoutes = [
  { path: '/admin/profiles', label: '协议档', icon: IconProfiles, t: 'var(--t-profiles)', c: 'var(--c-profiles)' },
  { path: '/admin/stress', label: '压测治理', icon: IconStress, t: 'var(--t-stress)', c: 'var(--c-stress)' },
  { path: '/admin/users', label: '账号', icon: IconUsers, t: 'var(--t-users)', c: 'var(--c-users)' },
]

const currentPath = computed(() => route.path)
const currentTitle = computed(() => (route.meta.title as string) || 'AI 测试与评估平台')
const isFlushView = computed(() => route.path.startsWith('/agent'))

const userInitial = computed(() => {
  const name = auth.user?.username || 'A'
  return name.charAt(0).toUpperCase()
})

// 移动端侧栏改为覆盖式导航，避免占用工作区横向空间。
function toggleMobileNavigation() {
  mobileNavOpen.value = !mobileNavOpen.value
}

function closeMobileNavigation() {
  // 路由切换或点击遮罩后关闭覆盖式移动导航。
  mobileNavOpen.value = false
}

function handleLogout() {
  dialog.warning({
    title: '退出登录？',
    content: '退出登录后，正在运行中的评测与压测任务不会停止。',
    positiveText: '确认退出',
    negativeText: '取消',
    onPositiveClick: async () => {
      await auth.logout()
      message.success('已退出登录')
      router.push('/login')
    },
  })
}

async function submitChangePassword() {
  if (!pwdForm.value.newPassword || pwdForm.value.newPassword.length < 8) {
    message.warning('新密码长度不能少于 8 位')
    return
  }
  if (pwdForm.value.newPassword !== pwdForm.value.confirmPassword) {
    message.warning('两次输入的新密码不一致')
    return
  }

  pwdLoading.value = true
  try {
    await auth.changePassword(pwdForm.value.newPassword, pwdForm.value.oldPassword)
    message.success('密码修改成功')
    showChangePwd.value = false
    pwdForm.value = { oldPassword: '', newPassword: '', confirmPassword: '' }
  } catch (err: any) {
    message.error(err.message || '密码修改失败')
  } finally {
    pwdLoading.value = false
  }
}
</script>

<style scoped>
.app {
  display: grid;
  grid-template-columns: var(--sidebar-w) 1fr;
  height: 100vh;
  transition: grid-template-columns var(--ease-shell);
}
.app.folded {
  grid-template-columns: var(--sidebar-w-fold) 1fr;
}
.mobile-nav-backdrop,
.mobile-nav-toggle {
  display: none;
}

.sidebar {
  display: flex;
  flex-direction: column;
  padding: 18px 14px;
  background: var(--sidebar-bg);
  backdrop-filter: blur(18px);
  -webkit-backdrop-filter: blur(18px);
  border-right: 1px solid rgba(255, 255, 255, 0.4);
  overflow: hidden;
  white-space: nowrap;
}

.brand {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 4px 8px 18px;
  cursor: pointer;
}
.brand-mark {
  width: 36px;
  height: 36px;
  flex: 0 0 36px;
  display: grid;
  place-items: center;
  border-radius: 10px;
  background: var(--text-primary);
  color: var(--bg-main);
  font-family: var(--font-display);
  font-weight: 700;
  font-size: 19px;
}
.brand-name {
  font-weight: 700;
  font-size: 15px;
  letter-spacing: -0.01em;
}
.brand-sub {
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: 0.14em;
  color: var(--text-tertiary);
}
.app.folded .brand-text {
  display: none;
}

.nav {
  flex: 1;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 3px;
}
.nav-group {
  margin: 14px 10px 6px;
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--text-tertiary);
}
.app.folded .nav-group {
  text-align: center;
  margin-inline: 0;
  font-size: 0;
}
.app.folded .nav-group::after {
  content: '·';
  font-size: 14px;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 12px;
  height: 44px;
  padding: 0 12px;
  border-radius: 14px;
  color: var(--text-secondary);
  font-size: 14px;
  font-weight: 500;
  transition: all 0.15s ease;
}
.nav-item:hover {
  background: var(--row-hover);
  color: var(--text-primary);
}
.nav-item .nav-ico {
  width: 20px;
  height: 20px;
  flex: 0 0 20px;
  display: grid;
  place-items: center;
}
.nav-item .nav-ico svg {
  width: 18px;
  height: 18px;
}
.app.folded .nav-item {
  justify-content: center;
  padding: 0;
}
.app.folded .nav-item .nav-label {
  display: none;
}
.nav-item.active {
  background: var(--t, var(--t-tasks));
  color: var(--c, var(--c-tasks));
  font-weight: 600;
}

.sidebar-foot {
  padding-top: 12px;
  border-top: 1px solid var(--border-subtle);
}
.user-card {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 10px;
  border-radius: 12px;
  background: var(--bg-elevated);
  border: 1px solid var(--border-subtle);
}
.app.folded .user-card {
  justify-content: center;
  padding: 8px 0;
  background: transparent;
  border-color: transparent;
}
.avatar {
  width: 30px;
  height: 30px;
  flex: 0 0 30px;
  border-radius: 50%;
  display: grid;
  place-items: center;
  background: var(--accent-ai);
  color: #fff;
  font-size: 12px;
  font-weight: 600;
}
.user-meta {
  min-width: 0;
  flex: 1;
}
.app.folded .user-meta {
  display: none;
}
.user-name {
  font-size: 13px;
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.user-role {
  font-size: 11px;
  color: var(--text-tertiary);
}
.logout-btn {
  background: none;
  border: 0;
  color: var(--text-tertiary);
  display: grid;
  place-items: center;
  padding: 4px;
  border-radius: 6px;
  transition: color 0.15s ease;
}
.logout-btn:hover {
  color: var(--accent-error);
}
.app.folded .logout-btn {
  display: none;
}

/* ─── 主内容区 ─── */
.main {
  margin: 10px 10px 10px 14px;
  border-radius: 18px;
  background: var(--bg-main);
  box-shadow: 0 12px 40px rgba(17, 24, 39, 0.08), 0 1px 3px rgba(17, 24, 39, 0.05);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  min-width: 0;
}
.topbar {
  position: relative;
  height: var(--topbar-h);
  flex: 0 0 var(--topbar-h);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 24px;
  border-bottom: 1px solid var(--border-subtle);
}
.topbar-title {
  font-size: 18px;
  font-weight: 600;
  display: flex;
  align-items: center;
  gap: 12px;
}
.topbar-actions {
  display: flex;
  align-items: center;
  gap: 12px;
}

.data-source-badge {
  display: inline-flex;
  align-items: center;
  height: 24px;
  padding: 0 8px;
  border-radius: 999px;
  border: 1px solid var(--border-subtle);
  font: 600 11px/1 var(--font-mono);
  letter-spacing: 0.01em;
  white-space: nowrap;
}
.data-source-badge.live {
  color: var(--accent-success);
  background: rgba(16, 185, 129, 0.08);
}
.data-source-badge.mock {
  color: var(--accent-warning);
  background: rgba(245, 158, 11, 0.1);
}

.topbar-icon-btn {
  width: 32px;
  height: 32px;
  border-radius: 8px;
  border: 1px solid var(--border-subtle);
  background: var(--bg-main);
  color: var(--text-secondary);
  display: grid;
  place-items: center;
  transition: all 0.15s ease;
}
.topbar-icon-btn:hover {
  border-color: var(--text-tertiary);
  color: var(--text-primary);
}

/* 顶栏大模型/RAG切换胶囊 */
.mode-switch {
  position: absolute;
  left: 50%;
  transform: translateX(-50%);
  display: flex;
  gap: 2px;
  padding: 3px;
  background: var(--bg-elevated);
  border: 1px solid var(--border-subtle);
  border-radius: 999px;
}
.mode-opt {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-height: 28px;
  padding: 3px 14px;
  border-radius: 999px;
  border: 1px solid transparent;
  background: transparent;
  font-size: 12px;
  font-weight: 600;
  color: var(--text-secondary);
  transition: all 0.16s ease;
}
.mode-opt .mode-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: currentColor;
  opacity: 0;
}
.mode-opt.on {
  background: var(--bg-main);
}
.mode-opt.on .mode-dot {
  opacity: 1;
}
.mode-opt.on[data-mode="llm"] {
  color: var(--c-datasets);
  border-color: rgba(29, 78, 216, 0.3);
}
.mode-opt.on[data-mode="rag"] {
  color: var(--c-kb);
  border-color: rgba(14, 116, 144, 0.3);
}

.content {
  flex: 1;
  overflow-y: auto;
  padding: 24px;
  min-height: 0;
}
.content.flush {
  padding: 0;
  display: flex;
  flex-direction: column;
}

@media (max-width: 700px) {
  .app,
  .app.folded {
    display: block;
    height: 100dvh;
  }
  .mobile-nav-backdrop {
    display: block;
    position: fixed;
    inset: 0;
    z-index: 20;
    border: 0;
    background: rgba(17, 24, 39, 0.38);
  }
  .sidebar {
    position: fixed;
    inset: 0 auto 0 0;
    z-index: 21;
    width: min(280px, calc(100vw - 52px));
    padding: 14px 12px;
    transform: translateX(-105%);
    transition: transform 0.2s ease;
    box-shadow: 12px 0 30px rgba(17, 24, 39, 0.2);
  }
  .sidebar.mobile-open {
    transform: translateX(0);
  }
  .app .brand-text,
  .app .nav-item .nav-label,
  .app .user-meta,
  .app.folded .brand-text,
  .app.folded .nav-item .nav-label,
  .app.folded .user-meta {
    display: block !important;
  }
  .app .nav-group,
  .app.folded .nav-group {
    margin: 14px 10px 6px;
    text-align: left;
    font-size: 10px;
  }
  .app .nav-group::after,
  .app.folded .nav-group::after {
    content: none;
  }
  .app .nav-item,
  .app.folded .nav-item {
    justify-content: flex-start !important;
    padding: 0 12px !important;
  }
  .app .user-card,
  .app.folded .user-card {
    justify-content: flex-start;
    padding: 8px 10px;
    background: var(--bg-elevated);
    border-color: var(--border-subtle);
  }
  .app .logout-btn,
  .app.folded .logout-btn {
    display: grid;
  }
  .main {
    height: 100dvh;
    margin: 0;
    border-radius: 0;
  }
  .topbar {
    height: 58px;
    flex-basis: 58px;
    padding: 0 10px;
  }
  .mobile-nav-toggle {
    display: grid;
    width: 34px;
    height: 34px;
    place-items: center;
    border: 1px solid var(--border-subtle);
    border-radius: 8px;
    background: var(--bg-main);
    color: var(--text-secondary);
  }
  .topbar-title,
  .data-source-badge {
    display: none;
  }
  .mode-switch {
    padding: 2px;
  }
  .mode-opt {
    min-height: 26px;
    padding: 2px 9px;
  }
  .topbar-actions {
    gap: 6px;
  }
  .content {
    padding: 12px;
  }
}
</style>
