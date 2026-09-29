<script setup>
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  MessageOutlined,
  DatabaseOutlined,
  SettingOutlined,
  BulbOutlined,
  BulbFilled,
  PlusOutlined,
  ReloadOutlined,
  ReadOutlined,
  StarOutlined,
  StarFilled,
  CheckOutlined,
} from '@ant-design/icons-vue'
import { useAppStore } from '../stores/app'
import { useKbStore } from '../stores/kb'
import { useChatStore } from '../stores/chat'
import { api } from '../api/client'

const app = useAppStore()
const kb = useKbStore()
const chat = useChatStore()
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

// ---------- 对话列表（按时间分组） ----------
const sessionOptions = computed(() => {
  const list = chat.sessionsOf(kb.currentId)
  if (!Array.isArray(list)) return []
  return list.map((s) => ({
    value: s.id,
    label: s.msg_count ? `${s.name} · ${s.msg_count}` : s.name,
    msg_count: s.msg_count || 0,
    created_at: s.created_at || '',
  }))
})

// ---------- 搜索过滤 ----------
const searchQuery = ref('')

const filteredSessionOptions = computed(() => {
  if (!searchQuery.value.trim()) return sessionOptions.value
  const q = searchQuery.value.toLowerCase()
  return sessionOptions.value.filter((s) =>
    s.label.toLowerCase().includes(q)
  )
})

// ---------- 批量删除 ----------
const batchMode = ref(false)
const selectedIds = ref([])

const allSelected = computed(() => {
  const all = filteredSessionOptions.value
  return all.length > 0 && all.every((s) => selectedIds.value.includes(s.value))
})

function toggleSelectAll() {
  if (allSelected.value) {
    selectedIds.value = []
  } else {
    selectedIds.value = filteredSessionOptions.value.map((s) => s.value)
  }
}

async function batchDelete() {
  if (!selectedIds.value.length) return
  try {
    for (const sid of selectedIds.value) {
      await chat.removeSession(kb.currentId, sid)
    }
    selectedIds.value = []
    batchMode.value = false
  } catch (e) {
    // 错误处理
  }
}

function toggleSelect(sid) {
  const idx = selectedIds.value.indexOf(sid)
  if (idx >= 0) {
    selectedIds.value.splice(idx, 1)
  } else {
    selectedIds.value.push(sid)
  }
}

/** 分组：今天、昨天、更早（防炸：非法日期归 earlier） */
const groupedSessions = computed(() => {
  const groups = { today: [], yesterday: [], earlier: [] }
  const now = new Date()
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime()
  const yesterday = today - 86400000
  for (const s of filteredSessionOptions.value) {
    const t = s.created_at ? new Date(s.created_at.replace(' ', 'T')).getTime() : NaN
    if (isNaN(t)) groups.earlier.push(s)
    else if (t >= today) groups.today.push(s)
    else if (t >= yesterday) groups.yesterday.push(s)
    else groups.earlier.push(s)
  }
  return groups
})

const currentSid = computed(() => chat.currentSession(kb.currentId)?.id || undefined)

function formatTime(s) {
  if (!s) return ''
  const d = new Date(s.replace(' ', 'T'))
  const now = new Date()
  const diff = now - d
  const days = Math.floor(diff / 86400000)
  if (days > 7) return d.toLocaleDateString('zh-CN')
  if (days > 0) return `${days} 天前`
  const hours = Math.floor(diff / 3600000)
  if (hours > 0) return `${hours} 小时前`
  return '刚刚'
}

async function onSessionChange(sid) {
  try {
    await chat.switchSession(kb.currentId, sid)
    router.push('/chat')
  } catch (e) {
    // 错误处理
  }
}

async function createSession() {
  try {
    await chat.newSession(kb.currentId)
    router.push('/chat')
  } catch (e) {
    // 错误处理
  }
}

// ---------- 对话详情弹窗 ----------
const detailOpen = ref(false)
const detailSession = ref(null)
const editing = ref(false)
const editName = ref('')
const saving = ref(false)

function openDetail(s) {
  detailSession.value = s
  editName.value = s.name
  editing.value = false
  detailOpen.value = true
}

function startEdit() {
  editing.value = true
}

async function saveName() {
  if (!detailSession.value || !editName.value.trim()) return
  saving.value = true
  try {
    await chat.renameSession(kb.currentId, detailSession.value.id, editName.value.trim())
    detailSession.value.name = editName.value.trim()
    editing.value = false
  } catch (e) {
    // 错误处理
  } finally {
    saving.value = false
  }
}

async function deleteSession() {
  if (!detailSession.value) return
  try {
    await chat.removeSession(kb.currentId, detailSession.value.id)
    detailOpen.value = false
    detailSession.value = null
  } catch (e) {
    // 错误处理
  }
}

async function exportSession() {
  if (!detailSession.value) return
  try {
    const messages = await api.historyList(kb.currentId, detailSession.value.id)
    const blob = new Blob([JSON.stringify(messages, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${detailSession.value.name}.json`
    a.click()
    URL.revokeObjectURL(url)
  } catch (e) {
    // 错误处理
  }
}

</script>

<template>
  <aside class="sider">
    <div class="brand">
      <div class="logo"><ReadOutlined /></div>
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

    <!-- ---------- 对话列表（按时间分组） ---------- -->
    <div v-if="kb.currentId" class="session-list">
      <div class="sl-header">
        <span class="sl-title">对话列表</span>
        <a-button type="text" size="small" @click="createSession()">
          <template #icon><PlusOutlined /></template>
        </a-button>
        <a-button type="text" size="small" @click="batchMode = true">
          <template #icon><CheckOutlined /></template>
        </a-button>
      </div>
      <div class="sl-search">
        <a-input
          v-model:value="searchQuery"
          size="small"
          placeholder="搜索对话..."
          allow-clear
        />
      </div>
      <div class="sl-items">
        <template v-if="groupedSessions.today.length">
          <div class="sl-group-title">今天</div>
          <div
            v-for="s in groupedSessions.today"
            :key="s.value"
            class="sl-item"
            :class="{ active: s.value === currentSid, selected: selectedIds.includes(s.value) }"
            @click="onSessionChange(s.value)"
            @dblclick="startRename(s)"
          >
            <a-checkbox
              v-if="batchMode"
              :checked="selectedIds.includes(s.value)"
              @change="toggleSelect(s.value)"
            />
            <div class="sl-name">
              <a-input
                v-if="renamingId === s.value"
                v-model:value="renameValue"
                size="small"
                :bordered="false"
                :autofocus="true"
                @blur="finishRename"
                @press-enter="finishRename"
                @press-esc="cancelRename"
              />
              <span v-else>{{ s.label }}</span>
            </div>
            <div class="sl-actions">
              <a-button
                type="text"
                size="small"
                @click.stop="chat.togglePinSession(kb.currentId, s.value)"
              >
                <template #icon>
                  <StarFilled v-if="s.pinned" />
                  <StarOutlined v-else />
                </template>
              </a-button>
            </div>
            <div class="sl-meta">
              <span>{{ s.msg_count }} 条</span>
              <span v-if="s.created_at">{{ formatTime(s.created_at) }}</span>
            </div>
          </div>
        </template>
        <template v-if="groupedSessions.yesterday.length">
          <div class="sl-group-title">昨天</div>
          <div
            v-for="s in groupedSessions.yesterday"
            :key="s.value"
            class="sl-item"
            :class="{ active: s.value === currentSid }"
            @click="onSessionChange(s.value)"
            @dblclick="startRename(s)"
          >
            <div class="sl-name">
              <a-input
                v-if="renamingId === s.value"
                v-model:value="renameValue"
                size="small"
                :bordered="false"
                :autofocus="true"
                @blur="finishRename"
                @press-enter="finishRename"
                @press-esc="cancelRename"
              />
              <span v-else>{{ s.label }}</span>
            </div>
            <div class="sl-actions">
              <a-button
                type="text"
                size="small"
                @click.stop="chat.togglePinSession(kb.currentId, s.value)"
              >
                <template #icon>
                  <StarFilled v-if="s.pinned" />
                  <StarOutlined v-else />
                </template>
              </a-button>
            </div>
            <div class="sl-meta">
              <span>{{ s.msg_count }} 条</span>
              <span v-if="s.created_at">{{ formatTime(s.created_at) }}</span>
            </div>
          </div>
        </template>
        <template v-if="groupedSessions.earlier.length">
          <div class="sl-group-title">更早</div>
          <div
            v-for="s in groupedSessions.earlier"
            :key="s.value"
            class="sl-item"
            :class="{ active: s.value === currentSid }"
            @click="onSessionChange(s.value)"
          >
            <div class="sl-name">{{ s.label }}</div>
            <div class="sl-actions">
              <a-button
                type="text"
                size="small"
                @click.stop="chat.togglePinSession(kb.currentId, s.value)"
              >
                <template #icon>
                  <StarFilled v-if="s.pinned" />
                  <StarOutlined v-else />
                </template>
              </a-button>
            </div>
            <div class="sl-meta">
              <span>{{ s.msg_count }} 条</span>
              <span v-if="s.created_at">{{ formatTime(s.created_at) }}</span>
            </div>
          </div>
        </template>
        <div v-if="!sessionOptions.length" class="sl-empty muted">
          暂无对话
        </div>
      </div>
    </div>

    <!-- ---------- 批量操作底部栏 ---------- -->
    <div v-if="batchMode" class="batch-bar">
      <a-button size="small" @click="toggleSelectAll">
        {{ allSelected ? '取消全选' : '全选' }}
      </a-button>
      <a-button size="small" danger :disabled="selectedIds.length === 0" @click="batchDelete">
        删除 ({{ selectedIds.length }})
      </a-button>
      <a-button size="small" @click="batchMode = false">取消</a-button>
    </div>

    <!-- ---------- 对话详情弹窗 ---------- -->
    <a-modal
      v-model:open="detailOpen"
      :title="detailSession?.name || '对话详情'"
      :footer="null"
      width="400px"
    >
      <div class="detail-body">
        <div class="detail-row">
          <span class="detail-label">消息数量</span>
          <span class="detail-value">{{ detailSession?.msg_count || 0 }} 条</span>
        </div>
        <div class="detail-row">
          <span class="detail-label">创建时间</span>
          <span class="detail-value">{{ detailSession?.created_at || '-' }}</span>
        </div>
        <div class="detail-row">
          <span class="detail-label">会话 ID</span>
          <span class="detail-value">{{ detailSession?.id || '-' }}</span>
        </div>
        <div class="detail-actions">
          <a-button v-if="!editing" @click="startEdit">重命名</a-button>
          <a-button v-else type="primary" :loading="saving" @click="saveName">保存</a-button>
          <a-button v-if="editing" @click="editing = false">取消</a-button>
          <a-button @click="exportSession">导出</a-button>
          <a-button danger @click="deleteSession">删除</a-button>
        </div>
      </div>
    </a-modal>


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
  flex-shrink: 0;
  border-radius: 10px;
  background: linear-gradient(135deg, var(--accent), #fbbf24);
  color: #ffffff;
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.5px;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 2px 8px rgba(249, 115, 22, 0.25);
}

/* ---------- 搜索框 ---------- */
.sl-search {
  padding: 8px 12px;
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
  padding: 4px 10px;
  flex-shrink: 0;
}
.nav-item {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 9px 10px;
  margin-bottom: 2px;
  border: none;
  border-radius: 10px;
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

/* ---------- 对话列表 ---------- */
.session-list {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  border-top: 1px solid var(--border);
  margin-top: 8px;
}
.sl-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 14px 8px;
}
.sl-title {
  font-size: 11px;
  font-weight: 600;
  color: var(--text-3);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}
.sl-items {
  flex: 1;
  overflow-y: auto;
  padding: 0 8px 8px;
  display: block;
}
.sl-group-title {
  font-size: 11px;
  font-weight: 600;
  color: var(--text-3);
  padding: 8px 10px 4px;
  text-transform: uppercase;
  letter-spacing: 0.3px;
}
.sl-item {
  display: block;
  width: 100%;
  padding: 8px 10px;
  margin-bottom: 2px;
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.15s;
  border: 1px solid transparent;
  box-sizing: border-box;
}
.sl-item:hover {
  background: var(--bg-hover);
}
.sl-item.active {
  background: var(--accent-soft);
  border-color: var(--accent);
}
.sl-name {
  font-size: 12.5px;
  font-weight: 500;
  color: var(--text-1);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  margin-bottom: 2px;
}
.sl-item.active .sl-name {
  color: var(--accent);
}
.sl-meta {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 10.5px;
  color: var(--text-3);
}
.sl-meta span {
  white-space: nowrap;
}
.sl-empty {
  padding: 16px 8px;
  text-align: center;
  font-size: 11.5px;
  color: var(--text-3);
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
  border-radius: 8px;
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

/* ---------- 对话详情弹窗 ---------- */
.detail-body {
  padding: 8px 0;
}
.detail-row {
  display: flex;
  justify-content: space-between;
  padding: 8px 0;
  border-bottom: 1px solid var(--border);
}
.detail-row:last-of-type {
  border-bottom: none;
}
.detail-label {
  color: var(--text-3);
  font-size: 13px;
}
.detail-value {
  color: var(--text-1);
  font-size: 13px;
  font-weight: 500;
}
.detail-actions {
  display: flex;
  gap: 8px;
  margin-top: 16px;
  flex-wrap: wrap;
}

/* ---------- 批量操作底部栏 ---------- */
.batch-bar {
  position: sticky;
  bottom: 0;
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 10px;
  background: var(--bg-panel);
  border-top: 1px solid var(--border);
  box-shadow: 0 -2px 8px rgba(0, 0, 0, 0.06);
  z-index: 10;
}
.batch-bar .ant-btn {
  flex: 1;
  height: 28px;
  font-size: 12px;
  border-radius: 6px;
}

/* ---------- 批量模式复选框 ---------- */
.sl-item :deep(.ant-checkbox-wrapper) {
  margin-right: 6px;
}
.sl-item :deep(.ant-checkbox-inner) {
  width: 14px;
  height: 14px;
}
.sl-item.selected {
  background: var(--accent-soft);
}
</style>
