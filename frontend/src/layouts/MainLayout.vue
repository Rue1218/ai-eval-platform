<template>
  <n-layout has-sider style="height: 100vh">
    <n-layout-sider
      bordered
      collapse-mode="width"
      :collapsed-width="72"
      :width="260"
      :collapsed="theme.collapsed"
      show-trigger
      @collapse="theme.collapsed = true"
      @expand="theme.collapsed = false"
    >
      <div class="logo">{{ theme.collapsed ? 'A' : 'AI Eval' }}</div>
      <n-menu :value="activeKey" :options="menuOptions" @update:value="onSelect" />
    </n-layout-sider>

    <n-layout>
      <n-layout-header bordered class="header">
        <span class="title">{{ currentTitle }}</span>
        <n-space align="center">
          <n-button size="small" quaternary @click="theme.toggle()">
            {{ theme.mode === 'light' ? '深色' : '浅色' }}
          </n-button>
          <n-tag size="small">{{ roleLabel }}</n-tag>
          <span>{{ auth.user?.username }}</span>
          <n-button size="small" @click="onLogout">退出</n-button>
        </n-space>
      </n-layout-header>

      <n-layout-content class="content">
        <router-view />
      </n-layout-content>
    </n-layout>
  </n-layout>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import type { MenuOption } from 'naive-ui'
import { useAuthStore } from '../stores/auth'
import { useThemeStore } from '../stores/theme'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const theme = useThemeStore()

function buildMenu(): MenuOption[] {
  const items: MenuOption[] = []

  const evalGroup: MenuOption[] = []
  // 只读看不到 Agent 与写入口（数据集/用例/知识库）
  if (auth.user && auth.user.role !== 'readonly') {
    evalGroup.push({ key: 'agent', label: '智能体' })
  }
  evalGroup.push({ key: 'tasks', label: '任务中心' })
  if (auth.user && auth.user.role !== 'readonly') {
    evalGroup.push(
      { key: 'datasets', label: '数据集' },
      { key: 'cases', label: '用例' },
      { key: 'kb', label: '知识库' },
    )
  }
  items.push({ key: 'eval', label: '评测', type: 'group', children: evalGroup } as MenuOption)

  if (auth.user?.role === 'admin') {
    items.push({
      key: 'admin',
      label: '管理',
      type: 'group',
      children: [
        { key: 'admin/profiles', label: '协议档' },
        { key: 'admin/stress', label: '压测治理' },
        { key: 'admin/users', label: '账号' },
      ],
    } as MenuOption)
  }

  return items
}

const menuOptions = computed<MenuOption[]>(() => buildMenu())

const activeKey = computed(() => {
  const p = route.path.replace(/^\//, '')
  return p === '' ? 'agent' : p
})

const currentTitle = computed(() => (route.meta.title as string) || '')

const roleLabel = computed(() => {
  const map: Record<string, string> = { admin: '管理员', engineer: '工程师', readonly: '只读' }
  return auth.user ? map[auth.user.role] || auth.user.role : ''
})

function onSelect(key: string) {
  router.push('/' + key)
}

async function onLogout() {
  await auth.logout()
  router.push('/login')
}
</script>

<style scoped>
.logo {
  height: 56px;
  line-height: 56px;
  text-align: center;
  font-weight: 700;
  font-size: 16px;
  color: var(--accent-ai);
}
.header {
  height: 56px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 20px;
}
.title {
  font-size: 16px;
  font-weight: 600;
}
.content {
  padding: 20px;
  overflow: auto;
  background: var(--bg-main);
}
</style>
