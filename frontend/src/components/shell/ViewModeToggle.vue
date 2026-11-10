<template>
  <!-- Admins only: one tap shows Castify as a plain user sees it (no
       admin controls anywhere), another brings the admin view back. -->
  <button
    v-if="auth.realIsAdmin.value"
    type="button"
    class="inline-flex h-9 shrink-0 items-center gap-2 rounded-full border px-2.5 text-[13px] font-semibold transition-colors sm:px-3.5"
    :class="
      auth.userView.value
        ? 'border-line-3 text-fg-2 hover:bg-surface-2'
        : 'border-accent/40 bg-accent/12 text-accent hover:bg-accent/20'
    "
    :aria-pressed="!auth.userView.value"
    :aria-label="label"
    :title="hint"
    @click="toggle"
  >
    <AppIcon :name="auth.userView.value ? 'user' : 'shield'" :size="16" />
    <span class="max-sm:sr-only">{{ label }}</span>
  </button>
</template>

<script setup>
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AppIcon from '../ui/AppIcon.vue'
import { useAuth } from '/src/model/auth'
import { useUi } from '/src/model/ui'
import { useI18n } from '/src/i18n'
import { ADMIN_ROUTES } from '/src/lib/viewMode'

const { t } = useI18n()
const auth = useAuth()
const ui = useUi()
const route = useRoute()
const router = useRouter()

const label = computed(() =>
  auth.userView.value ? t('viewMode.userView') : t('viewMode.adminView')
)
const hint = computed(() =>
  auth.userView.value ? t('viewMode.backToAdmin') : t('viewMode.seeAsUser')
)

function toggle() {
  auth.toggleUserView()
  ui.toast(
    auth.userView.value ? t('viewMode.nowUser') : t('viewMode.nowAdmin'),
    { kind: 'success' }
  )
  // A page only admins have: back home rather than a page of nothing.
  if (auth.userView.value && ADMIN_ROUTES.includes(String(route.name)))
    router.push({ name: 'Home' })
}
</script>
