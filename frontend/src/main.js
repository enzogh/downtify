import { createApp } from 'vue'
import App from './App.vue'
import router from './router/index'
import { localeReady } from './i18n'

import './index.css'
import './model/theme'
// Catches Chrome's install prompt, which can fire before the shell mounts.
import './model/install'
import { blockPageZoom } from './lib/noZoom'
import { startOffline } from './model/offline'

blockPageZoom()
startOffline()

// Mounted once the saved language is in (a few kB, fetched on its own),
// so the first paint is already in it - English if it can't be fetched.
localeReady.finally(() => createApp(App).use(router).mount('#app'))
