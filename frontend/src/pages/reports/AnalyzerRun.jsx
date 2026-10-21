import { useEffect, useRef, useState } from 'react'
import { api } from '../../api.js'

const GOING = ['queued', 'running']

/** Polls a run until it is over; downloads its workbook once when asked. */
export function useRun(id, { autoDownload = false } = {}) {
  const [job, setJob] = useState(null)
  const [err, setErr] = useState('')
  const downloaded = useRef(false)
  useEffect(() => {
    if (!id) return undefined
    let live = true
    let timer
    downloaded.current = false
    const tick = async () => {
      try {
        const j = await api.analyzerJob(id)
        if (!live) return
        setJob(j)
        if (GOING.includes(j.status)) timer = setTimeout(tick, 1500)
        else if (autoDownload && j.has_file && !downloaded.current) {
          downloaded.current = true
          api.analyzerFile(j.id, j.file_name).catch((e) => setErr(e.message))
        }
      } catch (e) { if (live) setErr(e.message) }
    }
    tick()
    return () => { live = false; clearTimeout(timer) }
  }, [id, autoDownload])
  return [job, setJob, err]
}

/** One run: its steps, the workbook, the email, and Send again. */
export function RunCard({ job, onChange, title }) {
  const [to, setTo] = useState('')
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState(null)
  if (!job) return null
  const going = GOING.includes(job.status)
  const tone = going ? 'warn' : job.status === 'done' ? 'ok' : 'bad'

  async function again() {
    setBusy(true); setMsg(null)
    try { onChange?.(await api.resendAnalyzer(job.id, to.trim() ? { recipients: to } : {})) }
    catch (e) { setMsg({ bad: true, t: e.message }) } finally { setBusy(false) }
  }
  return (
    <section className="panel">
      <h2>{title || 'Nepal Analyzer'} — {job.month} {job.year}</h2>
      <div className={`alert ${tone}`}>
        {going && <>Working: <b>{job.step}</b>…</>}
        {!going && job.status === 'done' && <>Done.{' '}
          {job.send ? (job.mail_status === 'sent' ? job.mail_detail : 'Not emailed.') : 'Made without emailing, as asked.'}</>}
        {!going && job.status === 'failed' && <>{job.error ? `Stopped: ${job.error}` : `The workbook is made, but the email was not sent: ${job.mail_detail}`}</>}
      </div>
      <ul className="fine run-log">
        {job.log.map((l, i) => <li key={i}>{l}</li>)}
        {going && <li className="faint">{job.step}…</li>}
      </ul>
      <div className="actions">
        {job.has_file && <button className="btn primary" onClick={() => api.analyzerFile(job.id, job.file_name)
          .catch((e) => setMsg({ bad: true, t: e.message }))}>Download {job.file_name}</button>}
        {job.has_file && !going && <>
          <input style={{ minWidth: 260 }} placeholder={job.recipients || 'Email to…'} value={to}
                 onChange={(e) => setTo(e.target.value)} aria-label="Send to" />
          <button className="btn" disabled={busy} onClick={again}>{busy ? 'Sending…' : job.mail_status === 'sent' ? 'Send again' : 'Send'}</button>
        </>}
      </div>
      {msg && <div className={`alert ${msg.bad ? 'bad' : 'ok'}`}>{msg.t}</div>}
      <p className="fine">Run {job.id}, {job.trigger === 'convert' ? `after batch ${job.batch_id} (${job.distributor})` : 'started by hand'},
        {' '}{job.created_at.replace('T', ' ')}{job.recipients ? ` · to ${job.recipients}${job.cc ? `, cc ${job.cc}` : ''}` : ''}.</p>
    </section>
  )
}

/** The latest runs, with their files. */
export function RunList({ jobs, onPick }) {
  if (!jobs?.length) return <p className="fine">No runs yet.</p>
  return (
    <div className="scroll"><table className="grid-old">
      <thead><tr><th className="sno">Run</th><th>When</th><th>Month</th><th>Started by</th><th>To</th><th>Status</th><th>Email</th><th /></tr></thead>
      <tbody>{jobs.map((j) => (
        <tr key={j.id}>
          <td className="sno">{j.id}</td><td>{j.created_at.replace('T', ' ')}</td><td>{j.month} {j.year}</td>
          <td>{j.trigger === 'convert' ? `Convert · batch ${j.batch_id} (${j.distributor})` : `Hand${j.created_by ? ` · ${j.created_by}` : ''}`}</td>
          <td>{j.send ? j.recipients : <span className="faint">—</span>}</td>
          <td>{j.status}{j.error ? ` — ${j.error}` : ''}</td>
          <td title={j.mail_detail || ''}>{j.mail_status || <span className="faint">—</span>}</td>
          <td>{j.has_file && <button className="btn sm" onClick={() => api.analyzerFile(j.id, j.file_name)}>Download</button>}
            {onPick && <button className="btn sm" onClick={() => onPick(j)}>Open</button>}</td>
        </tr>))}</tbody>
    </table></div>
  )
}
