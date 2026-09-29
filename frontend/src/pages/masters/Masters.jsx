import { useEffect, useState } from 'react'
import { NavLink, Navigate, Route, Routes } from 'react-router-dom'
import { api } from '../../api.js'
import MasterPage from './MasterPage.jsx'

// The order the rail reads in: set up first, then structure, then alignment,
// which leans on everything above it.
const GROUPS = ['Setup', 'Geography', 'Products', 'Customers', 'People', 'Alignment']

/** Every master screen, listed by what it is part of. The screens themselves
 *  are drawn from the server's description of each table (api /masters/meta),
 *  so a field or rule added on the server appears here without a code change. */
export default function Masters() {
  const [meta, setMeta] = useState(null)
  const [err, setErr] = useState('')
  const [open, setOpen] = useState(false)       // the rail, on a narrow screen

  useEffect(() => { api.masterMeta().then(setMeta).catch((e) => setErr(e.message)) }, [])

  if (err) return <div className="page"><div className="alert bad">{err}</div></div>
  if (!meta) return <div className="page muted">Loading the masters…</div>

  return (
    <div className="masters">
      <button className="btn sm rail-toggle" aria-expanded={open}
              onClick={() => setOpen((o) => !o)}>{open ? 'Hide list' : 'All masters'}</button>
      <nav className={`rail ${open ? 'open' : ''}`} aria-label="Masters">
        {GROUPS.map((g) => (
          <div key={g} className="rail-group">
            <div className="rail-head">{g}</div>
            {meta.filter((m) => m.group === g).map((m) => (
              <NavLink key={m.slug} to={`/masters/${m.slug}`} onClick={() => setOpen(false)}>
                {m.title}
              </NavLink>
            ))}
          </div>
        ))}
      </nav>
      <section className="master-pane">
        <Routes>
          <Route index element={<Navigate to="year" replace />} />
          {meta.map((m) => (
            <Route key={m.slug} path={m.slug}
                   element={<MasterPage key={m.slug} spec={m} />} />
          ))}
          <Route path="*" element={<Navigate to="year" replace />} />
        </Routes>
      </section>
    </div>
  )
}
