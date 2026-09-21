<script setup>
import { computed, onMounted, onUnmounted, watch } from 'vue'
import { theme as antTheme } from 'ant-design-vue'
import SideBar from './components/SideBar.vue'
import { useAppStore } from './stores/app'
import { useKbStore } from './stores/kb'

const app = useAppStore()
const kb = useKbStore()

const themeConfig = computed(() => ({
  algorithm: app.isDark ? antTheme.darkAlgorithm : antTheme.defaultAlgorithm,
  token: {
    colorPrimary: app.isDark ? '#6b86ff' : '#4f6ef7',
    colorBgBase: app.isDark ? '#1b1e24' : '#ffffff',
    borderRadius: 8,
  },
}))

/**
 * 知识库列表必须等后端真正就绪后再拉。
 * Electron 下后端由主进程拉起、要几秒才可用，init() 返回时通常还是 starting，
 * 因此不能只在启动时拉一次，要跟着连接状态走。
 */
watch(
  () => app.online,
  async (online) => {
    if (online) await kb.refresh()
  },
  { immediate: true },
)

/** 启动：等后端就绪 */
async function bootstrap() {
  await app.init()
}

/** 后端是独立进程，窗口重新获得焦点时重新探测，避免显示过期状态 */
async function onFocus() {
  if (app.online) return
  await app.checkBackend()
}

onMounted(() => {
  bootstrap()
  window.addEventListener('focus', onFocus)
})

onUnmounted(() => {
  window.removeEventListener('focus', onFocus)
  app.dispose()
})
</script>

<template>
  <a-config-provider :theme="themeConfig">
    <div class="shell">
      <SideBar />

      <main class="main">
        <!-- 后端由主进程拉起，需要几秒，先给个明确的等待态 -->
        <div v-if="app.phase === 'starting'" class="center">
          <a-spin size="large" />
          <p class="tip">正在启动本地服务…</p>
        </div>

        <div v-else-if="!app.online" class="center">
          <a-result
            status="warning"
            title="未连接到本地服务"
            :sub-title="app.backendError || '后端进程尚未就绪'"
          >
            <template #extra>
              <a-button type="primary" @click="bootstrap">重新连接</a-button>
            </template>
          </a-result>
        </div>

        <router-view v-else />
      </main>
    </div>
  </a-config-provider>
</template>

<style scoped>
.shell {
  display: flex;
  height: 100vh;
  overflow: hidden;
}

.main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.center {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 14px;
  height: 100%;
}

.tip {
  margin: 0;
  font-size: 13px;
  color: var(--text-3);
}
</style>
