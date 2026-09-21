<script setup>
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  MessageOutlined,
  DatabaseOutlined,
  SettingOutlined,
  BulbOutlined,
  BulbFilled,
} from '@ant-design/icons-vue'
import { useAppStore } from '../stores/app'
import { useKbStore } from '../stores/kb'

const app = useAppStore()
const kb = useKbStore()
const route = useRoute()
const router = useRouter()

const NAV = [
  { key: 'chat', path: '/chat', label: '对话', icon: MessageOutlined },
  { key: 'knowledge', path: '/knowledge', label: '知识库', icon: DatabaseOutlined },
  { key: 'settings', path: '/settings', label: '设置', icon: SettingOutlined },
]

const activeKey = computed(() => route.name)

const statusText = computed(() => {
  if (app.phase === 'starting') return '正在启动服务…'
  if (!app.online) return '服务未连接'
  const h = app.health
  if (!h) return '已连接'
  return h.llm_mode === 'local' ? `本地 · ${h.model}` : `云端 · ${h.model}`
})
</script>

<template>
  <aside class="sider">
    <div class="brand">
      <div class="logo">RAG</div>
      <div class="brand-text">
        <div class="brand-title">本地知识库</div>
        <div class="brand-sub">离线文档问答</div>
      </div>
    </div>

    <nav class="nav">
      <button
        v-for="item in NAV"
        :key="item.key"
        class="nav-item"
        :class="{ active: activeKey === item.key }"
        @click="router.push(item.path)"
      >
        <component :is="item.icon" class="nav-icon" />
        <span>{{ item.label }}</span>
        <span v-if="item.key === 'knowledge' && kb.list.length" class="badge">
          {{ kb.list.length }}
        </span>
      </button>
    </nav>

    <div class="foot">
      <div class="status">
        <span class="dot" :class="{ on: app.online, pending: app.phase === 'starting' }" />
        <span class="status-text" :title="statusText">{{ statusText }}</span>
      </div>
      <a-tooltip :title="app.isDark ? '切换到浅色' : '切换到深色'" placement="top">
        <button class="icon-btn" @click="app.toggleTheme()">
          <BulbFilled v-if="app.isDark" />
          <BulbOutlined v-else />
        </button>
      </a-tooltip>
    </div>
  </aside>
</template>

<style scoped>
.sider {
  width: 216px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  background: var(--bg-sider);
  border-right: 1px solid var(--border);
  user-select: none;
}

/* ---------- 品牌区 ---------- */
.brand {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 18px 16px 16px;
}
.logo {
  width: 34px;
  height: 34px;
  flex-shrink: 0;
  border-radius: 9px;
  background: linear-gradient(135deg, var(--accent), #7b8cff);
  color: #fff;
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.5px;
  display: flex;
  align-items: center;
  justify-content: center;
}
.brand-title {
  font-size: 14px;
  font-weight: 600;
  line-height: 1.3;
}
.brand-sub {
  font-size: 11px;
  color: var(--text-3);
  line-height: 1.4;
}

/* ---------- 导航 ---------- */
.nav {
  flex: 1;
  padding: 4px 10px;
  overflow-y: auto;
}
.nav-item {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 9px 10px;
  margin-bottom: 2px;
  border: none;
  border-radius: 8px;
  background: transparent;
  color: var(--text-2);
  font-size: 13.5px;
  font-family: inherit;
  cursor: pointer;
  text-align: left;
  transition: background 0.15s, color 0.15s;
}
.nav-item:hover {
  background: var(--bg-hover);
  color: var(--text-1);
}
.nav-item.active {
  background: var(--accent-soft);
  color: var(--accent);
  font-weight: 600;
}
.nav-icon {
  font-size: 15px;
}
.badge {
  margin-left: auto;
  min-width: 18px;
  height: 18px;
  padding: 0 5px;
  border-radius: 9px;
  background: var(--bg-hover);
  color: var(--text-3);
  font-size: 11px;
  font-weight: 500;
  display: flex;
  align-items: center;
  justify-content: center;
}

/* ---------- 底部状态 ---------- */
.foot {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 14px;
  border-top: 1px solid var(--border);
}
.status {
  flex: 1;
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 7px;
}
.dot {
  width: 7px;
  height: 7px;
  flex-shrink: 0;
  border-radius: 50%;
  background: var(--text-3);
}
.dot.on {
  background: #22c55e;
  box-shadow: 0 0 0 3px rgba(34, 197, 94, 0.16);
}
/* 后端启动中：琥珀色呼吸灯，与「连不上」的灰点区分开 */
.dot.pending {
  background: #f59e0b;
  animation: pulse 1.2s ease-in-out infinite;
}
@keyframes pulse {
  50% {
    opacity: 0.3;
  }
}
.status-text {
  font-size: 11.5px;
  color: var(--text-3);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.icon-btn {
  flex-shrink: 0;
  width: 28px;
  height: 28px;
  border: none;
  border-radius: 7px;
  background: transparent;
  color: var(--text-3);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: background 0.15s, color 0.15s;
}
.icon-btn:hover {
  background: var(--bg-hover);
  color: var(--text-1);
}
</style>
