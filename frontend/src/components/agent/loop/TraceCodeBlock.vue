<template>
  <pre class="trace-code-block"><code><span v-for="(token, index) in tokens" :key="index" class="trace-code-token" :class="`is-${token.kind}`">{{ token.text }}</span></code></pre>
</template>

<script setup lang="ts">
import { computed } from 'vue'

/** 将已脱敏的轨迹数据格式化为可读代码，不使用 v-html，避免事件内容注入页面。 */
const props = defineProps<{ value: unknown }>()
type TokenKind = 'plain' | 'key' | 'string' | 'number' | 'literal' | 'punctuation'
type CodeToken = { text: string; kind: TokenKind }

/** 字符串 JSON 保持结构化；其他文本原样显示，便于阅读工具输出。 */
function source(value: unknown) {
  if (typeof value === 'string') {
    try { return JSON.stringify(JSON.parse(value), null, 2) } catch { return value }
  }
  return JSON.stringify(value, null, 2) ?? '未提供'
}

/** 轻量 JSON 词法分段，只负责展示配色，不改变实际代码字符。 */
function tokenize(value: string): CodeToken[] {
  const result: CodeToken[] = [], matcher = /("(?:\\.|[^"\\])*")(\s*:)?|(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)|\b(true|false|null)\b|([{}\[\],:])/g
  let cursor = 0, match: RegExpExecArray | null
  while ((match = matcher.exec(value))) {
    if (match.index > cursor) result.push({ text: value.slice(cursor, match.index), kind: 'plain' })
    result.push({ text: match[0], kind: match[1] ? (match[2] ? 'key' : 'string') : match[3] ? 'number' : match[4] ? 'literal' : 'punctuation' })
    cursor = matcher.lastIndex
  }
  if (cursor < value.length) result.push({ text: value.slice(cursor), kind: 'plain' })
  return result
}

const tokens = computed(() => tokenize(source(props.value)))
</script>

<style scoped>
.trace-code-block { max-height: 460px; overflow: auto; margin: 0; border: 1px solid #dfe5ee; border-radius: 8px; background: #fbfcff; padding: 14px 16px; color: #3c4d65; font: 14px/1.75 var(--font-mono); white-space: pre-wrap; overflow-wrap: anywhere; tab-size: 2; }
.trace-code-token.is-key { color: #7756ad; } .trace-code-token.is-string { color: #a24d4a; } .trace-code-token.is-number { color: #1d7c61; } .trace-code-token.is-literal { color: #2d69a5; } .trace-code-token.is-punctuation { color: #65758b; }
</style>
