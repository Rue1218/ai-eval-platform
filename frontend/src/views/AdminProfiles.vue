<template>
  <div class="profiles-page">
    <!-- 顶部指定 Agent 后端设置 -->
    <div class="panel mb16">
      <div class="panel-title">智能体后台模型配置 (Agent Backend)</div>
      <div class="row" style="gap: 16px">
        <div style="font-size: 13px; color: var(--text-secondary)">
          指定系统唯一的 Agent 决策后台协议档：
        </div>
        <n-select
          v-model:value="selectedAgentProfileId"
          style="width: 260px"
          :options="agentProfileOptions"
          @update:value="handleUpdateAgentProfile"
        />
        <span class="mono" style="font-size: 12px; color: var(--text-tertiary)">
          (保存即刻全局生效)
        </span>
      </div>
    </div>

    <!-- 协议档列表 -->
    <div class="panel">
      <div class="panel-title">
        <div class="row">
          <span>大模型协议档列表</span>
          <span class="mono" style="font-size: 12px; color: var(--text-tertiary)">({{ profiles.length }} 个)</span>
        </div>

        <div class="row">
          <button class="btn btn-primary btn-sm" @click="openModal(null)">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <line x1="12" y1="5" x2="12" y2="19"></line>
              <line x1="5" y1="12" x2="19" y2="12"></line>
            </svg>
            <span>新增协议档</span>
          </button>

          <button class="btn btn-secondary btn-sm" :disabled="loading" @click="loadProfiles">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <polyline points="23 4 23 10 17 10"></polyline>
              <polyline points="1 20 1 14 7 14"></polyline>
              <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"></path>
            </svg>
            <span>刷新</span>
          </button>
        </div>
      </div>

      <table class="ds-table">
        <thead>
          <tr>
            <th>协议档名称</th>
            <th style="width: 160px">协议类型</th>
            <th style="width: 140px">模型标识</th>
            <th>Base URL</th>
            <th style="width: 180px">用途标签</th>
            <th style="width: 180px; text-align: right">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="p in profiles" :key="p.id">
            <td style="font-weight: 600; font-size: 14px">
              <span class="row" style="gap: 6px">
                <span v-if="p.id === selectedAgentProfileId" class="kind-tag kind-rag" style="font-size: 10px">Agent ●</span>
                <span>{{ p.name }}</span>
              </span>
            </td>
            <td>
              <span class="mono" style="font-size: 12px">{{ p.protocol }}</span>
            </td>
            <td>
              <span class="mono" style="font-size: 12px; font-weight: 500">{{ p.model }}</span>
            </td>
            <td>
              <span class="mono" style="font-size: 11.5px; color: var(--text-secondary)">{{ p.base_url }}</span>
            </td>
            <td>
              <div class="row" style="gap: 4px; flex-wrap: wrap">
                <span v-if="p.usages?.includes('target')" class="kind-tag kind-benchmark">被测</span>
                <span v-if="p.usages?.includes('judge')" class="kind-tag kind-cases">裁判</span>
                <span v-if="p.usages?.includes('agent')" class="kind-tag kind-rag">Agent</span>
              </div>
            </td>
            <td style="text-align: right">
              <div class="row" style="justify-content: flex-end; gap: 4px">
                <button class="link-btn" :disabled="checkingId === p.id" @click="handleCheck(p)">
                  {{ checkingId === p.id ? '检查中...' : '连通检查' }}
                </button>
                <button class="link-btn" @click="openModal(p)">编辑</button>
                <button
                  class="link-btn danger"
                  :disabled="p.id === selectedAgentProfileId"
                  :title="p.id === selectedAgentProfileId ? '当前档已被指定为 Agent 后端，禁止删除' : ''"
                  @click="handleDelete(p)"
                >
                  删除
                </button>
              </div>
            </td>
          </tr>

          <tr v-if="profiles.length === 0">
            <td colspan="6">
              <EmptyState title="暂无模型协议档" description="点击右上角新增 OpenAI / Anthropic 协议档">
                <template #action>
                  <button class="btn btn-primary btn-sm" @click="openModal(null)">新增协议档</button>
                </template>
              </EmptyState>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- 弹窗 -->
    <ProfileModal
      v-model:show="showModal"
      :profile="selectedProfile"
      @success="loadProfiles"
    />

    <CheckResultModal
      v-model:show="showCheckModal"
      :result="checkResult"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useMessage, useDialog } from 'naive-ui'
import { api } from '../api/http'
import type { Profile, ProfileCheckOut } from '../api/types'
import EmptyState from '../components/common/EmptyState.vue'
import ProfileModal from '../components/modals/ProfileModal.vue'
import CheckResultModal from '../components/modals/CheckResultModal.vue'

const message = useMessage()
const dialog = useDialog()

const profiles = ref<Profile[]>([])
const loading = ref(false)
const selectedAgentProfileId = ref<string | null>(null)

const showModal = ref(false)
const selectedProfile = ref<Profile | null>(null)

const showCheckModal = ref(false)
const checkResult = ref<ProfileCheckOut | null>(null)
const checkingId = ref<string | null>(null)

const agentProfileOptions = computed(() =>
  profiles.value.map((p) => ({ label: `${p.name} (${p.model})`, value: p.id })),
)

async function loadProfiles() {
  loading.value = true
  try {
    const [pList, settings] = await Promise.all([api.profiles.list(), api.admin.getSettings()])
    profiles.value = pList
    selectedAgentProfileId.value = settings.agent_profile_id || (pList.length ? pList[0].id : null)
  } catch (err: any) {
    message.error(err.message || '加载协议档失败')
  } finally {
    loading.value = false
  }
}

async function handleUpdateAgentProfile(profileId: string) {
  try {
    await api.admin.updateSettings({ agent_profile_id: profileId })
    message.success('Agent 后端模型已指定')
  } catch (err: any) {
    message.error(err.message || '设置失败')
  }
}

function openModal(profile: Profile | null) {
  selectedProfile.value = profile
  showModal.value = true
}

async function handleCheck(p: Profile) {
  checkingId.value = p.id
  try {
    const res = await api.profiles.check(p.id)
    checkResult.value = res
    showCheckModal.value = true
  } catch (err: any) {
    checkResult.value = { ok: false, error: err.message || '连接失败' }
    showCheckModal.value = true
  } finally {
    checkingId.value = null
  }
}

function handleDelete(p: Profile) {
  dialog.warning({
    title: `删除协议档「${p.name}」？`,
    content: '删除后，依赖此协议档的评测任务将无法再次发起。',
    positiveText: '确认删除',
    negativeText: '取消',
    onPositiveClick: async () => {
      try {
        await api.profiles.delete(p.id)
        message.success('协议档已删除')
        loadProfiles()
      } catch (err: any) {
        message.error(err.message || '删除失败')
      }
    },
  })
}

onMounted(loadProfiles)
</script>

<style scoped>
.profiles-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
</style>
