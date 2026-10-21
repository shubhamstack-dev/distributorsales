import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../../api.js'
import { RunCard, useRun } from './AnalyzerRun.jsx'

const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August',
  'September', 'October', 'November', 'December']

/** Send Mail: once the month's distributors are converted, one email of the
 *  Nepal Analyzer (actuals calculated first). Chooses its own month and year,
 *  or follows the page's (month / year given). */
export default function SendMailPanel({ month: ctlMonth, year: ctlYear, initialMonth, initialYear, title }) {
  const controlled = ctlMonth !== undefined
  const [years, setYears] = useState([])
  const [ownMonth, setOwnMonth] = useState(initialMonth || '')
  const [ownYear, setOwnYear] = useState(initialYear ? String(initialYear) : '')
  const month = controlled ? ctlMonth : ownMonth
  const year = controlled ? ctlYear : ownYear
  const [st, setSt] = useState(null)
  const [to, setTo] = useState('')
  const [cc, setCc] = useState('')
  const [calc, setCalc] = useState(true)
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const [runId, setRunId] = useState(null)
  const [job, setJob] = useRun(runId)

  useEffect(() => {
    if (!controlled) api.budgetYears().then(setYears).catch(() => {})
    api.mailSettings().then((s) => { setTo(s.recipients || ''); setCc(s.cc || '') }).catch(() => {})
  }, [controlled])
  // with no month chosen, the latest conversion's month
  useEffect(() => {
    if (controlled || ownMonth) return
    api.monthStatus().then((s) => { if (s.month) { setOwnMonth(s.month); setOwnYear(String(s.year)) } }).catch(() => {})
  }, [controlled]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    setSt(null)
    if (!month || !year) return
    api.monthStatus(month, year).then(setSt).catch((e) => setErr(e.message))
  }, [month, year, job?.mail_status])

  async function send() {
    if (!month || !year) { setErr('Select the month and the year.'); return }
    if (st && !st.all_converted) {
      const missing = st.distributors.filter((d) => !d.converted).map((d) => d.name).join(', ')
      if (!window.confirm(`${missing} not converted for ${month} ${year} yet.\n\nSend the mail anyway?`)) return
    }
    if (st?.last_mail && !window.confirm(`${month} ${year} was already mailed on ${st.last_mail.sent_at.replace('T', ' ')} `
      + `to ${st.last_mail.recipients}.\n\nSend it again?`)) return
    setErr(''); setBusy(true)
    try {
      const j = await api.startAnalyzer({ month, year: Number(year), calculate: calc, send: true, recipients: to, cc,
        who: sessionStorage.getItem('ds.who') || 'user' })
      setJob(j); setRunId(j.id)
    } catch (e) { setErr(e.message) } finally { setBusy(false) }
  }
  const going = ['queued', 'running'].includes(job?.status)

  return (
    <>
      <section className="panel">
        <h2>{title || 'Send Mail'}</h2>
        <p className="fine">One email of the Nepal Analyzer for the month, once its distributors are converted: the
          month's actuals calculated first, then the workbook attached. Sent from the mailbox on{' '}
          <Link to="/masters/analyzer-email">Analyzer Email</Link>.</p>
        {!controlled && <div className="grid2 de-form">
            <label><span>Month<b aria-hidden="true">*</b></span>
              <select value={ownMonth} onChange={(e) => { setOwnMonth(e.target.value); setJob(null) }}>
                <option value="">-- Select Month --</option>
                {MONTHS.map((m) => <option key={m} value={m}>{m}</option>)}
              </select></label>
            <label><span>Year<b aria-hidden="true">*</b></span>
              <select value={ownYear} onChange={(e) => { setOwnYear(e.target.value); setJob(null) }}>
                <option value="">-- Select Year --</option>
                {[...new Set([...(ownYear ? [ownYear] : []), ...years.map(String)])].map((y) => <option key={y} value={y}>{y}</option>)}
              </select></label>
        </div>}
        <div className="grid2 de-form">
          <label><span>To<b aria-hidden="true">*</b></span><input value={to} onChange={(e) => setTo(e.target.value)} /></label>
          <label><span>Cc</span><input value={cc} onChange={(e) => setCc(e.target.value)} /></label>
        </div>

        {month && year && <div className="dist-status">
          <b>{month} {year}:</b>
          {!st && <span className="faint">checking…</span>}
          {st?.distributors.map((d) => (
            <span key={d.id} className={`chip ${d.converted ? 'ok' : 'bad'}`}
                  title={d.last_batch ? `batch ${d.last_batch.id}, uploaded ${d.last_batch.as_of}, Mid Month ${d.last_batch.mid_month}` : 'no batch for this month'}>
              {d.converted ? '✓' : '✗'} {d.name}{d.converted ? ` · ${d.rows.toLocaleString('en-IN')} rows` : ' · not converted'}
            </span>))}
          {st && (st.all_converted
            ? <span className="fine">All converted — ready to send.</span>
            : <span className="fine">Not all converted yet.</span>)}
          {st?.last_mail && <span className="fine">Last mailed {st.last_mail.sent_at.replace('T', ' ')} to {st.last_mail.recipients}.</span>}
        </div>}

        <label className="check"><input type="checkbox" checked={calc} onChange={(e) => setCalc(e.target.checked)} />
          <span>Calculate {month || 'the month'}'s actuals first</span></label>
        <div className="actions">
          <button className="btn primary" disabled={busy || going || !month || !year} onClick={send}>
            {busy || going ? 'Sending…' : 'Send Mail'}</button>
        </div>
        {err && <div className="alert bad">{err}</div>}
      </section>
      {job && <RunCard job={job} title="Send Mail"
                       onChange={(j) => { setJob(j); setRunId(null); setTimeout(() => setRunId(j.id), 0) }} />}
    </>
  )
}

/** Reports › Send Mail */
export function SendMailPage() {
  return (
    <div className="page">
      <div className="head"><div>
        <p className="crumb">Reports</p>
        <h1>Send Mail</h1>
        <p className="lead">When the month's distributors are converted, send the Nepal Analyzer once. Choose any
          month and year to send (or send again) that month's report.</p>
      </div></div>
      <SendMailPanel />
    </div>
  )
}
