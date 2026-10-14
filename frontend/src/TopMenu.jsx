import { useEffect, useRef, useState } from 'react'
import { NavLink, useLocation } from 'react-router-dom'
import { useMasterMeta } from './pages/masters/meta.js'

/** One menu of the top bar (Administration, Assignment, Budgeting, Sales),
 *  laid out as the old Abbott application had it. A click opens it; choosing a
 *  screen, Escape, or a click anywhere else closes it. Administration is one
 *  wide panel of four columns, the others a short list under their name. */
export default function TopMenu({ menu }) {
  const [open, setOpen] = useState(false)
  const [meta, err] = useMasterMeta()
  const loc = useLocation()
  const wrap = useRef(null)
  const btn = useRef(null)
  const id = `menu-${menu.label.toLowerCase()}`

  const groups = menu.groups
    .map((g) => [g, (meta || []).filter((m) => m.group === g)])
    .filter(([, l]) => l.length)
  const tables = (meta || []).filter((m) => menu.also?.includes(m.group))
  const here = groups.some(([, l]) => l.some((m) => loc.pathname === `/masters/${m.slug}`))
    || (menu.links || []).some((x) => loc.pathname === x.to)
    || tables.some((m) => loc.pathname === `/masters/${m.slug}`)
    || (menu.wide && loc.pathname === '/masters/upload')

  useEffect(() => { setOpen(false) }, [loc.pathname])
  useEffect(() => {
    if (!open) return undefined
    const down = (e) => { if (!wrap.current?.contains(e.target)) setOpen(false) }
    const key = (e) => { if (e.key === 'Escape') { setOpen(false); btn.current?.focus() } }
    document.addEventListener('mousedown', down)
    document.addEventListener('keydown', key)
    return () => { document.removeEventListener('mousedown', down); document.removeEventListener('keydown', key) }
  }, [open])

  const close = () => setOpen(false)
  const list = (g, l) => (
    <section key={g} className="mm-group" aria-labelledby={`${id}-${g}`}>
      {menu.groups.length > 1 && <h3 id={`${id}-${g}`}>{g}</h3>}
      <ul>
        {l.map((m) => (
          <li key={m.slug}><NavLink to={`/masters/${m.slug}`} onClick={close}>{m.title}</NavLink></li>
        ))}
      </ul>
    </section>
  )

  return (
    <div className={`mm${menu.wide ? '' : ' narrow'}`} ref={wrap}>
      <button ref={btn} type="button" className={`nav-item${here ? ' active' : ''}${open ? ' open' : ''}`}
              aria-expanded={open} aria-controls={id} onClick={() => setOpen((o) => !o)}>
        <span>{menu.label}</span>
        <svg className="caret" viewBox="0 0 12 12" aria-hidden="true"><path d="M3 4.5 6 7.5 9 4.5" /></svg>
      </button>
      {open && <div className="mm-scrim" aria-hidden="true" onMouseDown={close} />}
      {open && (
        <div id={id} className="mm-panel" role="region" aria-label={menu.label}>
          {err && <div className="alert bad">{err}</div>}
          {!meta && !err && <p className="faint">Loading…</p>}
          {menu.wide ? (
            <div className="mm-inner">
              <div className="mm-grid">{groups.map(([g, l]) => list(g, l))}</div>
              <NavLink to="/masters/upload" className="mm-upload" onClick={close}>
                <b>Upload master data</b>
                <span>One Excel workbook or a file per table. Checked before anything is saved.</span>
              </NavLink>
            </div>
          ) : (
            <>
              {menu.links && (
                <section className="mm-group"><ul>
                  {menu.links.map((x) => (
                    <li key={x.to}><NavLink to={x.to} onClick={close}>{x.title}</NavLink></li>
                  ))}
                </ul></section>
              )}
              {groups.map(([g, l]) => list(g, l))}
            </>
          )}
        </div>
      )}
    </div>
  )
}
