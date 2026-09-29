import { createApp } from 'vue'
import { createPinia } from 'pinia'
import Antd from 'ant-design-vue'
import 'ant-design-vue/dist/reset.css'

import App from './App.vue'
import router from './router'
import './styles/global.css'

const app = createApp(App)

// 全局错误边界：避免未捕获错误导致白屏
app.config.errorHandler = (err, instance, info) => {
  console.error('[全局错误]', err, info)
  // 生产环境可上报到监控服务
}

app.use(createPinia()).use(router).use(Antd).mount('#app')
