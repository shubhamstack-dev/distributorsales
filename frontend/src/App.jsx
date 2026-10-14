import { useEffect, useState } from 'react'
import { NavLink, Navigate, Route, Routes } from 'react-router-dom'
import { api, getToken, onSignedOut, setToken } from './api.js'
import Login from './pages/Login.jsx'
import Upload from './pages/Upload.jsx'
import Batches from './pages/Batches.jsx'
import BatchDetail from './pages/BatchDetail.jsx'
import Distributors from './pages/Distributors.jsx'
import Masters from './pages/masters/Masters.jsx'
import TopMenu from './TopMenu.jsx'
import { MENUS } from './pages/masters/meta.js'

// The menus follow the old Abbott application: plain words, no icons.
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
      <header className="topbar">
        <div className="brand"><span className="mark" aria-hidden="true" />
          <div><b>Distributor sales</b><small>Aequm sales desk</small></div></div>
        <nav className="nav" aria-label="Main">
          {MENUS.map((m) => <TopMenu key={m.label} menu={m} />)}
          <span className="nav-sep" aria-hidden="true" />
          <NavLink className="nav-item" to="/" end>Convert</NavLink>
          <NavLink className="nav-item" to="/batches">Batches</NavLink>
          <NavLink className="nav-item" to="/distributors">Rules</NavLink>
        </nav>
        <div className="who"><span>Signed in as <b>{who}</b></span>
          <button className="btn sm" onClick={signOut}>Sign out</button></div>
      </header>
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
