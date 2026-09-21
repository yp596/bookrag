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

export function renderMarkdown(text) {
  return md.render(text || '')
}
