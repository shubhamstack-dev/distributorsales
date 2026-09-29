import { useEffect, useState } from 'react'
import { api } from '../../api.js'

const fmt = (n, d = 4, min = 0) =>
  Number(n).toLocaleString('en-IN', { minimumFractionDigits: min, maximumFractionDigits: d })

/** The INR / NPR rate in force on a day, both ways, and a quick conversion.
 *  Only one direction is stored; the other is its inverse, so they always agree. */
export default function CurrencyTool() {
  const [on, setOn] = useState(new Date().toISOString().slice(0, 10))
  const [amount, setAmount] = useState('1000')
  const [dir, setDir] = useState('NPR>INR')
  const [rates, setRates] = useState(null)
  const [err, setErr] = useState('')

  useEffect(() => {
    setErr('')
    Promise.all([api.rate('INR', 'NPR', on), api.rate('NPR', 'INR', on)])
      .then(([a, b]) => setRates({ a, b }))
      .catch((e) => { setRates(null); setErr(e.message) })
  }, [on])

  const [frm, to] = dir.split('>')
  const r = rates && (frm === 'INR' ? rates.a : rates.b)
  const out = r && amount !== '' ? Number(amount) * r.rate : null

  return (
    <div className="panel fx">
      <div className="fx-rates">
        <label><span>Rate on</span>
          <input type="date" value={on} onChange={(e) => setOn(e.target.value)} /></label>
        {rates ? (
          <div className="fx-pair" aria-live="polite">
            <div><b className="mono">1 INR = {fmt(rates.a.rate)} NPR</b></div>
            <div className="muted mono">1 NPR = {fmt(rates.b.rate, 6)} INR</div>
            <div className="fine">In force from {rates.a.effective_from}</div>
          </div>
        ) : <div className="fx-pair muted">{err || 'Loading…'}</div>}
      </div>
      <div className="fx-convert">
        <label><span>Amount</span>
          <input type="number" step="any" value={amount} onChange={(e) => setAmount(e.target.value)} /></label>
        <label><span>Convert</span>
          <select value={dir} onChange={(e) => setDir(e.target.value)}>
            <option value="NPR>INR">NPR to INR</option>
            <option value="INR>NPR">INR to NPR</option>
          </select></label>
        <div className="fx-out">
          <span className="fine">{to}</span>
          <b className="mono">{out === null ? '—' : fmt(out, 2, 2)}</b>
        </div>
      </div>
    </div>
  )
}
