import { useEffect, useState } from 'react'
import { api } from '../api.js'

/** The rules are data, so they are edited here rather than in the code. */
export default function Distributors() {
  const [rows, setRows] = useState([])
  const [msg, setMsg] = useState(null)
  const load = () => api.distributors().then(setRows).catch((e) => setMsg({ bad: true, t: e.message }))
  useEffect(() => { load() }, [])

  async function save(d, patch) {
    setMsg(null)
    try { await api.updateDistributor(d.id, patch); await load(); setMsg({ t: `${d.name} saved.` }) }
    catch (e) { setMsg({ bad: true, t: e.message }) }
  }
  return (
    <div className="page">
      <h1>Rules</h1>
      <p className="lead">Each distributor sends a different shape of file under different rules.
        Change one here and it applies to the next conversion — batches already converted keep the
        rules they were made with.</p>
      {msg && <div className={`alert ${msg.bad ? 'bad' : 'ok'}`}>{msg.t}</div>}
      <div className="cards">
        {rows.map((d) => (
          <div className="card" key={d.id}>
            <h3>{d.name}</h3>
            <p className="muted">{d.note}</p>
            <div className="grid2">
              <label>Month cut-off day
                <input type="number" min="1" max="28" defaultValue={d.cutoff_day}
                       onBlur={(e) => Number(e.target.value) !== d.cutoff_day
                         && save(d, { cutoff_day: Number(e.target.value) })} /></label>
              <label>Invoice No
                <select defaultValue={d.invoice_mode}
                        onChange={(e) => save(d, { invoice_mode: e.target.value })}>
                  <option value="seq">INV - 1, INV - 2 …</option>
                  <option value="file">Read from the file</option>
                </select></label>
              <label>Files this rule picks
                <input defaultValue={d.pick_pattern || ''} placeholder="e.g. PW\.(xlsx|xls)$"
                       onBlur={(e) => (e.target.value || '') !== (d.pick_pattern || '')
                         && save(d, { pick_pattern: e.target.value })} /></label>
              <label>Rate
                <select defaultValue={d.rate_mode || 'calc'}
                        onChange={(e) => save(d, { rate_mode: e.target.value })}>
                  <option value="calc">Amount ÷ Quantity</option>
                  <option value="file">Read from the file</option>
                </select></label>
              <label>Sales returns
                <select defaultValue={d.negate_returns ? '1' : '0'}
                        onChange={(e) => save(d, { negate_returns: e.target.value === '1' })}>
                  <option value="1">Negate quantity and amount</option>
                  <option value="0">Leave as they are</option>
                </select></label>
            </div>
            <p className="fine">On or before day {d.cutoff_day}: Month steps back one and Mid Month
              is N. After it: the current month, and Y.</p>
          </div>
        ))}
      </div>
    </div>
  )
}
