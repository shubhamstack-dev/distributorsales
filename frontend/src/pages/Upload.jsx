import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api.js'

const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August',
  'September', 'October', 'November', 'December']
const th = (n) => (n % 100 >= 11 && n % 100 <= 13) ? `${n}th`
  : `${n}${{ 1: 'st', 2: 'nd', 3: 'rd' }[n % 10] || 'th'}`

/** Month, Year and Mid Month, worked out the same way the server does, so the
 *  screen says what every row will carry before anything is converted. Mid
 *  Month can have its own cut-off (Pharmachem: month on the 10th, Mid on the 11th). */
function period(asOf, cutoff, midCutoff) {
  const d = new Date(asOf + 'T00:00:00')
  const day = d.getDate()
  const early = day <= cutoff
  let m = d.getMonth()
  if (early) m -= 1
  const wrapped = m < 0
  if (wrapped) m = 11
  const midEarly = day <= (midCutoff || cutoff)
  return { month: MONTHS[m], year: d.getFullYear(), mid: midEarly ? 'N' : 'Y', early, midEarly,
    wrapped, day }
}

export default function Upload() {
  const nav = useNavigate()
  const [dists, setDists] = useState([])
  const [distId, setDistId] = useState('')
  const [asOf, setAsOf] = useState(new Date().toISOString().slice(0, 10))
  const [cutoff, setCutoff] = useState(15)
  const [midCutoff, setMidCutoff] = useState(15)
  const [found, setFound] = useState(null)      // {token, source, files[], refused[]}
  const [sel, setSel] = useState(new Set())
  const [filter, setFilter] = useState('')
  const [progress, setProgress] = useState(null)
  const [busy, setBusy] = useState(false)
  const [over, setOver] = useState(false)
  const [err, setErr] = useState('')
  const pick = useRef(null)
  const [lists, setLists] = useState(null)
  const [listMsg, setListMsg] = useState(null)
  const custRef = useRef(null)
  const prodRef = useRef(null)

  useEffect(() => {
    // No distributor is chosen for you: whichever sorted first would apply its
    // own rules to files meant for another, and the result would look right.
    api.distributors().then((d) => setDists(d.filter((x) => x.active))).catch((e) => setErr(e.message))
  }, [])

  const dist = dists.find((d) => String(d.id) === String(distId))
  const anyFile = !!dist?.select_any
  const canPick = (f) => anyFile || (f.selectable ?? !f.error)
  function chooseDist(id) {
    setDistId(id)
    const d = dists.find((x) => String(x.id) === String(id))
    if (d) { setCutoff(d.cutoff_day); setMidCutoff(d.mid_cutoff_day || d.cutoff_day) }
    setFound(null); setSel(new Set()); setLists(null); setListMsg(null)
    if (d) api.nameLists(d.id).then(setLists).catch(() => setLists(null))
  }

  async function sendList(kind, file) {
    if (!file || !distId) return
    setListMsg(null)
    try {
      const r = await api.uploadNames(Number(distId), kind, file)
      setLists(r)
      setListMsg({ t: `${r.kept} ${kind} names saved from ${file.name}` +
        (r.read !== r.kept ? ` (${r.read - r.kept} duplicates ignored).` : '.') })
    } catch (e) { setListMsg({ bad: true, t: e.message }) }
  }

  async function send(list) {
    const files = [...list]
    if (!files.length || !distId) return
    setErr(''); setBusy(true); setProgress(0)
    try {
      const r = await api.inspect(files, Number(distId), setProgress)
      setFound(r)
      setSel(new Set(r.files.filter((f) => f.suggested).map((f) => f.name)))
    } catch (e) { setErr(e.message) } finally { setBusy(false); setProgress(null) }
  }

  async function convert() {
    setErr(''); setBusy(true)
    try {
      const r = await api.commit(found.token, {
        distributor_id: Number(distId), as_of: asOf, cutoff_day: Number(cutoff),
        mid_cutoff_day: Number(midCutoff), files: chosen.map((f) => f.name), source: found.source,
        who: sessionStorage.getItem('ds.who') || 'user',
      })
      nav(`/batches/${r.batch_id}`)
    } catch (e) { setErr(e.message); setBusy(false) }
  }

  const p = period(asOf, Number(cutoff) || 15, Number(midCutoff) || Number(cutoff) || 15)
  const shown = (found?.files || []).filter((f) =>
    !filter.trim() || f.name.toLowerCase().includes(filter.trim().toLowerCase()))
  const chosen = (found?.files || []).filter((f) => sel.has(f.name) && canPick(f))
  const rows = chosen.reduce((a, f) => a + f.rows, 0)
  const canConvert = anyFile ? chosen.length > 0 : rows > 0
  const sheetRule = dist && (dist.sales_sheet || dist.return_sheet)

  return (
    <div className="page">
      <h1>Convert</h1>
      <p className="lead">Drop the zip a distributor sends, choose the files that belong to this run,
        and the rows are kept as a batch and given back as the standard twelve-column sheet.</p>
      {err && <div className="alert bad">{err}</div>}

      <section className="panel">
        <div className="panel-head"><span className="step">1</span>
          <h2>Who sent the files</h2><p>Each distributor's files are read under its own rules.</p></div>
        <div className="dists">
          {dists.map((d) => (
            <button key={d.id} className={`dist ${String(d.id) === String(distId) ? 'on' : ''}`}
                    aria-pressed={String(d.id) === String(distId)} onClick={() => chooseDist(d.id)}>
              <b>{d.name}</b><small>{d.note}</small></button>
          ))}
        </div>

        {dist && <>
          <div className="readout" aria-live="polite">
            <div><div className="n">{p.month}</div><div className="l">Month</div>
              <div className="why">Day {p.day} is {p.early ? 'on or before' : 'after'} the {th(Number(cutoff))}</div></div>
            <div><div className="n">{p.year}</div><div className="l">Year</div>
              <div className="why">The current year</div></div>
            <div><div className="n sun">{p.mid}</div><div className="l">Mid Month</div>
              <div className="why">Day {p.day} is {p.midEarly ? 'on or before' : 'after'} the {th(Number(midCutoff))}</div></div>
          </div>
          {p.wrapped && <div className="alert warn"><b>Check before you convert.</b> The month steps
            back to December, but the rule says the year is the current year, so rows will read
            December {p.year}, not December {p.year - 1}.</div>}
          <div className="grid3">
            <label>Treat as uploaded on
              <input type="date" value={asOf} onChange={(e) => setAsOf(e.target.value)} /></label>
            <label>Month steps back up to day
              <input type="number" min="1" max="28" value={cutoff}
                     onChange={(e) => setCutoff(e.target.value)} /></label>
            <label>Mid Month is N up to day
              <input type="number" min="1" max="28" value={midCutoff}
                     onChange={(e) => setMidCutoff(e.target.value)} /></label>
            <label>Invoice No
              <input value={dist.invoice_mode === 'file' ? 'Read from the file' : 'INV - 1, INV - 2 …'} readOnly /></label>
          </div>
          {sheetRule && <div className="alert info">From each workbook, <b>sheet {dist.sales_sheet}</b> is read
            as sales{dist.return_sheet ? <> and <b>sheet {dist.return_sheet}</b> as sales returns, with
            quantity, free, B.Amount and Amount negative</> : null}. Other sheets are left alone.</div>}
        </>}
      </section>

      {dist && (
        <section className="panel">
          <div className="panel-head"><h2>Reference names</h2>
            <p>Optional. Names that match a list, ignoring case, spaces and special characters, are
              replaced with the list's spelling.</p></div>
          {listMsg && <div className={`alert ${listMsg.bad ? 'bad' : 'ok'}`}>{listMsg.t}</div>}
          <div className="lists">
            {[['customer', 'Customer names', custRef], ['product', 'Product names', prodRef]].map(([k, label, ref]) => (
              <div key={k}>
                <h3>{label}</h3>
                <p className="fine">{lists?.[k]?.count
                  ? `${lists[k].count} names, from ${lists[k].file || 'an upload'}`
                  : 'No list yet, so names are kept as extracted.'}</p>
                <button className="btn sm" onClick={() => ref.current?.click()}>
                  {lists?.[k]?.count ? 'Replace list' : 'Upload list'}</button>
                <input ref={ref} type="file" hidden accept=".xlsx,.xlsm"
                       onChange={(e) => { sendList(k, e.target.files[0]); e.target.value = '' }} />
              </div>
            ))}
          </div>
        </section>
      )}

      <section className="panel">
        <div className="panel-head"><span className="step">2</span><h2>The files</h2>
          <p>A zip is opened and every workbook and PDF inside it is listed.</p></div>
        <div className={`drop ${dist ? '' : 'disabled'} ${over ? 'over' : ''}`} tabIndex={0} role="button"
             aria-disabled={!dist} onClick={() => dist && pick.current?.click()}
             onKeyDown={(e) => { if (dist && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); pick.current?.click() } }}
             onDragOver={(e) => { e.preventDefault(); setOver(true) }}
             onDragLeave={() => setOver(false)}
             onDrop={(e) => { e.preventDefault(); setOver(false); if (dist) send(e.dataTransfer.files) }}>
          <b>{dist ? 'Drop a .zip or .xlsx / .pdf files here, or click to choose'
            : 'Choose who sent the files first'}</b>
          {dist && <span>{anyFile
            ? `For ${dist.name}, drop both zips together. Every file extracted is listed and can be ticked; the BATCHWISE PDFs are ticked to begin with.`
            : `Only the files ${dist.name}'s rule names are ticked to begin with.`}</span>}
          <input ref={pick} type="file" multiple hidden
                 accept={anyFile ? undefined : '.zip,.xlsx,.xls,.xlsm,.pdf'}
                 onChange={(e) => { send(e.target.files); e.target.value = '' }} />
        </div>
        {progress != null && (
          <div className="prog"><div className="bar"><i style={{ width: `${Math.round(progress * 100)}%` }} /></div>
            <span>{progress < 1 ? `Uploading, ${Math.round(progress * 100)}%` : 'Reading the files…'}</span></div>
        )}
        {found?.refused?.length > 0 && (
          <div className="alert warn">{found.refused.join(', ')} ignored. This reads Excel
            workbooks, PDFs and zips of them.</div>
        )}
        {found && dist?.pick_pattern && !found.files.some((f) => f.suggested) && (
          <div className="alert warn">Nothing in this upload matches {dist.name}'s rule, so nothing is
            ticked. Check it is the right zip, or tick the files by hand.</div>
        )}

        {found && (
          <>
            <div className="picker">
              <input placeholder="Filter by file name" value={filter}
                     onChange={(e) => setFilter(e.target.value)} aria-label="Filter files" />
              <button className="btn sm" onClick={() => setSel(new Set([...sel,
                ...shown.filter(canPick).map((f) => f.name)]))}>Select all shown</button>
              <button className="btn sm" onClick={() => setSel(new Set())}>Clear</button>
              <span className="fine">{chosen.length} of {found.files.length} chosen, {rows.toLocaleString('en-IN')} rows</span>
            </div>
            <ul className="files">
              {shown.map((f) => (
                <li key={f.name} className={sel.has(f.name) ? '' : 'off'}>
                  <input type="checkbox" checked={sel.has(f.name)} disabled={!canPick(f)}
                         aria-label={`Convert ${f.name}`}
                         onChange={(e) => {
                           const n = new Set(sel)
                           e.target.checked ? n.add(f.name) : n.delete(f.name)
                           setSel(n)
                         }} />
                  <span className="nm">{f.name}</span>
                  {f.error ? <span className="chip bad">{anyFile ? 'no rows found' : 'could not read'}</span>
                    : <span className="chip ok">{f.rows} rows</span>}
                  <span className="meta">{f.error || f.layout}</span>
                </li>
              ))}
              {!shown.length && <li className="fine">No file matches that filter.</li>}
            </ul>
          </>
        )}
      </section>

      {found && (
        <section className="panel">
          <div className="panel-head"><span className="step">3</span><h2>Convert</h2>
            <p>The rows are kept as a batch you can reopen and download again.</p></div>
          <div className="actions" style={{ marginTop: 0 }}>
            <button className="btn primary" disabled={busy || !canConvert} onClick={convert}>
              {busy ? 'Converting…' : `Convert ${chosen.length} file${chosen.length === 1 ? '' : 's'}`}
            </button>
            <span className="fine">{p.month} {p.year}, Mid Month {p.mid}, on every row.</span>
          </div>
        </section>
      )}
    </div>
  )
}
