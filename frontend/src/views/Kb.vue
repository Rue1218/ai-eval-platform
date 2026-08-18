<template>
  <div class="kb-workbench">
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
            <span v-if="k.is_core" style="color: var(--accent-warning); margin-right: 4px">★</span>
            <span>{{ k.name }}</span>
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
        <button class="btn btn-sign btn-sm" @click="showLaunchDrawer = true">发起 RAG 评测</button>
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

        <div class="section-gap" style="gap: 8px">
          <div
            v-for="ck in mockChunks"
            :key="ck.chunk_id"
            class="chunk"
            :class="{ hit: isChunkHit(ck.chunk_id) }"
          >
            <div class="row-between">
              <span class="ck-id mono">{{ ck.chunk_id }}</span>
              <span class="ck-tokens mono">{{ ck.tokens }} tok</span>
            </div>
            <div class="ck-text">{{ ck.text }}</div>
            <i v-if="overlap > 0" class="ck-ov" :style="{ width: `${Math.round((overlap / chunkSize) * 100)}%` }"></i>
          </div>
        </div>
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
            class="tag-soft"
            style="cursor: pointer"
            @click="fillAndQuery(q)"
          >
            {{ q }}
          </span>
        </div>

        <!-- 向量空间 2D 降维投影 SVG -->
        <div class="chart-box mb16">
          <div class="row-between mb8">
            <span class="small" style="font-weight: 600">向量空间 2D 降维投影 (Vector Projection)</span>
            <span class="small tertiary mono">bge-large-zh · 22 chunks</span>
          </div>

          <svg class="scatter" viewBox="0 0 520 220" style="height: 180px">
            <circle v-if="queried" class="ring" cx="312" cy="101" r="76" />
            <!-- 邻域连线 -->
            <template v-if="queried">
              <line class="lk" x1="312" y1="101" x2="208" y2="44" />
              <line class="lk" x1="312" y1="101" x2="327" y2="154" />
              <line class="lk" x1="312" y1="101" x2="286" y2="35" />
              <line class="lk" x1="312" y1="101" x2="353" y2="176" />
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
              <circle class="pt-query" cx="312" cy="101" r="6" />
              <circle class="ring" cx="312" cy="101" r="14" style="opacity: 0.5" />
            </template>
          </svg>

          <div class="chart-legend" style="margin-top: 6px">
            <span><i style="background: var(--text-tertiary); opacity: 0.45"></i>语料切块</span>
            <span><i style="background: var(--accent-ai)"></i>当前 Query</span>
            <span><i style="background: var(--c-kb)"></i>Top-5 召回邻域</span>
          </div>
        </div>

        <!-- Top-5 相似度召回结果 -->
        <div class="rail-label">Top-5 相似度召回结果</div>
        <div class="section-gap mb16" style="gap: 8px">
          <div
            v-for="(r, idx) in recallResults"
            :key="idx"
            class="chunk"
            :class="{ hit: r.hit }"
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

        <!-- 重排对比 -->
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
      </div>

      <!-- 3. 右栏：本次检索指标 + 黄金 QA -->
      <div class="kb-col panel" style="overflow-y: auto; max-height: calc(100vh - 160px)">
        <div class="rail-label">本次检索指标 · K=5</div>
        <div class="kpi-grid mb16" style="grid-template-columns: 1fr 1fr; gap: 10px">
          <div class="kpi" style="padding: 12px">
            <div class="kpi-num mono" style="font-size: 20px; color: var(--c-kb)">0.80</div>
            <div class="kpi-label">Hit Rate@5</div>
          </div>
          <div class="kpi" style="padding: 12px">
            <div class="kpi-num mono" style="font-size: 20px; color: var(--c-kb)">0.74</div>
            <div class="kpi-label">MRR 倒数排名</div>
          </div>
          <div class="kpi" style="padding: 12px">
            <div class="kpi-num mono" style="font-size: 20px">0.85</div>
            <div class="kpi-label">Recall@5</div>
          </div>
          <div class="kpi" style="padding: 12px">
            <div class="kpi-num mono" style="font-size: 20px">0.83</div>
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

        <div class="section-gap mb16" style="gap: 8px">
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
          <span class="tag-soft mono">rag-客服外挂 · rag-chat-v2</span>
          <span class="small tertiary">恰好 1 个，在协议档管理维护</span>
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

    <!-- 弹窗与抽屉 -->
    <UploadKbDocModal
      v-model:show="showUploadDocModal"
      :kb-id="activeKbId"
      @success="loadDocs"
    />

    <UploadGoldQaModal
      v-model:show="showUploadGoldQaModal"
      :kb-id="activeKbId"
      @success="loadGoldQas"
    />

    <RagLaunchDrawer
      v-model:show="showLaunchDrawer"
      :kb-id="activeKbId"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useMessage } from 'naive-ui'
import { api } from '../api/http'
import type { KnowledgeBase, KbDoc, GoldQA } from '../api/types'
import UploadKbDocModal from '../components/modals/UploadKbDocModal.vue'
import UploadGoldQaModal from '../components/modals/UploadGoldQaModal.vue'
import RagLaunchDrawer from '../components/drawers/RagLaunchDrawer.vue'

const message = useMessage()

const kbs = ref<KnowledgeBase[]>([
  { id: 'kb-default', name: 'default', kind: 'lightrag', doc_count: 12, is_core: true, owner: 'admin' },
  { id: 'kb-cs', name: '外挂客服', kind: 'external_chat', doc_count: null, is_core: false, owner: 'alice' },
])
const activeKbId = ref<string>('kb-default')
const currentKb = computed(() => kbs.value.find(k => k.id === activeKbId.value) || kbs.value[0])

const docs = ref<KbDoc[]>([
  { doc_id: 'd-01', filename: 'product-manual.pdf', status: 'indexed', size: '2.4 MB' },
  { doc_id: 'd-02', filename: 'faq-2026.md', status: 'indexed', size: '88 KB' },
  { doc_id: 'd-03', filename: 'refund-policy.html', status: 'indexing', size: '41 KB' },
])
const activeDocId = ref<string>('d-01')
const currentDoc = computed(() => docs.value.find(d => d.doc_id === activeDocId.value) || docs.value[0])

const goldQas = ref<GoldQA[]>([
  { id: 'gq-1', kb_id: 'kb-default', name: 'qa-v1', version: 2, row_count: 20, owner: 'admin', created_at: new Date().toISOString() },
])

const chunkSize = ref(512)
const overlap = ref(64)
const queryMode = ref('hybrid')
const queryText = ref('退款多久到账？')
const queried = ref(true)
const isQuerying = ref(false)

const showCreateKbModal = ref(false)
const showUploadDocModal = ref(false)
const showUploadGoldQaModal = ref(false)
const showLaunchDrawer = ref(false)

const CHUNK_TEXTS = [
  '……账户体系分为个人账户与企业账户。企业账户支持多人审批与额度管理，审批流最多两级……',
  '……结算账户用于接收平台打款。修改默认结算账户需进入「设置-账户-结算账户」并完成短信验证……',
  '……付款方式支持余额、银行卡与对公转账。余额提现单笔不超过 5 万元，单日不超过 20 万元……',
  '……退款审核通过后 1-3 个工作日原路退回。全额退款退回手续费，部分退款按剩余比例退回……',
  '……账单支持按项目维度导出 CSV。历史账单最长可查询 24 个月，支持自定义时间范围……',
  '……电子发票 24 小时内发送至预留邮箱；增值税专用发票需填写邮寄地址，3 个工作日内寄出……',
  '……连续输错支付密码 5 次将锁定 2 小时，可通过人脸验证立即解锁。风控拦截请联系客服……',
  '……冻结金额为进行中交易的预占金额，交易完成后自动解冻或扣减，可在账单详情中查看……',
]

const mockChunks = computed(() => {
  const count = chunkSize.value === 256 ? 14 : chunkSize.value === 1024 ? 4 : 8
  return Array.from({ length: count }, (_, i) => ({
    chunk_id: `${activeDocId.value || 'd-01'}#c${String(i + 1).padStart(2, '0')}`,
    tokens: Math.round(chunkSize.value * (0.75 + ((i * 37) % 25) / 100)),
    text: CHUNK_TEXTS[i % CHUNK_TEXTS.length],
  }))
})

const recallResults = ref([
  { chunk: 'd-01#c03', doc: 'product-manual.pdf', sim: 0.87, hit: true, text: CHUNK_TEXTS[3] },
  { chunk: 'd-01#c06', doc: 'product-manual.pdf', sim: 0.78, hit: false, text: CHUNK_TEXTS[6] },
  { chunk: 'd-01#c01', doc: 'product-manual.pdf', sim: 0.74, hit: false, text: CHUNK_TEXTS[1] },
  { chunk: 'd-02#c11', doc: 'faq-2026.md', sim: 0.69, hit: false, text: '……FAQ：退款相关问题的统一答复口径，含到账时间与手续费说明……' },
  { chunk: 'd-01#c04', doc: 'product-manual.pdf', sim: 0.62, hit: false, text: CHUNK_TEXTS[4] },
])

const rerankedIds = ref(['d-01#c03', 'd-01#c01', 'd-01#c06', 'd-02#c11', 'd-01#c04'])

const scatterPoints = [
  { x: 62, y: 66 }, { x: 104, y: 150 }, { x: 145, y: 44 }, { x: 176, y: 110 }, { x: 208, y: 171 },
  { x: 228, y: 74 }, { x: 260, y: 132 }, { x: 286, y: 35 }, { x: 301, y: 96 }, { x: 327, y: 154 },
  { x: 343, y: 66 }, { x: 364, y: 114 }, { x: 384, y: 44 }, { x: 405, y: 145 }, { x: 426, y: 88 },
  { x: 447, y: 127 }, { x: 83, y: 110 }, { x: 124, y: 180 }, { x: 249, y: 180 }, { x: 457, y: 57 },
  { x: 187, y: 145 }, { x: 353, y: 176 },
]
const hitIndices = [9, 13, 7, 21, 10]

function isChunkHit(cid: string) {
  return queried.value && recallResults.value.some(r => r.chunk === cid)
}

function getShiftDelta(chunkId: string, afterIdx: number) {
  const beforeIdx = recallResults.value.findIndex(r => r.chunk === chunkId)
  if (beforeIdx === -1) return 0
  return beforeIdx - afterIdx
}

function selectKb(k: KnowledgeBase) {
  activeKbId.value = k.id
  loadDocs()
  loadGoldQas()
}

function fillAndQuery(q: string) {
  queryText.value = q
  handleQuery()
}

async function handleQuery() {
  if (!queryText.value.trim()) return
  isQuerying.value = true
  await new Promise(r => setTimeout(r, 400))
  queried.value = true
  isQuerying.value = false
  message.success(`已返回 ${recallResults.value.length} 个检索切块 · 模式=${queryMode.value}`)
}

function markAsCore() {
  if (currentKb.value) {
    currentKb.value.is_core = true
    message.success('已标为核心知识库')
  }
}

function handleAiGenQa() {
  message.info('AI 正在基于已索引切块提炼高质量黄金问答对...')
  setTimeout(() => {
    goldQas.value.unshift({
      id: `gq-${Date.now()}`,
      kb_id: activeKbId.value,
      name: `AI-提炼-问答集-v${goldQas.value.length + 1}`,
      version: 1,
      row_count: 25,
      owner: 'admin',
      created_at: new Date().toISOString(),
    })
    message.success('AI 已成功提炼生成 25 条黄金问答对并入库')
  }, 1200)
}

async function loadDocs() {
  try {
    const res = await api.kb.listDocs(activeKbId.value)
    if (res && res.length) docs.value = res
  } catch {}
}

async function loadGoldQas() {
  try {
    const res = await api.kb.getGoldQA(activeKbId.value)
    if (res && res.length) goldQas.value = res
  } catch {}
}

onMounted(() => {
  loadDocs()
  loadGoldQas()
})
</script>

<style scoped>
.kb-grid-3col {
  display: grid;
  grid-template-columns: 280px 1fr 340px;
  gap: 16px;
}
@media (max-width: 1200px) {
  .kb-grid-3col {
    grid-template-columns: 1fr;
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
.metric-strip {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
}
</style>
