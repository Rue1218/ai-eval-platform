<template>
  <div class="stress-admin-page">
    <!-- 1. 发压目标安全白名单 -->
    <div class="panel mb16">
      <div class="panel-title">
        <div class="row">
          <span>发压目标 Host 白名单</span>
          <span style="font-size: 12px; color: var(--accent-error); font-weight: 500">(目标未加入白名单时严禁启动压测)</span>
        </div>
        <button class="btn btn-primary btn-sm" @click="showAddWhitelistModal = true">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <line x1="12" y1="5" x2="12" y2="19"></line>
            <line x1="5" y1="12" x2="19" y2="12"></line>
          </svg>
          <span>添加白名单</span>
        </button>
      </div>

      <table class="ds-table">
        <thead>
          <tr>
            <th>目标 Host / IP</th>
            <th style="width: 140px">生效环境</th>
            <th style="width: 100px">创建者</th>
            <th style="width: 140px">创建时间</th>
            <th style="width: 100px; text-align: right">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="w in whitelist" :key="w.id">
            <td class="mono" style="font-weight: 600">{{ w.host }}</td>
            <td>
              <span class="kind-tag" style="background: var(--bg-elevated); color: var(--text-secondary)">{{ w.scope }}</span>
            </td>
            <td>{{ w.creator }}</td>
            <td class="mono" style="font-size: 12px; color: var(--text-tertiary)">{{ w.created_at }}</td>
            <td style="text-align: right">
              <button class="link-btn danger" @click="handleDeleteWhitelist(w)">删除</button>
            </td>
          </tr>
          <tr v-if="whitelist.length === 0">
            <td colspan="5" style="text-align: center; color: var(--accent-error); padding: 16px">
              ⚠ 暂无白名单目标，当前所有压测任务将保持在排队中 (queued + WHITELIST)
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- 2. 并发阈值与成本治理 -->
    <div class="panel mb16">
      <div class="panel-title">并发限制与成本预算</div>
      <div class="form-row-3 mb16">
        <div class="field">
          <label class="field-label">最大并发任务数 (max_running_tasks)</label>
          <n-input-number v-model:value="settings.max_running_tasks" :min="1" :max="10" />
        </div>
        <div class="field">
          <label class="field-label">最大在途模型调用 (max_inflight)</label>
          <n-input-number v-model:value="settings.max_inflight_model_calls" :min="1" :max="32" />
        </div>
        <div class="field">
          <label class="field-label">单任务默认预算上限 ($ USD)</label>
          <n-input-number v-model:value="settings.default_max_usd" :min="1" :max="100" />
        </div>
      </div>

      <div class="form-row mb16">
        <div class="field">
          <label class="field-label">默认发压 QPS 上限</label>
          <n-input-number v-model:value="settings.stress.max_qps" :min="10" :max="1000" />
        </div>
        <div class="field">
          <label class="field-label">默认最大时长 (秒)</label>
          <n-input-number v-model:value="settings.stress.max_duration_s" :min="60" :max="7200" />
        </div>
      </div>

      <div class="field">
        <label class="field-label">Token 估算单价 ($ / 1k tokens)</label>
        <n-input-number v-model:value="settings.stress.price_per_1k_tokens" :min="0.0001" :step="0.0005" />
      </div>
    </div>

    <!-- 3. 通知集成设置 -->
    <div class="panel mb16">
      <div class="panel-title">异常与结果通知推送 (默认关闭)</div>
      <div class="switch-row">
        <div>
          <div style="font-weight: 500; font-size: 13px">企业微信机器人 Webhook 通知</div>
          <div style="font-size: 12px; color: var(--text-tertiary)">压测任务完成或触发 SLA 拐点时推送到企微群</div>
        </div>
        <n-switch v-model:value="settings.notify.wecom" />
      </div>
      <div class="switch-row">
        <div>
          <div style="font-weight: 500; font-size: 13px">邮件通知</div>
          <div style="font-size: 12px; color: var(--text-tertiary)">向任务创建者发送包含 HTML 报告摘要的邮件</div>
        </div>
        <n-switch v-model:value="settings.notify.email" />
      </div>
      <div class="switch-row">
        <div>
          <div style="font-weight: 500; font-size: 13px">自定义出站 Webhook</div>
          <div style="font-size: 12px; color: var(--text-tertiary)">向第三方监控/告警系统推送 JSON Payload</div>
        </div>
        <n-switch v-model:value="settings.notify.webhook" />
      </div>
    </div>

    <!-- 底部保存按钮 -->
    <div class="row" style="justify-content: flex-end">
      <button class="btn btn-sign" :disabled="saving" @click="saveSettings">
        {{ saving ? '保存中...' : '保存压测治理配置' }}
      </button>
    </div>

    <!-- 添加白名单弹窗 -->
    <n-modal v-model:show="showAddWhitelistModal" preset="card" title="添加发压目标 Host 白名单" style="width: 460px">
      <div class="field mb16">
        <label class="field-label">Host / IP 地址 <span class="req">*</span></label>
        <n-input v-model:value="newHost" placeholder="例如：10.0.0.8 或 api.internal.eval" />
      </div>
      <div class="field mb16">
        <label class="field-label">允许发压环境</label>
        <n-input v-model:value="newScope" placeholder="test,staging" />
      </div>
      <template #footer>
        <div style="display: flex; gap: 8px; justify-content: flex-end">
          <n-button @click="showAddWhitelistModal = false">取消</n-button>
          <n-button type="primary" :loading="addingHost" @click="handleAddWhitelist">确认添加</n-button>
        </div>
      </template>
    </n-modal>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useMessage, useDialog } from 'naive-ui'
import { api } from '../api/http'
import type { AdminSettings, WhitelistItem } from '../api/types'

const message = useMessage()
const dialog = useDialog()

const saving = ref(false)
const whitelist = ref<WhitelistItem[]>([])

const showAddWhitelistModal = ref(false)
const newHost = ref('')
const newScope = ref('test,staging')
const addingHost = ref(false)

const settings = ref<AdminSettings>({
  agent_profile_id: '',
  max_running_tasks: 3,
  max_inflight_model_calls: 8,
  default_max_usd: 5,
  stress: {
    host_whitelist: [],
    max_qps: 500,
    max_duration_s: 1800,
    price_per_1k_tokens: 0.002,
  },
  notify: {
    wecom: false,
    email: false,
    webhook: false,
  },
  prod_approvers: ['admin'],
})

async function loadData() {
  try {
    const [s, w] = await Promise.all([api.admin.getSettings(), api.admin.getWhitelist()])
    settings.value = s
    whitelist.value = w
  } catch (err: any) {
    message.error(err.message || '加载配置失败')
  }
}

async function handleAddWhitelist() {
  if (!newHost.value.trim()) {
    message.warning('请输入 Host 地址')
    return
  }
  addingHost.value = true
  try {
    const item = await api.admin.addWhitelist({ host: newHost.value.trim(), scope: newScope.value })
    whitelist.value.push(item)
    message.success('已添加至白名单')
    showAddWhitelistModal.value = false
    newHost.value = ''
  } catch (err: any) {
    message.error(err.message || '添加失败')
  } finally {
    addingHost.value = false
  }
}

function handleDeleteWhitelist(item: WhitelistItem) {
  dialog.warning({
    title: `删除白名单「${item.host}」？`,
    content: '删除后，指向此 Host 的压测任务将无法执行。',
    positiveText: '确认删除',
    negativeText: '取消',
    onPositiveClick: async () => {
      try {
        await api.admin.deleteWhitelist(item.id)
        whitelist.value = whitelist.value.filter((x) => x.id !== item.id)
        message.success('已从白名单移除')
      } catch (err: any) {
        message.error(err.message || '删除失败')
      }
    },
  })
}

async function saveSettings() {
  saving.value = true
  try {
    await api.admin.updateSettings(settings.value)
    message.success('压测治理与安全配置已保存')
  } catch (err: any) {
    message.error(err.message || '保存配置失败')
  } finally {
    saving.value = false
  }
}

onMounted(loadData)
</script>

<style scoped>
.stress-admin-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.field {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.field-label {
  font-size: 13px;
  font-weight: 500;
  color: var(--text-secondary);
}
.field-label .req {
  color: var(--accent-error);
}
.form-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 14px;
}
.form-row-3 {
  display: grid;
  grid-template-columns: 1fr 1fr 1fr;
  gap: 14px;
}
.switch-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 0;
  border-bottom: 1px solid var(--border-subtle);
}
.switch-row:last-child {
  border-bottom: none;
}
</style>
