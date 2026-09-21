<script setup>
import { computed, ref } from 'vue'
import { message as antMessage } from 'ant-design-vue'
import { CopyOutlined, CheckOutlined, WarningOutlined } from '@ant-design/icons-vue'
import SourceCard from './SourceCard.vue'
import { renderMarkdown } from '../utils/markdown'

const props = defineProps({
  message: { type: Object, required: true },
})

const isUser = computed(() => props.message.role === 'user')
const html = computed(() => (isUser.value ? '' : renderMarkdown(props.message.text)))
const copied = ref(false)

async function copy() {
  try {
    await navigator.clipboard.writeText(props.message.text)
    copied.value = true
    setTimeout(() => (copied.value = false), 1500)
  } catch {
    antMessage.error('复制失败')
  }
}
</script>

<template>
  <div class="row" :class="isUser ? 'right' : 'left'">
    <div v-if="!isUser" class="avatar ai">AI</div>

    <div class="stack">
      <div class="bubble" :class="isUser ? 'user' : 'ai'">
        <!-- 用户消息原样显示；助手消息渲染 Markdown -->
        <template v-if="isUser">{{ message.text }}</template>
        <template v-else>
          <div v-if="message.text" class="md-body" v-html="html" />
          <span v-if="message.streaming" class="cursor" />
          <div v-if="!message.text && message.streaming" class="thinking muted">
            正在检索资料…
          </div>
          <div v-if="message.error" class="error">
            <WarningOutlined />
            <span>{{ message.error }}</span>
          </div>
        </template>
      </div>

      <SourceCard v-if="!isUser" :sources="message.sources" />

      <div v-if="!isUser && message.text && !message.streaming" class="actions">
        <button class="act" @click="copy">
          <component :is="copied ? CheckOutlined : CopyOutlined" />
          {{ copied ? '已复制' : '复制' }}
        </button>
        <span v-if="message.stopped" class="muted">已中断</span>
      </div>
    </div>

    <div v-if="isUser" class="avatar me">我</div>
  </div>
</template>

<style scoped>
.row {
  display: flex;
  gap: 10px;
  margin-bottom: 22px;
  align-items: flex-start;
}
.row.right {
  flex-direction: row;
  justify-content: flex-end;
}

.avatar {
  width: 30px;
  height: 30px;
  flex-shrink: 0;
  margin-top: 2px;
  border-radius: 8px;
  font-size: 11px;
  font-weight: 600;
  display: flex;
  align-items: center;
  justify-content: center;
}
.avatar.ai {
  background: linear-gradient(135deg, var(--accent), #7b8cff);
  color: #fff;
}
.avatar.me {
  background: var(--bg-hover);
  color: var(--text-2);
  border: 1px solid var(--border);
}

.stack {
  max-width: min(760px, 78%);
  min-width: 0;
  display: flex;
  flex-direction: column;
}

.bubble {
  padding: 10px 14px;
  border-radius: 12px;
  font-size: 14px;
  line-height: 1.75;
  word-break: break-word;
  white-space: pre-wrap;
}
.bubble.user {
  background: var(--bubble-user);
  color: var(--bubble-user-text);
  border-bottom-right-radius: 4px;
}
.bubble.ai {
  background: var(--bubble-ai);
  color: var(--text-1);
  border: 1px solid var(--border);
  border-bottom-left-radius: 4px;
  box-shadow: var(--shadow-sm);
}
/* Markdown 渲染块自行控制换行，避免与 pre-wrap 叠加 */
.bubble.ai .md-body {
  white-space: normal;
}

/* 流式打字光标 */
.cursor {
  display: inline-block;
  width: 7px;
  height: 15px;
  margin-left: 2px;
  vertical-align: text-bottom;
  background: var(--accent);
  border-radius: 1px;
  animation: blink 1s steps(2, start) infinite;
}
@keyframes blink {
  to {
    visibility: hidden;
  }
}

.thinking {
  font-size: 13px;
}

.error {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 8px;
  padding: 7px 10px;
  border-radius: 7px;
  background: rgba(245, 63, 63, 0.08);
  color: #f53f3f;
  font-size: 12.5px;
}

.actions {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 7px;
  padding-left: 2px;
  font-size: 12px;
}
.act {
  display: flex;
  align-items: center;
  gap: 5px;
  padding: 3px 8px;
  border: none;
  border-radius: 6px;
  background: transparent;
  color: var(--text-3);
  font-family: inherit;
  font-size: 12px;
  cursor: pointer;
  transition: background 0.15s, color 0.15s;
}
.act:hover {
  background: var(--bg-hover);
  color: var(--text-1);
}
</style>
