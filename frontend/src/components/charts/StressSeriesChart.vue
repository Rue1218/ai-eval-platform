<template>
  <div ref="chartRef" class="stress-series-chart"></div>
</template>

<script setup lang="ts">
import { ref, watch, onMounted, onBeforeUnmount } from 'vue'
import { echarts } from './echarts'
import type { StressSeriesPoint } from '../../api/types'

/**
 * 压测时序性能曲线（对齐原型 report.html stress-chart）：
 * 三轴线图 = QPS（左轴）/ P99 RT ms（右轴）/ 错误率 %（隐藏第三轴）。
 */
const props = defineProps<{
  series: StressSeriesPoint[]
}>()

const chartRef = ref<HTMLDivElement | null>(null)
let chart: echarts.ECharts | null = null

function buildOption() {
  const labels = props.series.map(p => p.ts)
  return {
    tooltip: { trigger: 'axis' },
    legend: {
      bottom: 0,
      textStyle: { fontFamily: 'JetBrains Mono, monospace', fontSize: 11, color: '#6B7280' },
    },
    grid: { left: 48, right: 56, top: 16, bottom: 48 },
    xAxis: {
      type: 'category',
      data: labels,
      axisLine: { lineStyle: { color: '#E5E7EB' } },
      axisLabel: { fontFamily: 'JetBrains Mono, monospace', fontSize: 11 },
    },
    yAxis: [
      {
        type: 'value',
        name: 'QPS',
        position: 'left',
        splitLine: { lineStyle: { color: '#EEF2F2' } },
        axisLabel: { fontFamily: 'JetBrains Mono, monospace', fontSize: 11 },
      },
      {
        type: 'value',
        name: 'P99 (ms)',
        position: 'right',
        splitLine: { show: false },
        axisLabel: { fontFamily: 'JetBrains Mono, monospace', fontSize: 11 },
      },
      {
        // 错误率隐藏轴：数值小（%），仅参与 tooltip 与曲线映射
        type: 'value',
        show: false,
        max: 2,
      },
    ],
    series: [
      {
        name: 'QPS',
        type: 'line',
        smooth: true,
        symbolSize: 5,
        data: props.series.map(p => p.qps),
        lineStyle: { color: '#6366F1', width: 1.8 },
        itemStyle: { color: '#6366F1' },
        areaStyle: { color: '#6366F1', opacity: 0.14 },
        yAxisIndex: 0,
      },
      {
        name: 'P99 RT (ms)',
        type: 'line',
        smooth: true,
        symbolSize: 5,
        data: props.series.map(p => p.rt_ms),
        lineStyle: { color: '#0E7490', width: 1.8 },
        itemStyle: { color: '#0E7490' },
        areaStyle: { color: '#0E7490', opacity: 0.1 },
        yAxisIndex: 1,
      },
      {
        name: '错误率 (%)',
        type: 'line',
        smooth: true,
        symbolSize: 5,
        // 契约中 error_rate 为小数比率，图上按百分比呈现
        data: props.series.map(p => +(((p.error_rate ?? 0) * 100)).toFixed(2)),
        lineStyle: { color: '#EF4444', width: 1.8 },
        itemStyle: { color: '#EF4444' },
        areaStyle: { color: '#EF4444', opacity: 0.1 },
        yAxisIndex: 2,
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
watch(() => props.series, render, { deep: true })
onBeforeUnmount(() => {
  window.removeEventListener('resize', handleResize)
  chart?.dispose()
  chart = null
})

// 窗口尺寸变化时自适应
window.addEventListener('resize', handleResize)
</script>

<style scoped>
.stress-series-chart {
  width: 100%;
  height: 280px;
}
</style>
