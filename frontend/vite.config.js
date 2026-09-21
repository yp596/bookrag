import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 开发期由 Vite 代理到本地后端；Electron 打包后由渲染进程直连动态端口
const BACKEND = process.env.RAG_BACKEND || 'http://127.0.0.1:8756'

export default defineConfig({
  plugins: [vue()],
  // Electron 以 file:// 加载打包产物，必须用相对路径
  base: './',
  server: {
    port: 5178,
    proxy: {
      '/api': {
        target: BACKEND,
        changeOrigin: true,
        // SSE 需要关闭代理层缓冲，否则流式输出会被攒成一次性返回
        configure: (proxy) => {
          proxy.on('proxyRes', (proxyRes) => {
            proxyRes.headers['cache-control'] = 'no-cache, no-transform'
          })
        },
      },
    },
  },
  build: {
    outDir: 'dist',
    chunkSizeWarningLimit: 1500,
  },
})
