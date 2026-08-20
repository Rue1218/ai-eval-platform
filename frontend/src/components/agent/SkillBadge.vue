<template>
  <!-- 技能徽标：思考卡卡头展示（规划 / ReAct / 复核，开发说明书 §7 / §16.7 冻结） -->
  <span v-if="label" class="skill-badge" :data-skill="skillId">
    <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
      <path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5" />
    </svg>
    <span>{{ label }}</span>
  </span>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { skillLabel } from '../../agent/skillLabels'

const props = defineProps<{
  skillId?: string | null
}>()

const label = computed(() => skillLabel(props.skillId))
</script>

<style scoped>
.skill-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 1px 7px;
  border-radius: 999px;
  background: var(--t-agent, rgba(16, 185, 129, 0.12));
  color: var(--c-agent, #10b981);
  border: 1px solid rgba(16, 185, 129, 0.25);
  font-size: 11px;
  font-weight: 600;
  line-height: 1.4;
  letter-spacing: 0.02em;
  user-select: none;
  vertical-align: middle;
}
.skill-badge svg {
  flex-shrink: 0;
}
</style>
