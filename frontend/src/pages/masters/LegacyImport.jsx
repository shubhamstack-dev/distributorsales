import { useEffect, useState } from 'react'
import { api } from '../../api.js'

// What each old table becomes, in the order the import runs.
const LABELS = {
  state: 'States (names on customers)', classification: 'Customer classifications',
  remark: 'Customer remarks', sub_territory: 'Sub-territories (names on customers)',
  zone: 'Zones', hq: 'Headquarters', territory: 'Territories', product_group: 'Product groups',
  role: 'Roles', designation: 'Designations', team: 'Teams', brand: 'Brands',
  product_reporting: 'Product reporting lines (P1 / P2 / X)',
  team_product_group: 'Team › Product groups', product: 'SKUs',
  product_reporting_sku: 'Product reporting › SKUs', customer: 'Customers', employee: 'Employees',
}

/** Bring the old SQL Server masters in. Always a check first: the dry run does
 *  the whole import and rolls it back, so the numbers shown are what will happen. */
export default function LegacyImport() {
  const [files, setFiles] = useState([])
  const [years, setYears] = useState([])
  const [yearId, setYearId] = useState('')
  const [busy, setBusy] = useState('')
  const [progress, setProgress] = useState(0)
  const [report, setReport] = useState(null)
  const [checked, setChecked] = useState(false)
  const [err, setErr] = useState('')

  useEffect(() => { api.masterOptions('year', {}).then(setYears).catch(() => {}) }, [])

  const run = async (dry) => {
    setErr(''); setBusy(dry ? 'Checking…' : 'Importing…'); setProgress(0)
    try {
      const r = await api.legacyImport(files, dry, yearId, setProgress)
      setReport(r); setChecked(dry)
    } catch (e) { setErr(e.message); setReport(null); setChecked(false) }
    setBusy('')
  }

  const pick = (e) => { setFiles([...e.target.files]); setReport(null); setChecked(false) }

  return (
    <div className="page">
      <h1>Import old data</h1>
      <p className="lead">Brings the masters across from the old SQL Server system. Export each
        table from SQL Server Management Studio to Excel, save it under the table's name
        (<span className="mono">PRODUCT_MASTER.xlsx</span>) — or one workbook with a sheet per
        table — and choose them all here. Running it again updates what it brought in before;
        it never adds a row twice and never deletes anything.</p>

      <div className="card">
        <div className="grid2">
          <label>Old tables (.xlsx or .csv)
            <input type="file" multiple accept=".xlsx,.xlsm,.csv,.txt" onChange={pick} />
          </label>
          <label>Year for reporting lines and team › group
            <select value={yearId} onChange={(e) => { setYearId(e.target.value); setChecked(false) }}>
              <option value="">Current year</option>
              {years.map((y) => <option key={y.id} value={y.id}>{y.label}</option>)}
            </select>
          </label>
        </div>
        {files.length > 0 && <p className="muted">{files.length} file(s): {files.map((f) => f.name).join(', ')}</p>}
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
          <button className="btn" disabled={!files.length || !!busy} onClick={() => run(true)}>
            1. Check (nothing is saved)</button>
          <button className="btn primary" disabled={!checked || !!busy} onClick={() => run(false)}>
            2. Import</button>
        </div>
        {busy && <p className="muted">{progress < 1 ? `Uploading — ${Math.round(progress * 100)}%` : busy}</p>}
      </div>

      {err && <div className="alert bad">{err}</div>}

      {report && (
        <>
          <div className={`alert ${report.dry_run ? 'info' : 'ok'}`}>
            {report.dry_run
              ? 'This was a check — nothing has been saved yet. If the numbers look right, press Import.'
              : 'Imported and saved.'}
          </div>
          {report.messages.map((m, i) => <div key={i} className="alert warn">{m}</div>)}

          <h2>Files read</h2>
          <div className="scroll"><table>
            <thead><tr><th>Table</th><th className="r">Rows</th><th>Read as</th></tr></thead>
            <tbody>{report.files.map((f, i) => (
              <tr key={i}><td className="mono">{f.table}</td><td className="r mono">{f.rows}</td>
                <td>{f.read_as ? LABELS[f.read_as] || f.read_as : <span className="muted">not used</span>}</td></tr>
            ))}</tbody>
          </table></div>

          <h2>What {report.dry_run ? 'would change' : 'changed'}</h2>
          <div className="scroll"><table>
            <thead><tr><th>Master</th><th className="r">Added</th><th className="r">Updated</th>
              <th className="r">Placeholders</th><th className="r">Aliases added</th>
              <th className="r">Left out</th><th>Notes</th></tr></thead>
            <tbody>{Object.entries(report.tables).filter(([, t]) =>
              t.added || t.updated || t.placeholders || t.aliases || t.skipped || t.notes.length)
              .map(([k, t]) => (
                <tr key={k}>
                  <td><b>{LABELS[k] || k}</b></td>
                  <td className="r mono">{t.added}</td><td className="r mono">{t.updated}</td>
                  <td className="r mono">{t.placeholders}</td><td className="r mono">{t.aliases}</td>
                  <td className="r mono">{t.skipped}</td>
                  <td className="muted">{t.notes.join(' · ')}</td>
                </tr>
              ))}</tbody>
          </table></div>
        </>
      )}
    </div>
  )
}
