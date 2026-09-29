<script setup>
import { computed, ref } from 'vue'
import { CopyOutlined, CheckOutlined, WarningOutlined, EditOutlined, SaveOutlined, CloseOutlined, ReloadOutlined, ThunderboltOutlined, UpOutlined, DownOutlined } from '@ant-design/icons-vue'
import SourceCard from './SourceCard.vue'
import { renderMarkdown } from '../utils/markdown'
import { useClipboard } from '../composables/useClipboard'

const props = defineProps({
  message: { type: Object, required: true },
})

const emit = defineEmits(['edit', 'regenerate', 'feedback'])

const isUser = computed(() => props.message.role === 'user')
const html = computed(() => (isUser.value ? '' : renderMarkdown(props.message.text)))
const { copied, copy } = useClipboard()

// ---------- 消息编辑 ----------
const editing = ref(false)
const editText = ref('')

function startEdit() {
  editText.value = props.message.text
  editing.value = true
}

function saveEdit() {
  editing.value = false
  emit('edit', { id: props.message.id, text: editText.value })
}

function cancelEdit() {
  editing.value = false
}

function regenerate() {
  emit('regenerate', props.message.id)
}

</script>

<template>
  <div class="row" :class="isUser ? 'right' : 'left'">
    <div v-if="!isUser" class="avatar ai">AI</div>

    <div class="stack">
      <div class="bubble" :class="isUser ? 'user' : 'ai'">
        <!-- 用户消息原样显示；助手消息渲染 Markdown -->
        <template v-if="isUser && !editing">{{ message.text }}</template>
        <template v-else-if="isUser && editing">
          <textarea
            v-model="editText"
            class="edit-input"
            rows="3"
            @keydown.esc="cancelEdit"
          />
          <div class="edit-actions">
            <button class="edit-btn save" @click="saveEdit">
              <SaveOutlined /> 保存
            </button>
            <button class="edit-btn cancel" @click="cancelEdit">
              <CloseOutlined /> 取消
            </button>
          </div>
        </template>
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
        <button class="act" @click="regenerate" title="重新生成">
          <ReloadOutlined />
        </button>
        <button class="act" :class="{ active: message.feedback === 'up' }" @click="emit('feedback', { id: message.id, type: 'up' })">
          <UpOutlined />
        </button>
        <button class="act" :class="{ active: message.feedback === 'down' }" @click="emit('feedback', { id: message.id, type: 'down' })">
          <DownOutlined />
        </button>
        <span v-if="message.stopped" class="muted">已中断</span>
      </div>

      <div v-if="isUser && !message.streaming" class="actions">
        <button class="act" @click="startEdit">
          <EditOutlined />
          编辑
        </button>
      </div>
    </div>

    <div v-if="isUser" class="avatar me">我</div>
  </div>
</template>

<style scoped>
.row {
  display: flex;
  gap: 10px;
  margin-bottom: 16px;
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
  border-radius: 10px;
  font-size: 11px;
  font-weight: 600;
  display: flex;
  align-items: center;
  justify-content: center;
}
.avatar.ai {
  background: linear-gradient(135deg, var(--accent), #fbbf24);
  color: #ffffff;
  box-shadow: 0 2px 8px rgba(249, 115, 22, 0.25);
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
  border-radius: 14px;
  font-size: 14px;
  line-height: 1.75;
  word-break: break-word;
  white-space: pre-wrap;
}
.bubble.user {
  background: var(--bubble-user);
  color: var(--bubble-user-text);
  border-bottom-right-radius: 4px;
  box-shadow: 0 2px 12px rgba(249, 115, 22, 0.2);
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
  border-radius: 8px;
  background: rgba(245, 63, 63, 0.08);
  color: #f53f3f;
  font-size: 12.5px;
  border: 1px solid rgba(245, 63, 63, 0.15);
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
  border-radius: 8px;
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

/* ---------- 消息编辑 ---------- */
.edit-input {
  width: 100%;
  padding: 8px 10px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--bg-app);
  color: var(--text-1);
  font-family: inherit;
  font-size: 13px;
  line-height: 1.6;
  resize: vertical;
  outline: none;
}
.edit-input:focus {
  border-color: var(--accent);
}
.edit-actions {
  display: flex;
  gap: 8px;
  margin-top: 8px;
}
.edit-btn {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 4px 10px;
  border: none;
  border-radius: 6px;
  font-size: 12px;
  cursor: pointer;
  transition: all 0.15s;
}
.edit-btn.save {
  background: var(--accent);
  color: #ffffff;
}
.edit-btn.save:hover {
  opacity: 0.9;
}
.edit-btn.cancel {
  background: var(--bg-hover);
  color: var(--text-2);
}
.edit-btn.cancel:hover {
  background: var(--border);
}
</style>
