<script setup lang="ts">
/**
 * ECharts 轻量容器：按需注册图表类型，随容器尺寸自适应，卸载时销毁实例。
 * 只传 `option` 即可，避免每个页面重复写 init/resize/dispose。
 */
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts/core'
import { BarChart, LineChart, PieChart } from 'echarts/charts'
import {
  GridComponent,
  LegendComponent,
  TitleComponent,
  TooltipComponent
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import type { ECharts, EChartsCoreOption } from 'echarts/core'

echarts.use([
  BarChart,
  LineChart,
  PieChart,
  GridComponent,
  LegendComponent,
  TitleComponent,
  TooltipComponent,
  CanvasRenderer
])

const props = withDefaults(
  defineProps<{
    option: Record<string, unknown>
    height?: string
  }>(),
  { height: '180px' }
)

const container = ref<HTMLDivElement | null>(null)
let chart: ECharts | null = null
let observer: ResizeObserver | null = null

const render = () => {
  if (!container.value) return
  if (!chart) chart = echarts.init(container.value)
  chart.setOption(props.option as EChartsCoreOption, true)
}

onMounted(() => {
  render()
  if (container.value) {
    observer = new ResizeObserver(() => chart?.resize())
    observer.observe(container.value)
  }
})

watch(() => props.option, render, { deep: true })

onBeforeUnmount(() => {
  observer?.disconnect()
  observer = null
  chart?.dispose()
  chart = null
})
</script>

<template>
  <div ref="container" class="chart-box" :style="{ height }"></div>
</template>

<style scoped>
.chart-box {
  width: 100%;
}
</style>
