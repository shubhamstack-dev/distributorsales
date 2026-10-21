import { useEffect, useState } from 'react'
import { api } from '../../api.js'

const MONTH_NAMES = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August',
  'September', 'October', 'November', 'December']

/** Reports › Nepal Analyzer, as the old "All Nepal Analyzer Report" screen:
 *  a month and a year, Download gives NepalAnalyzerReports_<Month><Year>.xlsx
 *  (18 sheets, worked out on the server). */
export default function NepalAnalyzer() {
  const [years, setYears] = useState([])
  const [month, setMonth] = useState('')
  const [year, setYear] = useState('')
  const [err, setErr] = useState('')
  const [done, setDone] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => { api.budgetYears().then(setYears).catch((e) => setErr(e.message)) }, [])

  async function download() {
    if (!month || !year) { setErr('Select the month and the year.'); setDone(''); return }
    setErr(''); setDone(''); setBusy(true)
    const started = performance.now()
    try {
      const name = await api.nepalAnalyzer(month, year)
      if (name) setDone(`${name} downloaded in ${((performance.now() - started) / 1000).toFixed(1)} s.`)
    } catch (e) { setErr(e.message) } finally { setBusy(false) }
  }
  const clear = () => { setMonth(''); setYear(''); setErr(''); setDone('') }

  return (
    <div className="page">
      <div className="head"><div>
        <p className="crumb">Reports</p>
        <h1>Nepal Analyzer Report</h1>
        <p className="lead">All Nepal Analyzer Report: Nepal, distributor, HQ, brand and employee level, with
          and without expiry adjustment, and the month's sales, mid-month sales, expiry and adjustments, in
          one Excel workbook.</p>
      </div></div>

      <section className="panel">
        <h2>All Nepal Analyzer Report</h2>
        <div className="grid2 de-form">
          <label><span>Month<b aria-hidden="true">*</b></span>
            <select value={month} onChange={(e) => setMonth(e.target.value)}>
              <option value="">-- Select Month --</option>
              {MONTH_NAMES.map((m) => <option key={m} value={m}>{m}</option>)}
            </select></label>
          <label><span>Year<b aria-hidden="true">*</b></span>
            <select value={year} onChange={(e) => setYear(e.target.value)}>
              <option value="">-- Select From Year --</option>
              {years.map((y) => <option key={y} value={y}>{y}</option>)}
            </select></label>
        </div>
        <div className="actions">
          <button className="btn primary" disabled={busy} onClick={download}>{busy ? 'Preparing…' : 'Download'}</button>
          <button className="btn" disabled={busy} onClick={clear}>Clear</button>
        </div>
        {err && <div className="alert bad">{err}</div>}
        {done && <div className="alert ok">{done}</div>}
      </section>
    </div>
  )
}
