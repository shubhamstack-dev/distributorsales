import { useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../../api.js'
import RefSelect, { forgetOptions } from './RefSelect.jsx'
import CurrencyTool from './CurrencyTool.jsx'
import UploadReport from './UploadReport.jsx'

const SIZE = 50

// Where a structural master sits, shown above its table so it is clear what
// each row has to be attached to.
const PATHS = {
  zone: ['Country', 'Zone'], headquarter: ['Zone', 'Headquarter'],
  territory: ['Zone', 'Headquarter', 'Territory'],
  brand: ['Product group', 'Brand'], sku: ['Product group', 'Brand', 'Product'],
  customer: ['Zone', 'HQ', 'Territory', 'Customer'],
  product_reporting_sku: ['Reporting line (P1 / P2 / X)', 'SKU'],
  customer_assignment: ['Year', 'Customer', 'Territory + Team', 'Product group', 'SKU'],
  employee_assignment: ['Year', 'Employee', 'Territory', 'Product group', 'SKU'],
}

/** "Territories" -> "territory", "Team › Product groups" -> "product group", "SKUs" -> "SKU". */
function singular(title) {
  let t = title.split('› ').pop().replace(/\s*\(.*\)/, '')
  if (/ies$/.test(t)) t = t.replace(/ies$/, 'y')
  else if (/[^s]s$/.test(t)) t = t.slice(0, -1)
  return /^[A-Z]{2,}/.test(t) ? t : t.charAt(0).toLowerCase() + t.slice(1)
}

const editable = (spec) => spec.fields.filter((f) => !f.derived)

function blankForm(spec, filters) {
  const o = {}
  for (const f of editable(spec)) {
    if (f.type === 'bool') o[f.name] = f.default === null || f.default === undefined ? 0 : f.default
    else if (f.type === 'ref' && filters[f.name]) o[f.name] = Number(filters[f.name])
    else if (f.type === 'ref' || f.type === 'aliases') o[f.name] = ''   // a ref default is resolved by the server
    else o[f.name] = f.default ?? ''
  }
  return o
}

function toBody(spec, form, skip = [], editing = false) {
  const b = {}
  for (const f of editable(spec)) {
    if (skip.includes(f.name) || (editing && f.create_only)) continue
    const v = form[f.name]
    b[f.name] = v === '' || v === undefined ? null : v
  }
  return b
}

function Cell({ f, row }) {
  const v = row[f.name]
  if (f.type === 'aliases') {
    if (!v?.length) return <span className="faint">None</span>
    return <span title={v.join('\n')}>{v[0]}{v.length > 1 && <span className="aliascount"> and {v.length - 1} more</span>}</span>
  }
  if (f.type === 'ref') return v ? (row[`${f.name}__label`] || `#${v}`) : <span className="faint">—</span>
  if (f.type === 'bool') return v ? <span className="chip ok">Yes</span> : <span className="chip mute">No</span>
  if (f.name === 'flag') return <span className={`chip flag-${v}`}>{v === 'X' ? 'X · Others' : v}</span>
  if (v === null || v === undefined || v === '') return <span className="faint">—</span>
  if (f.name === 'id') return <span className="num">{v}</span>
  if (f.type === 'decimal') return <span className="mono">{Number(v).toLocaleString('en-IN', { maximumFractionDigits: 6 })}</span>
  if (f.type === 'code' || f.type === 'date' || f.type === 'int') return <span className="mono">{v}</span>
  return String(v)
}

/** One field in the add / edit form. */
function Input({ f, form, set, spec, row }) {
  const id = `f-${f.name}`
  const v = form[f.name] ?? ''
  let control
  if (f.type === 'aliases') {
    const n = String(v).split('\n').filter((x) => x.trim()).length
    return (
      <label htmlFor={id} className="wide">
        <span>{f.label} <span className="faint">({n} of {f.count})</span></span>
        <textarea id={id} value={v} rows={6} placeholder="One name per line"
                  onChange={(e) => set(f.name, e.target.value)} />
        {f.help && <small className="fine">{f.help}</small>}
      </label>
    )
  }
  if (f.create_only && row) {
    return (
      <label htmlFor={id}><span>{f.label}</span>
        <input id={id} value={v} readOnly className="num" />
        <small className="fine">Set when the row was added; other tables point at it.</small></label>
    )
  }
  if (f.type === 'ref') {
    const n = f.narrow
    const from = n ? spec.fields.find((x) => x.name === n.from) : null
    control = (
      <RefSelect id={id} slug={f.ref} value={v || null} required={f.required}
                 blank={f.required ? 'Choose…' : 'None'}
                 params={n ? { [n.param]: form[n.from] } : {}}
                 waitingFor={n && !form[n.from] ? from?.label.toLowerCase() : null}
                 currentLabel={row?.[`${f.name}__label`]} keyBy={f.key}
                 onChange={(x) => set(f.name, x)} />
    )
  } else if (f.type === 'bool') {
    return (
      <label className="check" htmlFor={id}>
        <input id={id} type="checkbox" checked={!!v} onChange={(e) => set(f.name, e.target.checked ? 1 : 0)} />
        <span>{f.label}{f.help && <small>{f.help}</small>}</span>
      </label>
    )
  } else if (f.type === 'select') {
    control = (
      <select id={id} value={v} required={f.required} onChange={(e) => set(f.name, e.target.value)}>
        <option value="">Choose…</option>
        {f.options.map((o) => <option key={o} value={o}>{o}</option>)}
      </select>
    )
  } else {
    const type = f.type === 'date' ? 'date' : (f.type === 'int' || f.type === 'decimal') ? 'number' : 'text'
    control = (
      <>
        <input id={id} type={type} value={v} required={f.required}
               step={f.type === 'decimal' ? 'any' : undefined}
               list={f.suggest ? `${id}-list` : undefined}
               className={f.type === 'code' ? 'upper' : undefined}
               onChange={(e) => set(f.name, e.target.value)} />
        {f.suggest && <datalist id={`${id}-list`}>{f.suggest.map((s) => <option key={s} value={s} />)}</datalist>}
      </>
    )
  }
  return (
    <label htmlFor={id}>
      <span>{f.label}{f.required && <b className="req" aria-label="required"> *</b>}</span>
      {control}
      {f.help && <small className="fine">{f.help}</small>}
    </label>
  )
}

export default function MasterPage({ spec }) {
  const refFields = spec.fields.filter((f) => f.type === 'ref')
  const hasYear = refFields.some((f) => f.name === 'year_id')
  const hasActive = spec.fields.some((f) => f.name === 'active')
  const filterFields = useMemo(() => [...refFields]
    .sort((a, b) => (b.name === 'year_id') - (a.name === 'year_id')).slice(0, 4),
  [spec.slug]) // eslint-disable-line react-hooks/exhaustive-deps

  const [filters, setFilters] = useState({})
  const [ready, setReady] = useState(!hasYear)
  const [q, setQ] = useState('')
  const [page, setPage] = useState(1)
  const [data, setData] = useState({ rows: [], total: 0 })
  const [sel, setSel] = useState(new Set())
  const [mode, setMode] = useState(null)          // null | 'add' | 'edit' | 'bulk' | 'copy'
  const [editing, setEditing] = useState(null)
  const [form, setForm] = useState({})
  const [msg, setMsg] = useState(null)
  const [busy, setBusy] = useState(false)
  const [upFiles, setUpFiles] = useState([])
  const [report, setReport] = useState(null)
  const filePick = useRef(null)

  // year-bound screens open on the current year, which is what people edit
  useEffect(() => {
    if (!hasYear) return
    api.masterList('year', { is_current: 1, size: 1 })
      .then((r) => { if (r.rows[0]) setFilters({ year_id: r.rows[0].id }) })
      .finally(() => setReady(true))
  }, [hasYear])

  function load() {
    if (!ready) return
    api.masterList(spec.slug, { ...filters, q, page, size: SIZE })
      .then((r) => { setData(r); setSel(new Set()) })
      .catch((e) => setMsg({ bad: true, t: e.message }))
  }
  useEffect(load, [ready, filters, q, page]) // eslint-disable-line react-hooks/exhaustive-deps

  const say = (t, bad = false) => setMsg({ t, bad })
  const set = (name, value) => setForm((f) => {
    const next = { ...f, [name]: value }
    // a field that narrows another clears it, so an SKU from the old group cannot stay chosen
    for (const g of spec.fields) if (g.narrow?.from === name && f[name] !== value) next[g.name] = null
    return next
  })

  function openAdd() { setEditing(null); setForm(blankForm(spec, filters)); setMode('add'); setMsg(null) }
  function openEdit(row) {
    const f = {}
    for (const x of editable(spec)) {
      f[x.name] = x.type === 'aliases' ? (row[x.name] || []).join('\n') : (row[x.name] ?? '')
    }
    setEditing(row); setForm(f); setMode('edit'); setMsg(null)
  }
  function openBulk() { setForm(blankForm(spec, filters)); setMode('bulk'); setMsg(null) }
  function openCopy() { setForm({ to_year_id: filters.year_id || null }); setMode('copy'); setMsg(null) }
  const close = () => { setMode(null); setEditing(null); setReport(null) }

  async function upload(dry, list = upFiles) {
    if (!list.length) return
    setBusy(true); setMsg(null)
    try {
      const r = await api.masterUpload(list, dry, spec.slug)
      setReport(r); setMode('upload')
      if (!dry) { setUpFiles([]); forgetOptions(); load() }
    } catch (e) { say(e.message, true) } finally { setBusy(false) }
  }

  async function run(fn) {
    setBusy(true); setMsg(null)
    try { await fn() } catch (e) { say(e.message, true) } finally { setBusy(false) }
  }

  const save = (e) => { e.preventDefault(); run(async () => {
    if (mode === 'edit') {
      await api.masterUpdate(spec.slug, editing.id, toBody(spec, form, [], true))
      forgetOptions(); close(); say('Changes saved.'); load()
    } else {
      const r = await api.masterCreate(spec.slug, toBody(spec, form))
      forgetOptions(); load()
      // stay open for the next one, keeping what is usually shared between rows
      setForm((f) => {
        const n = { ...f }
        for (const x of editable(spec)) if (['text', 'code', 'int', 'decimal'].includes(x.type)) n[x.name] = x.default ?? ''
        return n
      })
      say(`Added ${r.__label?.startsWith('#') ? 'the row' : r.__label}. Add the next one, or close.`)
    }
  }) }

  const bulk = (e) => { e.preventDefault(); run(async () => {
    const r = await api.masterBulk(spec.slug, { ...toBody(spec, form, ['sku_id']), brand_id: form.brand_id || null })
    forgetOptions(); load()
    say(`Assigned ${r.created} SKU${r.created === 1 ? '' : 's'}` +
        (r.skipped ? `; ${r.skipped} ${r.skipped === 1 ? 'was' : 'were'} already assigned and left as they were.` : '.'))
  }) }

  const copy = (e) => { e.preventDefault(); run(async () => {
    const r = await api.masterCopyYear(spec.slug, form)
    forgetOptions(); load()
    say(`Copied ${r.created} row${r.created === 1 ? '' : 's'}.` +
        (r.skipped ? ` ${r.skipped} skipped: ${r.reasons.join(' ')}` : ''), r.created === 0 && r.skipped > 0)
  }) }

  const remove = (row) => {
    if (!window.confirm(`Delete ${row.__label?.startsWith('#') ? 'this row' : row.__label}?`)) return
    run(async () => { await api.masterDelete(spec.slug, row.id); forgetOptions(); say('Deleted.'); load() })
  }
  const removeMany = () => {
    if (!window.confirm(`Delete ${sel.size} selected row${sel.size === 1 ? '' : 's'}?`)) return
    run(async () => {
      await api.masterDeleteMany(spec.slug, [...sel]); forgetOptions()
      say(`Deleted ${sel.size} row${sel.size === 1 ? '' : 's'}.`); load()
    })
  }

  const cols = spec.fields.filter((f) => f.in_list && !(f.derived && hasYear && f.name !== 'year_id'))
  const pages = Math.max(1, Math.ceil(data.total / SIZE))
  const allOn = data.rows.length > 0 && data.rows.every((r) => sel.has(r.id))
  const path = PATHS[spec.slug]
  const setFilter = (k, v) => { setPage(1); setFilters((f) => ({ ...f, [k]: v ?? '' })) }

  return (
    <div className="page master">
      <div className="head">
        <div>
          <h1>{spec.title}</h1>
          {spec.table === spec.table.toUpperCase() && <div className="tablename">Table {spec.table}</div>}
          {spec.description && <p className="lead">{spec.description}</p>}
          {path && (
            <ol className="path" aria-label="Where this sits">
              {path.map((p, i) => <li key={p} className={i === path.length - 1 ? 'here' : ''}>{p}</li>)}
            </ol>
          )}
        </div>
      </div>

      {spec.slug === 'currency_rate' && <CurrencyTool key={data.total} />}

      <div className="toolbar">
        {spec.searchable && (
          <input type="search" placeholder="Search" value={q}
                 onChange={(e) => { setPage(1); setQ(e.target.value) }} aria-label="Search" />
        )}
        {filterFields.map((f) => (
          <label key={f.name} className="filter">
            <span>{f.label}</span>
            <RefSelect slug={f.ref} value={filters[f.name] || null} blank="All" keyBy={f.key}
                       includeInactive onChange={(v) => setFilter(f.name, v)} />
          </label>
        ))}
        {hasActive && (
          <label className="filter"><span>Status</span>
            <select value={filters.active ?? ''} onChange={(e) => setFilter('active', e.target.value)}>
              <option value="">All</option><option value="1">Active</option><option value="0">Inactive</option>
            </select></label>
        )}
        <div className="toolbar-actions">
          <button className="btn" onClick={() => filePick.current?.click()} disabled={busy}>Upload Excel</button>
          <input ref={filePick} type="file" hidden accept=".xlsx,.xlsm,.csv"
                 onChange={(e) => { const l = [...e.target.files]; e.target.value = ''; setUpFiles(l); upload(true, l) }} />
          <button className="btn" onClick={() => api.masterExport(spec.slug).catch((e) => say(e.message, true))}>
            Download Excel</button>
          {spec.year_bound && <button className="btn" onClick={openCopy}>Copy from a year</button>}
          {spec.bulk_by_sku && <button className="btn" onClick={openBulk}>Assign a whole group</button>}
          <button className="btn primary" onClick={openAdd}>Add {singular(spec.title)}</button>
        </div>
      </div>

      {msg && <div className={`alert ${msg.bad ? 'bad' : 'ok'}`} role="status">{msg.t}</div>}

      {(mode === 'add' || mode === 'edit') && (
        <form className="panel editor" onSubmit={save}>
          <h3>{mode === 'edit' ? `Edit ${editing.__label?.startsWith('#') ? 'row' : editing.__label}` : `Add to ${spec.title}`}</h3>
          <div className="grid2">
            {editable(spec).map((f) => <Input key={f.name} f={f} form={form} set={set} spec={spec} row={editing} />)}
          </div>
          <div className="actions">
            <button className="btn primary" disabled={busy}>{mode === 'edit' ? 'Save changes' : 'Add'}</button>
            <button type="button" className="btn" onClick={close}>Close</button>
          </div>
        </form>
      )}

      {mode === 'upload' && report && (
        <section className="panel editor">
          <h3>{report.dry_run ? `Check of ${upFiles.map((f) => f.name).join(', ')}` : 'Upload done'}</h3>
          <UploadReport report={report} />
          <div className="actions">
            {report.dry_run && <button className="btn primary" disabled={busy} onClick={() => upload(false)}>Import</button>}
            <button type="button" className="btn" onClick={close}>Close</button>
          </div>
        </section>
      )}

      {mode === 'bulk' && (
        <form className="panel editor" onSubmit={bulk}>
          <h3>Assign every product of a group</h3>
          <p className="fine">One row is added per active product. Products already assigned are left as they are.
            Narrow it to one brand if only part of the group applies.</p>
          <div className="grid2">
            {editable(spec).filter((f) => f.name !== 'sku_id')
              .map((f) => <Input key={f.name} f={f} form={form} set={set} spec={spec} />)}
            <label htmlFor="f-brand"><span>Only this brand</span>
              <RefSelect id="f-brand" slug="brand" value={form.brand_id || null} blank="Every brand"
                         params={{ product_group_id: form.product_group_id }}
                         waitingFor={!form.product_group_id ? 'product group' : null}
                         onChange={(v) => setForm((f) => ({ ...f, brand_id: v }))} /></label>
          </div>
          <div className="actions">
            <button className="btn primary" disabled={busy}>Assign products</button>
            <button type="button" className="btn" onClick={close}>Close</button>
          </div>
        </form>
      )}

      {mode === 'copy' && (
        <form className="panel editor" onSubmit={copy}>
          <h3>Start a year from another</h3>
          <p className="fine">Copies every row of one year into another. Rows already there, or that
            no longer hold in the new year, are skipped and the reason is shown.
            {spec.slug === 'product_reporting' && ' Each line brings its SKUs with it.'}</p>
          <div className="grid2">
            <label><span>From year</span>
              <RefSelect slug="year" value={form.from_year_id || null} includeInactive
                         onChange={(v) => setForm((f) => ({ ...f, from_year_id: v }))} /></label>
            <label><span>Into year</span>
              <RefSelect slug="year" value={form.to_year_id || null}
                         onChange={(v) => setForm((f) => ({ ...f, to_year_id: v }))} /></label>
          </div>
          <div className="actions">
            <button className="btn primary" disabled={busy || !form.from_year_id || !form.to_year_id}>Copy rows</button>
            <button type="button" className="btn" onClick={close}>Close</button>
          </div>
        </form>
      )}

      <div className="listbar">
        <span className="muted">{data.total.toLocaleString('en-IN')} row{data.total === 1 ? '' : 's'}</span>
        {sel.size > 0 && <button className="btn sm danger" onClick={removeMany} disabled={busy}>Delete {sel.size} selected</button>}
      </div>
      <div className="scroll">
        <table>
          <thead><tr>
            <th className="sel"><input type="checkbox" aria-label="Select all on this page" checked={allOn}
              onChange={() => setSel(allOn ? new Set() : new Set(data.rows.map((r) => r.id)))} /></th>
            {cols.map((f) => <th key={f.name} className={f.type === 'decimal' ? 'r' : ''}>{f.label}</th>)}
            <th />
          </tr></thead>
          <tbody>
            {data.rows.map((row) => (
              <tr key={row.id} className={row.active === 0 ? 'off' : ''}>
                <td className="sel"><input type="checkbox" aria-label="Select row" checked={sel.has(row.id)}
                  onChange={() => setSel((s) => { const n = new Set(s); n.has(row.id) ? n.delete(row.id) : n.add(row.id); return n })} /></td>
                {cols.map((f) => <td key={f.name} className={f.type === 'decimal' ? 'r' : ''}><Cell f={f} row={row} /></td>)}
                <td className="row-actions"><div>
                  <button className="btn sm" onClick={() => openEdit(row)}>Edit</button>
                  <button className="btn sm danger" onClick={() => remove(row)}>Delete</button>
                </div></td>
              </tr>
            ))}
            {!data.rows.length && (
              <tr><td colSpan={cols.length + 2} className="empty">
                {q || Object.values(filters).some(Boolean)
                  ? 'Nothing matches. Clear the search or filters to see every row.'
                  : <>Nothing here yet. <button className="linkish" onClick={openAdd}>Add the first one</button>.</>}
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
