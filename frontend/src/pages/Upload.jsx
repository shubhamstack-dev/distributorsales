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
  const [lists, setLists] = useState(null)       // {customer:{count,file,...}, product:{...}}
  const [listMsg, setListMsg] = useState(null)
  const custRef = useRef(null)
  const prodRef = useRef(null)

  useEffect(() => {
    // No distributor is chosen for you. Whichever sorted first would otherwise
    // apply its own cut-off to a file somebody meant for another distributor,
    // and the result would look perfectly correct.
    api.distributors().then(setDists).catch((e) => setErr(e.message))
  }, [])

  const dist = dists.find((d) => String(d.id) === String(distId))
  // Gunjeshwari (select_any): every file extracted from the zip can be ticked,
  // under all conditions, and a ticked file is read under the distributor's rules.
  const anyFile = !!dist?.select_any
  const canPick = (f) => anyFile || (f.selectable ?? !f.error)
  function chooseDist(id) {
    setDistId(id)
    const d = dists.find((x) => String(x.id) === String(id))
    if (d) setCutoff(d.cutoff_day)
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
      // the distributor's own rule names its files; nothing else is ticked
      setSel(new Set(r.files.filter((f) => f.suggested).map((f) => f.name)))
    } catch (e) { setErr(e.message) } finally { setBusy(false); setProgress(null) }
  }

  async function convert() {
    setErr(''); setBusy(true)
    try {
      const r = await api.commit(found.token, {
        distributor_id: Number(distId), as_of: asOf, cutoff_day: Number(cutoff),
        files: chosen.map((f) => f.name), source: found.source,
        who: sessionStorage.getItem('ds.who') || 'user',
      })
      nav(`/batches/${r.batch_id}`)
    } catch (e) { setErr(e.message); setBusy(false) }
  }

  const p = period(asOf, Number(cutoff) || 15)
  const shown = (found?.files || []).filter((f) =>
    !filter.trim() || f.name.toLowerCase().includes(filter.trim().toLowerCase()))
  const chosen = (found?.files || []).filter((f) => sel.has(f.name) && canPick(f))
  const rows = chosen.reduce((a, f) => a + f.rows, 0)
  const canConvert = anyFile ? chosen.length > 0 : rows > 0

  return (
    <div className="page">
      <h1>Convert</h1>
      <p className="lead">Drop the zip a distributor sends — or loose workbooks and PDFs — pick the
        files that belong to this run, and the rows are stored and given back as the standard sheet.</p>
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

      {dist && (
        <section className="panel">
          <h2>Reference names <span className="fine">(optional)</span></h2>
          <p className="fine">Upload {dist.name}'s customer list and product list as Excel files.
            Extracted names that match one — ignoring case, spaces and special characters — are
            replaced with the name on the list. Each list is kept until you upload a new one.</p>
          {listMsg && <div className={`alert ${listMsg.bad ? 'bad' : 'ok'}`}>{listMsg.t}</div>}
          <div className="grid2">
            {[['customer', 'Customer names', custRef], ['product', 'Product names', prodRef]].map(([k, label, ref]) => (
              <div key={k}>
                <b>{label}</b>
                <p className="fine">{lists?.[k]?.count
                  ? `${lists[k].count} names, from ${lists[k].file || 'an upload'}`
                  : 'No list yet — names are kept as extracted.'}</p>
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
        <h2>2 · The files</h2>
        <div className={`drop ${dist ? '' : 'disabled'}`} tabIndex={0} role="button"
             aria-disabled={!dist} onClick={() => dist && pick.current?.click()}
             onKeyDown={(e) => { if (dist && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); pick.current?.click() } }}
             onDragOver={(e) => e.preventDefault()}
             onDrop={(e) => { e.preventDefault(); if (dist) send(e.dataTransfer.files) }}>
          <b>{dist ? 'Drop a .zip, or .xlsx or .pdf files, here — or choose them'
            : 'Choose a distributor above first'}</b>
          <span>A zip is opened and every workbook and PDF inside is listed for you to pick
            from.{anyFile && ` For ${dist.name}, every file extracted from the zip is listed and
            can be ticked, whatever its name or type; the PDF with Batch in its name is ticked to
            begin with, and whichever files you tick are read under ${dist.name}'s rules.`}</span>
          <input ref={pick} type="file" multiple hidden
                 accept={anyFile ? undefined : '.zip,.xlsx,.xls,.xlsm,.pdf'}
                 onChange={(e) => { send(e.target.files); e.target.value = '' }} />
        </div>
        {progress != null && (
          <div className="prog"><div className="bar"><i style={{ width: `${Math.round(progress * 100)}%` }} /></div>
            <span>{progress < 1 ? `Uploading — ${Math.round(progress * 100)}%` : 'Reading the files…'}</span></div>
        )}
        {found?.refused?.length > 0 && (
          <div className="alert warn">{found.refused.join(', ')} ignored — this reads Excel
            workbooks, PDFs and zips of them.</div>
        )}
        {found && dist?.pick_pattern && !found.files.some((f) => f.suggested) && (
          <div className="alert warn">Nothing in this upload matches {dist.name}'s rule
            {anyFile ? ' (a readable PDF with Batch in its name)' : ''}, so
            nothing is ticked. Check it is the right zip, or tick the file by hand
            {anyFile ? ' — any file below can be ticked' : ''}.</div>
        )}

        {found && (
          <>
            <div className="picker">
              <input placeholder="Filter by name, e.g. PW" value={filter}
                     onChange={(e) => setFilter(e.target.value)} />
              <button className="btn sm" onClick={() => setSel(new Set([...sel,
                ...shown.filter(canPick).map((f) => f.name)]))}>Select all shown</button>
              <button className="btn sm" onClick={() => setSel(new Set())}>Select none</button>
              <span className="fine">{chosen.length} of {found.files.length} selected · {rows} rows</span>
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
                  {f.error ? <span className="chip bad">{anyFile ? 'no rows found — can still be ticked'
                    : 'could not read'}</span>
                    : <span className="chip ok">{f.rows} rows</span>}
                  <span className="meta">{f.error || f.layout}</span>
                </li>
              ))}
              {!shown.length && <li className="fine">Nothing matches that filter.</li>}
            </ul>
            <div className="actions">
              <button className="btn primary" disabled={busy || !canConvert} onClick={convert}>
                {busy ? 'Converting…' : `Convert ${chosen.length} file${chosen.length === 1 ? '' : 's'}`}
              </button>
              <span className="fine">{anyFile
                ? `Tick any file — your choice overrides ${dist.name}'s file-name rule. Ticked
                  files are read under ${dist.name}'s rules; one with no rows is noted in the batch.`
                : "Nothing is ticked by itself except the files this distributor's rule names."}</span>
            </div>
          </>
        )}
      </section>
    </div>
  )
}
