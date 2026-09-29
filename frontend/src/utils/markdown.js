import MarkdownIt from 'markdown-it'
import hljs from 'highlight.js/lib/common'

// html:false —— 模型输出可能夹带 HTML 片段，禁用以避免注入
const md = new MarkdownIt({
  html: false,
  linkify: true,
  breaks: true,
  highlight(code, lang) {
    if (lang && hljs.getLanguage(lang)) {
      try {
        return hljs.highlight(code, { language: lang }).value
      } catch {
        /* 语法高亮失败时退回纯文本 */
      }
    }
    return ''
  },
})

// 渲染结果缓存：流式输出时 text 每次都在变，但历史消息的 text 不变，
// 缓存可避免重复渲染相同内容。LRU 策略，上限 200 条。
const _cache = new Map()
const CACHE_LIMIT = 200

export function renderMarkdown(text) {
  const key = text || ''
  if (_cache.has(key)) {
    // LRU：命中后移到末尾
    const val = _cache.get(key)
    _cache.delete(key)
    _cache.set(key, val)
    return val
  }
  const result = md.render(key)
  _cache.set(key, result)
  if (_cache.size > CACHE_LIMIT) {
    // 删除最旧的条目（Map 保持插入顺序）
    _cache.delete(_cache.keys().next().value)
  }
  return result
}
