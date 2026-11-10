<template>
  <!-- Spotify's filter pills: one row that slides sideways under a
       finger when it doesn't fit, the current one filled in green. -->
  <div
    ref="root"
    role="tablist"
    class="-mx-4 flex snap-x scroll-px-4 gap-2 overflow-x-auto px-4 py-0.5 [scrollbar-width:none] sm:mx-0 sm:px-0 [&::-webkit-scrollbar]:hidden"
  >
    <component
      :is="item.to ? RouterLink : 'button'"
      v-for="item in items"
      :key="item.id"
      :to="item.to || undefined"
      :type="item.to ? undefined : 'button'"
      role="tab"
      :aria-selected="item.id === modelValue"
      :data-tab="item.id"
      class="inline-flex h-9 shrink-0 snap-start items-center gap-1.5 rounded-full px-4 text-[13px] whitespace-nowrap transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
      :class="
        item.id === modelValue
          ? 'bg-accent font-semibold text-on-accent'
          : 'bg-surface-2 font-medium text-fg-2 hover:bg-raised hover:text-fg'
      "
      @click="$emit('update:modelValue', item.id)"
    >
      {{ item.label }}
      <span
        v-if="item.count !== undefined && item.count !== null"
        class="tabular text-[12px]"
        :class="item.id === modelValue ? 'opacity-70' : 'text-faint'"
        >{{ item.count }}</span
      >
    </component>
  </div>
</template>

<script setup>
import { nextTick, onMounted, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'

const props = defineProps({
  items: { type: Array, required: true },
  modelValue: { type: String, default: '' },
})
defineEmits(['update:modelValue'])

// The selected pill is never left off the edge of a phone's screen.
const root = ref(null)
function reveal() {
  nextTick(() => {
    const box = root.value
    const pill = box?.querySelector(`[data-tab="${props.modelValue}"]`)
    if (!box || !pill) return
    const left = pill.offsetLeft - box.offsetLeft
    if (
      left < box.scrollLeft ||
      left + pill.offsetWidth > box.scrollLeft + box.clientWidth
    )
      box.scrollTo({ left: Math.max(0, left - 16), behavior: 'smooth' })
  })
}
onMounted(reveal)
watch(() => props.modelValue, reveal)
</script>
