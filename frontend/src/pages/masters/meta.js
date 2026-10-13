import { useEffect, useState } from 'react'
import { api } from '../../api.js'

// The order masters are listed in, in the menu and anywhere else: set up first,
// then structure, then assignment, which leans on everything above it, then the
// sales and budget figures reported against all of it.
export const GROUPS = ['Setup', 'Geography', 'Products', 'Customers', 'People', 'Assignment', 'Sales & budget']

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
