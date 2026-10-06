// 后端 API 统一封装：基于原生 fetch，统一处理 base url、JSON 序列化与错误。
// API 请求一律使用相对路径（/api/xxx），开发环境由 vite dev server 代理转发，
// 生产环境由反向代理（nginx 等）转发，避免 CORS。

const BASE_URL = import.meta.env.VITE_API_BASE_URL || '/api'

/**
 * 通用请求方法
 * @param {string} path 相对路径，如 '/health'
 * @param {{ method?: string, query?: Record<string, any>, body?: any, headers?: Record<string, string> }} [options]
 * @returns {Promise<any>} 解析后的 JSON 数据
 */
export async function request(path, options = {}) {
  const { method = 'GET', query, body, headers } = options

  let url = `${BASE_URL}${path}`
  if (query) {
    const params = new URLSearchParams()
    for (const [key, value] of Object.entries(query)) {
      if (value !== undefined && value !== null) params.append(key, value)
    }
    const qs = params.toString()
    if (qs) url += `?${qs}`
  }

  const response = await fetch(url, {
    method,
    headers: {
      ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}),
      ...headers,
    },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })

  if (!response.ok) {
    const text = await response.text().catch(() => '')
    throw new Error(
      `API 请求失败: ${response.status} ${response.statusText}${text ? ` - ${text}` : ''}`,
    )
  }

  // 204 或空响应体直接返回 null
  if (response.status === 204) return null
  const contentType = response.headers.get('content-type') || ''
  if (!contentType.includes('application/json')) {
    return response.text()
  }
  return response.json()
}

/** GET 请求 */
export function get(path, query) {
  return request(path, { method: 'GET', query })
}

/** POST 请求（JSON body） */
export function post(path, body) {
  return request(path, { method: 'POST', body })
}

/** PUT 请求（JSON body） */
export function put(path, body) {
  return request(path, { method: 'PUT', body })
}

/** PATCH 请求（JSON body） */
export function patch(path, body) {
  return request(path, { method: 'PATCH', body })
}

/** DELETE 请求 */
export function del(path) {
  return request(path, { method: 'DELETE' })
}

/** multipart 文件上传 */
export async function upload(path, file, fieldName = 'file') {
  const form = new FormData()
  form.append(fieldName, file)
  const response = await fetch(`${BASE_URL}${path}`, { method: 'POST', body: form })
  if (!response.ok) {
    const text = await response.text().catch(() => '')
    throw new Error(`上传失败: ${response.status}${text ? ` - ${text}` : ''}`)
  }
  return response.json()
}

/**
 * POST SSE 流式请求：解析 data: {json} 事件块，逐个回调 onEvent。
 * 通过 AbortController.signal 支持中断（中断时服务端保留已生成内容）。
 * @param {string} path 相对路径
 * @param {object} body JSON 请求体
 * @param {{ signal?: AbortSignal, onEvent?: (event: object) => void }} [options]
 */
export async function postSSE(path, body, { signal, onEvent } = {}) {
  const response = await fetch(`${BASE_URL}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal,
  })
  if (!response.ok) {
    const text = await response.text().catch(() => '')
    throw new Error(`请求失败: ${response.status}${text ? ` - ${text}` : ''}`)
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    let sep
    while ((sep = buffer.indexOf('\n\n')) >= 0) {
      const block = buffer.slice(0, sep)
      buffer = buffer.slice(sep + 2)
      for (const line of block.split('\n')) {
        if (!line.startsWith('data:')) continue
        try {
          onEvent?.(JSON.parse(line.slice(5)))
        } catch {
          // 忽略无法解析的行
        }
      }
    }
  }
}
