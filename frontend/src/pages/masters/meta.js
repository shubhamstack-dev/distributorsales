import { useEffect, useState } from 'react'
import { api } from '../../api.js'

// The top bar's menus, as the old Abbott application had them. Administration
// opens one wide panel of four columns; the others are short lists.
export const MENUS = [
  { label: 'Administration', groups: ['Organisation structure', 'Product', 'Master data', 'Others'], wide: true },
  { label: 'Assignment', groups: ['Assignment'] },
  { label: 'Budgeting', groups: ['Budgeting'] },
  { label: 'Sales', groups: ['Sales'] },
]
export const GROUPS = MENUS.flatMap((m) => m.groups)
export const menuOf = (group) => MENUS.find((m) => m.groups.includes(group))?.label

// One request for the whole session: the top bar's menu and the master screens
// both draw from it. A failed request is forgotten so the next try asks again.
let pending = null
export function loadMeta() {
  if (!pending) pending = api.masterMeta().catch((e) => { pending = null; throw e })
  return pending
}

export function useMasterMeta(enabled = true) {
  const [meta, setMeta] = useState(null)
  const [err, setErr] = useState('')
  useEffect(() => {
    if (!enabled || meta) return
    let live = true
    loadMeta().then((m) => live && setMeta(m)).catch((e) => live && setErr(e.message))
    return () => { live = false }
  }, [enabled]) // eslint-disable-line react-hooks/exhaustive-deps
  return [meta, err]
}
