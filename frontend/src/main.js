import { createApp } from 'vue'
import App from './App.vue'
import router from './router/index'

import './index.css'
import './model/theme'
// Catches Chrome's install prompt, which can fire before the shell mounts.
import './model/install'
import { blockPageZoom } from './lib/noZoom'
import { startOffline } from './model/offline'

blockPageZoom()
startOffline()

createApp(App).use(router).mount('#app')
