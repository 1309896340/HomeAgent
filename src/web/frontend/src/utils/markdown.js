// Markdown 渲染：marked 解析 + DOMPurify 消毒 + highlight.js 代码高亮
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import hljs from 'highlight.js'

marked.setOptions({ gfm: true, breaks: true })

export function renderMarkdown(text) {
  if (!text) return ''
  const html = marked.parse(text)
  return DOMPurify.sanitize(html, { ADD_ATTR: ['target'] })
}

// 对容器内尚未高亮的 pre>code 执行高亮（流式渲染后反复调用安全）
export function highlightCode(rootEl) {
  rootEl?.querySelectorAll('pre code:not([data-hl])').forEach((block) => {
    hljs.highlightElement(block)
    block.dataset.hl = '1'
  })
}
