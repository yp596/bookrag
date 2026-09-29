import axios from 'axios'

/**
 * 后端地址在运行时才确定：
 *   - 浏览器开发态：走 Vite 代理，用相对路径 /api
 *   - Electron：主进程拉起 Python 后才知道端口，启动时由 setApiBase() 注入
 * 因此不能把 baseURL 写死在 axios 实例上，改为每次请求时读取。
 */
let apiBase = window.location.protocol === 'file:' ? 'http://127.0.0.1:8756/api' : '/api'

export function setApiBase(backendUrl) {
  apiBase = backendUrl ? `${backendUrl}/api` : '/api'
}

export function getApiBase() {
  return apiBase
}

const http = axios.create({ timeout: 300000 })
http.interceptors.request.use((config) => {
  config.baseURL = apiBase
  return config
})

// 统一把后端的 detail 提取成 Error.message，页面直接拿去提示即可
http.interceptors.response.use(
  (resp) => resp.data,
  (err) => {
    const detail = err.response?.data?.detail
    const message =
      typeof detail === 'string'
        ? detail
        : Array.isArray(detail)
          ? detail.map((d) => d.msg).join('；')
          : err.code === 'ECONNABORTED'
            ? '请求超时，模型可能仍在生成'
            : err.message || '请求失败'
    return Promise.reject(new Error(message))
  },
)

export const api = {
  health: () => http.get('/health'),

  listKbs: () => http.get('/kb/list'),
  createKb: (name) => http.post('/kb/create', { name }),
  deleteKb: (kbId) => http.delete(`/kb/${kbId}`),
  listDocs: (kbId) => http.get(`/kb/${kbId}/docs`),
  deleteDoc: (kbId, docId) => http.delete(`/kb/${kbId}/docs/${docId}`),
  clearDocs: (kbId) => http.delete(`/kb/${kbId}/docs`),
  fetchUrl: (kbId, url) => http.post(`/kb/${kbId}/fetch`, { url }),
  historyList: (kbId, sessionId, limit) =>
    http.get(`/kb/${kbId}/messages`, { params: { session_id: sessionId, limit } }),
  historyClear: (kbId, sessionId) =>
    http.delete(`/kb/${kbId}/messages`, { params: { session_id: sessionId } }),
  sessionList: (kbId) => http.get(`/kb/${kbId}/sessions`),
  sessionCreate: (kbId, name) => http.post(`/kb/${kbId}/sessions`, { name }),
  sessionRename: (kbId, sessionId, name) => http.patch(`/kb/${kbId}/sessions/${sessionId}`, { name }),
  sessionDelete: (kbId, sessionId) => http.delete(`/kb/${kbId}/sessions/${sessionId}`),

  uploadDoc: (kbId, file, onProgress) => {
    const form = new FormData()
    form.append('file', file)
    return http.post(`/kb/${kbId}/upload`, form, {
      onUploadProgress: (e) => {
        if (onProgress && e.total) onProgress(Math.round((e.loaded / e.total) * 100))
      },
    })
  },

  getSettings: () => http.get('/settings'),
  saveSettings: (payload) => http.post('/settings', payload),
  testSettings: () => http.post('/settings/test'),
  localModel: () => http.get('/settings/local-model'),
  kbGraph: (kbId) => http.get(`/kb/${kbId}/graph`),
  kbTasks: (kbId) => http.get(`/kb/${kbId}/tasks`),
  searchDocs: (kbId, q) => http.get(`/kb/${kbId}/search`, { params: { q } }),
  previewDoc: (kbId, docId) => http.get(`/kb/${kbId}/docs/${docId}/preview`),
  backupAll: () => http.get('/kb/backup'),
  restoreAll: (data) => http.post('/kb/restore', data),
  exportKb: (kbId) => http.get(`/kb/${kbId}/export`),
  importKb: (kbId, data) => http.post(`/kb/${kbId}/import`, data),
  testDirect: (payload) => http.post('/settings/test-direct', payload),
  chatMultiTurn: (payload) => http.post('/chat/multi-turn', payload),
  batchFetchUrls: (kbId, urls) => http.post(`/kb/${kbId}/batch-fetch`, { urls }),
  compareDocs: (docIds) => http.post('/kb/compare', { doc_ids: docIds }),
  previewDocument: (path) => http.post('/kb/preview', { path }),
  chatDebug: (payload) => http.post('/chat/debug', payload),
  exportChat: (kbId, sessionId) => http.get(`/chat/export/${sessionId}`, { params: { kb_id: kbId } }),
  chatRecommend: (payload) => http.post('/chat/recommend', payload),
  messageFeedback: (msgId, type) => http.post(`/chat/feedback/${msgId}`, { type }),
  recursiveFetch: (kbId, payload) => http.post(`/kb/${kbId}/recursive-fetch`, payload),
  createCrawlSchedule: (kbId, payload) => http.post(`/kb/${kbId}/crawl-schedule`, payload),
  listCrawlSchedules: (kbId) => http.get(`/kb/${kbId}/crawl-schedules`),
  deleteCrawlSchedule: (kbId, scheduleId) => http.delete(`/kb/${kbId}/crawl-schedules/${scheduleId}`),
  listCrawlHistory: (kbId, limit) => http.get(`/kb/${kbId}/crawl-history`, { params: { limit } }),
  incrementalFetch: (kbId, payload) => http.post(`/kb/${kbId}/incremental-fetch`, payload),
  createAgentTask: (kbId, payload) => http.post(`/kb/${kbId}/agent-tasks`, payload),
  listAgentTasks: (kbId) => http.get(`/kb/${kbId}/agent-tasks`),
  getAgentTask: (kbId, taskId) => http.get(`/kb/${kbId}/agent-tasks/${taskId}`),
  deleteAgentTask: (kbId, taskId) => http.delete(`/kb/${kbId}/agent-tasks/${taskId}`),
  addAgentTaskStep: (kbId, taskId, payload) => http.post(`/kb/${kbId}/agent-tasks/${taskId}/steps`, payload),
  executeAgentTask: (kbId, taskId) => http.post(`/kb/${kbId}/agent-tasks/${taskId}/execute`),
}

// ====================== SSE 解析 ======================

/**
 * 创建 SSE 帧解析器。
 * 将 ReadableStream 解析为事件回调，供 chatStream 使用。
 */
function createSSEParser({ onSources, onDelta, onError, onDone }) {
  let buffer = ''
  let event = ''
  let dataLines = []
  let finished = false

  const dispatch = () => {
    if (!dataLines.length) {
      event = ''
      return
    }
    const raw = dataLines.join('\n')
    try {
      const payload = JSON.parse(raw)
      if (event === 'sources') onSources?.(payload)
      else if (event === 'delta') onDelta?.(payload.text || '')
      else if (event === 'error') onError?.(new Error(payload.message || '生成失败'))
      else if (event === 'done') {
        finished = true
        onDone?.()
      }
    } catch {
      // 半截 JSON 或心跳注释，忽略即可
    }
    event = ''
    dataLines = []
  }

  return {
    /** 喂入一段解码后的文本，返回是否已结束 */
    feed(text) {
      buffer += text
      let nl
      while ((nl = buffer.indexOf('\n')) >= 0) {
        let line = buffer.slice(0, nl)
        buffer = buffer.slice(nl + 1)
        if (line.endsWith('\r')) line = line.slice(0, -1)

        if (line === '') {
          dispatch()
        } else if (line.startsWith(':')) {
          // 注释/心跳
        } else if (line.startsWith('event:')) {
          event = line.slice(6).trim()
        } else if (line.startsWith('data:')) {
          dataLines.push(line.slice(5).replace(/^ /, ''))
        }
      }
      return finished
    },
    /** 流结束时刷新残留帧 */
    flush() {
      dispatch()
      if (!finished) {
        finished = true
        onDone?.()
      }
    },
  }
}

/**
 * 发起流式问答请求（仅负责 HTTP 连接，SSE 解析由 createSSEParser 处理）。
 */
async function postChat({ kbId, question, topK, sessionId, signal }) {
  return fetch(`${apiBase}/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ kb_id: kbId, question, top_k: topK ?? null, session_id: sessionId ?? null }),
    signal,
  })
}

/**
 * SSE 流式问答。
 *
 * 浏览器原生 EventSource 只支持 GET，无法携带 JSON 请求体，
 * 因此改用 fetch + ReadableStream 手工解析 SSE 帧。
 *
 * @param {object}   opts
 * @param {string}   opts.kbId
 * @param {string}   opts.question
 * @param {number}   [opts.topK]
 * @param {Function} opts.onSources  命中引用，流开始前触发一次
 * @param {Function} opts.onDelta    文本增量
 * @param {Function} opts.onDone
 * @param {Function} opts.onError
 * @param {AbortSignal} [opts.signal]
 */
export async function chatStream({ kbId, question, topK, sessionId, onSources, onDelta, onDone, onError, signal }) {
  let resp
  try {
    resp = await fetch(`${apiBase}/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ kb_id: kbId, question, top_k: topK ?? null, session_id: sessionId ?? null }),
      signal,
    })
  } catch (e) {
    if (e.name === 'AbortError') return
    onError?.(new Error('无法连接后端服务，请确认服务已启动'))
    return
  }

  if (!resp.ok) {
    let message = `请求失败（${resp.status}）`
    try {
      const body = await resp.json()
      if (body.detail) message = body.detail
    } catch {
      /* 响应体非 JSON，沿用默认提示 */
    }
    onError?.(new Error(message))
    return
  }

  const reader = resp.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''
  let event = ''
  let dataLines = []
  let finished = false // done 事件与流关闭都会到达，用标记保证只回调一次

  // 一帧 SSE 以空行结束，此处统一分发
  const dispatch = () => {
    if (!dataLines.length) {
      event = ''
      return
    }
    const raw = dataLines.join('\n')
    try {
      const payload = JSON.parse(raw)
      if (event === 'sources') onSources?.(payload)
      else if (event === 'delta') onDelta?.(payload.text || '')
      else if (event === 'error') onError?.(new Error(payload.message || '生成失败'))
      else if (event === 'done') {
        finished = true
        onDone?.()
      }
    } catch {
      // 半截 JSON 或心跳注释，忽略即可
    }
    event = ''
    dataLines = []
  }

  try {
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })

      let nl
      while ((nl = buffer.indexOf('\n')) >= 0) {
        let line = buffer.slice(0, nl)
        buffer = buffer.slice(nl + 1)
        if (line.endsWith('\r')) line = line.slice(0, -1)

        if (line === '') {
          dispatch()
        } else if (line.startsWith(':')) {
          // 注释/心跳
        } else if (line.startsWith('event:')) {
          event = line.slice(6).trim()
        } else if (line.startsWith('data:')) {
          dataLines.push(line.slice(5).replace(/^ /, ''))
        }
      }
    }
    // 流结束时若还有未分发的残留帧
    dispatch()
    if (!finished) {
      finished = true
      onDone?.()
    }
  } catch (e) {
    if (e.name !== 'AbortError') onError?.(e)
  }
}
