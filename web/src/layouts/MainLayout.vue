<template>
  <n-layout has-sider style="height: 100vh">
    <n-layout-sider bordered width="220">
      <div class="logo">AI 评测平台</div>
      <n-menu
        :value="activeKey"
        :options="menuOptions"
        @update:value="onSelect"
      />
    </n-layout-sider>
    <n-layout>
      <n-layout-header bordered class="header">
        <span class="title">{{ currentTitle }}</span>
        <n-space align="center">
          <n-tag size="small">{{ auth.user?.role }}</n-tag>
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

<script setup>
import { computed, h } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { NIcon } from 'naive-ui'
import { useAuthStore } from '../stores/auth'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const menuOptions = [
  { label: 'Agent 会话', key: 'agent' },
  { label: '任务中心', key: 'tasks' },
  { label: '协议档', key: 'profiles' },
  { label: '数据集', key: 'datasets' },
  { label: '报告', key: 'reports' },
  { label: '知识库', key: 'kb' },
]

const activeKey = computed(() => route.path.replace('/', '') || 'agent')
const currentTitle = computed(() => route.meta?.title || '')

function onSelect(key) {
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
  font-weight: bold;
  font-size: 16px;
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
}
</style>
