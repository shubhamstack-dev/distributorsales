import { useEffect, useState } from 'react'
import { api } from '../api.js'

const num = (v) => (v === '' || v === null || v === undefined ? null : Number(v))

/** The rules are data, so they are edited here rather than in the code. */
export default function Distributors() {
  const [rows, setRows] = useState([])
  const [msg, setMsg] = useState(null)
  const load = () => api.distributors().then(setRows).catch((e) => setMsg({ bad: true, t: e.message }))
  useEffect(() => { load() }, [])

  async function save(d, patch) {
    setMsg(null)
    try { await api.updateDistributor(d.id, patch); await load(); setMsg({ t: `${d.name}'s rules saved.` }) }
    catch (e) { setMsg({ bad: true, t: e.message }); load() }
  }
  const blur = (d, key, cur, conv = (v) => v) => (e) => {
    const v = conv(e.target.value)
    if (v !== cur) save(d, { [key]: v })
  }

  return (
    <div className="page">
      <h1>Rules</h1>
      <p className="lead">Each distributor sends a different shape of file under different rules.
        A change here applies to the next conversion; batches already converted keep the rules they
        were made with.</p>
      {msg && <div className={`alert ${msg.bad ? 'bad' : 'ok'}`} role="status">{msg.t}</div>}
      <div className="cards">
        {rows.map((d) => (
          <div className="card" key={`${d.id}-${JSON.stringify(d)}`}>
            <h2>{d.name}</h2>
            <p className="muted">{d.note}</p>
            <div className="grid2">
              <label>Month steps back up to day
                <input type="number" min="1" max="28" defaultValue={d.cutoff_day}
                       onBlur={blur(d, 'cutoff_day', d.cutoff_day, Number)} /></label>
              <label>Mid Month is N up to day
                <input type="number" min="1" max="28" defaultValue={d.mid_cutoff_day}
                       onBlur={blur(d, 'mid_cutoff_day', d.mid_cutoff_day, Number)} /></label>
              <label>Invoice No
                <select defaultValue={d.invoice_mode} onChange={(e) => save(d, { invoice_mode: e.target.value })}>
                  <option value="seq">INV - 1, INV - 2 …</option>
                  <option value="file">Read from the file</option>
                </select></label>
              <label>Rate
                <select defaultValue={d.rate_mode || 'calc'} onChange={(e) => save(d, { rate_mode: e.target.value })}>
                  <option value="calc">Amount ÷ Quantity</option>
                  <option value="file">Read from the file</option>
                </select></label>
              <label>Sales sheet
                <input type="number" min="1" max="50" placeholder="Every sheet" defaultValue={d.sales_sheet ?? ''}
                       onBlur={blur(d, 'sales_sheet', d.sales_sheet, num)} /></label>
              <label>Sales return sheet
                <input type="number" min="1" max="50" placeholder="By sheet name" defaultValue={d.return_sheet ?? ''}
                       onBlur={blur(d, 'return_sheet', d.return_sheet, num)} /></label>
              <label>Sales returns
                <select defaultValue={d.negate_returns ? '1' : '0'}
                        onChange={(e) => save(d, { negate_returns: e.target.value === '1' })}>
                  <option value="1">Made negative</option>
                  <option value="0">Leave as they are</option>
                </select></label>
              <label>Product names
                <select defaultValue={d.product_keep_dot ? '1' : '0'}
                        onChange={(e) => save(d, { product_keep_dot: e.target.value === '1' })}>
                  <option value="0">No special characters</option>
                  <option value="1">Keep the '.'</option>
                </select></label>
              <label className="wide">Files this rule ticks (a pattern)
                <input defaultValue={d.pick_pattern || ''} placeholder="e.g. PW\.(xlsx|xls)$"
                       className="mono" onBlur={blur(d, 'pick_pattern', d.pick_pattern || '')} /></label>
            </div>
            <p className="fine">Up to day {d.cutoff_day}: Month is the previous month. Up to
              day {d.mid_cutoff_day}: Mid Month is N.{' '}
              {d.sales_sheet ? `Sheet ${d.sales_sheet} is read as sales${d.return_sheet ? `, sheet ${d.return_sheet} as returns` : ''}.`
                : 'Every sheet is read; a sheet named as a return is negated.'}</p>
          </div>
        ))}
      </div>
    </div>
  )
}
