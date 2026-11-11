<template>
  <!-- Only when the server has a Navidrome set up for Subsonic clients. -->
  <SettingGroup
    v-if="state.available"
    :title="t('subsonic.title')"
    :description="t('subsonic.hint')"
  >
    <div class="flex flex-col gap-4 px-5 py-4">
      <dl class="grid gap-3 text-sm sm:grid-cols-[auto_1fr] sm:gap-x-6">
        <dt class="text-muted">{{ t('subsonic.server') }}</dt>
        <dd class="flex min-w-0 items-center gap-2">
          <code class="truncate font-mono text-fg">{{ state.url }}</code>
          <UiIconButton
            icon="copy"
            size="sm"
            :label="t('subsonic.copy')"
            @click="copy(state.url)"
          />
        </dd>
        <dt class="text-muted">{{ t('subsonic.username') }}</dt>
        <dd class="flex min-w-0 items-center gap-2">
          <code class="truncate font-mono text-fg">{{ state.username }}</code>
          <UiIconButton
            icon="copy"
            size="sm"
            :label="t('subsonic.copy')"
            @click="copy(state.username)"
          />
        </dd>
        <template v-if="password">
          <dt class="text-muted">{{ t('subsonic.password') }}</dt>
          <dd class="flex min-w-0 items-center gap-2">
            <code class="truncate font-mono text-accent">{{ password }}</code>
            <UiIconButton
              icon="copy"
              size="sm"
              :label="t('subsonic.copy')"
              @click="copy(password)"
            />
          </dd>
        </template>
      </dl>

      <p
        v-if="password"
        class="rounded-control bg-warn/10 px-3 py-2.5 text-[13px] text-pretty text-warn"
        role="note"
      >
        {{ t('subsonic.shownOnce') }}
      </p>
      <p v-else class="text-sm text-pretty text-muted">
        {{ state.exists ? t('subsonic.active') : t('subsonic.inactive') }}
      </p>

      <div class="flex flex-wrap gap-2">
        <UiButton
          :variant="state.exists ? 'secondary' : 'primary'"
          :icon="state.exists ? 'retry' : 'plus'"
          :loading="busy === 'issue'"
          :disabled="Boolean(busy)"
          @click="issue"
        >
          {{ state.exists ? t('subsonic.newPassword') : t('subsonic.enable') }}
        </UiButton>
        <UiButton
          v-if="state.exists"
          variant="secondary"
          icon="trash"
          :loading="busy === 'remove'"
          :disabled="Boolean(busy)"
          @click="remove"
        >
          {{ t('subsonic.disable') }}
        </UiButton>
      </div>

      <p class="text-[13px] text-pretty text-muted">
        {{ t('subsonic.clients') }}
      </p>
    </div>
  </SettingGroup>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import SettingGroup from './SettingGroup.vue'
import UiButton from '../ui/UiButton.vue'
import UiIconButton from '../ui/UiIconButton.vue'
import API from '/src/model/api'
import { useUi } from '/src/model/ui'
import { useI18n } from '/src/i18n'

const { t } = useI18n()
const ui = useUi()

const state = reactive({
  available: false,
  url: '',
  username: '',
  exists: false,
})
// Shown once, right after it was made: only Navidrome keeps it.
const password = ref('')
const busy = ref('')

function failed(err) {
  ui.toast(err?.response?.data?.detail || t('toast.actionFailed'), {
    kind: 'error',
  })
}

async function load() {
  try {
    const res = await API.getMySubsonic()
    Object.assign(state, { available: false, ...res.data })
  } catch {
    state.available = false
  }
}

async function issue() {
  if (state.exists) {
    const ok = await ui.confirm({
      title: t('subsonic.newPasswordTitle'),
      body: t('subsonic.newPasswordBody'),
      confirmLabel: t('subsonic.newPassword'),
    })
    if (!ok) return
  }
  busy.value = 'issue'
  try {
    const res = await API.issueMySubsonic()
    password.value = res.data.password
    Object.assign(state, {
      url: res.data.url,
      username: res.data.username,
      exists: true,
    })
  } catch (err) {
    failed(err)
  } finally {
    busy.value = ''
  }
}

async function remove() {
  const ok = await ui.confirm({
    title: t('subsonic.disableTitle'),
    body: t('subsonic.disableBody'),
    confirmLabel: t('subsonic.disable'),
    danger: true,
  })
  if (!ok) return
  busy.value = 'remove'
  try {
    await API.removeMySubsonic()
    password.value = ''
    state.exists = false
  } catch (err) {
    failed(err)
  } finally {
    busy.value = ''
  }
}

async function copy(text) {
  try {
    await navigator.clipboard.writeText(text)
    ui.toast(t('subsonic.copied'), { kind: 'success' })
  } catch {
    // The text is on screen to copy by hand.
  }
}

onMounted(load)
</script>
