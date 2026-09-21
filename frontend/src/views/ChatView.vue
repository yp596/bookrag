<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { message as antMessage } from 'ant-design-vue'
import {
  SendOutlined,
  StopOutlined,
  DeleteOutlined,
  DatabaseOutlined,
  PlusOutlined,
  ThunderboltOutlined,
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
const canSend = computed(() => !!kb.currentId && !!input.value.trim() && !chat.streaming)

const SUGGESTIONS = [
  '这份资料主要讲了什么？',
  '有哪些关键条款需要注意？',
  '总结一下核心要点',
]

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
}

function clearConversation() {
  chat.clear(kb.currentId)
  antMessage.success('已清空当前对话')
}
</script>

<template>
  <div class="chat">
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
        <a-tooltip title="清空当前对话">
          <a-button type="text" :disabled="!messages.length" @click="clearConversation">
            <template #icon><DeleteOutlined /></template>
          </a-button>
        </a-tooltip>
      </div>
    </header>

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
        <MessageBubble v-for="m in messages" :key="m.id" :message="m" />
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
</template>

<style scoped>
.chat {
  display: flex;
  flex-direction: column;
  height: 100%;
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
  width: 240px;
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
  border-radius: 15px;
  background: var(--accent-soft);
  color: var(--accent);
  font-size: 24px;
  display: flex;
  align-items: center;
  justify-content: center;
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
  border-radius: 18px;
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
  border-radius: 12px;
  background: var(--bg-panel);
  box-shadow: var(--shadow-sm);
  transition: border-color 0.15s, box-shadow 0.15s;
}
.box:focus-within {
  border-color: var(--accent);
  box-shadow: 0 0 0 3px var(--accent-soft);
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
</style>
