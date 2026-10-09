import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api.js'

const money = (n) => n.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })

export default function Batches() {
  const [rows, setRows] = useState([])
  const [err, setErr] = useState('')
  useEffect(() => { api.batches().then(setRows).catch((e) => setErr(e.message)) }, [])
  return (
    <div className="page">
      <h1>Batches</h1>
      <p className="lead">Every conversion that has been kept. Each one remembers the rules it was
        made with, the files that went in and the files that did not.</p>
      {err && <div className="alert bad">{err}</div>}
      <div className="scroll">
        <table>
          <thead><tr><th>#</th><th>Distributor</th><th>Period</th><th>Uploaded</th>
            <th className="r">Rows</th><th className="r">Quantity</th><th className="r">Amount</th>
            <th>By</th><th /></tr></thead>
          <tbody>
            {rows.map((b) => (
              <tr key={b.id}>
                <td className="mono">{b.id}</td>
                <td><Link to={`/batches/${b.id}`}><b>{b.distributor}</b></Link></td>
                <td>{b.month} {b.year} <span className={`chip ${b.mid_month === 'Y' ? 'warn' : 'mute'}`}>Mid {b.mid_month}</span></td>
                <td className="mono">{b.as_of}</td>
                <td className="r mono">{b.rows}</td>
                <td className="r mono">{b.total_qty.toLocaleString('en-IN')}</td>
                <td className="r mono">{money(b.total_amount)}</td>
                <td>{b.created_by}</td>
                <td><Link className="btn sm" to={`/batches/${b.id}`}>Open</Link></td>
              </tr>
            ))}
            {!rows.length && <tr><td colSpan={9} className="empty">Nothing converted yet. <Link to="/">Convert a distributor's files</Link>.</td></tr>}
          </tbody>
        </table>
      </div>
    </div>
  )
}
