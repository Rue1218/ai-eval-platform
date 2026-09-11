<template>
  <!-- 富文本 Markdown 渲染器：支持实时流式解析、Mermaid 架构图/流程图、代码块高亮/复制、GFM 表格、公式与排版优化 -->
  <div
    ref="containerRef"
    class="markdown-view"
    :class="[customClass, { 'is-streaming': isStreaming }]"
    @click="handleContainerClick"
  >
    <StructuredDataView
      v-if="showStructuredValue"
      :value="structuredValue"
      label="结构化输出"
      show-toolbar
    />
    <div v-else class="markdown-content" v-html="renderedHtml"></div>
    <span v-if="isStreaming" class="md-streaming-cursor" aria-hidden="true">▍</span>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, nextTick, onMounted, onBeforeUnmount } from 'vue'
import mermaid from 'mermaid'
import StructuredDataView from './StructuredDataView.vue'
import { copyText } from '../../utils/clipboard'

const props = withDefaults(
  defineProps<{
    content: string
    customClass?: string
    isStreaming?: boolean
  }>(),
  {
    content: '',
    customClass: '',
    isStreaming: false,
  },
)

const containerRef = ref<HTMLElement | null>(null)
const renderedSource = ref(props.content)
let renderSvgCounter = 0
let markdownRenderFrame: number | undefined
let mermaidRenderFrame: number | undefined
let currentMermaidTheme: 'light' | 'dark' | null = null
let themeObserver: MutationObserver | null = null

function isDarkTheme(): boolean {
  return typeof document !== 'undefined' && document.documentElement.getAttribute('data-theme') === 'dark'
}

/**
 * 初始化 Mermaid 主题配置（适配平台浅色薄荷绿/深色深空蓝主题体系）
 */
function initMermaid(force = false): void {
  const isDark = isDarkTheme()
  const targetTheme = isDark ? 'dark' : 'light'
  if (!force && currentMermaidTheme === targetTheme) return

  if (isDark) {
    mermaid.initialize({
      startOnLoad: false,
      theme: 'dark',
      themeVariables: {
        darkMode: true,
        background: 'transparent',
        primaryColor: '#0f3d30',
        primaryTextColor: '#f8fafc',
        primaryBorderColor: '#16977a',
        lineColor: '#34d399',
        secondaryColor: '#12382c',
        tertiaryColor: '#0b261e',
        secondaryTextColor: '#cbd5e1',
        tertiaryTextColor: '#94a3b8',
        fontSize: '13.5px',
        fontFamily: '"Segoe UI Variable Text", "Segoe UI", system-ui, -apple-system, sans-serif',
        nodeBorder: '#16977a',
        mainBkg: '#0d2820',
        nodeTextColor: '#f8fafc',
        actorBkg: '#111827',
        actorBorder: '#16977a',
        actorTextColor: '#f8fafc',
        signalColor: '#34d399',
        signalTextColor: '#f8fafc',
        clusterBkg: '#091c16',
        clusterBorder: '#1a5c48',
        edgeLabelBackground: '#0b1915',
      },
      securityLevel: 'loose',
      fontFamily: '"Segoe UI Variable Text", "Segoe UI", system-ui, -apple-system, sans-serif',
    })
  } else {
    mermaid.initialize({
      startOnLoad: false,
      theme: 'base',
      themeVariables: {
        darkMode: false,
        background: 'transparent',
        primaryColor: '#e6f1ec',
        primaryTextColor: '#143d30',
        primaryBorderColor: '#1f5947',
        lineColor: '#1f5947',
        secondaryColor: '#edf5f1',
        tertiaryColor: '#f3f8f5',
        secondaryTextColor: '#374151',
        tertiaryTextColor: '#6b7280',
        fontSize: '13.5px',
        fontFamily: '"Segoe UI Variable Text", "Segoe UI", system-ui, -apple-system, sans-serif',
        nodeBorder: '#1f5947',
        mainBkg: '#f0f7f4',
        nodeTextColor: '#143d30',
        actorBkg: '#ffffff',
        actorBorder: '#1f5947',
        actorTextColor: '#143d30',
        signalColor: '#1f5947',
        signalTextColor: '#143d30',
        clusterBkg: '#f7faf8',
        clusterBorder: '#a3c2b5',
        edgeLabelBackground: '#ffffff',
      },
      securityLevel: 'loose',
      fontFamily: '"Segoe UI Variable Text", "Segoe UI", system-ui, -apple-system, sans-serif',
    })
  }
  currentMermaidTheme = targetTheme
}

/**
 * 异步渲染单个 Mermaid 结构图为 SVG
 */
async function renderMermaidSvg(id: string, code: string): Promise<string> {
  initMermaid()
  try {
    const { svg } = await mermaid.render(id, code)
    return svg
  } catch (err) {
    // 移除 Mermaid 渲染失败时可能挂载到 document.body 上的残留错误 DOM 节点
    const errEl = document.getElementById('d' + id) || document.getElementById(id)
    if (errEl && errEl.parentNode === document.body) {
      document.body.removeChild(errEl)
    }
    throw err
  }
}

/**
 * 遍历渲染容器内的所有 Mermaid 卡片
 */
async function renderAllMermaidDiagrams(): Promise<void> {
  await nextTick()
  if (!containerRef.value) return

  const cards = containerRef.value.querySelectorAll<HTMLElement>('.md-mermaid-card[data-mermaid-code]')
  for (const card of Array.from(cards)) {
    const encodedCode = card.getAttribute('data-mermaid-code')
    const chartView = card.querySelector<HTMLElement>('.md-mermaid-view-chart')
    if (!encodedCode || !chartView) continue

    const code = decodeURIComponent(encodedCode).trim()
    if (!code) continue

    // 若已经成功渲染过相同代码，则避免重复渲染
    if (card.getAttribute('data-rendered-code') === encodedCode) continue

    const uniqueId = `mermaid-svg-${Date.now()}-${++renderSvgCounter}`
    try {
      const svg = await renderMermaidSvg(uniqueId, code)
      chartView.innerHTML = svg
      card.setAttribute('data-rendered-code', encodedCode)
      card.classList.remove('has-error')
    } catch {
      card.classList.add('has-error')
      if (props.isStreaming) {
        chartView.innerHTML = `<div class="md-mermaid-streaming-hint"><span class="md-spin">⏳</span> 架构图生成中...</div>`
      } else {
        chartView.innerHTML = `<div class="md-mermaid-error-hint">⚠️ 图表语法不完整或解析异常，请切换「源码」查看</div>`
      }
    }
  }
}

/**
 * 基础 HTML 实体转义（防御 XSS）
 */
function escapeHtml(str: string): string {
  return str
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;')
}

/**
 * 行内 Markdown 解析（粗体、斜体、删除线、行内代码、安全超链接）
 */
function renderInlineMarkdown(str: string): string {
  let res = escapeHtml(str)
  // 粗斜体 ***text***
  res = res.replace(/\*\*\*(.+?)\*\*\*/g, '<strong><em>$1</em></strong>')
  // 粗体 **text**
  res = res.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
  // 斜体 *text*
  res = res.replace(/\*(.+?)\*/g, '<em>$1</em>')
  // 删除线 ~~text~~
  res = res.replace(/~~(.+?)~~/g, '<del>$1</del>')
  // 行内代码 `code`
  res = res.replace(/`([^`]+)`/g, '<code class="md-inline-code">$1</code>')
  // 安全超链接 [text](url)（仅允许 http/https 链接，拦截 javascript: 等伪协议）
  res = res.replace(
    /\[([^\]]+)\]\((https?:\/\/[^\s\)]+)\)/g,
    '<a href="$2" target="_blank" rel="noopener noreferrer" class="md-link">$1 <span class="link-arrow">↗</span></a>',
  )
  return res
}

/**
 * GFM 表格 HTML 渲染生成器
 */
function renderTableHtml(headerLine: string, separatorLine: string, bodyLines: string[]): string {
  const headerCells = headerLine
    .trim()
    .replace(/^\|/, '')
    .replace(/\|$/, '')
    .split('|')
    .map((c) => c.trim())

  const sepCells = separatorLine
    .trim()
    .replace(/^\|/, '')
    .replace(/\|$/, '')
    .split('|')
    .map((c) => c.trim())

  // 对齐方式解析 (:---: 居中, ---: 右对齐, :--- 或 --- 左对齐)
  const aligns = sepCells.map((s) => {
    const leftColon = s.startsWith(':')
    const rightColon = s.endsWith(':')
    if (leftColon && rightColon) return 'center'
    if (rightColon) return 'right'
    return 'left'
  })

  let thead = '<thead><tr>'
  headerCells.forEach((cell, idx) => {
    const align = aligns[idx] || 'left'
    thead += `<th class="md-th align-${align}" style="text-align: ${align}">${renderInlineMarkdown(cell)}</th>`
  })
  thead += '</tr></thead>'

  let tbody = '<tbody>'
  bodyLines.forEach((bLine) => {
    if (!bLine.trim()) return
    const bCells = bLine
      .trim()
      .replace(/^\|/, '')
      .replace(/\|$/, '')
      .split('|')
      .map((c) => c.trim())

    tbody += '<tr>'
    headerCells.forEach((_, idx) => {
      const cellVal = bCells[idx] ?? ''
      const align = aligns[idx] || 'left'
      tbody += `<td class="md-td align-${align}" style="text-align: ${align}">${renderInlineMarkdown(cellVal)}</td>`
    })
    tbody += '</tr>'
  })
  tbody += '</tbody>'

  return `<div class="md-table-wrap"><table class="md-table">${thead}${tbody}</table></div>`
}

/**
 * 语言展示名规范化
 */
function formatLanguageName(rawLang: string): string {
  const lang = (rawLang || '').trim().toLowerCase()
  const map: Record<string, string> = {
    py: 'Python',
    python: 'Python',
    ts: 'TypeScript',
    typescript: 'TypeScript',
    js: 'JavaScript',
    javascript: 'JavaScript',
    json: 'JSON',
    sql: 'SQL',
    bash: 'Bash',
    sh: 'Shell',
    shell: 'Shell',
    zsh: 'Zsh',
    html: 'HTML',
    css: 'CSS',
    yaml: 'YAML',
    yml: 'YAML',
    go: 'Go',
    golang: 'Go',
    rust: 'Rust',
    rs: 'Rust',
    cpp: 'C++',
    'c++': 'C++',
    c: 'C',
    java: 'Java',
    vue: 'Vue',
    md: 'Markdown',
    markdown: 'Markdown',
    xml: 'XML',
    text: 'Text',
    txt: 'Text',
  }
  return map[lang] || (lang ? lang.toUpperCase() : 'Code')
}

/**
 * 将 Markdown 格式文本转换为安全且样式优化的 HTML（支持实时流式解析）
 */
function renderMarkdown(raw: string): string {
  if (!raw) return ''

  // 保留流式文本末尾的换行与未闭合围栏，避免每个增量帧改变 Markdown 边界。
  let text = raw

  // 0. 清理可能由历史数据或后端预包裹的 <p> / </p> 标签
  text = text
    .replace(/^<p>/i, '')
    .replace(/<\/p>$/i, '')
    .replace(/<p\b[^>]*>/gi, '\n\n')
    .replace(/<\/p>/gi, '')

  // 占位符定义（私有区字符，防止转义破坏）
  const mermaidMarker = (idx: number) => `\uE000MERMAID_BLOCK_${idx}\uE001`
  const codeMarker = (idx: number) => `\uE000CODE_BLOCK_${idx}\uE001`
  const tableMarker = (idx: number) => `\uE000TABLE_BLOCK_${idx}\uE001`
  const mathMarker = (idx: number) => `\uE000MATH_BLOCK_${idx}\uE001`
  const inlineMathMarker = (idx: number) => `\uE000INLINE_MATH_${idx}\uE001`

  // 1. 优先提取并暂存 Mermaid 架构图/流程图（支持闭合与流式未闭合）
  const mermaidBlocks: { code: string; isStreamingUnclosed?: boolean }[] = []

  // 1.1 闭合 Mermaid 块
  text = text.replace(/```(?:mermaid)\n([\s\S]*?)```/gi, (_, code) => {
    const idx = mermaidBlocks.length
    mermaidBlocks.push({ code: code.trim() })
    return mermaidMarker(idx)
  })

  // 1.2 流式未闭合 Mermaid 块
  text = text.replace(/```(?:mermaid)\n([\s\S]*)$/gi, (_, code) => {
    const idx = mermaidBlocks.length
    mermaidBlocks.push({ code: code.trim(), isStreamingUnclosed: true })
    return mermaidMarker(idx)
  })

  // 2. 提取并暂存常规围栏代码块 ```lang\ncode\n```
  const codeBlocks: { lang: string; code: string; isStreamingUnclosed?: boolean }[] = []

  // 2.1 闭合代码块
  text = text.replace(/```([a-zA-Z0-9_#+-]*)\n([\s\S]*?)```/g, (_, lang, code) => {
    const idx = codeBlocks.length
    codeBlocks.push({ lang: (lang || 'text').trim(), code: code.replace(/\n$/, '') })
    return codeMarker(idx)
  })

  // 2.2 流式未闭合代码块
  text = text.replace(/```([a-zA-Z0-9_#+-]*)\n([\s\S]*)$/g, (_, lang, code) => {
    const idx = codeBlocks.length
    codeBlocks.push({ lang: (lang || 'text').trim(), code: code.replace(/\n$/, ''), isStreamingUnclosed: true })
    return codeMarker(idx)
  })

  // 2.3 刚打出 ```lang 还没有换行的情况
  text = text.replace(/```([a-zA-Z0-9_#+-]*)$/g, (_, lang) => {
    const idx = codeBlocks.length
    codeBlocks.push({ lang: (lang || 'text').trim(), code: '', isStreamingUnclosed: true })
    return codeMarker(idx)
  })

  // 3. 提取并暂存 GFM 表格
  const tableBlocks: string[] = []
  const lines = text.split('\n')
  const outLines: string[] = []
  let lineIdx = 0

  while (lineIdx < lines.length) {
    const curLine = lines[lineIdx]
    if (curLine.includes('|') && lineIdx + 1 < lines.length) {
      const nextLine = lines[lineIdx + 1]
      const isSeparator = /^[\s|:-]+$/.test(nextLine) && nextLine.includes('-') && nextLine.includes('|')
      if (isSeparator) {
        const headerLine = curLine
        const separatorLine = nextLine
        const bodyLines: string[] = []
        lineIdx += 2
        while (lineIdx < lines.length && lines[lineIdx].includes('|') && lines[lineIdx].trim() !== '') {
          bodyLines.push(lines[lineIdx])
          lineIdx++
        }
        const tableHtml = renderTableHtml(headerLine, separatorLine, bodyLines)
        const tIdx = tableBlocks.length
        tableBlocks.push(tableHtml)
        outLines.push(tableMarker(tIdx))
        continue
      }
    }
    outLines.push(curLine)
    lineIdx++
  }
  text = outLines.join('\n')

  // 4. 提取并暂存块级数学公式 $$formula$$
  const mathBlocks: string[] = []
  text = text.replace(/\$\$([\s\S]*?)\$\$/g, (_, formula) => {
    const idx = mathBlocks.length
    mathBlocks.push(formula.trim())
    return mathMarker(idx)
  })

  // 5. 提取并暂存行内数学公式 $formula$
  const inlineMaths: string[] = []
  text = text.replace(/\$([^\$\n]+?)\$/g, (_, formula) => {
    const idx = inlineMaths.length
    inlineMaths.push(formula.trim())
    return inlineMathMarker(idx)
  })

  // 6. HTML 实体转义
  text = escapeHtml(text)

  // 7. 标题转换 (# ~ ######)
  text = text.replace(/^######\s+(.+)$/gm, '<h6 class="md-h6">$1</h6>')
  text = text.replace(/^#####\s+(.+)$/gm, '<h5 class="md-h5">$1</h5>')
  text = text.replace(/^####\s+(.+)$/gm, '<h4 class="md-h4">$1</h4>')
  text = text.replace(/^###\s+(.+)$/gm, '<h3 class="md-h3">$1</h3>')
  text = text.replace(/^##\s+(.+)$/gm, '<h2 class="md-h2">$1</h2>')
  text = text.replace(/^#\s+(.+)$/gm, '<h1 class="md-h1">$1</h1>')

  // 8. 水平分割线 (--- 或 *** 或 ===)
  text = text.replace(/^(?:---|===|\*\*\*)$/gm, '<hr class="md-hr" />')

  // 9. 引用块 (> quote)
  text = text.replace(/^>\s+(.+)$/gm, '<blockquote class="md-quote">$1</blockquote>')

  // 10. 行内元素（粗体、斜体、删除线、行内代码、安全链接）
  text = text.replace(/\*\*\*(.+?)\*\*\*/g, '<strong><em>$1</em></strong>')
  text = text.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
  text = text.replace(/\*(.+?)\*/g, '<em>$1</em>')
  text = text.replace(/~~(.+?)~~/g, '<del>$1</del>')
  text = text.replace(/`([^`]+)`/g, '<code class="md-inline-code">$1</code>')
  text = text.replace(
    /\[([^\]]+)\]\((https?:\/\/[^\s\)]+)\)/g,
    '<a href="$2" target="_blank" rel="noopener noreferrer" class="md-link">$1 <span class="link-arrow">↗</span></a>',
  )

  // 11. 无序列表与有序列表
  text = text.replace(/^[\*\-\+]\s+(.+)$/gm, '<li class="md-li-bullet">$1</li>')
  text = text.replace(/^\d+\.\s+(.+)$/gm, '<li class="md-li-num">$1</li>')

  // 12. 段落分块与换行处理
  const paragraphs = text.split(/\n{2,}/)
  text = paragraphs
    .map((p) => {
      const trimmed = p.trim()
      if (!trimmed) return ''
      if (
        trimmed.startsWith('<h') ||
        trimmed.startsWith('<hr') ||
        trimmed.startsWith('<blockquote') ||
        trimmed.startsWith('\uE000MERMAID_BLOCK_') ||
        trimmed.startsWith('\uE000CODE_BLOCK_') ||
        trimmed.startsWith('\uE000TABLE_BLOCK_') ||
        trimmed.startsWith('\uE000MATH_BLOCK_')
      ) {
        return trimmed
      }
      if (trimmed.includes('<li')) {
        return `<ul class="md-ul">${trimmed}</ul>`
      }
      return `<p class="md-p">${trimmed.replace(/\n/g, '<br />')}</p>`
    })
    .join('\n')

  // 13. 回填 Mermaid 架构图卡片
  text = text.replace(/\uE000MERMAID_BLOCK_(\d+)\uE001/g, (_, idxStr) => {
    const item = mermaidBlocks[Number(idxStr)]
    if (!item) return ''
    const escapedCode = escapeHtml(item.code)
    const encodedCode = encodeURIComponent(item.code)

    return `<div class="md-mermaid-card" data-mermaid-code="${encodedCode}">
      <div class="md-code-head">
        <div class="md-code-lang-tag">
          <svg class="md-code-icon-svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="7" height="7"></rect><rect x="14" y="3" width="7" height="7"></rect><rect x="14" y="14" width="7" height="7"></rect><path d="M10 6.5h4"></path><path d="M17.5 10v4"></path></svg>
          <span class="md-code-lang">Mermaid 架构图 / 流程图</span>
        </div>
        <div class="md-mermaid-actions">
          <button class="md-mermaid-tab-btn active" data-action="tab-chart" type="button">图表</button>
          <button class="md-mermaid-tab-btn" data-action="tab-code" type="button">源码</button>
          <button class="md-copy-btn" data-copy="${escapedCode}" type="button" title="复制 Mermaid 源码">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg>
            <span class="md-copy-text">复制</span>
          </button>
        </div>
      </div>
      <div class="md-mermaid-view-chart">
        <div class="md-mermaid-loading"><span class="md-spin">⏳</span> 正在渲染架构图...</div>
      </div>
      <div class="md-mermaid-view-code" style="display: none;">
        <pre class="md-code-body mono"><code>${escapedCode}</code></pre>
      </div>
    </div>`
  })

  // 14. 回填表格
  text = text.replace(/\uE000TABLE_BLOCK_(\d+)\uE001/g, (_, idxStr) => {
    return tableBlocks[Number(idxStr)] || ''
  })

  // 15. 回填常规代码块
  text = text.replace(/\uE000CODE_BLOCK_(\d+)\uE001/g, (_, idxStr) => {
    const item = codeBlocks[Number(idxStr)]
    if (!item) return ''
    const escapedCode = escapeHtml(item.code)
    const langDisplay = formatLanguageName(item.lang)

    return `<div class="md-code-card">
      <div class="md-code-head">
        <div class="md-code-lang-tag">
          <svg class="md-code-icon-svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="16 18 22 12 16 6"></polyline><polyline points="8 6 2 12 8 18"></polyline></svg>
          <span class="md-code-lang">${escapeHtml(langDisplay)}</span>
        </div>
        <button class="md-copy-btn" data-copy="${escapeHtml(item.code)}" type="button" title="复制代码">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg>
          <span class="md-copy-text">复制代码</span>
        </button>
      </div>
      <pre class="md-code-body mono"><code>${escapedCode}</code></pre>
    </div>`
  })

  // 16. 回填块级数学公式
  text = text.replace(/\uE000MATH_BLOCK_(\d+)\uE001/g, (_, idxStr) => {
    const formula = mathBlocks[Number(idxStr)] || ''
    return `<div class="md-math-block mono">$$ ${escapeHtml(formula)} $$</div>`
  })

  // 17. 回填行内数学公式
  text = text.replace(/\uE000INLINE_MATH_(\d+)\uE001/g, (_, idxStr) => {
    const formula = inlineMaths[Number(idxStr)] || ''
    return `<span class="md-inline-math mono">$ ${escapeHtml(formula)} $</span>`
  })

  return text
}

/** 仅识别完整独立 JSON；未闭合的流式 JSON 仍按普通 Markdown 显示。 */
function parseStandaloneJson(raw: string): unknown | undefined {
  const trimmed = raw.trim()
  const fenced = trimmed.match(/^```json\s*\n([\s\S]*?)\n?```$/i)
  const candidate = (fenced?.[1] || trimmed).trim()
  if (!candidate.startsWith('{') && !candidate.startsWith('[')) return undefined
  try {
    return JSON.parse(candidate)
  } catch {
    return undefined
  }
}

const structuredValue = computed(() => parseStandaloneJson(renderedSource.value))
const showStructuredValue = computed(() => !props.isStreaming && structuredValue.value !== undefined)
const renderedHtml = computed(() => renderMarkdown(renderedSource.value))

/** 流式正文按动画帧合并，避免每个 token 都全量解析 Markdown 和更新 v-html。 */
function syncRenderedSource(content: string, streaming: boolean): void {
  if (markdownRenderFrame !== undefined) {
    window.cancelAnimationFrame(markdownRenderFrame)
    markdownRenderFrame = undefined
  }
  if (!streaming) {
    renderedSource.value = content
    return
  }
  markdownRenderFrame = window.requestAnimationFrame(() => {
    renderedSource.value = content
    markdownRenderFrame = undefined
  })
}

/**
 * 监听内容更新，自动触发 Mermaid 图表渲染
 */
watch(
  () => [props.content, props.isStreaming] as const,
  ([content, streaming]) => {
    syncRenderedSource(content, streaming)
    if (mermaidRenderFrame !== undefined) {
      window.cancelAnimationFrame(mermaidRenderFrame)
      mermaidRenderFrame = undefined
    }
    // Mermaid 在流式过程中常为未闭合状态；仅稳定正文触发一次真实 SVG 渲染。
    if (!streaming) {
      mermaidRenderFrame = window.requestAnimationFrame(() => {
        void renderAllMermaidDiagrams()
        mermaidRenderFrame = undefined
      })
    }
  },
  { immediate: true },
)

onMounted(() => {
  if (typeof MutationObserver !== 'undefined' && typeof document !== 'undefined') {
    themeObserver = new MutationObserver((mutations) => {
      for (const m of mutations) {
        if (m.type === 'attributes' && m.attributeName === 'data-theme') {
          initMermaid(true)
          if (containerRef.value) {
            const cards = containerRef.value.querySelectorAll<HTMLElement>('.md-mermaid-card[data-mermaid-code]')
            cards.forEach((card) => card.removeAttribute('data-rendered-code'))
          }
          void renderAllMermaidDiagrams()
          break
        }
      }
    })
    themeObserver.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })
  }
})

onBeforeUnmount(() => {
  if (themeObserver) {
    themeObserver.disconnect()
    themeObserver = null
  }
  if (markdownRenderFrame !== undefined) window.cancelAnimationFrame(markdownRenderFrame)
  if (mermaidRenderFrame !== undefined) window.cancelAnimationFrame(mermaidRenderFrame)
})

/**
 * 委托处理点击事件（代码复制、Mermaid 图表/源码 Tab 切换）
 */
function handleContainerClick(e: MouseEvent): void {
  const target = e.target as HTMLElement

  // 1. 处理复制代码
  const copyBtn = target.closest('.md-copy-btn') as HTMLElement | null
  if (copyBtn) {
    const code = copyBtn.getAttribute('data-copy')
    if (code) {
      void copyText(code).then((copied) => {
        if (!copied) return
        const textSpan = copyBtn.querySelector('.md-copy-text') || copyBtn
        const originalText = textSpan.textContent || '复制'
        textSpan.textContent = '已复制 ✓'
        copyBtn.classList.add('copied')
        setTimeout(() => {
          textSpan.textContent = originalText
          copyBtn.classList.remove('copied')
        }, 1800)
      })
    }
    return
  }

  // 2. 处理 Mermaid Tab 切换（图表 / 源码）
  const tabBtn = target.closest('.md-mermaid-tab-btn') as HTMLElement | null
  if (tabBtn) {
    const action = tabBtn.getAttribute('data-action')
    const card = tabBtn.closest('.md-mermaid-card') as HTMLElement | null
    if (card) {
      const chartView = card.querySelector<HTMLElement>('.md-mermaid-view-chart')
      const codeView = card.querySelector<HTMLElement>('.md-mermaid-view-code')
      const allTabs = card.querySelectorAll('.md-mermaid-tab-btn')

      allTabs.forEach((t) => t.classList.remove('active'))
      tabBtn.classList.add('active')

      if (action === 'tab-chart') {
        if (chartView) chartView.style.display = 'flex'
        if (codeView) codeView.style.display = 'none'
      } else if (action === 'tab-code') {
        if (chartView) chartView.style.display = 'none'
        if (codeView) codeView.style.display = 'block'
      }
    }
    return
  }
}
</script>

<style scoped>
.markdown-view {
  font-size: 15.5px;
  line-height: 1.8;
  color: var(--text-primary, #111827);
  word-break: break-word;
  position: relative;
}

[data-theme='dark'] .markdown-view {
  color: var(--text-primary, #f9fafb);
}

.markdown-content {
  display: inline;
}

/* 实时打字机光标 */
.md-streaming-cursor {
  display: inline-block;
  color: #1f5947;
  font-weight: 700;
  margin-left: 3px;
  font-size: 15px;
  vertical-align: baseline;
  animation: md-cursor-blink 0.8s infinite ease-in-out;
}

[data-theme='dark'] .md-streaming-cursor {
  color: #34d399;
}

@keyframes md-cursor-blink {
  0%, 100% { opacity: 1; transform: scaleY(1); }
  50% { opacity: 0; transform: scaleY(0.85); }
}

/* 段落与文本排版 */
:deep(.md-p) {
  margin: 0 0 14px;
  font-size: 15.5px;
  line-height: 1.8;
  letter-spacing: 0.01em;
}
:deep(.md-p:last-child) {
  margin-bottom: 0;
}

/* 标题层级 */
:deep(.md-h1),
:deep(.md-h2),
:deep(.md-h3),
:deep(.md-h4),
:deep(.md-h5),
:deep(.md-h6) {
  font-weight: 700;
  line-height: 1.45;
  color: var(--text-primary, #111827);
  letter-spacing: 0.02em;
}
[data-theme='dark'] :deep(.md-h1),
[data-theme='dark'] :deep(.md-h2),
[data-theme='dark'] :deep(.md-h3),
[data-theme='dark'] :deep(.md-h4),
[data-theme='dark'] :deep(.md-h5),
[data-theme='dark'] :deep(.md-h6) {
  color: var(--text-primary, #f9fafb);
}
:deep(.md-h1) {
  font-size: 22px;
  margin: 22px 0 12px;
  padding-bottom: 6px;
  border-bottom: 1px solid var(--border-subtle, #e5e7eb);
}
:deep(.md-h2) {
  font-size: 19.5px;
  margin: 18px 0 10px;
}
:deep(.md-h3) {
  font-size: 17.5px;
  margin: 15px 0 8px;
}
:deep(.md-h4) {
  font-size: 16px;
  margin: 12px 0 6px;
}
:deep(.md-h5),
:deep(.md-h6) {
  font-size: 15px;
  margin: 10px 0 6px;
  color: var(--text-secondary, #4b5563);
}
[data-theme='dark'] :deep(.md-h5),
[data-theme='dark'] :deep(.md-h6) {
  color: var(--text-secondary, #9ca3af);
}

:deep(.md-hr) {
  border: 0;
  border-top: 1px solid var(--border-subtle, #e5e7eb);
  margin: 18px 0;
}
[data-theme='dark'] :deep(.md-hr) {
  border-top-color: var(--border-subtle, rgba(255, 255, 255, 0.08));
}

:deep(.md-quote) {
  margin: 12px 0;
  padding: 10px 16px;
  border-left: 3.5px solid #1f5947;
  background: #f0f6f3;
  border-radius: 0 8px 8px 0;
  color: #263d33;
  font-size: 15px;
  line-height: 1.75;
}
[data-theme='dark'] :deep(.md-quote) {
  border-left-color: #16977a;
  background: rgba(22, 151, 122, 0.08);
  color: #cbd5e1;
}

/* 行内代码 */
:deep(.md-inline-code) {
  font-family: var(--font-mono, "JetBrains Mono", "Fira Code", monospace);
  font-size: 14px;
  background: #edf5f1;
  color: #1f5947;
  padding: 2.5px 7px;
  border-radius: 5px;
  border: 1px solid rgba(31, 89, 71, 0.2);
  margin: 0 2px;
}
[data-theme='dark'] :deep(.md-inline-code) {
  background: rgba(22, 151, 122, 0.15);
  color: #34d399;
  border-color: rgba(22, 151, 122, 0.3);
}

/* 超链接 */
:deep(.md-link) {
  color: #1f5947;
  text-decoration: underline;
  text-underline-offset: 3px;
  font-weight: 500;
  transition: opacity 0.15s ease, color 0.15s ease;
}
:deep(.md-link:hover) {
  opacity: 0.85;
  color: #174a3a;
}
[data-theme='dark'] :deep(.md-link) {
  color: #34d399;
}
[data-theme='dark'] :deep(.md-link:hover) {
  color: #6ee7b7;
}
:deep(.link-arrow) {
  font-size: 12px;
  opacity: 0.8;
}

/* 列表样式 */
:deep(.md-ul) {
  margin: 8px 0 14px 22px;
  padding: 0;
}
:deep(.md-li-bullet) {
  list-style-type: disc;
  margin-bottom: 8px;
  font-size: 15.5px;
  line-height: 1.8;
}
:deep(.md-li-bullet::marker) {
  color: #1f5947;
}
[data-theme='dark'] :deep(.md-li-bullet::marker) {
  color: #34d399;
}
:deep(.md-li-num) {
  list-style-type: decimal;
  margin-bottom: 8px;
  font-size: 15.5px;
  line-height: 1.8;
}
:deep(.md-li-num::marker) {
  color: #1f5947;
  font-weight: 600;
}
[data-theme='dark'] :deep(.md-li-num::marker) {
  color: #34d399;
}

/* 围栏代码块卡片 */
:deep(.md-code-card) {
  margin: 14px 0;
  border: 1px solid #d8e2de;
  border-radius: 10px;
  overflow: hidden;
  background: #f8fafc;
  box-shadow: 0 2px 8px rgba(23, 74, 58, 0.04);
}
[data-theme='dark'] :deep(.md-code-card) {
  background: #0b1015;
  border-color: rgba(255, 255, 255, 0.08);
  box-shadow: 0 4px 14px rgba(0, 0, 0, 0.35);
}

:deep(.md-code-head) {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 7px 14px;
  background: #eef4f1;
  border-bottom: 1px solid #d8e2de;
}
[data-theme='dark'] :deep(.md-code-head) {
  background: rgba(255, 255, 255, 0.035);
  border-bottom-color: rgba(255, 255, 255, 0.07);
}

:deep(.md-code-lang-tag) {
  display: flex;
  align-items: center;
  gap: 6px;
}
:deep(.md-code-icon-svg) {
  color: #1f5947;
  flex-shrink: 0;
}
[data-theme='dark'] :deep(.md-code-icon-svg) {
  color: #34d399;
}
:deep(.md-code-icon) {
  font-size: 13px;
}
:deep(.md-code-lang) {
  font-family: var(--font-mono, monospace);
  font-size: 12px;
  font-weight: 600;
  color: #1f5947;
  letter-spacing: 0.04em;
}
[data-theme='dark'] :deep(.md-code-lang) {
  color: #34d399;
}

:deep(.md-copy-btn) {
  display: flex;
  align-items: center;
  gap: 5px;
  background: #ffffff;
  border: 1px solid #d8e2de;
  color: #4b5563;
  border-radius: 5px;
  padding: 3px 9px;
  font-size: 12px;
  cursor: pointer;
  transition: all 0.18s ease;
}
:deep(.md-copy-btn:hover) {
  background: #eef4f1;
  color: #1f5947;
  border-color: #1f5947;
}
:deep(.md-copy-btn.copied) {
  color: #1f5947;
  border-color: #1f5947;
  background: #e6f1ec;
}
[data-theme='dark'] :deep(.md-copy-btn) {
  background: rgba(255, 255, 255, 0.04);
  border-color: rgba(255, 255, 255, 0.12);
  color: #94a3b8;
}
[data-theme='dark'] :deep(.md-copy-btn:hover) {
  background: rgba(22, 151, 122, 0.1);
  color: #34d399;
  border-color: #34d399;
}
[data-theme='dark'] :deep(.md-copy-btn.copied) {
  color: #34d399;
  border-color: #34d399;
  background: rgba(22, 151, 122, 0.18);
}

:deep(.md-code-body) {
  margin: 0;
  padding: 12px 16px;
  font-family: var(--font-mono, "JetBrains Mono", "Fira Code", monospace);
  font-size: 13.5px;
  line-height: 1.65;
  color: #1e293b;
  overflow-x: auto;
  background: transparent;
}
[data-theme='dark'] :deep(.md-code-body) {
  color: #e2e8f0;
}

/* Mermaid 架构图卡片样式 */
:deep(.md-mermaid-card) {
  margin: 16px 0;
  border: 1px solid #d8e2de;
  border-radius: 10px;
  overflow: hidden;
  background: #ffffff;
  box-shadow: 0 2px 10px rgba(23, 74, 58, 0.04);
}
[data-theme='dark'] :deep(.md-mermaid-card) {
  background: #0b1015;
  border-color: rgba(255, 255, 255, 0.08);
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.35);
}

:deep(.md-mermaid-actions) {
  display: flex;
  align-items: center;
  gap: 6px;
}
:deep(.md-mermaid-tab-btn) {
  background: transparent;
  border: 1px solid transparent;
  color: #4b5563;
  border-radius: 5px;
  padding: 2.5px 8px;
  font-size: 11.5px;
  cursor: pointer;
  transition: all 0.15s ease;
}
:deep(.md-mermaid-tab-btn:hover) {
  background: #eef4f1;
  color: #1f5947;
}
:deep(.md-mermaid-tab-btn.active) {
  background: #e6f1ec;
  color: #1f5947;
  border-color: rgba(31, 89, 71, 0.3);
  font-weight: 600;
}
[data-theme='dark'] :deep(.md-mermaid-tab-btn) {
  color: #94a3b8;
}
[data-theme='dark'] :deep(.md-mermaid-tab-btn:hover) {
  background: rgba(255, 255, 255, 0.06);
  color: #f8fafc;
}
[data-theme='dark'] :deep(.md-mermaid-tab-btn.active) {
  background: rgba(22, 151, 122, 0.2);
  color: #34d399;
  border-color: rgba(22, 151, 122, 0.4);
  font-weight: 600;
}

:deep(.md-mermaid-view-chart) {
  padding: 20px 16px;
  overflow-x: auto;
  display: flex;
  justify-content: center;
  align-items: center;
  min-height: 100px;
  background: #fafcfa;
}
[data-theme='dark'] :deep(.md-mermaid-view-chart) {
  background: #08110e;
}

:deep(.md-mermaid-view-chart svg) {
  max-width: 100% !important;
  height: auto !important;
  display: block;
  margin: 0 auto;
}
:deep(.md-mermaid-loading),
:deep(.md-mermaid-streaming-hint) {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: var(--text-tertiary, #64748b);
  padding: 12px;
}
:deep(.md-mermaid-error-hint) {
  font-size: 13px;
  color: #d97706;
  padding: 12px;
}
:deep(.md-spin) {
  display: inline-block;
  animation: md-spin 1.5s linear infinite;
}
@keyframes md-spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

/* GFM 表格样式 */
:deep(.md-table-wrap) {
  margin: 14px 0;
  overflow-x: auto;
  border-radius: 8px;
  border: 1px solid #d8e2de;
  box-shadow: 0 1px 4px rgba(23, 74, 58, 0.04);
  background: #ffffff;
}
[data-theme='dark'] :deep(.md-table-wrap) {
  background: #0f172a;
  border-color: rgba(255, 255, 255, 0.1);
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.2);
}

:deep(.md-table) {
  width: 100%;
  border-collapse: collapse;
  font-size: 14px;
  line-height: 1.6;
  text-align: left;
}
:deep(.md-th) {
  background: #eef5f2;
  color: #174a3a;
  font-weight: 600;
  padding: 11px 16px;
  border-bottom: 2px solid #a3c2b5;
  white-space: nowrap;
  font-size: 13.5px;
}
[data-theme='dark'] :deep(.md-th) {
  background: rgba(22, 151, 122, 0.15);
  color: #ecfdf5;
  border-bottom-color: rgba(22, 151, 122, 0.35);
}

:deep(.md-td) {
  padding: 10px 16px;
  border-bottom: 1px solid #e5e7eb;
  color: #1e293b;
  font-size: 13.5px;
}
[data-theme='dark'] :deep(.md-td) {
  color: #cbd5e1;
  border-bottom-color: rgba(255, 255, 255, 0.06);
}

:deep(.md-table tbody tr:nth-child(even)) {
  background: rgba(31, 89, 71, 0.018);
}
[data-theme='dark'] :deep(.md-table tbody tr:nth-child(even)) {
  background: rgba(255, 255, 255, 0.02);
}

:deep(.md-table tbody tr:last-child .md-td) {
  border-bottom: none;
}
:deep(.md-table tbody tr:hover) {
  background: rgba(31, 89, 71, 0.05);
}
[data-theme='dark'] :deep(.md-table tbody tr:hover) {
  background: rgba(22, 151, 122, 0.08);
}

/* 数学公式 */
:deep(.md-math-block) {
  padding: 12px 16px;
  margin: 12px 0;
  text-align: center;
  background: #f3f8f5;
  border: 1px solid #d8e2de;
  border-radius: 8px;
  color: #1e332a;
  font-size: 14.5px;
}
[data-theme='dark'] :deep(.md-math-block) {
  background: rgba(255, 255, 255, 0.03);
  border-color: rgba(255, 255, 255, 0.06);
  color: #cbd5e1;
}

:deep(.md-inline-math) {
  padding: 1px 6px;
  background: #edf5f1;
  border-radius: 4px;
  color: #1f5947;
  font-size: 13.5px;
}
[data-theme='dark'] :deep(.md-inline-math) {
  background: rgba(22, 151, 122, 0.15);
  color: #34d399;
}
</style>
