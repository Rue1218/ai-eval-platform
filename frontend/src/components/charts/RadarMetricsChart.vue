<template>
  <div ref="chartRef" class="radar-metrics-chart"></div>
</template>

<script setup lang="ts">
import { ref, watch, onMounted, onBeforeUnmount } from 'vue'
import { echarts } from './echarts'
import type { BenchmarkScore } from '../../api/types'

/**
 * 多维度对比雷达图（对齐原型 report.html bm-radar）：
 * 4 维 = contain 命中 / 低失败率 / 低延迟 / Judge 裁判分，全部归一化到 0~1。
 */
const props = defineProps<{
  scores: BenchmarkScore[]
}>()

const chartRef = ref<HTMLDivElement | null>(null)
let chart: echarts.ECharts | null = null

/** 协议档配色循环（原型前两档为蓝/紫，超过两档时顺延扩展色） */
const PALETTE = ['#1D4ED8', '#7C3AED', '#0E7490', '#B45309', '#047857']

/** 延迟归一化：'820ms'/'1.1s'/数字 统一转毫秒后按 2s 封顶折算 */
function latencyScore(latency?: string | number): number {
  if (latency === undefined) return 0
  const ms = typeof latency === 'number' ? latency : latency.endsWith('ms') ? parseFloat(latency) : parseFloat(latency) * 1000
  if (Number.isNaN(ms)) return 0
  return Math.max(0, 1 - ms / 2000)
}

function buildOption() {
  return {
    tooltip: { trigger: 'item' },
    legend: {
      show: props.scores.length > 1,
      bottom: 0,
      textStyle: { fontFamily: 'JetBrains Mono, monospace', fontSize: 11, color: '#6B7280' },
    },
    radar: {
      indicator: [
        { name: 'contain 命中', max: 1 },
        { name: '低失败率', max: 1 },
        { name: '低延迟', max: 1 },
        { name: 'Judge 裁判分', max: 1 },
      ],
      radius: '62%',
      splitLine: { lineStyle: { color: '#E5E7EB' } },
      axisLine: { lineStyle: { color: '#E5E7EB' } },
      splitArea: { show: false },
      axisName: { color: '#6B7280', fontFamily: 'JetBrains Mono, monospace', fontSize: 11 },
    },
    series: [
      {
        type: 'radar',
        symbolSize: 4,
        data: props.scores.map((s, i) => ({
          name: s.profile_name || s.profile,
          value: [
            s.contain ?? 0,
            1 - (s.fail_rate ?? 0),
            latencyScore(s.latency),
            (s.judge ?? 0) / 5,
          ],
          lineStyle: { color: PALETTE[i % PALETTE.length], width: 1.8 },
          itemStyle: { color: PALETTE[i % PALETTE.length] },
          areaStyle: { color: PALETTE[i % PALETTE.length], opacity: 0.12 },
        })),
      },
    ],
  }
}

function render() {
  if (!chartRef.value) return
  if (!chart) chart = echarts.init(chartRef.value)
  chart.setOption(buildOption(), true)
}

function handleResize() {
  chart?.resize()
}

onMounted(render)
watch(() => props.scores, render, { deep: true })
onBeforeUnmount(() => {
  window.removeEventListener('resize', handleResize)
  chart?.dispose()
  chart = null
})

// 窗口尺寸变化时自适应
window.addEventListener('resize', handleResize)
</script>

<style scoped>
.radar-metrics-chart {
  width: 100%;
  height: 300px;
}
</style>
