import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  // Electron 以 file:// 加载打包产物，必须用相对路径
  base: './',
  server: {
    port: 5178,
  },
  build: {
    outDir: 'dist',
    chunkSizeWarningLimit: 1500,
  },
})
