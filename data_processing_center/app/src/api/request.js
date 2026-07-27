const BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8001'

function buildUrl(url, params = {}) {
  const requestUrl = new URL(url, BASE_URL)
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') {
      requestUrl.searchParams.append(key, String(value))
    }
  })
  return requestUrl.toString()
}

async function request(url, options = {}) {
  const response = await fetch(url, options)
  const data = await response.json().catch(() => ({}))
  if (!response.ok) {
    const message = data.detail || data.message || '请求失败'
    throw new Error(message)
  }
  return data
}

export function get(url, params = {}, config = {}) {
  return request(buildUrl(url, params), {
    method: 'GET',
    headers: { 'Content-Type': 'application/json', ...(config.headers || {}) }
  })
}

export function post(url, body = {}, config = {}) {
  return request(buildUrl(url), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...(config.headers || {}) },
    body: JSON.stringify(body)
  })
}

export function del(url, config = {}) {
  return request(buildUrl(url), {
    method: 'DELETE',
    headers: { 'Content-Type': 'application/json', ...(config.headers || {}) }
  })
}
