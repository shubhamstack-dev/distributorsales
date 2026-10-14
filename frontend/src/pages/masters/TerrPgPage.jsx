import { useEffect, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../../api.js'
import RefSelect from './RefSelect.jsx'
import UploadReport from './UploadReport.jsx'
import AssignPanel, { checkThenRun } from './AssignPanel.jsx'

const SIZE = 50

// The two tables behind each page, in the order a row reads (territory, then product).
const TABLES = {
  customer: ['customer_terr_assignment', 'customer_pg_assignment'],
  employee: ['employee_terr_assignment', 'employee_pg_assignment'],
}
const ABOUT = {
  customer: 'Every product a customer is assigned, with the territory, HQ and team that cover it '
    + 'for that product group. CUSTOMER_PG_ASSIGNMENT joined to CUSTOMER_TERR_ASSIGNMENT on the '
    + 'customer and the product group.',
  employee: 'Every product an employee promotes, with the HQ and territory they cover. '
    + 'EMPLOYEE_PG_ASSIGNMENT joined to EMPLOYEE_TERR_ASSIGNMENT on the employee.',
}

/** Customer Terr-PG / Employee Terr-PG, as the old Abbott screens had them:
 *  one row per product assignment with its territory beside it. Rows are added
 *  and edited in the two tables behind the page, linked under the title. */
export default function TerrPgPage({ meta }) {
  const { kind } = useParams()
  const [filters, setFilters] = useState({})
  const [q, setQ] = useState('')
  const [typed, setTyped] = useState('')
  const [page, setPage] = useState(1)
  const [data, setData] = useState(null)
  const [msg, setMsg] = useState(null)
  const [busy, setBusy] = useState(false)
  const [files, setFiles] = useState([])
  const [report, setReport] = useState(null)
  const [editing, setEditing] = useState(false)
  const pick = useRef(null)

  useEffect(() => { setFilters({}); setQ(''); setTyped(''); setPage(1); setReport(null); setMsg(null); setEditing(false) }, [kind])
  useEffect(() => {
    const t = setTimeout(() => { setQ(typed.trim()); setPage(1) }, 400)
    return () => clearTimeout(t)
  }, [typed])
  function load() {
    api.terrPg(kind, { ...filters, q, page, size: SIZE })
      .then(setData).catch((e) => setMsg({ bad: true, t: e.message }))
  }
  useEffect(load, [kind, filters, q, page]) // eslint-disable-line react-hooks/exhaustive-deps

  if (!TABLES[kind]) return <div className="page"><div className="alert bad">No such page.</div></div>
  const tables = TABLES[kind].map((s) => meta.find((m) => m.slug === s)).filter(Boolean)
  const title = kind === 'customer' ? 'Customer Terr-PG' : 'Employee Terr-PG'
  const pages = data ? Math.max(1, Math.ceil(data.total / SIZE)) : 1
  const setFilter = (k, v) => { setFilters((f) => ({ ...f, [k]: v ?? '' })); setPage(1) }

  // Assign all / Delete all: every customer, or only the one the filter shows
  const who = kind === 'customer' ? 'customer_id' : 'employee_id'
  const scoped = filters[who] ? [filters[who]] : []
  async function bulk(action, verb) {
    setBusy(true); setMsg(null)
    try {
      const r = await checkThenRun(kind, action, { [`${who}s`]: scoped }, verb)
      if (r) { setMsg({ bad: !r.done, t: r.text }); if (r.done) load() }
    } catch (e) { setMsg({ bad: true, t: e.message }) } finally { setBusy(false) }
  }

  async function upload(dry, list = files) {
    setBusy(true); setMsg(null)
    try {
      const r = await api.masterUpload(list, dry)
      setReport(r)
      if (!dry) { load(); setFiles([]) }
    } catch (e) { setMsg({ bad: true, t: e.message }) } finally { setBusy(false) }
  }

  return (
    <div className="page">
      <div className="head">
        <div>
          <p className="crumb">Assignment</p>
          <h1>{title}</h1>
          <p className="lead">{ABOUT[kind]}</p>
          <p className="fine">Rows are added and edited in the two tables behind this page:{' '}
            {tables.map((t, i) => (
              <span key={t.slug}>{i > 0 && ' and '}<Link to={`/masters/${t.slug}`}>{t.table}</Link></span>
            ))}.</p>
        </div>
      </div>

      <div className="toolbar">
        <input type="search" placeholder={`Search ${kind}, brand or product`} value={typed}
               aria-label="Search" onChange={(e) => setTyped(e.target.value)} />
        {data?.filters.map((f) => (
          <label key={f.name} className="filter"><span>{f.label}</span>
            <RefSelect slug={f.ref} keyBy={f.key === 'id' ? undefined : f.key} blank="All" includeInactive
                       value={filters[f.name] || null} onChange={(v) => setFilter(f.name, v)} /></label>
        ))}
        <div className="toolbar-actions">
          <input ref={pick} type="file" multiple accept=".xlsx,.xlsm,.xls,.csv" hidden
                 onChange={(e) => { const l = [...e.target.files]; e.target.value = ''
                                    if (l.length) { setFiles(l); upload(true, l) } }} />
          <button className="btn primary" onClick={() => setEditing((x) => !x)}>
            {kind === 'customer' ? 'Add Customer Territory Pg' : 'Add Emp/Terr-Pg Assignment'}</button>
          {kind === 'customer' && (
            <button className="btn" disabled={busy}
                    onClick={() => bulk('assign_all', scoped.length ? 'assign every HQ and product to this customer'
                                                                    : 'assign every HQ and product to every active customer')}>
              {scoped.length ? 'Assign all to this customer' : 'Assign all customers'}</button>
          )}
          <button className="btn danger" disabled={busy}
                  onClick={() => bulk('clean', scoped.length ? `delete every assignment of this ${kind}`
                                                             : `delete every ${kind} assignment`)}>
            {scoped.length ? `Delete this ${kind}'s assignments` : 'Delete all assignments'}</button>
          <button className="btn" disabled={busy} onClick={() => pick.current?.click()}>Upload Excel</button>
          <button className="btn" disabled={busy}
                  onClick={() => api.terrPgExport(kind, { ...filters, q }).catch((e) => setMsg({ bad: true, t: e.message }))}>
            Download Excel</button>
        </div>
      </div>

      {editing && <AssignPanel kind={kind} onDone={load} onClose={() => setEditing(false)} />}
      {msg && <div className={`alert ${msg.bad ? 'bad' : 'ok'} pre`}>{msg.t}</div>}
      {busy && <div className="alert">Reading the file…</div>}
      {report && (
        <div className="panel editor">
          <h3>{report.dry_run ? `Check of ${files.map((f) => f.name).join(', ')}` : 'Upload done'}</h3>
          <p className="fine">The workbook's {TABLES[kind].map((s) => s.toUpperCase()).join(' and ')} sheets
            fill the two tables behind this page. Any other sheet goes to its own table.</p>
          <UploadReport report={report} />
          <div className="actions">
            {report.dry_run && <button className="btn primary" disabled={busy} onClick={() => upload(false)}>Import</button>}
            <button className="btn" onClick={() => setReport(null)}>Close</button>
          </div>
        </div>
      )}

      <div className="listbar">
        <span className="muted">{data ? `${data.total.toLocaleString('en-IN')} row${data.total === 1 ? '' : 's'}` : 'Loading…'}</span>
      </div>
      <div className="scroll">
        <table className="grid-old">
          <thead><tr>
            <th className="sno">S.No</th>
            {data?.columns.map((c) => <th key={c}>{c}</th>)}
          </tr></thead>
          <tbody>
            {data?.rows.map((r, i) => (
              <tr key={i}>
                <td className="sno">{(page - 1) * SIZE + i + 1}</td>
                {r.map((v, ci) => (
                  <td key={ci}>{v === null || v === undefined
                    ? <span className="faint">—</span>
                    : ci === 0 ? <span className="primary-name">{v}</span> : String(v)}</td>
                ))}
              </tr>
            ))}
            {data && !data.rows.length && (
              <tr><td colSpan={data.columns.length + 1} className="empty">
                {q || Object.values(filters).some(Boolean)
                  ? 'Nothing matches. Clear the search or filters to see every row.'
                  : 'Nothing assigned yet. Upload the workbook with both assignment sheets.'}
              </td></tr>
            )}
          </tbody>
        </table>
      </div>
      {pages > 1 && (
        <div className="pager">
          <button className="btn sm" disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous</button>
          <span className="muted">Page {page} of {pages}</span>
          <button className="btn sm" disabled={page >= pages} onClick={() => setPage(page + 1)}>Next</button>
        </div>
      )}
    </div>
  )
}
