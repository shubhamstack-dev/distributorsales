// The token lives in sessionStorage, not localStorage: on a shared machine a
// session should not outlive the browser window.
let token = sessionStorage.getItem('ds.token') || ''
let onOut = null

export function setToken(t) {
  token = t || ''
  if (token) sessionStorage.setItem('ds.token', token)
  else sessionStorage.removeItem('ds.token')
}
export const getToken = () => token
export const onSignedOut = (fn) => { onOut = fn }

export class ApiError extends Error {
  constructor(status, message) { super(message); this.status = status }
}

async function handle(res) {
  if (res.status === 401 && onOut) onOut()
  if (res.status === 204) return null
  const text = await res.text()
  let data = null
  try { data = text ? JSON.parse(text) : null } catch { data = null }
  if (!res.ok) {
    const d = data?.detail
    throw new ApiError(res.status, typeof d === 'string' ? d
      : Array.isArray(d) ? d.map((x) => x.msg || JSON.stringify(x)).join('; ')
      : data?.message || res.statusText)
  }
  return data
}
const auth = () => (token ? { Authorization: `Bearer ${token}` } : {})

async function call(method, url, body) {
  return handle(await fetch(url, {
    method,
    headers: { 'Content-Type': 'application/json', ...auth() },
    body: body === undefined ? undefined : JSON.stringify(body),
  }))
}

/** Upload with progress: fetch still cannot report it, and a 60 MB zip with no
 *  bar looks like a hang. */
function upload(url, form, onProgress) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open('POST', url)
    Object.entries(auth()).forEach(([k, v]) => xhr.setRequestHeader(k, v))
    if (onProgress) {
      xhr.upload.onprogress = (e) => { if (e.lengthComputable) onProgress(e.loaded / e.total) }
    }
    xhr.onerror = () => reject(new ApiError(0, 'The upload could not reach the server.'))
    xhr.onload = () => {
      if (xhr.status === 401 && onOut) onOut()
      let data = null
      try { data = xhr.responseText ? JSON.parse(xhr.responseText) : null } catch { data = null }
      if (xhr.status < 200 || xhr.status >= 300) {
        return reject(new ApiError(xhr.status,
          typeof data?.detail === 'string' ? data.detail : xhr.statusText))
      }
      resolve(data)
    }
    xhr.send(form)
  })
}

export const api = {
  login: (password, who) => call('POST', '/api/login', { password, who }),
  distributors: () => call('GET', '/api/distributors'),
  updateDistributor: (id, body) => call('PUT', `/api/distributors/${id}`, body),
  inspect: (files, distributorId, onProgress) => {
    const fd = new FormData()
    fd.append('distributor_id', distributorId)
    for (const f of files) fd.append('files', f)
    return upload('/api/uploads/inspect', fd, onProgress)
  },
  commit: (token_, body) => call('POST', `/api/uploads/${token_}/commit`, body),
  batches: () => call('GET', '/api/batches'),
  batch: (id) => call('GET', `/api/batches/${id}`),
  rows: (id, page, size, q) =>
    call('GET', `/api/batches/${id}/rows?page=${page}&size=${size}${q ? `&q=${encodeURIComponent(q)}` : ''}`),
  deleteBatch: (id) => call('DELETE', `/api/batches/${id}`),
  // the export needs the token in a header, so it is fetched and then saved
  download: async (id) => {
    const res = await fetch(`/api/batches/${id}/export`, { headers: auth() })
    if (!res.ok) { await handle(res); return }
    const cd = res.headers.get('content-disposition') || ''
    const name = (/filename="([^"]+)"/.exec(cd) || [])[1] || `batch-${id}.xlsx`
    const url = URL.createObjectURL(await res.blob())
    const a = document.createElement('a')
    a.href = url; a.download = name; document.body.appendChild(a); a.click()
    a.remove(); URL.revokeObjectURL(url)
    return name
  },
}
