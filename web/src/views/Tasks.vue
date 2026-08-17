<template>
  <n-card title="任务中心">
    <n-data-table
      :columns="columns"
      :data="tasks"
      :loading="loading"
      :pagination="false"
      :bordered="true"
    />
    <n-space style="margin-top: 16px">
      <n-button size="small" @click="load">刷新</n-button>
    </n-space>
  </n-card>
</template>

<script setup>
import { ref, onMounted, h } from 'vue'
import { NButton, NTag } from 'naive-ui'
import http from '../api'

const tasks = ref([])
const loading = ref(false)

const statusMap = {
  queued: 'default',
  running: 'info',
  succeeded: 'success',
  failed: 'error',
  cancelled: 'warning',
  awaiting_case_confirm: 'warning',
}

const columns = [
  { title: 'ID', key: 'id', width: 160, ellipsis: true },
  { title: '类型', key: 'kind', width: 100 },
  {
    title: '状态',
    key: 'status',
    width: 140,
    render: (row) => h(NTag, { type: statusMap[row.status] || 'default', size: 'small' }, { default: () => row.status }),
  },
  { title: '创建时间', key: 'created_at', width: 180, render: (row) => new Date(row.created_at).toLocaleString() },
  {
    title: '操作',
    key: 'actions',
    width: 160,
    render: (row) => {
      if (['queued', 'running'].includes(row.status)) {
        return h(NButton, { size: 'small', onClick: () => cancel(row) }, { default: () => '取消' })
      }
      return h(NButton, { size: 'small', onClick: () => rerun(row) }, { default: () => '重跑' })
    },
  },
]

async function load() {
  loading.value = true
  try {
    const { data } = await http.get('/api/tasks')
    tasks.value = data
  } finally {
    loading.value = false
  }
}

async function cancel(row) {
  await http.post(`/api/tasks/${row.id}/cancel`)
  load()
}

async function rerun(row) {
  await http.post(`/api/tasks/${row.id}/rerun`)
  load()
}

onMounted(load)
</script>
