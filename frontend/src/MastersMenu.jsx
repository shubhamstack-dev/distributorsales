import { useEffect, useRef, useState } from 'react'
import { NavLink, useLocation } from 'react-router-dom'
import { GROUPS, useMasterMeta } from './pages/masters/meta.js'

/** "Masters" in the top bar. A click opens every master as one panel under the
 *  bar, grouped as the data is built up (setup → … → sales & budget), so the
 *  screens below get the full width instead of a second rail beside them.
 *  It closes on choosing a master, on Escape, or on a click anywhere else. */
export default function MastersMenu({ icon }) {
  const [open, setOpen] = useState(false)
  const [meta, err] = useMasterMeta()
  const loc = useLocation()
  const wrap = useRef(null)
  const btn = useRef(null)
  const onMasters = loc.pathname.startsWith('/masters')

  useEffect(() => { setOpen(false) }, [loc.pathname])
  useEffect(() => {
    if (!open) return undefined
    const down = (e) => { if (!wrap.current?.contains(e.target)) setOpen(false) }
    const key = (e) => { if (e.key === 'Escape') { setOpen(false); btn.current?.focus() } }
    document.addEventListener('mousedown', down)
    document.addEventListener('keydown', key)
    return () => { document.removeEventListener('mousedown', down); document.removeEventListener('keydown', key) }
  }, [open])

  const groups = GROUPS.map((g) => [g, (meta || []).filter((m) => m.group === g)]).filter(([, l]) => l.length)

  return (
    <div className="mm" ref={wrap}>
      <button ref={btn} type="button" className={`nav-item${onMasters ? ' active' : ''}${open ? ' open' : ''}`}
              aria-expanded={open} aria-controls="masters-menu" onClick={() => setOpen((o) => !o)}>
        {icon}<span>Masters</span>
        <svg className="caret" viewBox="0 0 12 12" aria-hidden="true"><path d="M3 4.5 6 7.5 9 4.5" /></svg>
      </button>
      {open && <div className="mm-scrim" aria-hidden="true" onMouseDown={() => setOpen(false)} />}
      {open && (
        <div id="masters-menu" className="mm-panel" role="region" aria-label="Masters">
          <div className="mm-inner">
            <NavLink to="/masters/upload" className="mm-upload" onClick={() => setOpen(false)}>
              <b>Upload master data</b>
              <span>One Excel workbook or a file per table. Checked before anything is saved.</span>
            </NavLink>
            {err && <div className="alert bad">{err}</div>}
            {!meta && !err && <p className="faint">Loading the masters…</p>}
            <div className="mm-grid">
              {groups.map(([g, list]) => (
                <section key={g} className="mm-group" aria-labelledby={`mm-${g}`}>
                  <h3 id={`mm-${g}`}>{g}</h3>
                  <ul>
                    {list.map((m) => (
                      <li key={m.slug}>
                        <NavLink to={`/masters/${m.slug}`} onClick={() => setOpen(false)}>
                          {m.title}
                          {m.table === m.table.toUpperCase() && <small>{m.table}</small>}
                        </NavLink>
                      </li>
                    ))}
                  </ul>
                </section>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
