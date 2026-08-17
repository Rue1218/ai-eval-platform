<template>
  <n-card title="协议档">
    <n-form inline>
      <n-form-item label="名称">
        <n-input v-model:value="form.name" placeholder="例如 OpenAI GPT-4o" style="width: 180px" />
      </n-form-item>
      <n-form-item label="协议">
        <n-select v-model:value="form.protocol" :options="protocols" style="width: 180px" />
      </n-form-item>
      <n-form-item label="Base URL">
        <n-input v-model:value="form.base_url" placeholder="https://api.openai.com" style="width: 240px" />
      </n-form-item>
      <n-form-item label="模型">
        <n-input v-model:value="form.model" placeholder="gpt-4o" style="width: 140px" />
      </n-form-item>
      <n-form-item label="API Key">
        <n-input v-model:value="form.api_key" type="password" show-password-on="click" placeholder="只写不回显" style="width: 200px" />
      </n-form-item>
      <n-button type="primary" @click="create">新增</n-button>
    </n-form>

    <n-data-table :columns="columns" :data="profiles" :loading="loading" :bordered="true" style="margin-top: 16px" />
  </n-card>
</template>

<script setup>
import { ref, onMounted, h } from 'vue'
import { NButton, useMessage } from 'naive-ui'
import http from '../api'

const message = useMessage()
const profiles = ref([])
const loading = ref(false)
const form = ref({ name: '', protocol: 'openai_chat', base_url: '', model: '', api_key: '' })

const protocols = [
  { label: 'OpenAI Chat', value: 'openai_chat' },
  { label: 'OpenAI Responses', value: 'openai_responses' },
  { label: 'Anthropic Messages', value: 'anthropic_messages' },
]

const columns = [
  { title: '名称', key: 'name' },
  { title: '协议', key: 'protocol' },
  { title: 'Base URL', key: 'base_url' },
  { title: '模型', key: 'model' },
  {
    title: '操作',
    key: 'actions',
    width: 100,
    render: (row) => h(NButton, { size: 'small', type: 'error', onClick: () => remove(row) }, { default: () => '删除' }),
  },
]

async function load() {
  loading.value = true
  try {
    const { data } = await http.get('/api/profiles')
    profiles.value = data
  } finally {
    loading.value = false
  }
}

async function create() {
  try {
    await http.post('/api/profiles', form.value)
    message.success('已新增')
    form.value = { name: '', protocol: 'openai_chat', base_url: '', model: '', api_key: '' }
    load()
  } catch (e) {
    message.error(e.response?.data?.detail || '新增失败')
  }
}

async function remove(row) {
  await http.delete(`/api/profiles/${row.id}`)
  load()
}

onMounted(load)
</script>
