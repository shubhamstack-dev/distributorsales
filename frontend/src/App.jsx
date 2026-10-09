import { useEffect, useState } from 'react'
import { NavLink, Navigate, Route, Routes } from 'react-router-dom'
import { api, getToken, onSignedOut, setToken } from './api.js'
import Login from './pages/Login.jsx'
import Upload from './pages/Upload.jsx'
import Batches from './pages/Batches.jsx'
import BatchDetail from './pages/BatchDetail.jsx'
import Distributors from './pages/Distributors.jsx'
import Masters from './pages/masters/Masters.jsx'

const I = {
  convert: <path d="M4 7h11l-3-3M20 17H9l3 3" />,
  batches: <><rect x="4" y="4" width="16" height="5" rx="1.5" /><rect x="4" y="11" width="16" height="9" rx="1.5" /></>,
  rules: <><path d="M4 6h10M18 6h2M4 12h4M12 12h8M4 18h12M20 18h0" /><circle cx="16" cy="6" r="2" /><circle cx="10" cy="12" r="2" /><circle cx="18" cy="18" r="2" /></>,
  masters: <><ellipse cx="12" cy="6" rx="7" ry="2.5" /><path d="M5 6v6c0 1.4 3.1 2.5 7 2.5s7-1.1 7-2.5V6M5 12v6c0 1.4 3.1 2.5 7 2.5s7-1.1 7-2.5v-6" /></>,
}
const Icon = ({ d }) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7"
       strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{d}</svg>
)

export default function App() {
  const [who, setWho] = useState(sessionStorage.getItem('ds.who') || '')
  const [ready, setReady] = useState(false)

  useEffect(() => {
    onSignedOut(() => { setToken(''); setWho('') })
    if (!getToken()) { setReady(true); return }
    // a token in storage may be expired, so it is only trusted once used
    api.distributors().then(() => setReady(true)).catch(() => { setToken(''); setWho(''); setReady(true) })
  }, [])

  function signIn(token, name) {
    setToken(token); sessionStorage.setItem('ds.who', name); setWho(name)
  }
  function signOut() {
    setToken(''); sessionStorage.removeItem('ds.who'); setWho('')
  }

  if (!ready) return <div className="boot">Checking your session…</div>
  if (!getToken()) return <Login onSignedIn={signIn} />

  return (
    <div className="app">
      <aside className="side">
        <div className="brand"><span className="mark" aria-hidden="true" />
          <div><b>Distributor sales</b><small>Aequm sales desk</small></div></div>
        <NavLink to="/" end><Icon d={I.convert} /><span>Convert</span></NavLink>
        <NavLink to="/batches"><Icon d={I.batches} /><span>Batches</span></NavLink>
        <NavLink to="/distributors"><Icon d={I.rules} /><span>Rules</span></NavLink>
        <NavLink to="/masters"><Icon d={I.masters} /><span>Masters</span></NavLink>
        <div className="grow" />
        <div className="who"><span>Signed in as</span><b>{who}</b>
          <button className="btn sm" onClick={signOut}>Sign out</button></div>
      </aside>
      <main>
        <Routes>
          <Route path="/" element={<Upload />} />
          <Route path="/batches" element={<Batches />} />
          <Route path="/batches/:id" element={<BatchDetail />} />
          <Route path="/distributors" element={<Distributors />} />
          <Route path="/masters/*" element={<Masters />} />
          <Route path="*" element={<Navigate to="/" />} />
        </Routes>
      </main>
    </div>
  )
}
