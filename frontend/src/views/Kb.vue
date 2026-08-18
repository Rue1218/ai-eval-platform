<template>
  <div class="kb-page">
    <!-- 顶部状态栏 -->
    <div class="row-between mb16">
      <div class="row">
        <span style="font-size: 16px; font-weight: 600">知识库与 RAG 评测工作台</span>
        <span class="mono" style="font-size: 12px; color: var(--text-tertiary)">({{ kbs.length }} 个库)</span>
      </div>

      <div class="row">
        <button class="btn btn-primary btn-sm" @click="showCreateKbModal = true">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <line x1="12" y1="5" x2="12" y2="19"></line>
            <line x1="5" y1="12" x2="19" y2="12"></line>
          </svg>
          <span>新建知识库</span>
        </button>

        <button class="btn btn-secondary btn-sm" :disabled="loading" @click="loadKbs">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <polyline points="23 4 23 10 17 10"></polyline>
            <polyline points="1 20 1 14 7 14"></polyline>
            <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"></path>
          </svg>
          <span>刷新</span>
        </button>
      </div>
    </div>

    <!-- 知识库列表卡片 -->
    <div class="panel mb16">
      <div class="kb-grid">
        <div
          v-for="k in kbs"
          :key="k.id"
          class="kb-card"
          :class="{ active: currentKb?.id === k.id }"
          @click="selectKb(k)"
        >
          <div class="row-between">
            <div class="row" style="gap: 6px">
              <span v-if="k.is_core" style="color: var(--accent-warning); font-size: 16px" title="核心知识库">★</span>
              <span style="font-weight: 700; font-size: 14px">{{ k.name }}</span>
            </div>
            <span class="kind-tag" :class="k.kind === 'lightrag' ? 'kind-rag' : 'kind-benchmark'">
              {{ k.kind === 'lightrag' ? 'LightRAG' : '外部 Chat' }}
            </span>
          </div>

          <div class="row-between mt8" style="font-size: 12px; color: var(--text-secondary)">
            <span>{{ k.doc_count !== null ? `${k.doc_count} 篇文档` : '外部服务对接' }}</span>
            <span class="mono" style="color: var(--text-tertiary)">{{ k.owner }}</span>
          </div>
        </div>
      </div>
    </div>

    <!-- 选中知识库的管理面板 -->
    <div v-if="currentKb" class="panel">
      <div class="row-between mb16" style="padding-bottom: 12px; border-bottom: 1px solid var(--border-subtle)">
        <div class="row">
          <span style="font-size: 16px; font-weight: 700">{{ currentKb.name }}</span>
          <span class="kind-tag" :class="currentKb.kind === 'lightrag' ? 'kind-rag' : 'kind-benchmark'">
            {{ currentKb.kind === 'lightrag' ? 'LightRAG 混合图谱检索' : '外部 RAG 对话服务' }}
          </span>
        </div>

        <div class="row">
          <button class="btn btn-secondary btn-sm" @click="showLaunchDrawer = true">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <polygon points="5 3 19 12 5 21 5 3"></polygon>
            </svg>
            <span>发起 RAG 评测</span>
          </button>
        </div>
      </div>

      <!-- 选项卡切换：文档索引 / 检索召回测试 / 黄金问答集 -->
      <n-tabs type="line" animated>
        <!-- 1. 文档索引管理 -->
        <n-tab-pane name="docs" tab="文档索引库">
          <div class="row-between mb16">
            <div style="font-size: 12px; color: var(--text-tertiary)">
              内置库检索走 LightRAG Query 混合引擎；支持 PDF, Markdown, TXT, HTML。
            </div>
            <button class="btn btn-primary btn-sm" @click="showUploadDocModal = true">
              上传新文档
            </button>
          </div>

          <table class="ds-table">
            <thead>
              <tr>
                <th>文档名称</th>
                <th style="width: 100px">大小</th>
                <th style="width: 120px">索引状态</th>
                <th style="width: 100px; text-align: right">操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="doc in docs" :key="doc.doc_id">
                <td style="font-weight: 500">
                  <span class="row" style="gap: 6px">
                    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
                      <polyline points="14 2 14 8 20 8"></polyline>
                    </svg>
                    <span>{{ doc.filename }}</span>
                  </span>
                </td>
                <td class="mono" style="font-size: 12px">{{ doc.size }}</td>
                <td>
                  <span v-if="doc.status === 'indexed'" class="badge badge-succeeded">已索引</span>
                  <span v-else-if="doc.status === 'indexing'" class="badge badge-running">
                    <i class="bdot"></i>
                    索引中
                  </span>
                  <span v-else class="badge badge-failed">索引失败</span>
                </td>
                <td style="text-align: right">
                  <button class="link-btn danger" @click="handleDeleteDoc(doc)">删除</button>
                </td>
              </tr>
              <tr v-if="docs.length === 0">
                <td colspan="4">
                  <EmptyState title="暂无文档" description="点击上方「上传新文档」上传 PDF/MD 文档" />
                </td>
              </tr>
            </tbody>
          </table>
        </n-tab-pane>

        <!-- 2. 黄金问答集 (Gold QA) -->
        <n-tab-pane name="goldQa" tab="黄金问答集 (Gold QA)">
          <div class="row-between mb16">
            <div style="font-size: 12px; color: var(--text-tertiary)">
              黄金 QA 用于评测 RAG 召回率 Hit Rate@K 及问答准确率；无 expected_doc_ids 样本仅参与答案评分。
            </div>
            <button class="btn btn-primary btn-sm" @click="showUploadGoldQaModal = true">
              上传黄金问答集
            </button>
          </div>

          <table class="ds-table">
            <thead>
              <tr>
                <th>问答集名称</th>
                <th style="width: 80px">版本</th>
                <th style="width: 100px">总条数</th>
                <th style="width: 100px">创建者</th>
                <th style="width: 150px">创建时间</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="g in goldQAs" :key="g.id">
                <td style="font-weight: 600">{{ g.name }}</td>
                <td>
                  <span class="kind-tag" style="background: var(--bg-elevated); color: var(--text-secondary)">v{{ g.version }}</span>
                </td>
                <td class="mono">{{ g.row_count }} 条</td>
                <td>{{ g.owner }}</td>
                <td class="mono" style="font-size: 12px; color: var(--text-tertiary)">{{ formatDate(g.created_at) }}</td>
              </tr>
              <tr v-if="goldQAs.length === 0">
                <td colspan="5">
                  <EmptyState title="暂无黄金问答集" description="上传带标准答案与期望召回文档 ID 的测试问答集" />
                </td>
              </tr>
            </tbody>
          </table>
        </n-tab-pane>

        <!-- 3. 检索能力测试 -->
        <n-tab-pane name="query" tab="检索召回探活">
          <div class="query-box">
            <div class="row mb16">
              <n-input v-model:value="queryText" placeholder="输入测试查询语句..." style="flex: 1" />
              <n-select
                v-model:value="queryMode"
                style="width: 140px"
                :options="[
                  { label: 'Hybrid (混合)', value: 'hybrid' },
                  { label: 'Local (局部)', value: 'local' },
                  { label: 'Global (全局)', value: 'global' },
                  { label: 'Naive (传统)', value: 'naive' },
                ]"
              />
              <button class="btn btn-primary btn-sm" :disabled="querying || !queryText.trim()" @click="runQueryTest">
                {{ querying ? '检索中...' : '测试检索' }}
              </button>
            </div>

            <div v-if="queryResult" class="panel" style="background: var(--bg-elevated)">
              <div style="font-weight: 600; font-size: 13px; margin-bottom: 8px">检索回答预览:</div>
              <div style="font-size: 13.5px; line-height: 1.6; color: var(--text-primary); margin-bottom: 14px">
                {{ queryResult.response }}
              </div>

              <div style="font-weight: 600; font-size: 12.5px; margin-bottom: 8px; color: var(--c-kb)">召回切块与相似度:</div>
              <div v-for="c in queryResult.chunks" :key="c.chunk_id" class="chunk-item mb8">
                <div class="row-between">
                  <span class="mono" style="font-size: 11px; color: var(--c-kb); font-weight: 600">{{ c.chunk_id }} (来自 {{ c.doc_id }})</span>
                  <span class="mono" style="font-size: 11px">相似度: {{ (c.similarity * 100).toFixed(1) }}%</span>
                </div>
                <div style="font-size: 12px; color: var(--text-secondary); margin-top: 4px">{{ c.text }}</div>
              </div>
            </div>
          </div>
        </n-tab-pane>
      </n-tabs>
    </div>

    <!-- 弹窗与抽屉 -->
    <UploadKbDocModal
      v-model:show="showUploadDocModal"
      :kb="currentKb"
      @success="loadDocs"
    />

    <UploadGoldQaModal
      v-model:show="showUploadGoldQaModal"
      :kb="currentKb"
      @success="loadGoldQAs"
    />

    <RagLaunchDrawer
      v-model:show="showLaunchDrawer"
      :default-kb-id="currentKb?.id"
      @success="handleLaunchSuccess"
    />

    <!-- 新建知识库弹窗 -->
    <n-modal v-model:show="showCreateKbModal" preset="card" title="新建知识库" style="width: 460px">
      <div class="field mb16">
        <label class="field-label">知识库名称 <span class="req">*</span></label>
        <n-input v-model:value="newKbName" placeholder="例如：default 或 售后客服知识库" />
      </div>
      <div class="field mb16">
        <label class="field-label">类型</label>
        <n-select
          v-model:value="newKbKind"
          :options="[
            { label: 'LightRAG (内置混合图谱引擎)', value: 'lightrag' },
            { label: 'External Chat (外部对接 RAG 服务)', value: 'external_chat' },
          ]"
        />
      </div>
      <template #footer>
        <div style="display: flex; gap: 8px; justify-content: flex-end">
          <n-button @click="showCreateKbModal = false">取消</n-button>
          <n-button type="primary" :loading="creatingKb" @click="handleCreateKb">确认创建</n-button>
        </div>
      </template>
    </n-modal>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useMessage, useDialog } from 'naive-ui'
import { api } from '../api/http'
import type { KnowledgeBase, KbDocument, GoldQA } from '../api/types'
import EmptyState from '../components/common/EmptyState.vue'
import UploadKbDocModal from '../components/modals/UploadKbDocModal.vue'
import UploadGoldQaModal from '../components/modals/UploadGoldQaModal.vue'
import RagLaunchDrawer from '../components/drawers/RagLaunchDrawer.vue'

const router = useRouter()
const message = useMessage()
const dialog = useDialog()

const kbs = ref<KnowledgeBase[]>([])
const currentKb = ref<KnowledgeBase | null>(null)
const docs = ref<KbDocument[]>([])
const goldQAs = ref<GoldQA[]>([])
const loading = ref(false)

const showUploadDocModal = ref(false)
const showUploadGoldQaModal = ref(false)
const showLaunchDrawer = ref(false)

const showCreateKbModal = ref(false)
const newKbName = ref('')
const newKbKind = ref<'lightrag' | 'external_chat'>('lightrag')
const creatingKb = ref(false)

const queryText = ref('如何修改结算账户？')
const queryMode = ref('hybrid')
const querying = ref(false)
const queryResult = ref<any>(null)

function formatDate(d?: string) {
  if (!d) return ''
  return new Date(d).toLocaleDateString('zh-CN')
}

async function loadKbs() {
  loading.value = true
  try {
    kbs.value = await api.kb.list()
    if (kbs.value.length && !currentKb.value) {
      selectKb(kbs.value[0])
    }
  } catch (err: any) {
    message.error(err.message || '加载知识库列表失败')
  } finally {
    loading.value = false
  }
}

async function selectKb(kb: KnowledgeBase) {
  currentKb.value = kb
  loadDocs()
  loadGoldQAs()
}

async function loadDocs() {
  if (!currentKb.value) return
  try {
    docs.value = await api.kb.listDocs(currentKb.value.id)
  } catch (err) {
    docs.value = []
  }
}

async function loadGoldQAs() {
  if (!currentKb.value) return
  try {
    goldQAs.value = await api.kb.getGoldQA(currentKb.value.id)
  } catch (err) {
    goldQAs.value = []
  }
}

function handleDeleteDoc(doc: KbDocument) {
  dialog.warning({
    title: `删除文档「${doc.filename}」？`,
    content: '删除后对应的图谱实体与向量索引将被清理。',
    positiveText: '确认删除',
    negativeText: '取消',
    onPositiveClick: async () => {
      try {
        await api.kb.deleteDoc(currentKb.value!.id, doc.doc_id)
        message.success('文档已删除')
        loadDocs()
      } catch (err: any) {
        message.error(err.message || '删除失败')
      }
    },
  })
}

async function runQueryTest() {
  if (!currentKb.value || !queryText.value.trim()) return
  querying.value = true
  try {
    queryResult.value = await api.kb.query(currentKb.value.id, {
      query: queryText.value,
      mode: queryMode.value,
    })
  } catch (err: any) {
    message.error(err.message || '检索测试失败')
  } finally {
    querying.value = false
  }
}

async function handleCreateKb() {
  if (!newKbName.value.trim()) {
    message.warning('请输入知识库名称')
    return
  }
  creatingKb.value = true
  try {
    const created = await api.kb.create({ name: newKbName.value, kind: newKbKind.value })
    message.success('知识库已创建')
    showCreateKbModal.value = false
    newKbName.value = ''
    loadKbs()
    selectKb(created)
  } catch (err: any) {
    message.error(err.message || '创建失败')
  } finally {
    creatingKb.value = false
  }
}

function handleLaunchSuccess(taskId: string) {
  router.push('/tasks')
}

onMounted(loadKbs)
</script>

<style scoped>
.kb-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.kb-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 12px;
}
.kb-card {
  padding: 14px 16px;
  border-radius: 14px;
  border: 1px solid var(--border-subtle);
  background: var(--bg-elevated);
  cursor: pointer;
  transition: all 0.15s ease;
}
.kb-card:hover {
  border-color: var(--accent-ai);
}
.kb-card.active {
  border-color: var(--c-kb);
  background: var(--bg-main);
  box-shadow: 0 0 0 1px var(--c-kb);
}

.chunk-item {
  padding: 8px 12px;
  background: var(--bg-main);
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
}
</style>
