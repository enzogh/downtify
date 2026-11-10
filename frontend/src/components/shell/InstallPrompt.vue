<template>
  <!-- "Install Castify": a bottom sheet on phones that walks through
       adding the app to the home screen, step by step for the browser
       in hand. It comes back (at most daily) until the app is installed. -->
  <Teleport to="body">
    <Transition name="install-sheet">
      <div
        v-if="install.open.value"
        class="install-backdrop fixed inset-0 z-[85] flex items-end justify-center bg-black/60 backdrop-blur-sm sm:items-center sm:p-4"
        @click.self="install.snooze()"
      >
        <div
          ref="panel"
          role="dialog"
          aria-modal="true"
          :aria-labelledby="titleId"
          tabindex="-1"
          class="install-panel relative flex max-h-[94dvh] w-full max-w-md flex-col overflow-hidden rounded-t-[28px] border border-line-3 bg-surface shadow-float outline-none sm:rounded-[28px]"
          @keydown.esc="install.snooze()"
        >
          <!-- Spotify-style glow from the brand green behind the icon. -->
          <div
            class="pointer-events-none absolute inset-x-0 top-0 h-56 bg-gradient-to-b from-accent/30 via-accent/10 to-transparent"
            aria-hidden="true"
          />
          <div
            class="relative mx-auto mt-2.5 h-1 w-10 shrink-0 rounded-full bg-fg/25 sm:hidden"
            aria-hidden="true"
          />
          <UiIconButton
            icon="x"
            :label="t('install.later')"
            class="absolute top-3 right-3 z-10"
            @click="install.snooze()"
          />

          <div
            class="install-scroll relative min-h-0 flex-1 overflow-y-auto px-5 pt-5 pb-1 sm:px-6"
          >
            <div class="flex flex-col items-center text-center">
              <img
                src="/192.png"
                alt=""
                width="64"
                height="64"
                class="size-16 rounded-[18px] shadow-cover ring-1 ring-white/10"
              />
              <h2
                :id="titleId"
                class="text-display mt-3 text-xl leading-tight font-bold text-balance text-fg"
              >
                {{ t('install.title') }}
              </h2>
              <!-- Short screens (iPhone SE) keep the steps in view: the extras go. -->
              <p
                class="mt-1.5 max-w-xs text-sm text-pretty text-fg-2 [@media(max-height:600px)]:hidden"
              >
                {{ t('install.subtitle') }}
              </p>
              <ul
                class="mt-3.5 flex flex-wrap justify-center gap-1.5 [@media(max-height:700px)]:hidden"
              >
                <li
                  v-for="perk in perks"
                  :key="perk.icon"
                  class="flex items-center gap-1.5 rounded-full bg-fg/[0.07] px-3 py-1.5 text-xs font-medium text-fg-2"
                >
                  <AppIcon
                    :name="perk.icon"
                    :size="13"
                    stroke-width="2.2"
                    class="text-accent"
                  />
                  {{ perk.label }}
                </li>
              </ul>
            </div>

            <template v-if="!install.canPrompt.value">
              <p
                class="mt-5 mb-2 text-[11px] font-bold tracking-[0.12em] text-muted uppercase"
              >
                {{ t('install.howTo') }}
              </p>
              <ol class="flex flex-col gap-2">
                <li
                  v-for="(step, i) in steps"
                  :key="step.text"
                  class="install-step flex items-center gap-3 rounded-2xl bg-surface-2 px-3.5 py-2.5"
                  :style="{ animationDelay: `${120 + i * 90}ms` }"
                >
                  <span
                    class="flex size-7 shrink-0 items-center justify-center rounded-full bg-accent text-[13px] font-bold text-on-accent"
                    >{{ i + 1 }}</span
                  >
                  <span class="min-w-0 flex-1">
                    <span
                      class="block text-sm leading-snug font-semibold text-fg"
                      >{{ step.text }}</span
                    >
                    <span
                      v-if="step.hint"
                      class="mt-0.5 block text-xs leading-snug text-muted"
                      >{{ step.hint }}</span
                    >
                  </span>
                  <span
                    class="flex size-9 shrink-0 items-center justify-center rounded-xl bg-raised text-fg"
                    aria-hidden="true"
                  >
                    <AppIcon :name="step.icon" :size="20" stroke-width="2" />
                  </span>
                </li>
              </ol>
            </template>
            <p v-else class="mt-6 text-center text-xs text-muted">
              {{ t('install.promptHint') }}
            </p>
          </div>

          <div
            class="relative flex shrink-0 flex-col gap-0.5 border-t border-line-2 px-5 pt-4 sm:px-6 pb-[max(1.25rem,env(safe-area-inset-bottom))]"
          >
            <button
              v-if="install.canPrompt.value"
              type="button"
              class="flex h-12 w-full items-center justify-center gap-2 rounded-full bg-accent text-[15px] font-bold text-on-accent transition-[transform,background-color] hover:bg-accent-hi active:scale-[0.98]"
              @click="install.promptInstall()"
            >
              <AppIcon name="download" :size="18" stroke-width="2.2" />
              {{ t('install.installNow') }}
            </button>
            <button
              v-else
              type="button"
              class="flex h-12 w-full items-center justify-center gap-2 rounded-full bg-accent text-[15px] font-bold text-on-accent transition-[transform,background-color] hover:bg-accent-hi active:scale-[0.98]"
              @click="install.markInstalled()"
            >
              <AppIcon name="check" :size="18" stroke-width="2.4" />
              {{ t('install.done') }}
            </button>
            <button
              type="button"
              class="h-11 w-full rounded-full text-sm font-semibold text-fg-2 transition-colors hover:text-fg"
              @click="install.snooze()"
            >
              {{ t('install.later') }}
            </button>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup>
import { computed, nextTick, onMounted, ref, useId, watch } from 'vue'
import AppIcon from '../ui/AppIcon.vue'
import UiIconButton from '../ui/UiIconButton.vue'
import { useInstall } from '/src/model/install'
import { useI18n } from '/src/i18n'

const { t } = useI18n()
const install = useInstall()
const titleId = `install-${useId()}`
const panel = ref(null)

const perks = computed(() => [
  { icon: 'home', label: t('install.perkHome') },
  { icon: 'expand', label: t('install.perkFull') },
  { icon: 'play', label: t('install.perkLock') },
])

// The steps for the browser in hand; the icon on the right is the button
// to look for on screen.
const steps = computed(() => {
  const step = (icon, key) => ({
    icon,
    text: t(`install.${key}`),
    hint: t(`install.${key}Hint`),
  })
  switch (install.platform.value) {
    case 'ios-inapp':
      return [
        step('more', 'inAppMenu'),
        step('globe', 'inAppSafari'),
        step('ios-share', 'inAppThen'),
      ]
    case 'ios-other':
      return [
        step('ios-share', 'otherShare'),
        step('plus-square', 'iosAdd'),
        step('check', 'iosConfirm'),
      ]
    case 'android':
      return [
        step('more-vertical', 'androidMenu'),
        step('smartphone', 'androidInstall'),
        step('check', 'androidConfirm'),
      ]
    default:
      return [
        step('ios-share', 'iosShare'),
        step('plus-square', 'iosAdd'),
        step('check', 'iosConfirm'),
      ]
  }
})

watch(install.open, async (isOpen) => {
  if (!isOpen) return
  await nextTick()
  panel.value?.focus()
})

// Give the page a moment to settle before sliding the sheet in.
onMounted(() => setTimeout(() => install.offer(), 1200))
</script>

<style scoped>
.install-sheet-enter-active,
.install-sheet-leave-active {
  transition: opacity 240ms ease;
}
.install-sheet-enter-active .install-panel,
.install-sheet-leave-active .install-panel {
  transition: transform 380ms var(--ease-out-soft);
}
.install-sheet-enter-from,
.install-sheet-leave-to {
  opacity: 0;
}
.install-sheet-enter-from .install-panel,
.install-sheet-leave-to .install-panel {
  transform: translateY(100%);
}
@media (min-width: 640px) {
  .install-sheet-enter-from .install-panel,
  .install-sheet-leave-to .install-panel {
    transform: translateY(24px) scale(0.97);
  }
}
.install-step {
  animation: rise 420ms var(--ease-out-soft) both;
}
@media (prefers-reduced-motion: reduce) {
  .install-sheet-enter-active .install-panel,
  .install-sheet-leave-active .install-panel,
  .install-step {
    transition: none;
    animation: none;
  }
}
</style>
