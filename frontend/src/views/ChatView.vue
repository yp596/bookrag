<script setup>
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { Modal, message as antMessage } from 'ant-design-vue'
import {
  SendOutlined,
  StopOutlined,
  ClearOutlined,
  DeleteOutlined,
  DatabaseOutlined,
  MessageOutlined,
  EditOutlined,
  PlusOutlined,
  ThunderboltOutlined,
  SearchOutlined,
  DownloadOutlined,
  ReloadOutlined,
  CloseOutlined,
  UpOutlined,
  DownOutlined,
} from '@ant-design/icons-vue'
import MessageBubble from '../components/MessageBubble.vue'
import { useKbStore } from '../stores/kb'
import { useChatStore } from '../stores/chat'

const kb = useKbStore()
const chat = useChatStore()
const router = useRouter()

const input = ref('')
const scroller = ref(null)

const messages = computed(() => chat.messages(kb.currentId))
const currentKb = computed(() => kb.current())
const canSend = computed(() => !!kb.currentId && !!input.value.trim() && !chat.streaming && !chat.sending)

/** 会话列表：含名称、消息数、创建时间 */
const sessionOptions = computed(() =>
  chat.sessionsOf(kb.currentId).map((s) => ({
    value: s.id,
    label: s.msg_count ? `${s.name} · ${s.msg_count}` : s.name,
    msg_count: s.msg_count || 0,
    created_at: s.created_at || '',
  })),
)

/** 分组：今天、昨天、更早 */
const groupedSessions = computed(() => {
  const groups = { today: [], yesterday: [], earlier: [] }
  const now = new Date()
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime()
  const yesterday = today - 86400000
  for (const s of sessionOptions.value) {
    const t = new Date(s.created_at.replace(' ', 'T')).getTime()
    if (t >= today) groups.today.push(s)
    else if (t >= yesterday) groups.yesterday.push(s)
    else groups.earlier.push(s)
  }
  return groups
})
const currentSid = computed(() => chat.currentSession(kb.currentId)?.id || undefined)
const renameOpen = ref(false)
const renameText = ref('')

const SUGGESTIONS = [
  '这份资料主要讲了什么？',
  '有哪些关键条款需要注意？',
  '总结一下核心要点',
]

// ---------- P3: 消息搜索 ----------
const searchOpen = ref(false)
const searchQuery = ref('')
const searchIndex = ref(0)

const searchResults = computed(() => {
  if (!searchQuery.value.trim()) return []
  const q = searchQuery.value.trim().toLowerCase()
  const results = []
  for (const m of messages.value) {
    const text = m.text.toLowerCase()
    let pos = 0
    while (true) {
      const idx = text.indexOf(q, pos)
      if (idx === -1) break
      results.push({ msgId: m.id, start: idx, end: idx + q.length })
      pos = idx + q.length
    }
  }
  return results
})

function goToMessage(msgId) {
  const el = document.querySelector(`[data-msg-id="${msgId}"]`)
  if (el) {
    el.scrollIntoView({ behavior: 'smooth', block: 'center' })
    el.style.backgroundColor = 'rgba(255, 230, 100, 0.3)'
    setTimeout(() => { el.style.backgroundColor = '' }, 1500)
  }
}

// ---------- P3: 导出对话 ----------
function exportConversation() {
  if (!messages.value.length) return
  const lines = [`# ${currentKb?.name || '对话'} — ${currentSid.value || '未命名'}`]
  for (const m of messages.value) {
    lines.push('')
    lines.push(`**${m.role === 'user' ? '我' : 'AI'}**`)
    lines.push('')
    lines.push(m.text)
    if (m.sources?.length) {
      lines.push('')
      lines.push('---')
      lines.push('引用来源：')
      for (const s of m.sources) {
        lines.push(`- ${s.title || s.source}（${s.source}）`)
      }
    }
  }
  const blob = new Blob([lines.join('\n')], { type: 'text/markdown;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `对话_${new Date().toISOString().slice(0, 19).replace(/:/g, '-')}.md`
  a.click()
  URL.revokeObjectURL(url)
  antMessage.success('已导出对话')
}

// ---------- P3: 消息重新生成 ----------
async function regenerateLast() {
  const lastAssistant = [...messages.value].reverse().find((m) => m.role === 'assistant')
  if (!lastAssistant) return
  const lastUser = [...messages.value].reverse().find((m) => m.role === 'user' && m.id < lastAssistant.id)
  if (!lastUser) return
  const msgList = messages.value
  const idx = msgList.findIndex((m) => m.id === lastAssistant.id)
  if (idx !== -1) msgList.splice(idx, 1)
  await chat.ask(kb.currentId, lastUser.text)
}

// ---------- 消息编辑 ----------
async function handleEdit({ id, text }) {
  const msgList = messages.value
  const idx = msgList.findIndex((m) => m.id === id)
  if (idx === -1) return
  msgList.splice(idx)
  await chat.ask(kb.currentId, text)
}

// 消息追加或流式增量到达时保持贴底
watch(
  () => [messages.value.length, messages.value.at(-1)?.text?.length],
  async () => {
    await nextTick()
    const el = scroller.value
    if (el) el.scrollTop = el.scrollHeight
  },
)

async function send() {
  if (!canSend.value) return
  const question = input.value.trim()
  input.value = ''
  await chat.ask(kb.currentId, question)
}

/** Enter 发送，Shift+Enter 换行 */
function onKeydown(e) {
  if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
    e.preventDefault()
    send()
  }
}

function onKbChange(id) {
  kb.select(id)
  chat.load(id)
}

async function clearConversation() {
  try {
    await chat.clear(kb.currentId)
    antMessage.success('已清空当前会话')
  } catch (e) {
    antMessage.error(`清空失败：${e.message}`)
  }
}

async function onSessionChange(sid) {
  try {
    await chat.switchSession(kb.currentId, sid)
  } catch (e) {
    antMessage.error(`切换会话失败：${e.message}`)
  }
}

async function createSession() {
  try {
    await chat.newSession(kb.currentId)
  } catch (e) {
    antMessage.error(`新建会话失败：${e.message}`)
  }
}

// ---------- 多轮检索 ----------
const multiTurnLoading = ref(false)

async function multiTurnChat() {
  if (!kb.currentId || !input.value.trim() || chat.streaming || chat.sending) return
  multiTurnLoading.value = true
  const question = input.value.trim()
  input.value = ''
  try {
    // 添加用户消息
    await chat.pushUserMessage(kb.currentId, question)
    // 调用多轮检索 API
    const res = await api.chatMultiTurn({
      kb_id: kb.currentId,
      question,
      session_id: currentSid.value,
    })
    // 添加助手消息
    await chat.pushAssistantMessage(kb.currentId, res.answer, res.sources)
    antMessage.success('多轮检索完成')
  } catch (e) {
    antMessage.error(`多轮检索失败：${e.message}`)
  } finally {
    multiTurnLoading.value = false
  }
}

// ---------- 人工审批 ----------
const approvalPending = ref(false)

function approveGeneration() {
  approvalPending.value = false
  // 继续生成答案
  antMessage.success('已确认，继续生成')
}

function rejectGeneration() {
  approvalPending.value = false
  antMessage.warning('已拒绝生成')
}

function openRename() {
  renameText.value = chat.currentSession(kb.currentId)?.name || ''
  renameOpen.value = true
}

async function commitRename() {
  const sid = chat.currentSession(kb.currentId)?.id
  if (!sid) {
    renameOpen.value = false
    return
  }
  try {
    await chat.renameSession(kb.currentId, sid, renameText.value)
    renameOpen.value = false
  } catch (e) {
    antMessage.error(`重命名失败：${e.message}`)
  }
}

function confirmDeleteSession() {
  const sess = chat.currentSession(kb.currentId)
  if (!sess) return
  Modal.confirm({
    title: '删除当前会话？',
    content: `将删除「${sess.name}」及其全部 ${sess.msg_count} 条消息，可通过清空保留空会话。`,
    okText: '删除',
    okType: 'danger',
    cancelText: '取消',
    async onOk() {
      try {
        await chat.removeSession(kb.currentId, sess.id)
        antMessage.success('已删除会话')
      } catch (e) {
        antMessage.error(`删除失败：${e.message}`)
      }
    },
  })
}

// ---------- P3: 快捷键 ----------
function onGlobalKeydown(e) {
  if (e.ctrlKey && e.key === 'k') {
    e.preventDefault()
    searchOpen.value = !searchOpen.value
  } else if (e.ctrlKey && e.key === 'e') {
    e.preventDefault()
    exportConversation()
  } else if (e.ctrlKey && e.key === 'r') {
    e.preventDefault()
    regenerateLast()
  }
}

// 刷新/重启后恢复当前库的历史展示；失败静默，本轮仍可正常提问
onMounted(() => {
  if (kb.currentId) chat.load(kb.currentId)
  window.addEventListener('keydown', onGlobalKeydown)
})

onUnmounted(() => {
  window.removeEventListener('keydown', onGlobalKeydown)
})

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

// ---------- 检索调试 ----------
const debugOpen = ref(false)
const debugData = ref(null)
const debugLoading = ref(false)

async function openDebug() {
  if (!kb.currentId || !input.value.trim()) {
    antMessage.warning('请先输入问题')
    return
  }
  debugOpen.value = true
  debugLoading.value = true
  debugData.value = null
  try {
    const res = await api.chatDebug({
      kb_id: kb.currentId,
      question: input.value.trim(),
    })
    debugData.value = res
  } catch (e) {
    antMessage.error(`调试失败：${e.message}`)
  } finally {
    debugLoading.value = false
  }
}

// ---------- 主动推荐 ----------
const recommendations = ref([])
const recommendOpen = ref(false)
const recommendLoading = ref(false)

async function loadRecommendations() {
  if (!kb.currentId) return
  recommendOpen.value = true
  recommendLoading.value = true
  recommendations.value = []
  try {
    const res = await api.chatRecommend({
      kb_id: kb.currentId,
      question: messages.value[messages.value.length - 1]?.text || '',
      session_id: currentSid.value,
    })
    recommendations.value = res.questions || []
  } catch (e) {
    antMessage.error(`获取推荐失败：${e.message}`)
  } finally {
    recommendLoading.value = false
  }
}
</script>

<template>
  <div class="chat">
    <!-- ---------- 主内容区 ---------- -->
    <div class="chat-main">
      <!-- ---------- 顶部 ---------- -->
      <header class="bar">
        <a-select
          :value="kb.currentId || undefined"
          class="kb-select"
          placeholder="选择知识库"
          size="middle"
          :options="kb.list.map((k) => ({ value: k.id, label: k.name }))"
          @change="onKbChange"
        />
        <span v-if="currentKb" class="meta muted">
          {{ currentKb.doc_count }} 个文档 · {{ currentKb.chunk_count }} 个片段
        </span>

        <div class="bar-right">
          <a-tooltip title="新建知识库">
            <a-button type="text" @click="router.push('/knowledge')">
              <template #icon><PlusOutlined /></template>
            </a-button>
          </a-tooltip>
          <template v-if="currentKb">
            <a-tooltip title="新建会话">
              <a-button type="text" :disabled="chat.streaming" @click="createSession">
                <template #icon><MessageOutlined /></template>
              </a-button>
            </a-tooltip>
            <a-tooltip title="重命名当前会话">
              <a-button type="text" :disabled="chat.streaming || !currentSid" @click="openRename">
                <template #icon><EditOutlined /></template>
              </a-button>
            </a-tooltip>
            <a-tooltip title="删除当前会话（含全部消息）">
              <a-button type="text" danger :disabled="chat.streaming || !currentSid" @click="confirmDeleteSession">
                <template #icon><DeleteOutlined /></template>
              </a-button>
            </a-tooltip>
          </template>
          <a-tooltip title="清空当前会话消息">
            <a-button type="text" :disabled="!messages.length || chat.streaming" @click="clearConversation">
              <template #icon><ClearOutlined /></template>
            </a-button>
          </a-tooltip>
          <a-tooltip title="搜索消息 (Ctrl+K)">
            <a-button type="text" @click="searchOpen = !searchOpen">
              <template #icon><SearchOutlined /></template>
            </a-button>
          </a-tooltip>
          <a-tooltip title="导出对话 (Ctrl+E)">
            <a-button type="text" :disabled="!messages.length" @click="exportConversation">
              <template #icon><DownloadOutlined /></template>
            </a-button>
          </a-tooltip>
          <a-tooltip title="检索调试">
            <a-button type="text" :disabled="chat.streaming || chat.sending" @click="openDebug">
              <template #icon><SearchOutlined /></template>
            </a-button>
          </a-tooltip>
          <a-tooltip title="推荐问题">
            <a-button type="text" :disabled="chat.streaming || chat.sending || !messages.length" @click="loadRecommendations">
              <template #icon><MessageOutlined /></template>
            </a-button>
          </a-tooltip>
        </div>
      </header>

      <!-- ---------- 消息搜索 ---------- -->
      <div v-if="searchOpen" class="search-bar">
        <a-input
          v-model:value="searchQuery"
          size="small"
          placeholder="搜索消息..."
          allow-clear
          @press-enter="nextSearchResult"
        />
        <span class="search-count">
          {{ searchResults.length ? `${currentSearchIndex + 1}/${searchResults.length}` : '0/0' }}
        </span>
        <a-button size="small" @click="prevSearchResult">
          <template #icon><UpOutlined /></template>
        </a-button>
        <a-button size="small" @click="nextSearchResult">
          <template #icon><DownOutlined /></template>
        </a-button>
        <a-button size="small" @click="closeSearch">
          <template #icon><CloseOutlined /></template>
        </a-button>
      </div>

      <!-- ---------- 多轮检索状态 ---------- -->
      <div v-if="multiTurnLoading" class="multi-turn-status">
        <a-spin size="small" />
        <span class="muted">多轮检索中...</span>
      </div>

      <!-- ---------- 人工审批 ---------- -->
      <div v-if="approvalPending" class="approval-panel">
        <div class="approval-title">人工审批</div>
        <p class="muted">请确认是否继续生成答案</p>
        <div class="approval-actions">
          <a-button type="primary" @click="approveGeneration">确认</a-button>
          <a-button @click="rejectGeneration">拒绝</a-button>
        </div>
      </div>

      <!-- ---------- P3: 消息搜索面板 ---------- -->
      <div v-if="searchOpen" class="search-panel">
        <div class="search-box">
          <SearchOutlined class="search-icon" />
          <input
            v-model="searchQuery"
            class="search-input"
            placeholder="搜索消息内容…"
            @keydown.esc="searchOpen = false"
          />
          <span class="search-count muted">{{ searchResults.length }} 条结果</span>
          <a-button size="small" type="text" @click="searchOpen = false">
            <template #icon><CloseOutlined /></template>
          </a-button>
        </div>
        <div class="search-results">
          <div
            v-for="(r, i) in searchResults.slice(0, 20)"
            :key="i"
            class="search-item"
            :class="{ active: i === searchIndex }"
            @click="goToMessage(r.msgId)"
          >
            <span class="search-msg-role">{{ messages.find(m => m.id === r.msgId)?.role === 'user' ? '我' : 'AI' }}</span>
            <span class="search-msg-text">{{ messages.find(m => m.id === r.msgId)?.text?.slice(0, 100) }}…</span>
          </div>
        </div>
      </div>

      <!-- ---------- 消息区 ---------- -->
      <div ref="scroller" class="scroll">
        <!-- 无知识库：引导式空状态 -->
        <div v-if="!kb.list.length" class="empty">
          <div class="empty-icon"><DatabaseOutlined /></div>
          <h3>还没有知识库</h3>
          <p class="muted">
            导入 PDF、Word、Markdown 或纯文本，建立本地索引后即可提问。
            <br />所有文档与索引都保存在本机，不会上传。
          </p>
          <a-button type="primary" size="large" @click="router.push('/knowledge')">
            <template #icon><PlusOutlined /></template>
            创建第一个知识库
          </a-button>
        </div>

        <!-- 有知识库但无对话：示例提问 -->
        <div v-else-if="!messages.length" class="empty">
          <div class="empty-icon"><ThunderboltOutlined /></div>
          <h3>{{ currentKb?.name || '知识库' }}</h3>
          <p class="muted">
            <template v-if="currentKb?.chunk_count">
              已就绪，共 {{ currentKb.chunk_count }} 个片段。试试这样问：
            </template>
            <template v-else>这个知识库还没有文档，先导入资料再提问。</template>
          </p>
          <div class="chips">
            <button
              v-for="s in SUGGESTIONS"
              :key="s"
              class="chip"
              :disabled="!currentKb?.chunk_count"
              @click="((input = s), send())"
            >
              {{ s }}
            </button>
          </div>
        </div>

        <!-- 对话正文 -->
        <div v-else class="thread">
          <MessageBubble v-for="m in messages" :key="m.id" :message="m" @edit="handleEdit" @regenerate="regenerateLast" />
        </div>
      </div>

      <!-- ---------- 输入区 ---------- -->
      <footer class="composer">
        <div class="box">
          <textarea
            v-model="input"
            class="ta"
            rows="1"
            placeholder="基于当前知识库提问，Enter 发送，Shift + Enter 换行"
            :disabled="!kb.list.length"
            @keydown="onKeydown"
          />
          <div class="box-foot">
            <span class="hint muted">
              <template v-if="!kb.list.length">请先创建并导入知识库</template>
              <template v-else-if="!currentKb?.chunk_count">当前知识库还没有文档</template>
              <template v-else>回答仅依据检索到的资料片段</template>
            </span>
            <a-button v-if="chat.streaming" danger @click="chat.stop()">
              <template #icon><StopOutlined /></template>
              停止
            </a-button>
            <a-button v-else type="primary" :disabled="!canSend" @click="send">
              <template #icon><SendOutlined /></template>
              发送
            </a-button>
          </div>
        </div>
      </footer>
    </div>

    <!-- ---------- 重命名会话 ---------- -->
    <a-modal
      v-model:open="renameOpen"
      title="重命名会话"
      ok-text="确定"
      cancel-text="取消"
      @ok="commitRename"
    >
      <a-input
        v-model:value="renameText"
        maxlength="32"
        show-count
        placeholder="输入会话名称"
        @pressEnter="commitRename"
      />
    </a-modal>

    <!-- ---------- 检索调试弹窗 ---------- -->
    <a-modal
      v-model:open="debugOpen"
      title="检索调试"
      :footer="null"
      width="800px"
    >
      <div v-if="debugLoading" class="debug-loading">
        <a-spin />
      </div>
      <div v-else-if="debugData" class="debug-body">
        <div class="debug-section">
          <div class="debug-label">查询</div>
          <div class="debug-value">{{ debugData.query }}</div>
        </div>
        <div class="debug-section">
          <div class="debug-label">改写后查询</div>
          <div class="debug-value">{{ debugData.rewritten_query }}</div>
        </div>
        <div class="debug-section">
          <div class="debug-label">命中片段 ({{ debugData.total_hits }})</div>
          <div v-for="hit in debugData.hits" :key="hit.title" class="debug-hit">
            <div class="debug-hit-title">{{ hit.title }}</div>
            <div class="debug-hit-meta">得分: {{ hit.score }} · 覆盖率: {{ hit.coverage }}</div>
            <div class="debug-hit-text">{{ hit.text }}</div>
          </div>
        </div>
      </div>
    </a-modal>

    <!-- ---------- 主动推荐弹窗 ---------- -->
    <a-modal
      v-model:open="recommendOpen"
      title="推荐问题"
      :footer="null"
      width="500px"
    >
      <div v-if="recommendLoading" class="recommend-loading">
        <a-spin />
      </div>
      <div v-else class="recommend-body">
        <div v-if="!recommendations.length" class="recommend-empty muted">
          暂无推荐问题
        </div>
        <div
          v-for="q in recommendations"
          :key="q"
          class="recommend-item"
          @click="input = q; recommendOpen = false"
        >
          {{ q }}
        </div>
      </div>
    </a-modal>
  </div>
</template>

<style scoped>
.chat {
  display: flex;
  height: 100%;
  overflow: hidden;
}

/* ---------- 对话列表侧边栏（Codex 风格） ---------- */
.session-list {
  width: 240px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  border-right: 1px solid var(--border);
  background: var(--bg-sider);
}
.sl-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 16px;
  border-bottom: 1px solid var(--border);
}
.sl-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-3);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}
.sl-items {
  flex: 1;
  overflow-y: auto;
  padding: 6px;
  display: block;
}
.sl-item {
  display: block;
  width: 100%;
  padding: 10px 12px;
  margin-bottom: 2px;
  border-radius: 10px;
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
  font-size: 13px;
  font-weight: 500;
  color: var(--text-1);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  margin-bottom: 4px;
}
.sl-item.active .sl-name {
  color: var(--accent);
}
.sl-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 11px;
  color: var(--text-3);
}
.sl-meta span {
  white-space: nowrap;
}
.sl-empty {
  padding: 24px 12px;
  text-align: center;
  font-size: 12px;
  color: var(--text-3);
}

/* ---------- 主内容区 ---------- */
.chat-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

/* ---------- 顶部栏 ---------- */
.bar {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 20px;
  border-bottom: 1px solid var(--border);
  background: var(--bg-panel);
}
.kb-select {
  width: 220px;
}
.meta {
  font-size: 12px;
}
.bar-right {
  margin-left: auto;
  display: flex;
  gap: 2px;
}

/* ---------- 消息滚动区 ---------- */
.scroll {
  flex: 1;
  overflow-y: auto;
  padding: 24px 20px 8px;
}
.thread {
  max-width: 1000px;
  margin: 0 auto;
}

/* 虚拟滚动：浏览器原生 content-visibility，视口外消息跳过渲染 */
.thread > * {
  content-visibility: auto;
  contain-intrinsic-size: auto 200px;
}

/* ---------- P3: 搜索面板 ---------- */
.search-panel {
  max-width: 1000px;
  margin: 0 auto 12px;
  border: 1px solid var(--border);
  border-radius: 12px;
  background: var(--bg-panel);
  box-shadow: var(--shadow-sm);
  overflow: hidden;
}
.search-box {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 14px;
  border-bottom: 1px solid var(--border);
}
.search-icon {
  color: var(--text-3);
  font-size: 15px;
}
.search-input {
  flex: 1;
  border: none;
  outline: none;
  background: transparent;
  color: var(--text-1);
  font-size: 14px;
}
.search-count {
  font-size: 12px;
  white-space: nowrap;
}
.search-results {
  max-height: 240px;
  overflow-y: auto;
}
.search-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 14px;
  cursor: pointer;
  transition: background 0.15s;
}
.search-item:hover,
.search-item.active {
  background: var(--accent-soft);
}
.search-msg-role {
  flex-shrink: 0;
  font-size: 12px;
  font-weight: 600;
  color: var(--accent);
}
.search-msg-text {
  font-size: 13px;
  color: var(--text-2);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* ---------- 空状态 ---------- */
.empty {
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  padding: 0 24px 60px;
}
.empty-icon {
  width: 54px;
  height: 54px;
  margin-bottom: 16px;
  border-radius: 16px;
  background: var(--accent-soft);
  color: var(--accent);
  font-size: 24px;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 2px 12px rgba(249, 115, 22, 0.15);
}
.empty h3 {
  margin: 0 0 8px;
  font-size: 17px;
  font-weight: 600;
}
.empty p {
  margin: 0 0 22px;
  font-size: 13.5px;
  line-height: 1.8;
  max-width: 460px;
}
.chips {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  justify-content: center;
}
.chip {
  padding: 7px 14px;
  border: 1px solid var(--border);
  border-radius: 20px;
  background: var(--bg-panel);
  color: var(--text-2);
  font-family: inherit;
  font-size: 13px;
  cursor: pointer;
  transition: all 0.15s;
}
.chip:hover:not(:disabled) {
  border-color: var(--accent);
  color: var(--accent);
  background: var(--accent-soft);
  box-shadow: 0 2px 8px rgba(249, 115, 22, 0.15);
}
.chip:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

/* ---------- 输入区 ---------- */
.composer {
  padding: 10px 20px 18px;
}
.box {
  max-width: 1000px;
  margin: 0 auto;
  border: 1px solid var(--border-strong);
  border-radius: 14px;
  background: var(--bg-panel);
  box-shadow: var(--shadow-sm);
  transition: border-color 0.15s, box-shadow 0.15s;
}
.box:focus-within {
  border-color: var(--accent);
  box-shadow: 0 0 0 3px var(--accent-soft), 0 2px 16px rgba(249, 115, 22, 0.12);
}
.ta {
  display: block;
  width: 100%;
  min-height: 52px;
  max-height: 180px;
  padding: 13px 15px 4px;
  border: none;
  outline: none;
  resize: vertical;
  background: transparent;
  color: var(--text-1);
  font-family: inherit;
  font-size: 14px;
  line-height: 1.6;
}
.ta::placeholder {
  color: var(--text-3);
}
.box-foot {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 6px 10px 9px 15px;
}
.hint {
  flex: 1;
  font-size: 11.5px;
}

/* ---------- 多轮检索状态 ---------- */
.multi-turn-status {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 20px;
  background: var(--accent-soft);
  border-bottom: 1px solid var(--border);
  font-size: 13px;
}

/* ---------- 人工审批 ---------- */
.approval-panel {
  position: fixed;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  z-index: 1000;
  background: var(--bg-panel);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 24px;
  box-shadow: var(--shadow-md);
  min-width: 320px;
  text-align: center;
}
.approval-title {
  font-size: 16px;
  font-weight: 600;
  margin-bottom: 8px;
}
.approval-actions {
  display: flex;
  gap: 12px;
  justify-content: center;
  margin-top: 16px;
}
</style>
