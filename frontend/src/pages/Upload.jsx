import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api.js'

const MONTHS = ['January','February','March','April','May','June','July','August',
  'September','October','November','December']

/** Month, Year and Mid Month, worked out the same way the server does, so the
 *  screen can say what will happen before anything is converted. */
function period(asOf, cutoff) {
  const d = new Date(asOf + 'T00:00:00')
  const early = d.getDate() <= cutoff
  let m = d.getMonth()
  if (early) m -= 1
  const wrapped = m < 0
  if (wrapped) m = 11
  return { month: MONTHS[m], year: d.getFullYear(), mid: early ? 'N' : 'Y', early, wrapped,
    day: d.getDate() }
}

export default function Upload() {
  const nav = useNavigate()
  const [dists, setDists] = useState([])
  const [distId, setDistId] = useState('')
  const [asOf, setAsOf] = useState(new Date().toISOString().slice(0, 10))
  const [cutoff, setCutoff] = useState(15)
  const [found, setFound] = useState(null)      // {token, source, files[], refused[]}
  const [sel, setSel] = useState(new Set())
  const [filter, setFilter] = useState('')
  const [progress, setProgress] = useState(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const pick = useRef(null)

  useEffect(() => {
    // No distributor is chosen for you. Whichever sorted first would otherwise
    // apply its own cut-off to a file somebody meant for another distributor,
    // and the result would look perfectly correct.
    api.distributors().then(setDists).catch((e) => setErr(e.message))
  }, [])

  const dist = dists.find((d) => String(d.id) === String(distId))
  function chooseDist(id) {
    setDistId(id)
    const d = dists.find((x) => String(x.id) === String(id))
    if (d) setCutoff(d.cutoff_day)
    setFound(null); setSel(new Set())
  }

  async function send(list) {
    const files = [...list]
    if (!files.length || !distId) return
    setErr(''); setBusy(true); setProgress(0)
    try {
      const r = await api.inspect(files, Number(distId), setProgress)
      setFound(r)
      // the distributor's own rule names its files; nothing else is ticked
      setSel(new Set(r.files.filter((f) => f.suggested).map((f) => f.name)))
    } catch (e) { setErr(e.message) } finally { setBusy(false); setProgress(null) }
  }

  async function convert() {
    setErr(''); setBusy(true)
    try {
      const r = await api.commit(found.token, {
        distributor_id: Number(distId), as_of: asOf, cutoff_day: Number(cutoff),
        files: [...sel], source: found.source,
        who: sessionStorage.getItem('ds.who') || 'user',
      })
      nav(`/batches/${r.batch_id}`)
    } catch (e) { setErr(e.message); setBusy(false) }
  }

  const p = period(asOf, Number(cutoff) || 15)
  const shown = (found?.files || []).filter((f) =>
    !filter.trim() || f.name.toLowerCase().includes(filter.trim().toLowerCase()))
  const chosen = (found?.files || []).filter((f) => sel.has(f.name) && !f.error)
  const rows = chosen.reduce((a, f) => a + f.rows, 0)

  return (
    <div className="page">
      <h1>Convert</h1>
      <p className="lead">Drop the zip a distributor sends — or loose workbooks — pick the files
        that belong to this run, and the rows are stored and given back as the standard sheet.</p>
      {err && <div className="alert bad">{err}</div>}

      <section className="panel">
        <h2>1 · Distributor and rules</h2>
        <div className="dists">
          {dists.map((d) => (
            <button key={d.id} className={`dist ${String(d.id) === String(distId) ? 'on' : ''}`}
                    onClick={() => chooseDist(d.id)}>
              <b>{d.name}</b><small>{d.note}</small></button>
          ))}
        </div>
        {!dist && <div className="alert warn" style={{ marginTop: 14 }}>
          Choose the distributor these files came from. Each one is read under its own rules,
          so nothing is chosen for you.</div>}
        {dist && <><div className="grid3">
          <label>Treat as uploaded on
            <input type="date" value={asOf} onChange={(e) => setAsOf(e.target.value)} /></label>
          <label>Month cut-off day
            <input type="number" min="1" max="28" value={cutoff}
                   onChange={(e) => setCutoff(e.target.value)} /></label>
          <label>Invoice No
            <input value={dist?.invoice_mode === 'file' ? 'Read from the file'
              : 'INV - 1, INV - 2 …'} readOnly /></label>
        </div>
        <div className="alert info">Day {p.day} is {p.early ? 'on or before' : 'after'} the
          {' '}{cutoff}th, so <b>Month = {p.month}</b>, <b>Year = {p.year}</b> and
          {' '}<b>Mid Month = {p.mid}</b> on every row.</div>
        {p.wrapped && <div className="alert warn"><b>Worth a look before you convert.</b> The month
          steps back to December, but the rule says the year is the current year, so these rows
          will read December {p.year} — not December {p.year - 1}.</div>}
        </>}
      </section>

      <section className="panel">
        <h2>2 · The files</h2>
        <div className={`drop ${dist ? '' : 'disabled'}`} tabIndex={0} role="button"
             aria-disabled={!dist} onClick={() => dist && pick.current?.click()}
             onKeyDown={(e) => { if (dist && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); pick.current?.click() } }}
             onDragOver={(e) => e.preventDefault()}
             onDrop={(e) => { e.preventDefault(); if (dist) send(e.dataTransfer.files) }}>
          <b>{dist ? 'Drop a .zip, or .xlsx files, here — or choose them'
            : 'Choose a distributor above first'}</b>
          <span>A zip is opened and every workbook inside is listed for you to pick from.</span>
          <input ref={pick} type="file" multiple hidden accept=".zip,.xlsx,.xls,.xlsm"
                 onChange={(e) => { send(e.target.files); e.target.value = '' }} />
        </div>
        {progress != null && (
          <div className="prog"><div className="bar"><i style={{ width: `${Math.round(progress * 100)}%` }} /></div>
            <span>{progress < 1 ? `Uploading — ${Math.round(progress * 100)}%` : 'Reading the workbooks…'}</span></div>
        )}
        {found?.refused?.length > 0 && (
          <div className="alert warn">{found.refused.join(', ')} ignored — this reads Excel
            workbooks and zips of them, not PDFs.</div>
        )}

        {found && (
          <>
            <div className="picker">
              <input placeholder="Filter by name, e.g. PW" value={filter}
                     onChange={(e) => setFilter(e.target.value)} />
              <button className="btn sm" onClick={() => setSel(new Set([...sel,
                ...shown.filter((f) => !f.error).map((f) => f.name)]))}>Select all shown</button>
              <button className="btn sm" onClick={() => setSel(new Set())}>Select none</button>
              <span className="fine">{chosen.length} of {found.files.length} selected · {rows} rows</span>
            </div>
            <ul className="files">
              {shown.map((f) => (
                <li key={f.name} className={sel.has(f.name) ? '' : 'off'}>
                  <input type="checkbox" checked={sel.has(f.name)} disabled={!!f.error}
                         aria-label={`Convert ${f.name}`}
                         onChange={(e) => {
                           const n = new Set(sel)
                           e.target.checked ? n.add(f.name) : n.delete(f.name)
                           setSel(n)
                         }} />
                  <span className="nm">{f.name}</span>
                  {f.error ? <span className="chip bad">could not read</span>
                    : <span className="chip ok">{f.rows} rows</span>}
                  <span className="meta">{f.error || f.layout}</span>
                </li>
              ))}
              {!shown.length && <li className="fine">Nothing matches that filter.</li>}
            </ul>
            <div className="actions">
              <button className="btn primary" disabled={busy || rows === 0} onClick={convert}>
                {busy ? 'Converting…' : `Convert ${chosen.length} file${chosen.length === 1 ? '' : 's'}`}
              </button>
              <span className="fine">Nothing is ticked by itself except the files this
                distributor's rule names.</span>
            </div>
          </>
        )}
      </section>
    </div>
  )
}
