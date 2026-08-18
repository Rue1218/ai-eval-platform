<template>
  <div class="kb-workbench">
    <div v-if="modeStore.mode === 'llm'" class="mode-context-panel panel">
      <span class="eyebrow">大模型测试模式</span>
      <h2>基准评测使用协议档与数据集</h2>
      <p>知识库、切块与黄金 QA 仅属于 RAG 测试链路。请切换到 RAG 模式管理检索资产；当前可前往数据集工作台准备 Benchmark 输入。</p>
      <router-link to="/datasets" class="btn btn-sign btn-sm">进入数据集工作台</router-link>
    </div>

    <template v-else>
    <!-- 顶部知识库选择与操作栏 -->
    <div class="kb-bar row-between mb16">
      <div class="row wrap" style="gap: 8px">
        <div class="chip-group">
          <button
            v-for="k in kbs"
            :key="k.id"
            class="chip"
            :class="{ on: activeKbId === k.id }"
            @click="selectKb(k)"
          >
            <span>{{ k.name }}</span>
            <!-- 核心库 ★ 标记置于名称之后并沿用默认色，对齐原型 kb.html。 -->
            <span v-if="k.is_core" style="margin-left: 4px">★</span>
          </button>
        </div>

        <span v-if="currentKb" class="kind-tag" :class="currentKb.kind === 'lightrag' ? 'kind-rag' : 'kind-benchmark'">
          {{ currentKb.kind === 'lightrag' ? 'lightrag · 原生 query' : 'external_chat · 仅 chat/completions' }}
        </span>
      </div>

      <div class="row" style="gap: 8px">
        <button class="btn btn-secondary btn-sm" @click="showCreateKbModal = true">+ 新建知识库</button>
        <button v-if="currentKb?.kind === 'lightrag'" class="btn btn-secondary btn-sm" @click="showUploadDocModal = true">
          ↑ 上传文档
        </button>
        <button class="btn btn-sign btn-sm" :disabled="!currentKb" @click="showLaunchDrawer = true">发起 RAG 评测</button>
      </div>
    </div>

    <!-- 3 栏网格工作区 -->
    <div v-if="currentKb && currentKb.kind === 'lightrag'" class="kb-grid-3col">
      <!-- 1. 左栏：文档与切块流 -->
      <div class="kb-col panel" style="overflow-y: auto; max-height: calc(100vh - 160px)">
        <div class="row-between mb8">
          <span class="rail-label" style="margin: 0">知识文档（{{ docs.length }}）</span>
          <button class="link-btn" style="font-size: 11px" @click="showUploadDocModal = true">+ 添加</button>
        </div>

        <!-- 库无文档空态：对齐原型，不再渲染下方的切块预览区。 -->
        <div v-if="!docs.length" class="empty" style="padding: 32px 20px">
          <div class="small tertiary">当前库暂无文档，点上方「↑ 上传文档」开始分块建索引；doc_id 由系统自动生成。</div>
        </div>

        <template v-else>
        <div class="section-gap" style="gap: 8px; margin-bottom: 18px">
          <div
            v-for="d in docs"
            :key="d.doc_id"
            class="doc-item"
            :class="{ on: activeDocId === d.doc_id }"
            @click="activeDocId = d.doc_id"
          >
            <span class="grow" style="min-width: 0">
              <span class="d-name" style="font-size: 13px; font-weight: 600; display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap">
                {{ d.filename }}
              </span>
              <span class="small tertiary mono">{{ d.size }} · {{ d.doc_id }}</span>
            </span>
            <span v-if="d.status === 'indexed'" class="badge badge-succeeded"><i class="bdot"></i>已索引</span>
            <span v-else class="badge badge-running"><i class="bdot"></i>索引中</span>
            <button class="link-btn danger" style="font-size: 11px" title="删除文档" @click.stop="handleDeleteDoc(d)">删除</button>
          </div>
        </div>

        <div class="row-between mb8">
          <span class="rail-label" style="margin: 0">切块预览 · {{ currentDoc?.filename || '文档' }}</span>
        </div>

        <div class="row mb12" style="gap: 8px">
          <select v-model="chunkSize" class="select" style="height: 30px; padding: 3px 24px 3px 10px; font-size: 12px; flex: 1">
            <option :value="256">chunk 256</option>
            <option :value="512">chunk 512</option>
            <option :value="1024">chunk 1024</option>
          </select>
          <select v-model="overlap" class="select" style="height: 30px; padding: 3px 24px 3px 10px; font-size: 12px; flex: 1">
            <option :value="0">overlap 0</option>
            <option :value="64">overlap 64</option>
            <option :value="128">overlap 128</option>
          </select>
        </div>

        <div v-if="chunkPreview.length" ref="chunkFlowRef" class="section-gap" style="gap: 8px">
          <div
            v-for="ck in chunkPreview"
            :key="ck.chunk_id"
            class="chunk"
            :class="{ hit: isChunkHit(ck.chunk_id), flash: flashChunkId === ck.chunk_id }"
            :data-chunk="ck.chunk_id"
          >
            <div class="row-between">
              <span class="ck-id mono">{{ ck.chunk_id }}</span>
              <span class="ck-tokens mono">{{ ck.tokens }} tok</span>
            </div>
            <div class="ck-text">{{ ck.text }}</div>
            <i v-if="overlap > 0" class="ck-ov" :style="{ width: `${Math.round((overlap / chunkSize) * 100)}%` }"></i>
          </div>
        </div>
        <!-- 服务端无切块返回时的空态提示。 -->
        <div v-else class="empty" style="padding: 24px 12px">
          <div class="small tertiary">服务端未返回切块预览。</div>
        </div>
        <!-- 分块策略说明：参数跟随当前预览选择，命中召回的切块会自动高亮。 -->
        <p class="small tertiary mt8">分块策略: chunk_size={{ chunkSize }} · overlap={{ overlap }}；命中召回的切块自动高亮。</p>
        </template>
      </div>

      <!-- 2. 中栏：检索 Playground -->
      <div class="kb-col panel" style="overflow-y: auto; max-height: calc(100vh - 160px)">
        <div class="row-between mb8">
          <span class="rail-label" style="margin: 0">检索 Playground · {{ queryMode }}</span>
          <div class="chip-group">
            <button
              v-for="m in ['hybrid', 'local', 'global', 'naive']"
              :key="m"
              class="chip"
              :class="{ on: queryMode === m }"
              @click="queryMode = m"
            >
              {{ m }}
            </button>
          </div>
        </div>

        <div class="row mb8" style="gap: 8px">
          <input
            v-model="queryText"
            class="input mono"
            style="font-size: 13px"
            placeholder="输入测试 Query 问句..."
            @keyup.enter="handleQuery"
          />
          <button class="btn btn-sign btn-sm" :disabled="isQuerying" @click="handleQuery">
            {{ isQuerying ? '检索中…' : '检索' }}
          </button>
        </div>

        <div class="row wrap mb12" style="gap: 6px; font-size: 12px">
          <span class="tertiary">快速填充:</span>
          <span
            v-for="q in ['退款多久到账？', '如何修改默认结算账户？', '发票开具申请入口在哪里？', '连续输错支付密码怎么办？']"
            :key="q"
            class="tag-soft quick-pill"
            @click="fillAndQuery(q)"
          >
            {{ q }}
          </span>
        </div>

        <!-- 向量空间 2D 降维投影仅在后端明确声明支持时展示。 -->
        <div v-if="supportsProjection" class="chart-box mb16">
          <div class="row-between mb8">
            <span class="small" style="font-weight: 600">向量空间 2D 降维投影 (Vector Projection)</span>
            <span class="small tertiary mono">bge-large-zh · 22 chunks</span>
          </div>

          <!-- 散点坐标按原型 kb.html 校准：viewBox 520×280，Query 点 (312,128.8)。 -->
          <svg class="scatter" viewBox="0 0 520 280">
            <circle v-if="queried" class="ring" cx="312" cy="128.8" r="96" />
            <!-- Top-5 召回邻域连线：由 Query 点指向 5 个命中散点。 -->
            <template v-if="queried">
              <line class="lk" x1="312" y1="128.8" x2="328" y2="196" />
              <line class="lk" x1="312" y1="128.8" x2="406" y2="185" />
              <line class="lk" x1="312" y1="128.8" x2="286" y2="45" />
              <line class="lk" x1="312" y1="128.8" x2="187" y2="185" />
              <line class="lk" x1="312" y1="128.8" x2="343" y2="84" />
            </template>
            <!-- 语料切块散点 -->
            <circle
              v-for="(p, i) in scatterPoints"
              :key="i"
              class="pt"
              :class="{ hit: queried && hitIndices.includes(i) }"
              :cx="p.x"
              :cy="p.y"
              :r="queried && hitIndices.includes(i) ? 5.5 : 3.4"
            />
            <!-- Query 点与波纹 -->
            <template v-if="queried">
              <circle class="pt-query" cx="312" cy="128.8" r="6" />
              <circle class="ring" cx="312" cy="128.8" r="14" style="opacity: 0.5" />
            </template>
          </svg>

          <div class="chart-legend" style="margin-top: 6px">
            <span><i style="background: var(--text-tertiary); opacity: 0.45"></i>语料切块</span>
            <span><i style="background: var(--accent-ai)"></i>当前 Query</span>
            <span><i style="background: var(--c-kb)"></i>Top-5 召回邻域</span>
          </div>
        </div>
        <div v-else class="info-strip mb16">
          当前知识库未启用向量投影能力，检索结果以服务端返回的 Top-K 切块为准。
        </div>

        <!-- Top-5 相似度召回结果 -->
        <div class="rail-label">Top-5 相似度召回结果</div>
        <div class="section-gap mb16" style="gap: 8px">
          <div
            v-for="(r, idx) in recallResults"
            :key="idx"
            class="chunk recall-card"
            :class="{ hit: r.hit }"
            title="点击定位左栏对应切块"
            @click="locateChunk(r.chunk)"
          >
            <div class="row mb8" style="gap: 8px">
              <span class="mono" style="font-weight: 600; color: var(--c-kb)">#{{ idx + 1 }} {{ r.chunk }}</span>
              <span class="small tertiary mono">{{ r.doc }}</span>
              <span class="grow"></span>
              <span v-if="r.hit" class="badge badge-succeeded"><i class="bdot"></i>命中 expected_doc_ids</span>
              <span v-else class="small tertiary">未命中</span>
            </div>
            <div class="sim-row">
              <span class="sim-track"><i :style="{ width: `${Math.round(r.sim * 100)}%` }"></i></span>
              <span class="mono small" style="width: 42px; text-align: right">{{ r.sim.toFixed(2) }}</span>
            </div>
            <div class="ck-text" style="margin-top: 6px; font-size: 12px">{{ r.text }}</div>
          </div>
        </div>

        <!-- 重排对比仅在后端明确声明支持时展示。 -->
        <template v-if="supportsRerankCompare">
          <div class="rail-label">重排对比 · Rerank Rank Shifts</div>
          <div class="row" style="align-items: flex-start; gap: 12px">
          <div class="grow">
            <div class="small tertiary mb8">向量初检召回序</div>
            <div v-for="(r, i) in recallResults" :key="i" class="tag-soft mb8" style="width: 100%; justify-content: flex-start">
              <span class="tertiary mono" style="margin-right: 6px">{{ i + 1 }}</span>
              <span class="mono">{{ r.chunk }}</span>
            </div>
          </div>
          <div class="grow">
            <div class="small tertiary mb8">重排后最终序 (Reranked)</div>
            <div
              v-for="(c, i) in rerankedIds"
              :key="i"
              class="tag-soft mb8"
              style="width: 100%; justify-content: space-between"
              :style="{ borderColor: i === 0 ? 'var(--c-kb)' : undefined }"
            >
              <div class="row">
                <span class="tertiary mono" style="margin-right: 6px">{{ i + 1 }}</span>
                <span class="mono">{{ c }}</span>
              </div>
              <span class="mono small" :style="{ color: getShiftDelta(c, i) > 0 ? 'var(--accent-success)' : 'var(--accent-warning)' }">
                {{ getShiftDelta(c, i) > 0 ? `↑${getShiftDelta(c, i)}` : getShiftDelta(c, i) < 0 ? `↓${Math.abs(getShiftDelta(c, i))}` : '—' }}
              </span>
            </div>
          </div>
          </div>
        </template>
        <div v-else class="info-strip">
          当前知识库未启用重排对比能力。
        </div>
      </div>

      <!-- 3. 右栏：本次检索指标 + 黄金 QA -->
      <div class="kb-col panel" style="overflow-y: auto; max-height: calc(100vh - 160px)">
        <div class="rail-label">本次检索指标 · K=5</div>
        <!-- 四个指标卡数字统一使用 accent-ai 主色，对齐原型 metric-cell 视觉。 -->
        <div class="kpi-grid mb16" style="grid-template-columns: 1fr 1fr; gap: 10px">
          <div class="kpi" style="padding: 12px">
            <div class="kpi-num mono" style="font-size: 20px; color: var(--accent-ai)">{{ formatMetric(queryMetrics.hit_rate) }}</div>
            <div class="kpi-label">Hit Rate@5</div>
          </div>
          <div class="kpi" style="padding: 12px">
            <div class="kpi-num mono" style="font-size: 20px; color: var(--accent-ai)">{{ formatMetric(queryMetrics.mrr) }}</div>
            <div class="kpi-label">MRR 倒数排名</div>
          </div>
          <div class="kpi" style="padding: 12px">
            <div class="kpi-num mono" style="font-size: 20px; color: var(--accent-ai)">{{ formatMetric(queryMetrics.recall) }}</div>
            <div class="kpi-label">Recall@5</div>
          </div>
          <div class="kpi" style="padding: 12px">
            <div class="kpi-num mono" style="font-size: 20px; color: var(--accent-ai)">{{ formatMetric(queryMetrics.contain) }}</div>
            <div class="kpi-label">答案 contain 分</div>
          </div>
        </div>

        <div class="row-between mb8">
          <span class="rail-label" style="margin: 0">黄金问答集 (Gold QA)</span>
          <div class="row" style="gap: 6px">
            <button class="btn btn-ai btn-sm" @click="handleAiGenQa">✨ AI 生成</button>
            <button class="btn btn-secondary btn-sm" @click="showUploadGoldQaModal = true">
              {{ goldQas.length ? '覆盖上传 +1' : '上传 QA' }}
            </button>
          </div>
        </div>

        <div v-if="goldQas.length" class="section-gap mb16" style="gap: 8px">
          <div
            v-for="g in goldQas"
            :key="g.id"
            class="panel"
            style="padding: 12px 14px; border-radius: 10px"
          >
            <div class="row-between">
              <span style="font-size: 13px; font-weight: 600">{{ g.name }}</span>
              <span class="tag-soft" style="color: var(--c-kb)">v{{ g.version }}</span>
            </div>
            <div class="small tertiary mt8">
              <span class="num">{{ g.row_count }}</span> 条 · 无 expected_doc_ids 样本不进分母
            </div>
          </div>
        </div>
        <!-- 黄金 QA 空态：提示先上传或 AI 生成后再发起评测。 -->
        <div v-else class="empty mb16" style="padding: 24px 12px">
          <div class="small tertiary">该库暂无黄金 QA，需先上传或 AI 生成。</div>
        </div>

        <div class="rail-label">评测口径说明</div>
        <p class="small muted" style="line-height: 1.6">
          <b>命中判定</b>：返回 context.id / doc_id 与 expected_doc_ids 集合相交即为 Hit。内置库检索走 LightRAG 原生 query（naive / local / global / hybrid），不伪装成 Chat。
        </p>

        <button
          v-if="!currentKb.is_core"
          class="btn btn-ghost btn-sm mt16"
          style="width: 100%"
          @click="markAsCore"
        >
          ★ 标为核心知识库
        </button>
      </div>
    </div>

    <!-- 外部 Chat 库对接视图 -->
    <div v-else-if="currentKb" class="panel page-narrow" style="max-width: 760px; margin: 20px auto">
      <div class="info-strip mb16" style="border-radius: 12px">
        外部库仅通过 <span class="mono">POST {base}/v1/chat/completions</span> 对接：检索切块过程对平台黑盒不可见，不展示分块与空间投影，评测关注端到端答案侧指标（contain / judge）。
      </div>

      <div class="panel mb16">
        <div class="panel-title">绑定 RAG 服务档</div>
        <div class="row">
          <span class="tag-soft mono">{{ currentKb.profile_id || '未绑定协议档' }}</span>
          <span class="small tertiary">外部库恰好绑定 1 个协议档，在协议档管理维护</span>
        </div>
      </div>

      <div class="panel">
        <div class="row-between mb8">
          <div class="panel-title" style="margin: 0">黄金 QA 集</div>
          <button class="btn btn-secondary btn-sm" @click="showUploadGoldQaModal = true">覆盖上传 +1</button>
        </div>
        <div v-for="g in goldQas" :key="g.id" class="row" style="padding: 6px 0">
          <span style="font-weight: 500">{{ g.name }}</span>
          <span class="tag-soft" style="color: var(--c-kb)">v{{ g.version }}</span>
          <span class="small tertiary num" style="margin-left: auto">{{ g.row_count }} 条</span>
        </div>
      </div>
    </div>

    <div v-else class="info-strip page-narrow" style="max-width: 760px; margin: 20px auto">
      暂无知识库。请先新建知识库，或确认知识库服务已部署。
    </div>

    <!-- 弹窗与抽屉 -->
    <n-modal v-model:show="showCreateKbModal" preset="card" title="新建知识库" style="width: 460px">
      <div class="field mb16">
        <label class="field-label">知识库名称 <span class="req">*</span></label>
        <n-input v-model:value="newKbName" placeholder="例如：客服产品手册" />
      </div>
      <div class="field">
        <label class="field-label">知识库类型</label>
        <n-select v-model:value="newKbKind" :options="kbKindOptions" />
      </div>
      <!-- 外部 Chat 库必须绑定 1 个 RAG 服务协议档，创建时随 profile_id 提交。 -->
      <div v-if="newKbKind === 'external_chat'" class="field">
        <label class="field-label">绑定 RAG 服务协议档 <span class="req">*</span></label>
        <n-select
          v-model:value="newKbProfileId"
          :options="ragProfileOptions"
          placeholder="选择提供 chat/completions 的协议档"
        />
      </div>
      <template #footer>
        <div style="display: flex; justify-content: flex-end; gap: 8px">
          <n-button @click="showCreateKbModal = false">取消</n-button>
          <n-button type="primary" :loading="creatingKb" @click="handleCreateKb">创建知识库</n-button>
        </div>
      </template>
    </n-modal>

    <UploadKbDocModal
      v-model:show="showUploadDocModal"
      :kb="currentKb"
      @success="loadDocs"
    />

    <UploadGoldQaModal
      v-model:show="showUploadGoldQaModal"
      :kb="currentKb"
      @success="loadGoldQas"
    />

    <RagLaunchDrawer
      v-model:show="showLaunchDrawer"
      :default-kb-id="activeKbId"
      @success="handleLaunchSuccess"
    />
    </template>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useDialog, useMessage } from 'naive-ui'
import { api } from '../api/http'
import type { KnowledgeBase, KbChunk, KbDoc, GoldQA, Profile } from '../api/types'
import { useModeStore } from '../stores/mode'
import UploadKbDocModal from '../components/modals/UploadKbDocModal.vue'
import UploadGoldQaModal from '../components/modals/UploadGoldQaModal.vue'
import RagLaunchDrawer from '../components/drawers/RagLaunchDrawer.vue'

const message = useMessage()
const dialog = useDialog()
const router = useRouter()
const modeStore = useModeStore()

const kbs = ref<KnowledgeBase[]>([])
const activeKbId = ref<string>('')
const currentKb = computed(() => kbs.value.find(k => k.id === activeKbId.value) || kbs.value[0])
const supportsProjection = computed(() => currentKb.value?.capabilities?.projection === true)
const supportsRerankCompare = computed(() => currentKb.value?.capabilities?.rerank_compare === true)

const docs = ref<KbDoc[]>([])
const activeDocId = ref<string>('')
const currentDoc = computed(() => docs.value.find(d => d.doc_id === activeDocId.value) || docs.value[0])
const chunkPreview = ref<KbChunk[]>([])

const goldQas = ref<GoldQA[]>([])

const chunkSize = ref(512)
const overlap = ref(64)
const queryMode = ref('hybrid')
const queryText = ref('退款多久到账？')
const queried = ref(false)
const isQuerying = ref(false)

const showCreateKbModal = ref(false)
const showUploadDocModal = ref(false)
const showUploadGoldQaModal = ref(false)
const showLaunchDrawer = ref(false)
/** RAG 评测下单成功后跳转任务中心，与原型交互保持一致。 */
function handleLaunchSuccess() {
  router.push('/tasks')
}
const creatingKb = ref(false)
const newKbName = ref('')
const newKbKind = ref<KnowledgeBase['kind']>('lightrag')
const newKbProfileId = ref<string | null>(null)
const kbKindOptions = [
  { label: 'LightRAG 原生知识库', value: 'lightrag' },
  { label: '外部 Chat 知识库', value: 'external_chat' },
]

// 外部 Chat 库可选的 RAG 服务协议档：按现有类型约定取 usages 含 agent/target 的协议档。
const ragProfiles = ref<Profile[]>([])
const ragProfileOptions = computed(() =>
  ragProfiles.value.map(p => ({ label: `${p.name} · ${p.model}`, value: p.id })),
)

// 打开新建弹窗时按需拉取协议档，过滤出可作为外部 RAG 服务绑定的候选。
async function loadRagProfiles() {
  try {
    const list = await api.profiles.list()
    ragProfiles.value = list.filter(p => !p.usages?.length || p.usages.some(u => u === 'agent' || u === 'target'))
  } catch (err: any) {
    ragProfiles.value = []
    message.error(err.message || '加载协议档失败')
  }
}

watch(showCreateKbModal, (show) => {
  if (show) void loadRagProfiles()
})

const recallResults = ref<Array<{ chunk: string; doc: string; sim: number; hit: boolean; text: string }>>([])
const rerankedIds = ref<string[]>([])
const queryMetrics = ref({ hit_rate: null as number | null, mrr: null as number | null, recall: null as number | null, contain: null as number | null })

/** 左栏切块流容器与当前闪烁定位的切块 ID，用于召回点击联动定位。 */
const chunkFlowRef = ref<HTMLElement | null>(null)
const flashChunkId = ref('')

// 点击召回卡片后滚动左栏切块流到对应切块并短暂高亮；切块属于其他文档时给出提示。
function locateChunk(chunkId: string) {
  const target = chunkFlowRef.value?.querySelector(`[data-chunk="${chunkId}"]`) as HTMLElement | null
  if (!target) {
    message.info(`${chunkId} 属于其他文档，左栏未找到对应切块`)
    return
  }
  target.scrollIntoView({ behavior: 'smooth', block: 'center' })
  flashChunkId.value = chunkId
  window.setTimeout(() => {
    if (flashChunkId.value === chunkId) flashChunkId.value = ''
  }, 1200)
}

// 语料切块散点坐标，按原型 PTS 归一化点位 × 520×280 画布取整得到。
const scatterPoints = [
  { x: 62, y: 84 }, { x: 104, y: 190 }, { x: 146, y: 56 }, { x: 177, y: 140 }, { x: 208, y: 218 },
  { x: 229, y: 95 }, { x: 260, y: 168 }, { x: 286, y: 45 }, { x: 302, y: 123 }, { x: 328, y: 196 },
  { x: 343, y: 84 }, { x: 364, y: 146 }, { x: 385, y: 56 }, { x: 406, y: 185 }, { x: 426, y: 112 },
  { x: 447, y: 162 }, { x: 83, y: 140 }, { x: 125, y: 230 }, { x: 250, y: 230 }, { x: 458, y: 73 },
  { x: 187, y: 185 }, { x: 354, y: 224 },
]
// Top-5 命中散点下标，与原型 HIT_IDX 保持一致。
const hitIndices = [9, 13, 7, 20, 10]

function isChunkHit(cid: string) {
  // 仅根据当前检索接口返回的命中切块高亮预览。
  return queried.value && recallResults.value.some(r => r.chunk === cid)
}

// 将接口可选指标转换为固定两位显示，未检索时明确显示占位符。
function formatMetric(value: number | null) {
  return value === null ? '—' : value.toFixed(2)
}

function getShiftDelta(chunkId: string, afterIdx: number) {
  // 在后端启用重排能力时计算展示用的排名变化。
  const beforeIdx = recallResults.value.findIndex(r => r.chunk === chunkId)
  if (beforeIdx === -1) return 0
  return beforeIdx - afterIdx
}

// 切换知识库时清除上一个库的派生视图，并重新拉取当前库资源。
async function selectKb(k: KnowledgeBase) {
  activeKbId.value = k.id
  docs.value = []
  chunkPreview.value = []
  goldQas.value = []
  recallResults.value = []
  rerankedIds.value = []
  queryMetrics.value = { hit_rate: null, mrr: null, recall: null, contain: null }
  queried.value = false
  await Promise.all([loadDocs(), loadGoldQas()])
}

function fillAndQuery(q: string) {
  // 快速填充预置查询后复用正式检索流程。
  queryText.value = q
  void handleQuery()
}

// 调用 LightRAG 原生 query，并用契约中的 Top-K 与指标回填 Playground。
async function handleQuery() {
  if (!currentKb.value) {
    message.warning('请先创建或选择知识库')
    return
  }
  if (currentKb.value.kind !== 'lightrag') {
    message.warning('外部 Chat 知识库不支持原生检索 Playground')
    return
  }
  if (!queryText.value.trim()) {
    message.warning('请输入测试 Query')
    return
  }
  isQuerying.value = true
  try {
    const result = await api.kb.query(currentKb.value.id, {
      query: queryText.value.trim(),
      mode: queryMode.value,
      k: 5,
    })
    const items = Array.isArray(result.items) ? result.items : []
    recallResults.value = items.map((item: Record<string, unknown>) => ({
      chunk: String(item.chunk_id || ''),
      doc: String(item.doc_name || item.doc_id || '未知文档'),
      sim: Number.isFinite(Number(item.similarity)) ? Number(item.similarity) : 0,
      hit: item.hit === true,
      text: String(item.text || ''),
    }))
    const metrics = result.metrics || {}
    queryMetrics.value = {
      hit_rate: Number.isFinite(Number(metrics.hit_rate)) ? Number(metrics.hit_rate) : null,
      mrr: Number.isFinite(Number(metrics.mrr)) ? Number(metrics.mrr) : null,
      recall: Number.isFinite(Number(metrics.recall)) ? Number(metrics.recall) : null,
      contain: Number.isFinite(Number(metrics.contain)) ? Number(metrics.contain) : null,
    }
    rerankedIds.value = Array.isArray(result.reranked_ids) ? result.reranked_ids.map(String) : []
    queried.value = true
    message.success(`已返回 ${recallResults.value.length} 个检索切块 · 模式=${queryMode.value}`)
  } catch (err: any) {
    message.error(err.message || '检索请求失败')
  } finally {
    isQuerying.value = false
  }
}

// 标为核心库必须落库，避免刷新页面后错误保留本地状态。
async function markAsCore() {
  if (!currentKb.value) return
  try {
    const updated = await api.kb.update(currentKb.value.id, { is_core: true })
    const index = kbs.value.findIndex(kb => kb.id === updated.id)
    if (index !== -1) kbs.value[index] = updated
    message.success('已标为核心知识库')
  } catch (err: any) {
    message.error(err.message || '设置核心知识库失败')
  }
}

// 当前契约未定义浏览器端 AI 生成黄金 QA 的调用入口，不能在前端虚构已入库结果。
function handleAiGenQa() {
  message.warning('黄金 QA 的 AI 生成功能尚未提供正式接口，请上传符合规范的 QA 文件')
}

// 创建知识库后以接口响应更新选择态，再加载该库的子资源。
async function handleCreateKb() {
  const name = newKbName.value.trim()
  if (!name) {
    message.warning('请输入知识库名称')
    return
  }
  // 外部 Chat 库必须绑定 RAG 服务协议档，否则无法通过 chat/completions 对接。
  if (newKbKind.value === 'external_chat' && !newKbProfileId.value) {
    message.warning('请选择绑定的 RAG 服务协议档')
    return
  }
  creatingKb.value = true
  try {
    const created = await api.kb.create({
      name,
      kind: newKbKind.value,
      profile_id: newKbKind.value === 'external_chat' ? newKbProfileId.value || undefined : undefined,
    })
    kbs.value.unshift(created)
    newKbName.value = ''
    newKbProfileId.value = null
    showCreateKbModal.value = false
    await selectKb(created)
    message.success('知识库已创建')
  } catch (err: any) {
    message.error(err.message || '创建知识库失败')
  } finally {
    creatingKb.value = false
  }
}

// 删除文档会同时删除对应索引，确认后才发出不可逆请求。
function handleDeleteDoc(doc: KbDoc) {
  if (!currentKb.value) return
  dialog.warning({
    title: '删除知识库文档',
    content: `将删除「${doc.filename}」及其切块索引，此操作不可恢复。`,
    positiveText: '删除',
    negativeText: '取消',
    onPositiveClick: async () => {
      try {
        await api.kb.deleteDoc(currentKb.value!.id, doc.doc_id)
        docs.value = docs.value.filter(item => item.doc_id !== doc.doc_id)
        if (activeDocId.value === doc.doc_id) activeDocId.value = docs.value[0]?.doc_id || ''
        await loadChunkPreview()
        message.success('文档及其索引已删除')
      } catch (err: any) {
        message.error(err.message || '删除文档失败')
      }
    },
  })
}

// 读取当前文档的服务端切块预览；切块参数仅影响预览，不在浏览器生成样本正文。
async function loadChunkPreview() {
  if (!currentKb.value || !activeDocId.value) {
    chunkPreview.value = []
    return
  }
  try {
    chunkPreview.value = await api.kb.getDocChunks(currentKb.value.id, activeDocId.value, {
      chunk_size: chunkSize.value,
      overlap: overlap.value,
    })
  } catch (err: any) {
    chunkPreview.value = []
    message.error(err.message || '加载文档切块失败')
  }
}

async function loadDocs() {
  // 获取当前知识库文档，并同步首个可预览文档。
  if (!activeKbId.value) return
  try {
    const res = await api.kb.listDocs(activeKbId.value)
    docs.value = res
    if (!docs.value.some(doc => doc.doc_id === activeDocId.value)) {
      activeDocId.value = docs.value[0]?.doc_id || ''
    }
    await loadChunkPreview()
  } catch (err: any) {
    docs.value = []
    chunkPreview.value = []
    message.error(err.message || '加载知识库文档失败')
  }
}

async function loadGoldQas() {
  // 获取当前知识库关联的黄金 QA 版本列表。
  if (!activeKbId.value) return
  try {
    goldQas.value = await api.kb.getGoldQA(activeKbId.value)
  } catch (err: any) {
    goldQas.value = []
    message.error(err.message || '加载黄金 QA 失败')
  }
}

// 只要切换文档或调整预览参数，就重新请求当前文档的切块结果。
watch([activeDocId, chunkSize, overlap], () => {
  void loadChunkPreview()
})

// 读取 RAG 资产时才初始化知识库与子资源，切回 RAG 模式后可复用已加载的内容。
async function loadKnowledgeBases() {
  try {
    const list = await api.kb.list()
    kbs.value = list
    const first = list[0]
    if (first) await selectKb(first)
  } catch (err: any) {
    message.error(err.message || '加载知识库失败')
  }
}

onMounted(() => {
  if (modeStore.mode === 'rag') void loadKnowledgeBases()
})

// 从大模型模式切回 RAG 时补齐首次加载，避免空白工作台。
watch(() => modeStore.mode, (mode) => {
  if (mode === 'rag' && !kbs.value.length) void loadKnowledgeBases()
})
</script>

<style scoped>
.kb-grid-3col {
  display: grid;
  grid-template-columns: 280px 1fr 340px;
  gap: 16px;
}
.mode-context-panel {
  max-width: 680px;
  margin: 48px auto;
  padding: 28px;
}
.mode-context-panel h2 {
  margin: 8px 0 10px;
  font-size: 20px;
}
.mode-context-panel p {
  max-width: 560px;
  margin: 0 0 20px;
  color: var(--text-secondary);
  line-height: 1.7;
}
@media (max-width: 1200px) {
  .kb-grid-3col {
    grid-template-columns: 1fr;
  }
}
@media (max-width: 700px) {
  .kb-bar {
    align-items: flex-start;
    flex-direction: column;
    gap: 10px;
  }
  .kb-bar > .row:last-child {
    flex-wrap: wrap;
  }
}
.doc-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  border-radius: 12px;
  border: 1px solid var(--border-subtle);
  cursor: pointer;
  transition: all 0.15s ease;
}
.doc-item:hover {
  background: var(--bg-elevated);
}
.doc-item.on {
  border-color: var(--c-kb);
  background: color-mix(in srgb, var(--t-kb) 30%, var(--bg-main));
}
/* 快速填充 pill 悬停时染主色，对齐原型 quick-q-pill 交互。 */
.quick-pill {
  cursor: pointer;
  transition: border-color 0.15s ease, color 0.15s ease;
}
.quick-pill:hover {
  border-color: var(--accent-ai);
  color: var(--accent-ai);
}
/* 召回卡片可点击，点击后联动定位左栏切块。 */
.recall-card {
  cursor: pointer;
}
/* 召回定位的 1.2s 闪烁高亮动画。 */
.chunk.flash {
  animation: chunk-flash 1.2s ease;
}
@keyframes chunk-flash {
  0%, 60% {
    box-shadow: 0 0 0 2px var(--c-kb);
  }
  100% {
    box-shadow: 0 0 0 0 transparent;
  }
}
.metric-strip {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
}
</style>
