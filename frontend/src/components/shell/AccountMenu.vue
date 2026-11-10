<template>
  <!-- Spotify's avatar in the corner: who's signed in, settings, theme,
       and signing out - the same on a phone. -->
  <UiMenu
    v-if="auth.user.value"
    :items="items"
    :label="t('account.menu')"
    align="end"
  >
    <template #trigger>
      <button
        type="button"
        class="flex size-9 shrink-0 items-center justify-center rounded-full bg-surface-2 ring-1 ring-line-3 transition-transform hover:scale-105"
        :aria-label="t('account.menu')"
        :title="auth.user.value.username"
      >
        <span
          class="flex size-7 items-center justify-center rounded-full text-[13px] font-bold"
          :class="
            auth.isAdmin.value
              ? 'bg-accent text-on-accent'
              : 'bg-invert text-on-invert'
          "
          >{{ avatarLetter(auth.user.value.username) }}</span
        >
      </button>
    </template>
  </UiMenu>
</template>

<script setup>
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import UiMenu from '../ui/UiMenu.vue'
import { useAuth } from '/src/model/auth'
import { useTheme } from '/src/model/theme'
import { useI18n } from '/src/i18n'
import { avatarLetter } from '/src/lib/viewMode'

const { t } = useI18n()
const auth = useAuth()
const theme = useTheme()
const router = useRouter()

const items = computed(() => [
  {
    label: auth.user.value?.username || '',
    icon: 'user',
    disabled: true,
  },
  {
    hidden: !auth.realIsAdmin.value,
    label: auth.userView.value
      ? t('viewMode.backToAdmin')
      : t('viewMode.seeAsUser'),
    icon: auth.userView.value ? 'shield' : 'eye',
    action: () => auth.toggleUserView(),
  },
  {
    label: t('nav.settings'),
    icon: 'settings',
    action: () => router.push({ name: 'Settings' }),
  },
  {
    label:
      theme.resolved.value === 'dark'
        ? t('settings.themeLight')
        : t('settings.themeDark'),
    icon: theme.resolved.value === 'dark' ? 'sun' : 'moon',
    action: () => theme.toggle(),
  },
  { divider: true, hidden: auth.authDisabled.value },
  {
    hidden: auth.authDisabled.value,
    label: t('nav.signOut'),
    icon: 'log-out',
    danger: true,
    action: () => auth.signOut(),
  },
])
</script>
