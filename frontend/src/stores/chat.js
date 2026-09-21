import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { chatStream } from '../api/client'

let seq = 0
const nextId = () => `m${++seq}`

export const useChatStore = defineStore('chat', () => {
  /** 每个知识库一份独立会话：{ [kbId]: Message[] } */
  const sessions = ref({})
  const streaming = ref(false)
  let controller = null

  const messages = (kbId) => sessions.value[kbId] || []

  /**
   * 追加一条消息，并返回它在数组中的**响应式代理**。
   *
   * 注意：不能直接返回传入的 msg —— sessions 是 ref({})，push 进去的是原始对象，
   * 而读出来的是 Proxy。若后续修改原始对象，会绕过 Proxy 的 set 陷阱，
   * 流式增量就不会触发重新渲染。必须改读回来的那个引用。
   */
  function push(kbId, msg) {
    if (!sessions.value[kbId]) sessions.value[kbId] = []
    const list = sessions.value[kbId]
    list.push(msg)
    return list[list.length - 1]
  }

  function clear(kbId) {
    if (kbId) sessions.value[kbId] = []
    else sessions.value = {}
  }

  function stop() {
    controller?.abort()
    controller = null
    streaming.value = false
  }

  /**
   * 发起一次提问。
   * 用户消息与助手占位消息先入列，随后由 SSE 增量填充助手消息。
   */
  async function ask(kbId, question, topK) {
    if (!kbId || !question.trim() || streaming.value) return

    push(kbId, { id: nextId(), role: 'user', text: question })
    const reply = push(kbId, {
      id: nextId(),
      role: 'assistant',
      text: '',
      sources: [],
      streaming: true,
      error: '',
      stopped: false,
    })

    streaming.value = true
    controller = new AbortController()

    const finish = () => {
      reply.streaming = false
      streaming.value = false
      controller = null
    }

    await chatStream({
      kbId,
      question,
      topK,
      signal: controller.signal,
      onSources: (list) => { reply.sources = list },
      onDelta: (t) => { reply.text += t },
      onError: (e) => {
        reply.error = e.message
        finish()
      },
      onDone: () => {
        // 中断时可能已收到部分内容，标记出来避免看起来像生成失败
        if (!reply.text && !reply.error) reply.error = '未收到回答内容'
        finish()
      },
    })

    if (reply.streaming) {
      reply.stopped = true
      finish()
    }
    return reply
  }

  return { sessions, streaming, messages, ask, clear, stop }
})
