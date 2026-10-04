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

/** DELETE 请求 */
export function del(path) {
  return request(path, { method: 'DELETE' })
}
