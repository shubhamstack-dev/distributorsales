import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { api } from '../api.js'

const money = (n) => n.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })

export default function BatchDetail() {
  const { id } = useParams()
  const nav = useNavigate()
  const [b, setB] = useState(null)
  const [data, setData] = useState({ rows: [], total: 0, page: 1, size: 100 })
  const [q, setQ] = useState('')
  const [page, setPage] = useState(1)
  const [msg, setMsg] = useState(null)

  useEffect(() => { api.batch(id).then(setB).catch((e) => setMsg({ bad: true, t: e.message })) }, [id])
  useEffect(() => {
    api.rows(id, page, 100, q).then(setData).catch((e) => setMsg({ bad: true, t: e.message }))
  }, [id, page, q])

  if (!b) return <div className="page">{msg ? <div className="alert bad">{msg.t}</div> : 'Loading…'}</div>
  const pages = Math.max(1, Math.ceil(data.total / data.size))
  const used = b.files.filter((f) => f.used)
  const left = b.files.filter((f) => !f.used)

  return (
    <div className="page">
      <div className="head">
        <div><h1>Batch {b.id} — {b.distributor}</h1>
          <p className="lead">{b.month} {b.year}, Mid Month {b.mid_month}. Uploaded {b.as_of} by
            {' '}{b.created_by}; month cut-off day {b.cutoff_day}, Mid Month day {b.mid_cutoff_day}.</p></div>
        <div className="actions">
          <button className="btn primary" onClick={() => api.download(b.id)
            .then((n) => setMsg({ t: `${n} downloaded.` }))
            .catch((e) => setMsg({ bad: true, t: e.message }))}>Download Excel</button>
          <button className="btn danger" onClick={async () => {
            if (!confirm(`Delete batch ${b.id} and its ${b.rows} rows?`)) return
            try { await api.deleteBatch(b.id); nav('/batches') }
            catch (e) { setMsg({ bad: true, t: e.message }) }
          }}>Delete</button>
        </div>
      </div>
      {msg && <div className={`alert ${msg.bad ? 'bad' : 'ok'}`}>{msg.t}</div>}
      {b.notes && <div className="alert info">{b.notes}</div>}

      <div className="kpis">
        <div className="kpi hl"><div className="k">Rows</div><div className="v">{b.rows}</div>
          <div className="s">{b.omitted} left out: quantity and free both zero</div></div>
        <div className="kpi"><div className="k">Quantity</div>
          <div className="v">{b.total_qty.toLocaleString('en-IN')}</div></div>
        <div className="kpi"><div className="k">Amount</div><div className="v">{money(b.total_amount)}</div>
          <div className="s">Returns included, as negatives</div></div>
        <div className="kpi"><div className="k">Files</div><div className="v">{used.length}</div>
          <div className="s">{left.length} offered and not used</div></div>
      </div>

      <details open>
        <summary>Which files went in</summary>
        <ul className="files">
          {b.files.map((f) => (
            <li key={f.name} className={f.used ? '' : 'off'}>
              <span className="nm">{f.name}</span>
              <span className={`chip ${f.used ? 'ok' : 'mute'}`}>{f.used ? `${f.rows} rows` : 'not used'}</span>
              <span className="meta">{f.layout || f.detail}</span>
            </li>
          ))}
        </ul>
      </details>

      <div className="picker">
        <input type="search" aria-label="Search rows" placeholder="Search customer or product" value={q}
               onChange={(e) => { setQ(e.target.value); setPage(1) }} />
        <span className="fine">{data.total} rows</span>
        <button className="btn sm" disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous</button>
        <span className="fine">page {page} of {pages}</span>
        <button className="btn sm" disabled={page >= pages} onClick={() => setPage(page + 1)}>Next</button>
      </div>
      <div className="scroll">
        <table className="rows">
          <thead><tr><th>Distributor</th><th>Invoice</th><th>Month</th><th>Year</th><th>Mid</th>
            <th>Customer</th><th>Product</th><th className="r">Qty</th><th className="r">Free</th>
            <th className="r">Rate</th><th className="r">B.Amount</th><th className="r">Amount</th></tr></thead>
          <tbody>
            {data.rows.map((r) => (
              <tr key={r.seq} className={r.is_return ? 'ret' : ''}>
                <td>{r.distributor_name}</td><td className="mono">{r.invoice_no}</td>
                <td>{r.month}</td><td className="mono">{r.year}</td><td>{r.mid_month}</td>
                <td>{r.customer_name}</td><td>{r.product_name}</td>
                <td className="r mono">{r.quantity.toLocaleString('en-IN')}</td>
                <td className="r mono">{r.free_quantity}</td>
                <td className="r mono">{r.rate.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 4 })}</td>
                <td className="r mono">{money(r.b_amount)}</td>
                <td className="r mono">{money(r.amount)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
