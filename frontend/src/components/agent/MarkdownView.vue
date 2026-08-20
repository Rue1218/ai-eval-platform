<template>
  <!-- 富文本渲染器：支持 Markdown、围栏代码块（带复制）、Mermaid 降级与 KaTeX 公式 -->
  <div class="markdown-view" :class="customClass" v-html="renderedHtml" @click="handleContainerClick"></div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(
  defineProps<{
    content: string
    customClass?: string
  }>(),
  {
    content: '',
    customClass: '',
  },
)

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
 * 将 Markdown 格式文本转换为安全的 HTML
 */
function renderMarkdown(raw: string): string {
  if (!raw) return ''

  let text = raw.trim()

  // 0. 清理可能由历史数据或后端预包裹的 <p> / </p> 标签，防止转义后输出字面标签
  text = text
    .replace(/^<p>/i, '')
    .replace(/<\/p>$/i, '')
    .replace(/<p\b[^>]*>/gi, '\n\n')
    .replace(/<\/p>/gi, '')

  // 使用私有区字符保存占位符，避免后续 HTML 转义破坏围栏代码和公式的回填标记。
  const codeMarker = (idx: number) => `\uE000CODE_BLOCK_${idx}\uE001`
  const mathMarker = (idx: number) => `\uE000MATH_BLOCK_${idx}\uE001`
  const inlineMathMarker = (idx: number) => `\uE000INLINE_MATH_${idx}\uE001`

  // 1. 提取并暂存围栏代码块 ```lang\ncode\n```
  const codeBlocks: { lang: string; code: string }[] = []
  text = text.replace(/```([a-zA-Z0-9_-]*)\n([\s\S]*?)```/g, (_, lang, code) => {
    const idx = codeBlocks.length
    codeBlocks.push({ lang: (lang || 'text').trim(), code: code.replace(/\n$/, '') })
    return codeMarker(idx)
  })

  // 2. 提取并暂存块级数学公式 $$formula$$
  const mathBlocks: string[] = []
  text = text.replace(/\$\$([\s\S]*?)\$\$/g, (_, formula) => {
    const idx = mathBlocks.length
    mathBlocks.push(formula.trim())
    return mathMarker(idx)
  })

  // 3. 提取并暂存行内数学公式 $formula$
  const inlineMaths: string[] = []
  text = text.replace(/\$([^\$\n]+?)\$/g, (_, formula) => {
    const idx = inlineMaths.length
    inlineMaths.push(formula.trim())
    return inlineMathMarker(idx)
  })

  // 4. HTML 实体转义（消除普通文本中的 XSS 漏洞）
  text = escapeHtml(text)

  // 5. 标题转换 (# ~ ######)
  text = text.replace(/^######\s+(.+)$/gm, '<h6 class="md-h6">$1</h6>')
  text = text.replace(/^#####\s+(.+)$/gm, '<h5 class="md-h5">$1</h5>')
  text = text.replace(/^####\s+(.+)$/gm, '<h4 class="md-h4">$1</h4>')
  text = text.replace(/^###\s+(.+)$/gm, '<h3 class="md-h3">$1</h3>')
  text = text.replace(/^##\s+(.+)$/gm, '<h2 class="md-h2">$1</h2>')
  text = text.replace(/^#\s+(.+)$/gm, '<h1 class="md-h1">$1</h1>')

  // 6. 水平分割线 (--- 或 ***)
  text = text.replace(/^(?:---|===|\*\*\*)$/gm, '<hr class="md-hr" />')

  // 7. 引用块 (> quote)
  text = text.replace(/^>\s+(.+)$/gm, '<blockquote class="md-quote">$1</blockquote>')

  // 8. 粗体与斜体
  text = text.replace(/\*\*\*(.+?)\*\*\*/g, '<strong><em>$1</em></strong>')
  text = text.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
  text = text.replace(/\*(.+?)\*/g, '<em>$1</em>')
  text = text.replace(/~~(.+?)~~/g, '<del>$1</del>')

  // 9. 行内代码 `code`
  text = text.replace(/`([^`]+)`/g, '<code class="md-inline-code">$1</code>')

  // 10. 安全链接 [text](url)（仅允许 http/https 链接，拦截 javascript:）
  text = text.replace(/\[([^\]]+)\]\((https?:\/\/[^\s\)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer" class="md-link">$1 ↗</a>')

  // 11. 无序列表与有序列表项
  text = text.replace(/^[\*\-]\s+(.+)$/gm, '<li class="md-li-bullet">$1</li>')
  text = text.replace(/^\d+\.\s+(.+)$/gm, '<li class="md-li-num">$1</li>')

  // 12. 换行与段落分块
  const paragraphs = text.split(/\n{2,}/)
  text = paragraphs
    .map((p) => {
      const trimmed = p.trim()
      if (!trimmed) return ''
      if (
        trimmed.startsWith('<h') ||
        trimmed.startsWith('<hr') ||
        trimmed.startsWith('<blockquote') ||
        trimmed.startsWith('\uE000CODE_BLOCK_') ||
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

  // 13. 回填围栏代码块
  text = text.replace(/\uE000CODE_BLOCK_(\d+)\uE001/g, (_, idxStr) => {
    const item = codeBlocks[Number(idxStr)]
    if (!item) return ''
    const escapedCode = escapeHtml(item.code)
    const isMermaid = item.lang.toLowerCase() === 'mermaid'

    if (isMermaid) {
      // Mermaid 降级渲染：展示源码并标注 Mermaid 图表
      return `<div class="md-code-card md-mermaid-card">
        <div class="md-code-head">
          <span class="md-code-lang">📊 Mermaid 结构图</span>
          <button class="md-copy-btn" data-copy="${escapeHtml(item.code)}" type="button">复制源码</button>
        </div>
        <pre class="md-code-body mono"><code>${escapedCode}</code></pre>
      </div>`
    }

    return `<div class="md-code-card">
      <div class="md-code-head">
        <span class="md-code-lang">${escapeHtml(item.lang || 'text')}</span>
        <button class="md-copy-btn" data-copy="${escapeHtml(item.code)}" type="button">复制代码</button>
      </div>
      <pre class="md-code-body mono"><code>${escapedCode}</code></pre>
    </div>`
  })

  // 14. 回填块级数学公式
  text = text.replace(/\uE000MATH_BLOCK_(\d+)\uE001/g, (_, idxStr) => {
    const formula = mathBlocks[Number(idxStr)] || ''
    return `<div class="md-math-block mono">$$ ${escapeHtml(formula)} $$</div>`
  })

  // 15. 回填行内数学公式
  text = text.replace(/\uE000INLINE_MATH_(\d+)\uE001/g, (_, idxStr) => {
    const formula = inlineMaths[Number(idxStr)] || ''
    return `<span class="md-inline-math mono">$ ${escapeHtml(formula)} $</span>`
  })

  return text
}

const renderedHtml = computed(() => renderMarkdown(props.content))

/**
 * 委托处理代码块复制按钮点击
 */
function handleContainerClick(e: MouseEvent) {
  const target = e.target as HTMLElement
  if (target && target.classList.contains('md-copy-btn')) {
    const code = target.getAttribute('data-copy')
    if (code) {
      navigator.clipboard.writeText(code).then(() => {
        const originalText = target.innerText
        target.innerText = '已复制 ✓'
        target.classList.add('copied')
        setTimeout(() => {
          target.innerText = originalText
          target.classList.remove('copied')
        }, 1500)
      })
    }
  }
}
</script>

<style scoped>
.markdown-view {
  font-size: 15px;
  line-height: 1.8;
  color: var(--text-primary, #f1f5f9);
  word-break: break-word;
}

:deep(.md-p) {
  margin: 0 0 12px;
  font-size: 15px;
  line-height: 1.8;
}
:deep(.md-p:last-child) {
  margin-bottom: 0;
}

:deep(.md-h1),
:deep(.md-h2),
:deep(.md-h3),
:deep(.md-h4) {
  font-weight: 700;
  margin: 16px 0 10px;
  line-height: 1.4;
  color: var(--text-primary, #ffffff);
}
:deep(.md-h1) { font-size: 19px; }
:deep(.md-h2) { font-size: 17.5px; }
:deep(.md-h3) { font-size: 16px; }
:deep(.md-h4) { font-size: 15px; }

:deep(.md-hr) {
  border: 0;
  border-top: 1px solid var(--border-subtle, rgba(255, 255, 255, 0.08));
  margin: 16px 0;
}

:deep(.md-quote) {
  margin: 10px 0;
  padding: 8px 14px;
  border-left: 3px solid var(--accent-ai, #10b981);
  background: var(--bg-elevated, rgba(255, 255, 255, 0.04));
  border-radius: 0 6px 6px 0;
  color: var(--text-secondary, #94a3b8);
  font-size: 14px;
}

:deep(.md-inline-code) {
  font-family: var(--font-mono, monospace);
  font-size: 13px;
  background: var(--bg-elevated, rgba(255, 255, 255, 0.08));
  color: var(--accent-ai, #10b981);
  padding: 2px 6px;
  border-radius: 4px;
  border: 1px solid var(--border-subtle, rgba(255, 255, 255, 0.08));
}

:deep(.md-link) {
  color: var(--accent-ai, #10b981);
  text-decoration: underline;
  text-underline-offset: 3px;
  transition: opacity 0.15s ease;
}
:deep(.md-link:hover) {
  opacity: 0.8;
}

:deep(.md-ul) {
  margin: 8px 0 12px 20px;
  padding: 0;
}
:deep(.md-li-bullet) {
  list-style-type: disc;
  margin-bottom: 6px;
  font-size: 15px;
  line-height: 1.8;
}
:deep(.md-li-num) {
  list-style-type: decimal;
  margin-bottom: 6px;
  font-size: 15px;
  line-height: 1.8;
}

/* 围栏代码块卡片 */
:deep(.md-code-card) {
  margin: 12px 0;
  border: 1px solid var(--border-subtle, rgba(255, 255, 255, 0.1));
  border-radius: 8px;
  overflow: hidden;
  background: #0f172a;
}
:deep(.md-code-head) {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 12px;
  background: rgba(255, 255, 255, 0.03);
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
}
:deep(.md-code-lang) {
  font-family: var(--font-mono, monospace);
  font-size: 12px;
  color: var(--text-tertiary, #64748b);
  text-transform: lowercase;
}
:deep(.md-copy-btn) {
  background: transparent;
  border: 1px solid rgba(255, 255, 255, 0.12);
  color: var(--text-secondary, #94a3b8);
  border-radius: 4px;
  padding: 2px 8px;
  font-size: 11.5px;
  cursor: pointer;
  transition: all 0.15s ease;
}
:deep(.md-copy-btn:hover) {
  background: rgba(255, 255, 255, 0.08);
  color: var(--text-primary, #ffffff);
}
:deep(.md-copy-btn.copied) {
  color: var(--accent-ai, #10b981);
  border-color: var(--accent-ai, #10b981);
}
:deep(.md-code-body) {
  margin: 0;
  padding: 10px 12px;
  font-size: 13px;
  line-height: 1.6;
  color: #e2e8f0;
  overflow-x: auto;
}

/* 数学公式与 Mermaid 降级样式 */
:deep(.md-math-block) {
  padding: 10px 14px;
  margin: 10px 0;
  text-align: center;
  background: var(--bg-elevated, rgba(255, 255, 255, 0.03));
  border-radius: 6px;
  color: #cbd5e1;
  font-size: 14px;
}
:deep(.md-inline-math) {
  padding: 1px 5px;
  background: var(--bg-elevated, rgba(255, 255, 255, 0.04));
  border-radius: 3px;
  color: #cbd5e1;
  font-size: 13.5px;
}
</style>
