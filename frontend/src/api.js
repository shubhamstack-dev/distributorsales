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
  constructor(status, message, detail) { super(message); this.status = status; this.detail = detail }
}

async function handle(res) {
  if (res.status === 401 && onOut) onOut()
  if (res.status === 204) return null
  const text = await res.text()
  let data = null
  try { data = text ? JSON.parse(text) : null } catch { data = null }
  if (!res.ok) {
    const d = data?.detail
    // detail may be an object with a message and the lists behind it (a refused conversion)
    throw new ApiError(res.status, typeof d === 'string' ? d
      : Array.isArray(d) ? d.map((x) => x.msg || JSON.stringify(x)).join('; ')
      : d?.message || data?.message || res.statusText
        // never an empty message: over HTTPS a crash comes back with no status text
        || `The server stopped with error ${res.status} and gave no reason. Nothing was saved; `
          + 'the reason is in the server log (docker compose logs --tail=80 backend).',
      d && typeof d === 'object' && !Array.isArray(d) ? d : null)
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

/** Query string from an object, leaving out empty values. */
export function qs(params = {}) {
  return Object.entries(params)
    .filter(([, v]) => v !== undefined && v !== null && v !== '')
    .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(v)}`).join('&')
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
  nameLists: (id) => call('GET', `/api/distributors/${id}/names`),
  uploadNames: (id, kind, file) => {
    const fd = new FormData()
    fd.append('kind', kind)
    fd.append('file', file)
    return upload(`/api/distributors/${id}/names`, fd)
  },
  batches: () => call('GET', '/api/batches'),
  batch: (id) => call('GET', `/api/batches/${id}`),
  rows: (id, page, size, q) =>
    call('GET', `/api/batches/${id}/rows?page=${page}&size=${size}${q ? `&q=${encodeURIComponent(q)}` : ''}`),
  deleteBatch: (id) => call('DELETE', `/api/batches/${id}`),

  // ---- master data: one set of calls for every master, by slug
  masterMeta: () => call('GET', '/api/masters/meta'),
  masterList: (slug, params) => call('GET', `/api/masters/${slug}?${qs(params)}`),
  masterOptions: (slug, params) => call('GET', `/api/masters/${slug}/options?${qs(params)}`),
  masterCreate: (slug, body) => call('POST', `/api/masters/${slug}`, body),
  masterUpdate: (slug, id, body) => call('PUT', `/api/masters/${slug}/${id}`, body),
  masterDelete: (slug, id) => call('DELETE', `/api/masters/${slug}/${id}`),
  masterDeleteMany: (slug, ids) => call('POST', `/api/masters/${slug}/delete-many`, { ids }),
  masterUpload: (files, dryRun, slug, onProgress) => {
    const fd = new FormData()
    files.forEach((f) => fd.append('files', f))
    fd.append('dry_run', dryRun ? 'true' : 'false')
    if (slug) fd.append('slug', slug)
    return upload('/api/masters/upload', fd, onProgress)
  },
  masterExport: (slug) => save(`/api/masters/${slug}/export`, `${slug}.xlsx`),
  masterExportAll: () => save('/api/masters/export-all', 'MASTER_DATA.xlsx'),
  // Customer / Employee Terr-PG: the two assignment tables of a kind, joined
  // create / delete / assign all / clean on the assignment pages; dry_run only counts
  assign: (kind, action, body) => call('POST', `/api/assign/${kind}/${action}`, body),
  // a file's spelling matched to a master by hand, on Convert's panel
  nameMatch: (kind, name, masterId) => call('POST', '/api/name-match', { kind, name, master_id: masterId }),
  // Budget Upload (check, then post) and Budget Report
  budgetYears: () => call('GET', '/api/budget/years'),
  budgetTemplate: () => save('/api/budget/template', 'AbbottBudgetFormet.xlsx'),
  budgetUpload: (year, file, dryRun) => {
    const fd = new FormData()
    fd.append('year', year)
    fd.append('dry_run', dryRun ? 'true' : 'false')
    fd.append('file', file)
    return upload('/api/budget/upload', fd)
  },
  budgetCarry: (body) => call('POST', '/api/budget/carry-forward', body),
  budgetZero: (body) => call('POST', '/api/budget/zero-rows', body),
  budgetActuals: (year, month) => call('POST', '/api/budget/calculate-actuals', { year, month }),
  budgetReport: (params) => call('GET', `/api/budget/report?${qs(params)}`),
  budgetExport: (params) => save(`/api/budget/report/export?${qs(params)}`, `BUDGET_REPORT_${params.year}.xlsx`),
  dataError: (distributorId, fileType) =>
    call('GET', `/api/data-error?${qs({ distributor_id: distributorId, file_type: fileType })}`),
  terrPg: (kind, params) => call('GET', `/api/terr-pg/${kind}?${qs(params)}`),
  terrPgExport: (kind, params) => save(`/api/terr-pg/${kind}/export?${qs(params)}`, `${kind}-terr-pg.xlsx`),
  rate: (frm, to, on) => call('GET', `/api/currency/rate?${qs({ frm, to, on })}`),
  convert: (amount, frm, to, on) => call('GET', `/api/currency/convert?${qs({ amount, frm, to, on })}`),
  download: (id) => save(`/api/batches/${id}/export`, `batch-${id}.xlsx`),
}

/** A file download that needs the token in a header: fetched, then saved. */
async function save(url, fallback) {
  const res = await fetch(url, { headers: auth() })
  if (!res.ok) { await handle(res); return }
  const cd = res.headers.get('content-disposition') || ''
  const name = (/filename="([^"]+)"/.exec(cd) || [])[1] || fallback
  const href = URL.createObjectURL(await res.blob())
  const a = document.createElement('a')
  a.href = href; a.download = name; document.body.appendChild(a); a.click()
  a.remove(); URL.revokeObjectURL(href)
  return name
}
