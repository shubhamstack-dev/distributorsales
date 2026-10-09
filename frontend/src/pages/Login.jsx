import { useState } from 'react'
import { api } from '../api.js'

export default function Login({ onSignedIn }) {
  const [who, setWho] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')

  async function go(e) {
    e.preventDefault()
    setErr(''); setBusy(true)
    try {
      const r = await api.login(password, who.trim() || 'user')
      onSignedIn(r.token, r.who)
    } catch (e2) { setErr(e2.message) } finally { setBusy(false) }
  }
  return (
    <div className="signin-wrap">
      <form className="signin-card" onSubmit={go}>
        <div className="signin-head"><span className="mark" aria-hidden="true" />
          <div><h1>Distributor sales</h1>
            <p>Turn distributors' files into the standard sales sheet.</p></div></div>
        {err && <div className="alert bad">{err}</div>}
        <label htmlFor="who">Your name <small>Recorded on every batch you convert</small></label>
        <input id="who" value={who} onChange={(e) => setWho(e.target.value)} placeholder="e.g. Alok"
               autoComplete="name" />
        <label htmlFor="pw">Password</label>
        <input id="pw" type="password" autoComplete="current-password"
               value={password} onChange={(e) => setPassword(e.target.value)} />
        <button className="btn primary" disabled={busy || !password}>
          {busy ? 'Signing in…' : 'Sign in'}</button>
      </form>
    </div>
  )
}
