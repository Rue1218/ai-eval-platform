<template>
  <span
    class="provider-logo"
    :class="{ 'provider-logo-mark': !hasGraphic, 'provider-logo-compact': props.compact, 'provider-logo-round': logo.round }"
    :style="{ color: brandSvg ? 'var(--text-primary, #222831)' : logo.color, backgroundColor: logo.background, ...(size ? { width: `${size}px`, height: `${size}px`, flexBasis: `${size}px` } : {}) }"
    :title="logo.label"
    role="img"
    :aria-label="logo.label"
  >
    <span v-if="brandSvg" class="provider-brand-svg" aria-hidden="true" v-html="brandSvg"/>
    <svg v-else-if="hasGraphic" :viewBox="logo.viewBox || '0 0 24 24'" aria-hidden="true">
      <defs v-if="logo.gradient">
        <linearGradient :id="gradientId" x1="0%" y1="100%" x2="100%" y2="0%">
          <stop offset="0%" stop-color="#F9AB00" />
          <stop offset="34%" stop-color="#34A853" />
          <stop offset="66%" stop-color="#4285F4" />
          <stop offset="100%" stop-color="#A142F4" />
        </linearGradient>
      </defs>
      <path v-if="logo.path" :d="logo.path" :fill="logo.gradient ? `url(#${gradientId})` : (logo.pathColor || 'currentColor')" />
      <path
        v-for="(brandPath, index) in logo.paths || []"
        :key="index"
        :d="brandPath.d"
        :fill="brandPath.fill || logo.pathColor || 'currentColor'"
      />
    </svg>
    <span v-else aria-hidden="true">{{ logo.mark }}</span>
  </span>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import zhipuSvg from '../assets/providers/glm.svg?raw'
import moonshotSvg from '../assets/providers/kimi.svg?raw'
import deepseekSvg from '../assets/providers/deepseek.svg?raw'
import qwenSvg from '../assets/providers/qwen.svg?raw'
import minimaxSvg from '../assets/providers/minimax.svg?raw'
import nvidiaSvg from '../assets/providers/nvidia.svg?raw'
import volcengineSvg from '../assets/providers/volcengine.svg?raw'
import geminiSvg from '../assets/providers/gemini.svg?raw'
import openaiSvg from '../assets/providers/openai.svg?raw'
import anthropicSvg from '../assets/providers/claude.svg?raw'
import newapiSvg from '../assets/providers/newapi.svg?raw'
import ollamaSvg from '../assets/providers/ollama.svg?raw'
import type { ProviderLogoKey } from '../utils/providerLogo'

export type { ProviderLogoKey } from '../utils/providerLogo'

const props = defineProps<{ provider?: ProviderLogoKey | string | null; compact?: boolean; size?: number }>()

interface ProviderLogoDefinition {
  label: string
  color: string
  mark: string
  viewBox?: string
  path?: string
  paths?: Array<{ d: string; fill?: string }>
  pathColor?: string
  background?: string
  gradient?: boolean
  round?: boolean
}

// 图形来源于 Simple Icons 或供应商官网公开品牌资源；未提供可验证独立图形的供应商使用文字标记，避免借用母公司 Logo。
const LOGOS: Record<ProviderLogoKey, ProviderLogoDefinition> = {
  newapi: { label: 'New API', color: '#222831', mark: '' },
  stepfun: {
    label: '阶跃星辰 StepFun', color: '#111827', mark: '阶', viewBox: '0 0 20 20',
    // 来源：https://www.stepfun.com/step_favicon.svg，紧凑态还原图二的黑色阶梯方块标记。
    paths: [
      { d: 'M3.65 12.69h3.65v3.65H3.65zM8.17 12.69h3.65v3.65H8.17zM8.17 8.17h3.65v3.66H8.17zM8.17 3.66h3.65v3.65H8.17zM12.69 3.65h3.65v3.66h-3.65z', fill: '#111827' },
    ],
  },
  nvidia: { label: 'NVIDIA NIM', color: '#222831', mark: '' },
  mimo: {
    label: 'Xiaomi Mimo', color: '#FF6900', mark: 'MI',
    path: 'M12 0C8.016 0 4.756.255 2.493 2.516.23 4.776 0 8.033 0 12.012c0 3.98.23 7.235 2.494 9.497C4.757 23.77 8.017 24 12 24c3.983 0 7.243-.23 9.506-2.491C23.77 19.247 24 15.99 24 12.012c0-3.984-.233-7.243-2.502-9.504C19.234.252 15.978 0 12 0zM4.906 7.405h5.624c1.47 0 3.007.068 3.764.827.746.746.827 2.233.83 3.676v4.54a.15.15 0 0 1-.152.147h-1.947a.15.15 0 0 1-.152-.148V11.83c-.002-.806-.048-1.634-.464-2.051-.358-.36-1.026-.441-1.72-.458H7.158a.15.15 0 0 0-.151.147v6.98a.15.15 0 0 1-.152.148H4.906a.15.15 0 0 1-.15-.148V7.554a.15.15 0 0 1 .15-.149zm12.131 0h1.949a.15.15 0 0 1 .15.15v8.892a.15.15 0 0 1-.15.148h-1.949a.15.15 0 0 1-.151-.148V7.554a.15.15 0 0 1 .151-.149zM8.92 10.948h2.046c.083 0 .15.066.15.147v5.352c0 .082-.067.148-.15.148H8.92a.15.15 0 0 1-.152-.148v-5.352c0-.081.068-.147.152-.147Z',
  },
  openai: { label: 'OpenAI', color: '#222831', mark: '' },
  anthropic: { label: 'Anthropic Claude', color: '#222831', mark: '' },
  gemini: { label: 'Gemini', color: '#222831', mark: '' },
  deepseek: { label: 'DeepSeek', color: '#222831', mark: '' },
  siliconflow: {
    label: 'SiliconFlow', color: '#6E29F5', mark: 'SF', viewBox: '0 0 53.0207 25.3538',
    // 来源：https://www.siliconflow.cn/logo-new.svg，仅取官网 Logo 左侧图形用于紧凑供应商标识。
    path: 'M50.7172 0H27.6622C26.3877 0 25.3586 1.03397 25.3586 2.30358V9.21911C25.3586 10.4935 24.3294 11.5227 23.055 11.5227H2.30357C1.02914 11.5227 0 12.5567 0 13.8263V23.0502C0 24.3246 1.03395 25.3538 2.30357 25.3538H25.3586C26.633 25.3538 27.6622 24.3198 27.6622 23.0502V16.1347C27.6622 14.8602 28.6913 13.8311 29.9657 13.8311H50.7172C51.9916 13.8311 53.0207 12.7971 53.0207 11.5275V2.30358C53.0207 1.02916 51.9868 0 50.7172 0Z',
  },
  qwen: { label: 'Qwen', color: '#222831', mark: '' },
  volcengine: { label: '火山引擎', color: '#222831', mark: '' },
  qianfan: {
    label: 'Baidu Qianfan', color: '#2932E1', mark: '千',
  },
  hunyuan: { label: 'Tencent Hunyuan', color: '#00A4EF', mark: '元' },
  grok: {
    label: 'xAI Grok', color: '#0A0A0A', mark: 'G', viewBox: '0 0 1024 1024',
    // 来源：xAI 官方品牌资源 SpaceXAI_Grok_Assets.zip 中的 Grok_Logomark_Dark.svg，按原始路径内联。
    paths: [
      { d: 'M395.479 633.828L735.91 381.105C752.599 368.715 776.454 373.548 784.406 392.792C826.26 494.285 807.561 616.253 724.288 699.996C641.016 783.739 525.151 802.104 419.247 760.277L303.556 814.143C469.49 928.202 670.987 899.995 796.901 773.282C896.776 672.843 927.708 535.937 898.785 412.476L899.047 412.739C857.105 231.37 909.358 158.874 1016.4 10.6326C1018.93 7.11771 1021.47 3.60279 1024 0L883.144 141.651V141.212L395.392 633.916', fill: '#0A0A0A' },
      { d: 'M325.226 695.251C206.128 580.84 226.662 403.776 328.285 301.668C403.431 226.097 526.549 195.254 634.026 240.596L749.454 186.994C728.657 171.88 702.007 155.623 671.424 144.2C533.19 86.9942 367.693 115.465 255.323 228.382C147.234 337.081 113.244 504.215 171.613 646.833C215.216 753.423 143.739 828.818 71.7385 904.916C46.2237 931.893 20.6216 958.87 0 987.429L325.139 695.339', fill: '#0A0A0A' },
    ],
  },
  groq: {
    label: 'Groq', color: '#F43E01', mark: 'G', viewBox: '0 0 33 33',
    // 来源：https://groq.com/favicon.svg，修复旧路径坐标系与官网闪电图形不一致的问题。
    paths: [
      { d: 'M.54.39h32v32h-32z', fill: '#F43E01' },
      { d: 'm18.445 4.406-9.468 13.74 7.341.665-1.69 9.578 9.469-13.74-7.342-.664 1.69-9.579Z', fill: '#FFFFFF' },
    ],
  },
  ollama: { label: 'Ollama', color: '#222831', mark: '' },
  zhipu: { label: 'GLM / Z.ai', color: '#222831', mark: '' },
  moonshot: { label: 'Kimi', color: '#222831', mark: '' },
  mistral: {
    label: 'Mistral AI', color: '#FF7000', mark: 'M',
    path: 'M17.143 3.429v3.428h-3.429v3.429h-3.428V6.857H6.857V3.43H3.43v13.714H0v3.428h10.286v-3.428H6.857v-3.429h3.429v3.429h3.429v-3.429h3.428v3.429h-3.428v3.428H24v-3.428h-3.43V3.429z',
  },
  together: { label: 'Together AI', color: '#111827', mark: 'T' },
  minimax: { label: 'MiniMax', color: '#F23F5D', mark: 'M' },
  custom: { label: '自定义端点 / 内部代理', color: '#64748B', mark: '↗' },
}

// 只渲染随包分发的静态品牌 SVG；来源和许可证见 assets/providers/README.md。
const BRAND_SVGS: Partial<Record<ProviderLogoKey, string>> = {newapi: newapiSvg, ollama: ollamaSvg, zhipu: zhipuSvg, moonshot: moonshotSvg, deepseek: deepseekSvg, qwen: qwenSvg, minimax: minimaxSvg, nvidia: nvidiaSvg, volcengine: volcengineSvg, gemini: geminiSvg, openai: openaiSvg, anthropic: anthropicSvg}
const brandSvg = computed(() => BRAND_SVGS[props.provider as ProviderLogoKey])
const logo = computed(() => {
  const key = props.provider as ProviderLogoKey
  return (key && LOGOS[key]) ? LOGOS[key] : LOGOS.custom
})
const hasGraphic = computed(() => Boolean(brandSvg.value || logo.value.path || logo.value.paths?.length))
const gradientId = computed(() => `provider-logo-gradient-${props.provider || 'custom'}`)
</script>

<style scoped>
.provider-brand-svg{display:flex;width:100%;height:100%;align-items:center;justify-content:center}.provider-brand-svg :deep(svg){display:block;width:85%;height:85%}

.provider-logo {
  width: 28px;
  height: 28px;
  display: inline-flex;
  flex: 0 0 28px;
  align-items: center;
  justify-content: center;
  border: 0;
  border-radius: 0;
  background: transparent;
}

.provider-logo svg {
  width: 19px;
  height: 19px;
}

.provider-logo-mark {
  font-size: 12px;
  font-weight: 800;
  letter-spacing: -0.04em;
}

.provider-logo-round {
  border-radius: 50%;
}

.provider-logo-compact {
  width: 16px;
  height: 16px;
  flex-basis: 16px;
  border-radius: 0;
}

.provider-logo-compact svg {
  width: 12px;
  height: 12px;
}

.provider-logo-compact.provider-logo-mark {
  font-size: 8px;
}
</style>
