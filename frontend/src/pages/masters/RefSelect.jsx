import { useEffect, useMemo, useState } from 'react'
import { api, qs } from '../../api.js'

// Drop-down options, kept between screens and thrown away whenever anything is
// saved — a brand added a moment ago has to be choosable on the SKU screen.
const cache = new Map()
export const forgetOptions = () => cache.clear()

export function useOptions(slug, params, enabled = true) {
  const key = `${slug}?${qs(params)}`
  const [opts, setOpts] = useState(cache.get(key) || null)
  useEffect(() => {
    if (!enabled) { setOpts([]); return }
    if (cache.has(key)) { setOpts(cache.get(key)); return }
    let live = true
    api.masterOptions(slug, { ...params, limit: 2000 })
      .then((o) => { cache.set(key, o); if (live) setOpts(o) })
      .catch(() => live && setOpts([]))
    return () => { live = false }
  }, [key, enabled])  // eslint-disable-line react-hooks/exhaustive-deps
  return opts
}

/** A select for a field that points at another master. Long lists (customers,
 *  SKUs) get a filter box above them; `params` narrows the list, e.g. SKUs to
 *  the product group chosen beside it. */
export default function RefSelect({ slug, value, onChange, params = {}, blank = '— choose —',
                                    waitingFor, id, required, includeInactive, currentLabel }) {
  const opts = useOptions(slug, includeInactive ? { ...params, include_inactive: 1 } : params,
    !waitingFor)
  const [filter, setFilter] = useState('')
  const shown = useMemo(() => {
    if (!opts) return []
    const f = filter.trim().toLowerCase()
    let list = f ? opts.filter((o) => o.label.toLowerCase().includes(f)) : opts
    // keep the chosen value visible even when the filter or "active only" hides it
    if (value && !list.some((o) => String(o.id) === String(value))) {
      const cur = opts.find((o) => String(o.id) === String(value))
      list = [cur || { id: value, label: currentLabel || `#${value} (inactive)` }, ...list]
    }
    return list
  }, [opts, filter, value, currentLabel])

  if (waitingFor) {
    return <select id={id} disabled><option>Choose the {waitingFor} first</option></select>
  }
  return (
    <div className="refsel">
      {opts && opts.length > 25 && (
        <input className="refsel-filter" placeholder={`Filter ${opts.length}…`} value={filter}
               onChange={(e) => setFilter(e.target.value)} aria-label="Filter the list" />
      )}
      <select id={id} value={value ?? ''} required={required}
              onChange={(e) => onChange(e.target.value ? Number(e.target.value) : null)}>
        <option value="">{opts ? blank : 'Loading…'}</option>
        {shown.map((o) => <option key={o.id} value={o.id}>{o.label}</option>)}
      </select>
    </div>
  )
}
