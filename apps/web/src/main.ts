import { createApp } from 'vue'
import { createPinia } from 'pinia'
import 'element-plus/es/components/dialog/style/css'
import 'element-plus/es/components/message/style/css'
import App from './App.vue'
import './styles.css'
import './review-polish.css'
createApp(App).use(createPinia()).mount('#app')
