import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { api, chatStream } from '../api/client'

let seq = 0
const nextId = () => `m${++seq}`
/** 后端 id（h 前缀）与本轮 id（m 前缀）天然区分，不会碰撞 */
const toMessage = (r) => ({
  id: `h${r.id}`,
  role: r.role,
  text: r.text,
  sources: r.role === 'assistant' ? (r.sources || []) : [],
  streaming: false,
  error: '',
  stopped: false,
})

export const useChatStore = defineStore('chat', () => {
  /** 当前会话的消息：{ [kbId]: Message[] }（切换会话时整体替换，按需回读） */
  const sessions = ref({})
  /** 某库的会话列表：{ [kbId]: [{id, name, msg_count, ...}] } */
  const sessionList = ref({})
  /** 某库当前会话 id：{ [kbId]: sessionId } */
  const currentSid = ref({})
  const streaming = ref(false)
  const sending = ref(false)
  /** 已恢复的会话 + 恢复中的 promise（ask 必先等它，避免新消息插到历史前面） */
  const loaded = ref({})
  const pendingLoad = {}
  let controller = null

  const messages = (kbId) => sessions.value[kbId] || []
  const sessionsOf = (kbId) => sessionList.value[kbId] || []
  const currentSession = (kbId) =>
    sessionsOf(kbId).find((s) => s.id === currentSid.value[kbId]) || null

  /** 会话恢复状态键：按会话粒度，避免切会话后误用别会话的 loaded */
  const loadKey = (kbId, sid) => `${kbId}:${sid}`

  async function refreshSessions(kbId) {
    const { items } = await api.sessionList(kbId)
    sessionList.value[kbId] = items || []
    // 当前会话被外部删掉时回落到第一个（后端按最近活跃排序）
    if (!sessionsOf(kbId).some((s) => s.id === currentSid.value[kbId])) {
      currentSid.value[kbId] = sessionsOf(kbId)[0]?.id || null
    }
  }

  async function loadHistory(kbId, sid) {
    const key = loadKey(kbId, sid)
    if (loaded.value[key]) return
    if (!pendingLoad[key]) {
      pendingLoad[key] = (async () => {
        try {
          const { items } = await api.historyList(kbId, sid)
          // ask 会先 await 本 promise，理论上到这里会话一定为空；
          // 判空是防御：非空则保留活会话（后端数据完整，下次重进即全量）
          if (currentSid.value[kbId] === sid && !sessions.value[kbId]?.length) {
            sessions.value[kbId] = (items || []).map(toMessage)
          }
          loaded.value[key] = true
        } catch {
          /* 后端不可用时跳过，下次切换重试 */
        } finally {
          delete pendingLoad[key]
        }
      })()
    }
    return pendingLoad[key]
  }

  /**
   * 从后端恢复某库：先拉会话列表（为空则建一个），再恢复当前会话的历史。
   * 幂等，失败静默跳过——本轮仍可正常提问，下次切换重试。
   */
  async function load(kbId) {
    if (!kbId) return
    try {
      if (!sessionList.value[kbId]) {
        await refreshSessions(kbId)
      }
      if (!sessionsOf(kbId).length) {
        await newSession(kbId)
        return
      }
      if (!currentSid.value[kbId]) {
        currentSid.value[kbId] = sessionsOf(kbId)[0].id
      }
      await loadHistory(kbId, currentSid.value[kbId])
    } catch {
      /* 后端不可用时跳过，下次切换重试 */
    }
  }

  /**
   * 切换会话。流式生成中禁止切换——半截回答只记当前会话，
   * 切走会导致落库与展示错位。
   */
  async function switchSession(kbId, sid) {
    if (streaming.value || currentSid.value[kbId] === sid) return
    currentSid.value[kbId] = sid
    sessions.value[kbId] = []
    await loadHistory(kbId, sid)
  }

  /** 新建会话并切过去。失败抛给调用方提示（静默建会让用户对着旧会话提问） */
  async function newSession(kbId) {
    if (!kbId || streaming.value) return null
    const created = await api.sessionCreate(kbId)
    sessionList.value[kbId] = [created, ...sessionsOf(kbId)]
    currentSid.value[kbId] = created.id
    sessions.value[kbId] = []
    loaded.value[loadKey(kbId, created.id)] = true
    return created
  }

  /** 删除会话（含其消息）。删的是当前会话则回落到最近会话，删空则建新 */
  async function removeSession(kbId, sid) {
    if (!kbId || streaming.value) return
    await api.sessionDelete(kbId, sid)
    sessionList.value[kbId] = sessionsOf(kbId).filter((s) => s.id !== sid)
    delete loaded.value[loadKey(kbId, sid)]
    if (currentSid.value[kbId] === sid) {
      sessions.value[kbId] = []
      if (!sessionsOf(kbId).length) {
        await newSession(kbId)
      } else {
        currentSid.value[kbId] = sessionsOf(kbId)[0].id
        await loadHistory(kbId, currentSid.value[kbId])
      }
    }
  }

  /** 重命名会话，空名由后端拒绝（404/422 抛给调用方提示） */
  async function renameSession(kbId, sid, name) {
    await api.sessionRename(kbId, sid, name)
    const item = sessionsOf(kbId).find((s) => s.id === sid)
    if (item) item.name = name.trim()
  }

/** 置顶/取消置顶会话 */
async function togglePinSession(kbId, sid) {
  const item = sessionsOf(kbId).find((s) => s.id === sid)
  if (!item) return
  item.pinned = !item.pinned
  // 重新排序：置顶在前
  sessionList.value[kbId] = [...sessionsOf(kbId)].sort((a, b) => {
    if (a.pinned && !b.pinned) return -1
    if (!a.pinned && b.pinned) return 1
    return 0
  })
}

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

  /**
   * 清空当前会话：先调后端删除落库记录，成功才清本地。
   * 失败时抛给调用方提示——静默清本地会导致刷新后记录"复活"，更迷惑。
   */
  async function clear(kbId) {
    if (kbId) {
      await api.historyClear(kbId, currentSid.value[kbId])
      sessions.value[kbId] = []
      delete loaded.value[loadKey(kbId, currentSid.value[kbId])]
    } else {
      sessions.value = {}
      sessionList.value = {}
      currentSid.value = {}
      loaded.value = {}
    }
  }

  function stop() {
    controller?.abort()
    controller = null
    streaming.value = false
  }

  // ---------- ask 内部拆分 ----------

  /** 校验是否可发送 */
  function validateAsk(kbId, question) {
    if (!kbId || !question.trim() || streaming.value || sending.value) return false
    return true
  }

  /** 推送用户消息和空的助手占位消息 */
  function pushUserAndPlaceholder(kbId, question) {
    push(kbId, { id: nextId(), role: 'user', text: question })
    return push(kbId, {
      id: nextId(),
      role: 'assistant',
      text: '',
      sources: [],
      streaming: true,
      error: '',
      stopped: false,
    })
  }

  /** 流式请求完成后的清理 */
  function finishReply(reply) {
    reply.streaming = false
    streaming.value = false
    sending.value = false
    controller = null
  }

  /** 处理流式回调 */
  function bindStreamCallbacks(reply) {
    return {
      onSources: (list) => { reply.sources = list },
      onDelta: (t) => { reply.text += t },
      onError: (e) => {
        reply.error = e.message
        finishReply(reply)
      },
      onDone: () => {
        if (!reply.text && !reply.error) reply.error = '未收到回答内容'
        finishReply(reply)
      },
    }
  }

  async function ask(kbId, question, topK) {
    if (!validateAsk(kbId, question)) return
    await load(kbId)
    const sid = currentSid.value[kbId]

    const reply = pushUserAndPlaceholder(kbId, question)
    streaming.value = true
    sending.value = true
    controller = new AbortController()

    const callbacks = bindStreamCallbacks(reply)
    await chatStream({
      kbId, question, topK, sessionId: sid,
      signal: controller.signal,
      ...callbacks,
    })

    if (reply.streaming) {
      reply.stopped = true
      finishReply(reply)
    }
    try {
      await refreshSessions(kbId)
    } catch {
      /* 列表刷新失败不影响本轮展示，下次切换即全量 */
    }
    return reply
  }

/** 添加用户消息 */
function pushUserMessage(kbId, text) {
  return push(kbId, {
    id: `u${Date.now()}`,
    role: 'user',
    text,
    sources: [],
    streaming: false,
    error: '',
    stopped: false,
  })
}

/** 添加助手消息 */
function pushAssistantMessage(kbId, text, sources) {
  return push(kbId, {
    id: `a${Date.now()}`,
    role: 'assistant',
    text,
    sources: sources || [],
    streaming: false,
    error: '',
    stopped: false,
  })
}

  return {
    sessions, sessionList, streaming,
    messages, sessionsOf, currentSession,
    ask, clear, stop, load,
    switchSession, newSession, removeSession, renameSession, togglePinSession,
  }
})
