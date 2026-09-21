import { defineStore } from 'pinia'
import { ref, computed, watch } from 'vue'
import { api, setApiBase } from '../api/client'

const THEME_KEY = 'rag-theme'

export const useAppStore = defineStore('app', () => {
  const theme = ref(localStorage.getItem(THEME_KEY) || 'light')
  const isDark = computed(() => theme.value === 'dark')

  /**
   * 桌面端后端由 Electron 主进程拉起，启动需要几秒（要加载 jieba 词典等），
   * 因此必须把「启动中」和「启动失败」区分开，否则用户会先看到报错再看到成功。
   */
  const phase = ref('starting') // starting | ready | error
  const online = ref(false)
  const health = ref(null)
  const backendError = ref('')
  let unsubscribe = null

  watch(
    theme,
    (v) => {
      localStorage.setItem(THEME_KEY, v)
      document.documentElement.dataset.theme = v
    },
    { immediate: true },
  )

  function toggleTheme() {
    theme.value = theme.value === 'dark' ? 'light' : 'dark'
  }

  /** 真正打一次健康接口，确认后端可用 */
  async function checkBackend() {
    try {
      health.value = await api.health()
      online.value = true
      backendError.value = ''
      phase.value = 'ready'
    } catch (e) {
      online.value = false
      backendError.value = e.message
      phase.value = 'error'
    }
    return online.value
  }

  /** 处理主进程推送的后端状态 */
  function applyBackendInfo(info) {
    if (!info) return
    if (info.status === 'ready') {
      setApiBase(info.url)
      checkBackend()
    } else if (info.status === 'error') {
      online.value = false
      phase.value = 'error'
      backendError.value = info.message || '后端启动失败'
    } else {
      phase.value = 'starting'
    }
  }

  /**
   * 应用启动入口。
   * Electron 下后端由主进程负责拉起，这里只订阅状态；
   * 浏览器里没有桥，直接探测（走 Vite 代理）即可。
   */
  async function init() {
    const bridge = window.ragBridge
    if (!bridge) {
      await checkBackend()
      return online.value
    }

    const info = await bridge.getBackendInfo()
    applyBackendInfo(info)
    if (info?.status === 'starting') {
      unsubscribe?.()
      unsubscribe = bridge.onBackendStatus(applyBackendInfo)
    }
    return phase.value === 'ready'
  }

  function dispose() {
    unsubscribe?.()
    unsubscribe = null
  }

  return {
    theme, isDark, toggleTheme,
    phase, online, health, backendError,
    init, checkBackend, dispose,
  }
})
