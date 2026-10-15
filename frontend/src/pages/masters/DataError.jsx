import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../../api.js'

const n = (v) => (v === null || v === undefined ? '—' : Number(v).toLocaleString('en-IN'))
const money = (v) => (v === null || v === undefined ? '—'
  : Number(v).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 }))

/** Data Error, as the old "Resolve" screen: a distributor's last conversion,
 *  rows in temp (sales_row) against rows in main (MAPPING_MASTER, or
 *  MAPPING_MASTER_MID for Mid Month), and what is wrong with them. */
export default function DataError() {
  const [dists, setDists] = useState([])
  const [dist, setDist] = useState('')
  const [type, setType] = useState('invoice')
  const [r, setR] = useState(null)
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => { api.distributors().then(setDists).catch((e) => setErr(e.message)) }, [])

  async function submit() {
    if (!dist) { setErr('Choose a distributor.'); return }
    setErr(''); setBusy(true)
    try { setR(await api.dataError(dist, type)) } catch (e) { setErr(e.message) } finally { setBusy(false) }
  }
  const clear = () => { setDist(''); setType('invoice'); setR(null); setErr('') }

  const boxes = r && [
    ['No of Records in Temp', n(r.temp)],
    ['No of Records in Main', n(r.main)],
    ['Records Not Inserted', n(r.not_inserted), r.not_inserted > 0],
    ['No of Duplicate Records', n(r.duplicates), r.duplicates > 0],
    ['Incomplete in Main', n(r.incomplete), r.incomplete > 0],
    ['Month', r.month || '—'],
    ['Year', r.year || '—'],
    ['Sum of Amount in Main (INR)', money(r.amount_inr)],       // as the old screen
    ['Sum of Amount in Main (NPR)', money(r.amount_npr)],       // as MAPPING_MASTER keeps it
  ]

  return (
    <div className="page">
      <div className="head"><div>
        <p className="crumb">Sales</p>
        <h1>Data Error</h1>
        <p className="lead">A distributor's last conversion: the rows that came in (the sales rows
          table) against the rows in the main table, with any repeated or incomplete.</p>
      </div></div>

      <section className="panel">
        <div className="grid2 de-form">
          <label><span>Distributor<b aria-hidden="true">*</b></span>
            <select value={dist} onChange={(e) => setDist(e.target.value)}>
              <option value="">Choose…</option>
              {dists.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
            </select></label>
          <label><span>File Type<b aria-hidden="true">*</b></span>
            <select value={type} onChange={(e) => setType(e.target.value)}>
              <option value="invoice">Invoice (MAPPING_MASTER)</option>
              <option value="mid">Mid Month (MAPPING_MASTER_MID)</option>
            </select></label>
        </div>
        <div className="actions">
          <button className="btn primary" disabled={busy} onClick={submit}>{busy ? 'Checking…' : 'Submit'}</button>
          <button className="btn" onClick={clear}>Clear</button>
        </div>
        {err && <div className="alert bad">{err}</div>}

        {r && <>
          <div className="de-boxes">
            {boxes.map(([label, v, warn]) => (
              <div key={label} className={`de-box${warn ? ' warn' : ''}`}><span>{label}</span><b>{v}</b></div>
            ))}
          </div>
          <p className="fine">
            {r.batch_id
              ? <>From <Link to={`/batches/${r.batch_id}`}>batch {r.batch_id}</Link>, converted
                  for {r.as_of} (Mid Month {r.mid_month}); main is {r.table} for DIST_ID {r.dist_id ?? '—'}.
                  {r.temp === 0 && ' The sales rows table now holds a later conversion, so Temp is 0.'}</>
              : null}
            {r.note && <> {r.note}</>}
          </p>
        </>}
      </section>

      {r?.duplicate_rows?.length > 0 && <Rows title="Duplicate records" note="Rows repeating each other's invoice, customer, product, quantities and rate." rows={r.duplicate_rows} />}
      {r?.incomplete_rows?.length > 0 && <Rows title="Incomplete in main" note="Rows without a product, customer or HQ." rows={r.incomplete_rows} />}
    </div>
  )
}

function Rows({ title, note, rows }) {
  return (
    <section className="panel">
      <h2>{title}</h2>
      <p className="fine">{note}</p>
      <div className="scroll"><table className="grid-old">
        <thead><tr><th className="sno">ID</th><th>Invoice</th><th>Customer</th><th>Product</th><th>HQ</th>
          <th className="r">Qty</th><th className="r">Free</th><th className="r">Return</th><th className="r">Rate</th><th className="r">Value</th></tr></thead>
        <tbody>{rows.map((x) => (
          <tr key={x.id}><td className="sno">{x.id}</td><td>{x.invoice_no}</td><td>{x.customer}</td><td>{x.product}</td>
            <td>{x.hq || <span className="faint">—</span>}</td>
            <td className="r">{n(x.sales_qty)}</td><td className="r">{n(x.free_quantity)}</td>
            <td className="r">{n(x.return_quantity)}</td><td className="r">{money(x.rate)}</td><td className="r">{money(x.sales_value)}</td></tr>
        ))}</tbody>
      </table></div>
    </section>
  )
}
