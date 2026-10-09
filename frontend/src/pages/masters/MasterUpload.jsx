import { useRef, useState } from 'react'
import { api } from '../../api.js'
import UploadReport from './UploadReport.jsx'

/** Every master from Excel, in one go. Always a check first: it does the whole
 *  upload and rolls it back, so the numbers shown are what Import will do. */
export default function MasterUpload({ meta }) {
  const [files, setFiles] = useState([])
  const [busy, setBusy] = useState('')
  const [progress, setProgress] = useState(0)
  const [report, setReport] = useState(null)
  const [checked, setChecked] = useState(false)
  const [over, setOver] = useState(false)
  const [err, setErr] = useState('')
  const pick = useRef(null)

  const choose = (list) => {
    const f = [...list].filter((x) => /\.(xlsx|xlsm|csv|txt)$/i.test(x.name))
    setFiles(f); setReport(null); setChecked(false)
    setErr(f.length || !list.length ? '' : 'Choose Excel (.xlsx) or CSV files.')
  }
  const run = async (dry) => {
    setErr(''); setBusy(dry ? 'Checking…' : 'Importing…'); setProgress(0)
    try {
      const r = await api.masterUpload(files, dry, null, setProgress)
      setReport(r); setChecked(dry)
      if (!dry) setFiles([])
    } catch (e) { setErr(e.message); setReport(null); setChecked(false) }
    setBusy('')
  }
  const excel = meta.filter((m) => m.table === m.table.toUpperCase())

  return (
    <div className="page">
      <div className="head">
        <div><h1>Upload master data</h1>
          <p className="lead">Send MASTER DATA &amp; TABLES.xlsx as it is, or a file per master. Each
            sheet is read into the master it is named after, parents first, so zones go in before
            headquarters and brands before products. Uploading again updates the same rows; nothing
            is ever deleted.</p></div>
        <div className="actions">
          <button className="btn" onClick={() => api.masterExportAll().catch((e) => setErr(e.message))}>
            Download every master</button>
        </div>
      </div>

      <section className="panel">
        <div className="panel-head"><span className="step">1</span><h2>Choose the files</h2></div>
        <div className={`drop ${over ? 'over' : ''}`} tabIndex={0} role="button"
             onClick={() => pick.current?.click()}
             onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); pick.current?.click() } }}
             onDragOver={(e) => { e.preventDefault(); setOver(true) }} onDragLeave={() => setOver(false)}
             onDrop={(e) => { e.preventDefault(); setOver(false); choose(e.dataTransfer.files) }}>
          <b>{files.length ? files.map((f) => f.name).join(', ') : 'Drop Excel or CSV files here, or click to choose'}</b>
          <span>Sheets are matched by name: {excel.map((m) => m.table).join(', ')}, and the old
            system's ZONE, HQ_MASTER, TERRITORY, PRODUCT_MASTER_GROUP, TEAM, ROLE_MASTER and
            DESIGNATION. Every other master goes by its title, e.g. Years or Countries.</span>
          <input ref={pick} type="file" multiple hidden accept=".xlsx,.xlsm,.csv,.txt"
                 onChange={(e) => { choose(e.target.files); e.target.value = '' }} />
        </div>
        {busy && <div className="prog"><div className="bar"><i style={{ width: `${Math.round(progress * 100)}%` }} /></div>
          <span>{progress < 1 ? `Uploading, ${Math.round(progress * 100)}%` : busy}</span></div>}
      </section>

      <section className="panel">
        <div className="panel-head"><span className="step">2</span><h2>Check, then import</h2>
          <p>The check saves nothing and shows every row that would be left out, with the reason.</p></div>
        <div className="actions" style={{ marginTop: 0 }}>
          <button className="btn cool" disabled={!files.length || !!busy} onClick={() => run(true)}>Check the files</button>
          <button className="btn primary" disabled={!checked || !files.length || !!busy} onClick={() => run(false)}>Import</button>
          <span className="fine">The PASSWORD column of EMPLOYEE_MASTER is never stored.</span>
        </div>
        {err && <div className="alert bad">{err}</div>}
        <UploadReport report={report} />
      </section>
    </div>
  )
}
