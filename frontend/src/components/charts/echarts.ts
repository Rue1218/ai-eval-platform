/**
 * ECharts 按需注册入口：仅引入报告页用到的雷达图/折线图与基础组件，控制打包体积。
 */
import * as echarts from 'echarts/core'
import { RadarChart, LineChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, LegendComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

echarts.use([RadarChart, LineChart, GridComponent, TooltipComponent, LegendComponent, CanvasRenderer])

export { echarts }
