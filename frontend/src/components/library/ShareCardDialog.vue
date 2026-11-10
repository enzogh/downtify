<template>
  <UiModal
    :open="Boolean(target)"
    :title="t('shareCard.title')"
    :description="t('shareCard.hint')"
    width="sm:max-w-md"
    @close="close"
  >
    <div v-if="target" class="flex flex-col items-center gap-4">
      <div
        class="relative aspect-[9/16] w-full max-w-[260px] overflow-hidden rounded-[12px] bg-surface-2"
        :aria-busy="!preview"
      >
        <img
          v-if="preview"
          :src="preview"
          :alt="t('shareCard.alt', { title: target.song.title })"
          class="size-full object-cover"
        />
        <div v-else class="shimmer absolute inset-0" />
      </div>
      <p v-if="!hasLink && preview" class="text-center text-[12px] text-muted">
        {{ t('shareCard.noLink') }}
      </p>
    </div>
    <template #footer>
      <UiButton variant="ghost" icon="download" :disabled="!blob" @click="save">
        {{ t('shareCard.save') }}
      </UiButton>
      <UiButton
        v-if="canShareFiles"
        variant="primary"
        icon="share"
        :disabled="!blob"
        @click="share"
      >
        {{ t('shareCard.share') }}
      </UiButton>
    </template>
  </UiModal>
</template>

<script setup>
// "Share as image": a story-sized picture of a song (lib/shareCard.js),
// shared straight to an app on phones or saved as a PNG.
import { computed, ref, watch } from 'vue'
import UiButton from '../ui/UiButton.vue'
import UiModal from '../ui/UiModal.vue'
import {
  CARD_HEIGHT,
  CARD_WIDTH,
  cardFileName,
  drawShareCard,
} from '/src/lib/shareCard'
import { extractPalette } from '/src/lib/palette'
import { useShareCard } from '/src/model/shareCard'
import { useUi } from '/src/model/ui'
import { useI18n } from '/src/i18n'

const { t } = useI18n()
const ui = useUi()
const { target, close } = useShareCard()

const preview = ref('')
const blob = ref(null)
const link = ref('')
const hasLink = computed(() => !!link.value)
let run = 0

const fileName = computed(() =>
  target.value
    ? cardFileName(target.value.song.title, target.value.song.artist)
    : 'castify.png'
)

function cardFile() {
  return new File([blob.value], fileName.value, { type: 'image/png' })
}

const canShareFiles = computed(() => {
  if (!blob.value) return false
  const nav = globalThis.navigator
  try {
    return !!nav?.canShare?.({ files: [cardFile()] })
  } catch {
    return false
  }
})

function loadImage(src) {
  return new Promise((resolve) => {
    if (!src) return resolve(null)
    const img = new Image()
    // A remote cover (a song that isn't downloaded) can only be drawn
    // when its host allows it; otherwise the card goes without.
    if (/^https?:/.test(src)) img.crossOrigin = 'anonymous'
    img.onload = () => resolve(img)
    img.onerror = () => resolve(null)
    img.src = src
  })
}

function paletteOf(image) {
  if (!image) return null
  try {
    const canvas = document.createElement('canvas')
    canvas.width = 48
    canvas.height = 48
    const ctx = canvas.getContext('2d', { willReadFrequently: true })
    ctx.drawImage(image, 0, 0, 48, 48)
    return extractPalette(ctx.getImageData(0, 0, 48, 48).data)
  } catch {
    return null
  }
}

async function render(current) {
  const mine = ++run
  const { song } = current
  const [image, url] = await Promise.all([
    loadImage(song.hasCover === false ? '' : song.cover),
    current.link().catch(() => ''),
    document.fonts
      ?.load?.("700 76px 'Sora Variable'")
      .then(() => document.fonts.load("500 46px 'DM Sans Variable'"))
      .catch(() => {}),
  ])
  if (mine !== run) return
  link.value = url || ''
  const canvas = document.createElement('canvas')
  canvas.width = CARD_WIDTH
  canvas.height = CARD_HEIGHT
  const ctx = canvas.getContext('2d')
  const draw = (img) =>
    drawShareCard(ctx, {
      song,
      image: img,
      palette: paletteOf(img),
      url: link.value,
      labels: { listen: t('shareCard.listen'), brand: 'Castify' },
    })
  draw(image)
  let png = await toPng(canvas)
  // A cover that tainted the canvas after all: draw it without.
  if (!png && image) {
    ctx.reset?.()
    draw(null)
    png = await toPng(canvas)
  }
  if (mine !== run) return
  if (!png) {
    ui.toast(t('toast.actionFailed'), { kind: 'error' })
    close()
    return
  }
  blob.value = png
  preview.value = URL.createObjectURL(png)
}

function toPng(canvas) {
  return new Promise((resolve) => {
    try {
      canvas.toBlob(resolve, 'image/png')
    } catch {
      resolve(null)
    }
  })
}

function reset() {
  run += 1
  if (preview.value) URL.revokeObjectURL(preview.value)
  preview.value = ''
  blob.value = null
  link.value = ''
}

watch(target, (current) => {
  reset()
  if (current) void render(current)
})

function save() {
  if (!blob.value) return
  const a = document.createElement('a')
  a.href = preview.value
  a.download = fileName.value
  document.body.appendChild(a)
  a.click()
  a.remove()
}

async function share() {
  if (!blob.value) return
  const { song } = target.value
  try {
    await navigator.share({
      files: [cardFile()],
      title: song.title,
      text: [[song.title, song.artist].filter(Boolean).join(' · '), link.value]
        .filter(Boolean)
        .join('\n'),
    })
    close()
  } catch (err) {
    if (err?.name !== 'AbortError') save()
  }
}
</script>
