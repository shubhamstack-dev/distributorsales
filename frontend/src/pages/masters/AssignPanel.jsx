import { useMemo, useState } from 'react'
import { api } from '../../api.js'
import RefSelect, { useOptions } from './RefSelect.jsx'

// "6 · TKATH6 — KATHMANDU" -> "KATHMANDU": the name alone, as the old forms listed it
const plain = (label) => label.split(' — ').pop()

/** Several rows of a master picked at once: a filterable list of checkboxes,
 *  for the old forms' multi-select boxes (Headquarter, Product Group). */
export function MultiPick({ slug, keyBy, value, onChange, label }) {
  const opts = useOptions(slug, keyBy ? { key: keyBy } : {})
  const [filter, setFilter] = useState('')
  const shown = useMemo(() => {
    const f = filter.trim().toLowerCase()
    return (opts || []).filter((o) => !f || plain(o.label).toLowerCase().includes(f))
  }, [opts, filter])
  const on = new Set(value)
  const flip = (id) => onChange(on.has(id) ? value.filter((x) => x !== id) : [...value, id])
  const all = shown.length > 0 && shown.every((o) => on.has(o.id))
  return (
    <div className="multipick" role="group" aria-label={label}>
      <div className="multipick-bar">
        <input placeholder="Filter…" value={filter} onChange={(e) => setFilter(e.target.value)}
               aria-label={`Filter ${label}`} />
        <button type="button" className="linkish" disabled={!shown.length}
                onClick={() => onChange(all ? value.filter((x) => !shown.some((o) => o.id === x))
                                            : [...new Set([...value, ...shown.map((o) => o.id)])])}>
          {all ? 'None' : 'All'}</button>
        <span className="faint">{value.length} chosen</span>
      </div>
      <div className="multipick-list">
        {!opts && <span className="faint">Loading…</span>}
        {shown.map((o) => (
          <label key={o.id} className={on.has(o.id) ? 'on' : ''}>
            <input type="checkbox" checked={on.has(o.id)} onChange={() => flip(o.id)} />
            <span>{plain(o.label)}</span>
          </label>
        ))}
      </div>
    </div>
  )
}

// The old Abbott forms: what each page asks for. ids are what the API takes.
const FORMS = {
  customer: {
    title: 'Customer Territory Pg',
    blank: { customer_ids: null, territory_ids: [], product_group_ids: [], team_id: null },
    help: 'Each territory brings its HQ. Leave Team on "From Team PG HQ" and the team that '
      + 'carries the group in that HQ is used. Every active product of the group is assigned.',
  },
  employee: {
    title: 'Emp/Terr-Pg Assignment',
    blank: { employee_ids: null, hq_ids: [], product_group_ids: [] },
    help: 'Each HQ brings its territories; each product group, every active product in it. '
      + 'Delete takes out the HQs and groups ticked, and leaves the rest of the employee as it is.',
  },
  team_pg_hq: {
    title: 'Team Hq Pg',
    blank: { team_ids: null, hq_ids: [], product_group_ids: [] },
    help: 'One row per HQ and product group ticked, for the team chosen.',
  },
}

/** What a check found, in words, for the confirm box and the message after. */
export function summary(r) {
  const parts = []
  const n = (k, what) => {          // what: "territory row|s added"
    if (r[k] === undefined) return
    const [one, rest] = what.split('|')
    parts.push(`${r[k].toLocaleString('en-IN')} ${one}${r[k] === 1 ? '' : 's'}${rest}`)
  }
  n('territory_rows_added', 'territory row|s added')
  n('product_rows_added', 'product row|s added')
  n('rows_added', 'row|s added')
  n('territory_rows_removed', 'territory row|s removed')
  n('product_rows_removed', 'product row|s removed')
  n('rows_removed', 'row|s removed')
  let t = parts.join(', ') + '.'
  if (r.customers) t = `${r.customers.toLocaleString('en-IN')} customers: ${t}`
  if (r.notes?.length) t += `\n\n${r.notes.join('\n')}`
  return t
}

/** Check, ask, then do: every change goes through here. */
export async function checkThenRun(kind, action, body, verb) {
  const dry = await api.assign(kind, action, { ...body, dry_run: true })
  const nothing = !Object.entries(dry).some(([k, v]) => /_(added|removed)$/.test(k) && v > 0)
  if (nothing) {
    const why = action === 'create' || action === 'assign_all'
      ? 'Already assigned: there is nothing new to add.'
      : 'Nothing to delete: none of these are assigned.'
    return { done: false, text: why + (dry.notes?.length ? `\n\n${dry.notes.join('\n')}` : '') }
  }
  if (!window.confirm(`${verb[0].toUpperCase()}${verb.slice(1)}?\n\n${summary(dry)}`)) return null
  const r = await api.assign(kind, action, body)
  return { done: true, text: summary(r) }
}

/** The add / remove form of Customer Terr-PG, Employee Terr-PG and Team PG HQ. */
export default function AssignPanel({ kind, onDone, onClose }) {
  const f = FORMS[kind]
  const [form, setForm] = useState(f.blank)
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState(null)
  const set = (k) => (v) => setForm((x) => ({ ...x, [k]: v }))

  async function go(action) {
    setBusy(true); setMsg(null)
    const body = Object.fromEntries(Object.entries(form).map(([k, v]) => [k, v === null ? [] : v]))
    try {
      const r = await checkThenRun(kind, action, body, action === 'create' ? 'create these' : 'delete these')
      if (r) { setMsg({ bad: !r.done, t: r.text }); if (r.done) onDone() }
    } catch (e) { setMsg({ bad: true, t: e.message }) } finally { setBusy(false) }
  }

  return (
    <div className="panel editor assign">
      <h3>{f.title}</h3>
      <p className="fine">{f.help}</p>
      <div className="grid2">
        {kind === 'customer' && <>
          <label><span>Customer Name<b aria-hidden="true">*</b></span>
            <RefSelect slug="customer" value={form.customer_ids} onChange={set('customer_ids')} /></label>
          <label><span>Team Name</span>
            <RefSelect slug="team" keyBy="legacy_id" blank="From Team PG HQ" value={form.team_id}
                       onChange={set('team_id')} /></label>
          <div><span className="lbl">Territory*</span>
            <MultiPick slug="territory" keyBy="legacy_id" label="Territory" value={form.territory_ids}
                       onChange={set('territory_ids')} /></div>
        </>}
        {kind === 'employee' && (
          <label className="wide"><span>Employee<b aria-hidden="true">*</b></span>
            <RefSelect slug="employee" value={form.employee_ids} onChange={set('employee_ids')} /></label>
        )}
        {kind === 'team_pg_hq' && (
          <label className="wide"><span>Team Name<b aria-hidden="true">*</b></span>
            <RefSelect slug="team" keyBy="legacy_id" value={form.team_ids} onChange={set('team_ids')} /></label>
        )}
        {kind !== 'customer' && (
          <div><span className="lbl">Headquarter{kind === 'team_pg_hq' ? '*' : ''}</span>
            <MultiPick slug="headquarter" keyBy="legacy_id" label="Headquarter" value={form.hq_ids}
                       onChange={set('hq_ids')} /></div>
        )}
        <div><span className="lbl">Product Group{kind === 'employee' ? '' : '*'}</span>
          <MultiPick slug="product_group" keyBy="legacy_id" label="Product Group"
                     value={form.product_group_ids} onChange={set('product_group_ids')} /></div>
      </div>
      {msg && <div className={`alert ${msg.bad ? 'bad' : 'ok'} pre`}>{msg.t}</div>}
      <div className="actions">
        <button className="btn primary" disabled={busy} onClick={() => go('create')}>Create</button>
        <button className="btn danger" disabled={busy} onClick={() => go('delete')}>Delete</button>
        <button className="btn" disabled={busy} onClick={() => { setForm(f.blank); setMsg(null) }}>Clear</button>
        <button className="btn" onClick={onClose}>Close</button>
      </div>
    </div>
  )
}
