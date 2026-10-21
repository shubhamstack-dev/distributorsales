import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../../api.js'
import { RunList } from './AnalyzerRun.jsx'

const PRESET_LABELS = { m365: 'Microsoft 365', google: 'Google Workspace / Gmail', zoho_in: 'Zoho Mail (India)' }

/** Reports › Analyzer Email: who gets the Nepal Analyzer, how it is sent, and
 *  what happens after a conversion. */
export default function AnalyzerEmail() {
  const [s, setS] = useState(null)
  const [password, setPassword] = useState('')
  const [secret, setSecret] = useState('')
  const [testTo, setTestTo] = useState('')
  const [jobs, setJobs] = useState([])
  const [msg, setMsg] = useState(null)
  const [busy, setBusy] = useState('')

  const load = () => {
    api.mailSettings().then(setS).catch((e) => setMsg({ bad: true, t: e.message }))
    api.analyzerJobs({ limit: 30 }).then(setJobs).catch(() => {})
  }
  useEffect(load, [])
  if (!s) return <div className="page">{msg ? <div className="alert bad">{msg.t}</div> : 'Loading…'}</div>

  const set = (k) => (e) => setS({ ...s, [k]: e.target.type === 'checkbox' ? e.target.checked : e.target.value })
  const preset = (k) => setS({ ...s, ...s.presets[k], ...(k === 'm365' ? {} : { auth: 'password' }) })

  async function save() {
    setBusy('save'); setMsg(null)
    try {
      const body = { ...s }
      delete body.presets
      if (password) body.password = password
      if (secret) body.client_secret = secret
      setS(await api.saveMailSettings(body)); setPassword(''); setSecret('')
      setMsg({ t: 'Saved.' })
    } catch (e) { setMsg({ bad: true, t: e.message }) } finally { setBusy('') }
  }
  async function test() {
    setBusy('test'); setMsg(null)
    try { setMsg({ t: (await api.testMail(testTo || s.recipients)).message }) }
    catch (e) { setMsg({ bad: true, t: e.message }) } finally { setBusy('') }
  }
  const ready = s.smtp_host && s.smtp_port && (s.auth === 'none'
    || (s.auth === 'password' ? s.password_set : s.tenant_id && s.client_id && s.client_secret_set))

  return (
    <div className="page">
      <div className="head"><div>
        <p className="crumb">Reports</p>
        <h1>Analyzer Email</h1>
        <p className="lead">After a zip is converted, the month's actuals are calculated, the Nepal Analyzer
          is made and downloaded, and emailed with the workbook attached. It can also be sent by hand
          from <Link to="/masters/nepal-analyzer">Nepal Analyzer</Link>.</p>
      </div></div>

      <div className="mail-grid">
        <section className="panel stack">
          <h2>The report email</h2>
          <label><span>To<b aria-hidden="true">*</b> <small className="faint">(commas between addresses)</small></span>
            <input value={s.recipients || ''} onChange={set('recipients')} placeholder="181296shubham@gmail.com" /></label>
          <label><span>Cc</span><input value={s.cc || ''} onChange={set('cc')} /></label>
          <label><span>Subject <small className="faint">{'{month} {year} {distributor}'}</small></span>
            <input value={s.subject || ''} onChange={set('subject')} /></label>
          <h3>After a conversion</h3>
          <label className="check"><input type="checkbox" checked={s.auto_on_convert} onChange={set('auto_on_convert')} />
            <span>Make the Nepal Analyzer for the month converted
              <small>Convert shows this, and it can be unticked there for one conversion.</small></span></label>
          <label className="check"><input type="checkbox" checked={s.calculate_first} onChange={set('calculate_first')} disabled={!s.auto_on_convert} />
            <span>Calculate the month's actuals first <small>As Budgeting › Calculate Actuals.</small></span></label>
          <label className="check"><input type="checkbox" checked={s.send_mail} onChange={set('send_mail')} disabled={!s.auto_on_convert} />
            <span>Email it, with the workbook attached</span></label>
          <label className="check"><input type="checkbox" checked={s.download_after} onChange={set('download_after')} disabled={!s.auto_on_convert} />
            <span>Download it in the browser too</span></label>
        </section>

        <section className="panel">
          <h2>Sending — SMTP {ready ? <span className="chip">Ready</span> : <span className="chip">Not set</span>}</h2>
          <div className="presets"><span className="faint">Fill in the servers for</span>
            {Object.keys(s.presets).map((k) => <button key={k} className="btn sm" onClick={() => preset(k)}>{PRESET_LABELS[k] || k}</button>)}</div>
          <div className="grid2">
            <label><span>Server</span><input value={s.smtp_host || ''} onChange={set('smtp_host')} placeholder="smtp.office365.com" /></label>
            <label><span>Port</span><input value={s.smtp_port || ''} onChange={set('smtp_port')} placeholder="587" /></label>
            <label><span>Security</span><select value={s.security} onChange={set('security')}>
              <option value="starttls">STARTTLS (port 587)</option><option value="ssl">SSL/TLS (port 465)</option>
              <option value="none">None</option></select></label>
            <label><span>Authentication</span><select value={s.auth} onChange={set('auth')}>
              <option value="m365_oauth">Microsoft 365 (OAuth, no password)</option>
              <option value="password">User and password</option><option value="none">None</option></select></label>
            <label><span>User (mailbox)</span><input value={s.username || ''} onChange={set('username')} placeholder="name@aequmindia.in" /></label>
            {s.auth === 'password' && <label><span>Password {s.password_set && <small className="faint">
              {s.password_readable ? 'set — leave empty to keep it' : 'set, but unreadable since SECRET_KEY changed: enter it again'}</small>}</span>
              <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="new-password" /></label>}
            <label><span>From address</span><input value={s.from_address || ''} onChange={set('from_address')} placeholder="the mailbox" /></label>
            <label><span>From name</span><input value={s.from_name || ''} onChange={set('from_name')} /></label>
          </div>
          {s.auth === 'm365_oauth' && <>
            <h3>Microsoft 365 app (OAuth)</h3>
            <p className="fine">The app needs the Exchange Online application permission <b>SMTP.SendAsApp</b> with admin
              consent, and the mailbox granted to the app in Exchange. The ProjectSystem's app (same tenant and client ID)
              already has this if it sends from the same mailbox.</p>
            <div className="grid2">
              <label><span>Tenant ID</span><input value={s.tenant_id || ''} onChange={set('tenant_id')} /></label>
              <label><span>Client ID</span><input value={s.client_id || ''} onChange={set('client_id')} /></label>
              <label><span>Client secret {s.client_secret_set && <small className="faint">
                {s.client_secret_readable ? 'set — leave empty to keep it' : 'unreadable since SECRET_KEY changed: enter it again'}</small>}</span>
                <input type="password" value={secret} onChange={(e) => setSecret(e.target.value)} autoComplete="new-password" /></label>
            </div>
          </>}
        </section>
      </div>

      <section className="panel">
        <div className="actions">
          <button className="btn primary" disabled={!!busy} onClick={save}>{busy === 'save' ? 'Saving…' : 'Save settings'}</button>
          <input style={{ minWidth: 260 }} placeholder={`Send a test to… (${s.recipients || 'an address'})`} value={testTo}
                 onChange={(e) => setTestTo(e.target.value)} aria-label="Test address" />
          <button className="btn" disabled={!!busy} onClick={test}>{busy === 'test' ? 'Sending…' : 'Send test'}</button>
        </div>
        <p className="fine">Save before Send test. Passwords and the client secret are stored encrypted with the server's
          SECRET_KEY; if that key changes, enter them again.</p>
        {msg && <div className={`alert ${msg.bad ? 'bad' : 'ok'}`}>{msg.t}</div>}
      </section>

      <section className="panel">
        <div className="panel-head"><h2>Sent and made</h2>
          <button className="btn sm" onClick={load}>Refresh</button></div>
        <RunList jobs={jobs} />
      </section>
    </div>
  )
}
