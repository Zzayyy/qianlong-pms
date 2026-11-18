/**
 * 极简 Markdown 渲染：只支持周报正文用到的几类语法（标题 / 有序无序列表 / 引用 / 加粗）。
 * 先转义再加标签，避免用户正文里的 HTML 被执行（XSS）。
 */

const escapeHtml = (text: string) =>
  text.replace(/[&<>"']/g, (char) => {
    const map: Record<string, string> = {
      '&': '&amp;',
      '<': '&lt;',
      '>': '&gt;',
      '"': '&quot;',
      "'": '&#39;'
    }
    return map[char] ?? char
  })

/** Markdown 文本 → 可直接 v-html 的 HTML 片段。 */
export const renderMarkdown = (raw: string) => {
  const lines = escapeHtml(raw || '').split(/\r?\n/)
  const html: string[] = []
  let listTag: 'ul' | 'ol' | '' = ''
  const closeList = () => {
    if (listTag) {
      html.push(`</${listTag}>`)
      listTag = ''
    }
  }
  const openList = (tag: 'ul' | 'ol') => {
    if (listTag !== tag) {
      closeList()
      html.push(`<${tag}>`)
      listTag = tag
    }
  }
  for (const line of lines) {
    const text = line.replace(/\*\*(.+?)\*\*/g, '<b>$1</b>')
    if (!text.trim()) {
      closeList()
      continue
    }
    const heading = /^(#{1,4})\s+(.*)$/.exec(text)
    if (heading) {
      closeList()
      const level = Math.min(heading[1].length + 1, 5)
      html.push(`<h${level}>${heading[2]}</h${level}>`)
      continue
    }
    if (/^\s*\d+[.、)]\s+/.test(text)) {
      openList('ol')
      html.push(`<li>${text.replace(/^\s*\d+[.、)]\s+/, '')}</li>`)
      continue
    }
    if (/^\s*[-*]\s+/.test(text)) {
      openList('ul')
      html.push(`<li>${text.replace(/^\s*[-*]\s+/, '')}</li>`)
      continue
    }
    if (/^&gt;\s?/.test(text)) {
      closeList()
      html.push(`<blockquote>${text.replace(/^&gt;\s?/, '')}</blockquote>`)
      continue
    }
    closeList()
    html.push(`<p>${text}</p>`)
  }
  closeList()
  return html.join('')
}

/** 去掉正文首行一级标题（标题通常已在详情头部展示，避免重复）。 */
export const stripLeadingTitle = (content: string) =>
  (content || '').replace(/^\s*#\s+.*(?:\r?\n)+/, '')
