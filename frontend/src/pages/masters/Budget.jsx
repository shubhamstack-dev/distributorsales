import { useEffect, useRef, useState } from 'react'
import { api } from '../../api.js'
import RefSelect from './RefSelect.jsx'
import { MultiPick } from './AssignPanel.jsx'

const n = (v, d = 2) => (v === null || v === undefined ? '—'
  : Number(v).toLocaleString('en-IN', { maximumFractionDigits: d }))

function useYears(setErr) {
  const [years, setYears] = useState([])
  useEffect(() => { api.budgetYears().then(setYears).catch((e) => setErr(e.message)) }, []) // eslint-disable-line react-hooks/exhaustive-deps
  return years
}

/** Budget Upload, as the old screen: a year and the AbbottBudgetFormet.xlsx.
 *  Checked first (nothing saved, every bad row named), posted only when clean. */
export function BudgetUpload() {
  const [err, setErr] = useState('')
  const years = useYears(setErr)
  const [year, setYear] = useState('')
  const [file, setFile] = useState(null)
  const [r, setR] = useState(null)
  const [busy, setBusy] = useState(false)
  const pick = useRef(null)

  async function send(dry) {
    if (!year) { setErr('Select the year.'); return }
    if (!file) { setErr('Choose the .xlsx file.'); return }
    setErr(''); setBusy(true)
    try { setR(await api.budgetUpload(year, file, dry)) } catch (e) { setErr(e.message) } finally { setBusy(false) }
  }
  const clean = r && r.dry_run && r.error_rows === 0 && r.ok_rows > 0

  return (
    <div className="page">
      <div className="head"><div>
        <p className="crumb">Budgeting</p>
        <h1>Budget Upload</h1>
        <p className="lead">The year and the budget file (AbbottBudgetFormet.xlsx). The file is checked
          first and nothing is saved until every row is right. Each month's value is the units times
          the SKU's NRV. Sending a year again updates its rows; the actuals are kept.</p>
      </div></div>

      <section className="panel">
        <div className="grid2 de-form">
          <label><span>Select Year<b aria-hidden="true">*</b></span>
            <select value={year} onChange={(e) => { setYear(e.target.value); setR(null) }}>
              <option value="">-- Select Year --</option>
              {years.map((y) => <option key={y} value={y}>{y}</option>)}
            </select></label>
          <label><span>Upload File Here<b aria-hidden="true">*</b></span>
            <div className="file-pick">
              <button type="button" className="btn sm" onClick={() => pick.current?.click()}>Browse…</button>
              <span className={file ? '' : 'faint'}>{file ? file.name : 'No file selected.'}</span>
              <input ref={pick} type="file" hidden accept=".xlsx,.xlsm"
                     onChange={(e) => { setFile(e.target.files[0] || null); setR(null); e.target.value = '' }} />
            </div>
            <small className="fine">Self validate the data before posting (only .xlsx).{' '}
              <button type="button" className="linkish" onClick={() => api.budgetTemplate().catch((e) => setErr(e.message))}>
                Download the format</button></small>
          </label>
        </div>
        <div className="actions">
          <button className="btn" disabled={busy} onClick={() => send(true)}>{busy ? 'Checking…' : 'Check'}</button>
          <button className="btn primary" disabled={busy || !clean} onClick={() => send(false)}
                  title={clean ? '' : 'Check the file first; it posts when no row is wrong'}>Upload</button>
        </div>
        {err && <div className="alert bad">{err}</div>}
      </section>

      {r && (
        <section className={`panel${r.error_rows ? ' blocked' : ''}`}>
          <h2>{r.dry_run ? (r.error_rows ? 'Put these right first' : 'Ready to post') : 'Posted'}</h2>
          {r.message && <p className="lead">{r.message}</p>}
          <div className="de-boxes">
            <div className="de-box"><span>Rows in the file</span><b>{n(r.rows, 0)}</b></div>
            <div className={`de-box${r.error_rows ? ' warn' : ''}`}><span>Rows with a problem</span><b>{n(r.error_rows, 0)}</b></div>
            <div className="de-box"><span>{r.dry_run ? 'Would be added' : 'Added'}</span><b>{n(r.added, 0)}</b></div>
            <div className="de-box"><span>{r.dry_run ? 'Would be updated' : 'Updated'}</span><b>{n(r.updated, 0)}</b></div>
            <div className="de-box"><span>Total units</span><b>{n(r.total_units)}</b></div>
            <div className="de-box"><span>Total value (units × NRV)</span><b>{n(r.total_value)}</b></div>
          </div>
          {r.errors.length > 0 && (
            <div className="scroll"><table className="grid-old">
              <thead><tr><th className="sno">Row</th><th>What is wrong</th></tr></thead>
              <tbody>{r.errors.map((e) => (
                <tr key={e.row}><td className="sno">{e.row}</td><td>{e.problems.join('; ')}</td></tr>
              ))}</tbody>
            </table></div>
          )}
          {r.error_rows > r.errors.length && <p className="fine">and {r.error_rows - r.errors.length} more rows.</p>}
          {r.warnings.length > 0 && (
            <div className="alert"><b>Worth a look (these do not stop it):</b>
              <ul>{r.warnings.map((w, i) => <li key={i}>{w}</li>)}</ul></div>
          )}
        </section>
      )}
    </div>
  )
}

const BLANK = { employee_id: null, hq_id: null, product_group_id: null, product_brand_id: null, product_id: null }
const PAGE = 200

/** Budget Report, as the old screen and its Excel: TARGET_YEAR … PRODUCT_NAME,
 *  the twelve months' units, the twelve months' value, and a Total row. The
 *  values are NPR in BUDGET_MASTER and shown in INR (or NPR, if chosen). */
export function BudgetReport() {
  const [err, setErr] = useState('')
  const years = useYears(setErr)
  const [year, setYear] = useState('')
  const [f, setF] = useState(BLANK)
  const [currency, setCurrency] = useState('INR')
  const [r, setR] = useState(null)
  const [page, setPage] = useState(1)
  const [busy, setBusy] = useState(false)
  const set = (k) => (v) => setF((x) => ({ ...x, [k]: v }))
  const params = { year, currency, ...Object.fromEntries(Object.entries(f).filter(([, v]) => v)) }

  async function go() {
    if (!year) { setErr('Select the year.'); return }
    setErr(''); setBusy(true)
    try { setR(await api.budgetReport(params)); setPage(1) } catch (e) { setErr(e.message) } finally { setBusy(false) }
  }
  const clear = () => { setYear(''); setF(BLANK); setCurrency('INR'); setR(null); setErr('') }
  const pages = r ? Math.max(1, Math.ceil(r.rows.length / PAGE)) : 1
  const shown = r ? r.rows.slice((page - 1) * PAGE, page * PAGE) : []
  const sum = (a) => a.reduce((x, y) => x + y, 0)

  return (
    <div className="page">
      <div className="head"><div>
        <p className="crumb">Budgeting</p>
        <h1>Budget Report</h1>
        <p className="lead">BUDGET_MASTER for a year, as the old report: each row's units and value
          month by month, with a Total. The budget is kept in NPR; the report shows it in INR.</p>
      </div></div>

      <section className="panel">
        <div className="grid2 br-form">
          <label><span>Year<b aria-hidden="true">*</b></span>
            <select value={year} onChange={(e) => setYear(e.target.value)}>
              <option value="">-- Select Year --</option>
              {years.map((y) => <option key={y} value={y}>{y}</option>)}
            </select></label>
          <label><span>Employee</span>
            <RefSelect slug="employee" blank="All" value={f.employee_id} onChange={set('employee_id')} /></label>
          <label><span>Headquarter</span>
            <RefSelect slug="headquarter" keyBy="legacy_id" blank="All" value={f.hq_id} onChange={set('hq_id')} /></label>
          <label><span>Product Group</span>
            <RefSelect slug="product_group" keyBy="legacy_id" blank="All" value={f.product_group_id} onChange={set('product_group_id')} /></label>
          <label><span>Product Brand</span>
            <RefSelect slug="brand" blank="All" value={f.product_brand_id} onChange={set('product_brand_id')} /></label>
          <label><span>Product</span>
            <RefSelect slug="sku" blank="All" value={f.product_id} onChange={set('product_id')} /></label>
          <label><span>Value in</span>
            <select value={currency} onChange={(e) => setCurrency(e.target.value)}>
              <option value="INR">INR</option>
              <option value="NPR">NPR (as kept)</option>
            </select></label>
        </div>
        <div className="actions">
          <button className="btn primary" disabled={busy} onClick={go}>{busy ? 'Loading…' : 'Go'}</button>
          <button className="btn" onClick={clear}>Clear</button>
          <button className="btn" disabled={!year}
                  onClick={() => api.budgetExport(params).catch((e) => setErr(e.message))}>Excel</button>
        </div>
        {err && <div className="alert bad">{err}</div>}
      </section>

      {r && (
        <section className="panel">
          <p className="muted">{r.rows.length.toLocaleString('en-IN')} rows for {r.year}. {r.note}
            {r.left_out > 0 && ` ${r.left_out} budget row(s) name a SKU not in the SKU master and are left out, as the old report did.`}</p>
          <div className="de-boxes">
            <div className="de-box"><span>Total units</span><b>{n(sum(r.total_units))}</b></div>
            <div className="de-box"><span>Total value ({r.currency})</span><b>{n(sum(r.total_values))}</b></div>
          </div>
          <div className="scroll"><table className="grid-old budget-grid">
            <thead><tr>
              <th className="sno">S.No</th><th>Year</th><th>Employee Id</th><th>Employee Name</th><th>HQ Id</th><th>HQ Name</th>
              <th>PG Id</th><th>Product Group</th><th>Brand Id</th><th>Product Brand</th><th>Product Id</th><th>Product Name</th>
              {r.months.map((m) => <th key={`u${m}`} className="r">{m.slice(0, 3).toUpperCase()} UNITS</th>)}
              {r.months.map((m) => <th key={`v${m}`} className="r">{m.toUpperCase()}</th>)}
            </tr></thead>
            <tbody>
              {shown.map((x, i) => (
                <tr key={x.id}>
                  <td className="sno">{(page - 1) * PAGE + i + 1}</td>
                  <td>{x.target_year}</td><td className="mono">{x.employee_id}</td>
                  <td><span className="primary-name">{x.employee_name || '—'}</span></td>
                  <td className="mono">{x.hq_id}</td><td>{x.hq_name}</td>
                  <td className="mono">{x.product_group_id}</td><td>{x.product_group}</td>
                  <td className="mono">{x.product_brand_id}</td><td>{x.product_brand}</td>
                  <td className="mono">{x.product_id}</td><td>{x.product_name}</td>
                  {x.units.map((v, j) => <td key={`u${j}`} className="r mono">{n(v)}</td>)}
                  {x.values.map((v, j) => <td key={`v${j}`} className="r mono">{n(v)}</td>)}
                </tr>
              ))}
              {!r.rows.length && <tr><td colSpan={36} className="empty">No budget for these choices.</td></tr>}
            </tbody>
            {r.rows.length > 0 && (
              <tfoot><tr>
                <td /><td colSpan={11}><b>Total</b></td>
                {r.total_units.map((v, j) => <td key={`u${j}`} className="r mono"><b>{n(v)}</b></td>)}
                {r.total_values.map((v, j) => <td key={`v${j}`} className="r mono"><b>{n(v)}</b></td>)}
              </tr></tfoot>
            )}
          </table></div>
          {pages > 1 && (
            <div className="pager">
              <button className="btn sm" disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous</button>
              <span className="muted">Page {page} of {pages}</span>
              <button className="btn sm" disabled={page >= pages} onClick={() => setPage(page + 1)}>Next</button>
            </div>
          )}
        </section>
      )}
    </div>
  )
}


/** What a zero-row check found, in words. */
function said(r) {
  const out = [`${r.added} row${r.added === 1 ? '' : 's'} to make`]
  if (r.already_there) out.push(`${r.already_there} already there (left as they are)`)
  const left = Object.entries(r.left_out || {})
  if (left.length) out.push(`left out, not in the masters: ${left.map(([k, v]) => `${v} (${k})`).join(', ')}`)
  return out.join('; ') + '.'
}

/** Zero Budget: 0-budget rows, (a) for every employee / HQ / product budgeted in
 *  one year and missing from another, (b) for a new product of an employee.
 *  Each checks first, says how many, and asks. Rows already there are kept. */
export function BudgetZero() {
  const [err, setErr] = useState('')
  const years = useYears(setErr)
  const [carry, setCarry] = useState({ from_year: '', to_year: '', employee_id: null })
  const [zero, setZero] = useState({ year: '', employee_id: null, hq_ids: [], product_ids: [] })
  // Product Group and Product Brand narrow the products to choose from (as the old forms)
  const [pg, setPg] = useState(null)
  const [brand, setBrand] = useState(null)
  const narrow = { ...(pg ? { product_group_id: pg } : {}), ...(brand ? { product_brand_id: brand } : {}) }
  const [msg, setMsg] = useState({})
  const [busy, setBusy] = useState(false)

  async function run(which, call, body) {
    setErr(''); setBusy(true); setMsg((m) => ({ ...m, [which]: null }))
    try {
      const dry = await call({ ...body, dry_run: true })
      if (!dry.added) { setMsg((m) => ({ ...m, [which]: { ok: false, t: `Nothing to make: ${said(dry)}` } })); return }
      if (!window.confirm(`Make the 0-budget rows for ${dry.year}?\n\n${said(dry)}`)) return
      const r = await call(body)
      setMsg((m) => ({ ...m, [which]: { ok: true, t: `Made ${r.added} row${r.added === 1 ? '' : 's'} for ${r.year}.` } }))
    } catch (e) { setMsg((m) => ({ ...m, [which]: { ok: false, t: e.message } })) } finally { setBusy(false) }
  }
  const yearSel = (value, onChange, blank = '-- Select Year --') => (
    <select value={value} onChange={(e) => onChange(e.target.value)}>
      <option value="">{blank}</option>
      {years.map((y) => <option key={y} value={y}>{y}</option>)}
    </select>
  )

  return (
    <div className="page">
      <div className="head"><div>
        <p className="crumb">Budgeting</p>
        <h1>Zero Budget</h1>
        <p className="lead">Budget rows with 0 units and 0 value, so a year has a row for every employee,
          HQ and product it should, ready to be filled by the next Budget Upload. A row already there is
          never changed.</p>
      </div></div>

      <section className="panel">
        <h2>From another year</h2>
        <p className="fine">Every employee / HQ / product with a budget in the first year and none in the
          second gets a 0 row in the second. Leave Employee on All for everyone.</p>
        <div className="grid2 br-form">
          <label><span>Budget of year<b aria-hidden="true">*</b></span>
            {yearSel(carry.from_year, (v) => setCarry((c) => ({ ...c, from_year: v })))}</label>
          <label><span>Make rows in year<b aria-hidden="true">*</b></span>
            {yearSel(carry.to_year, (v) => setCarry((c) => ({ ...c, to_year: v })))}</label>
          <label><span>Employee</span>
            <RefSelect slug="employee" blank="All" value={carry.employee_id}
                       onChange={(v) => setCarry((c) => ({ ...c, employee_id: v }))} /></label>
        </div>
        <div className="actions">
          <button className="btn primary" disabled={busy || !carry.from_year || !carry.to_year}
                  onClick={() => run('carry', api.budgetCarry, carry)}>Make the 0 rows</button>
        </div>
        {msg.carry && <div className={`alert ${msg.carry.ok ? 'ok' : 'bad'}`}>{msg.carry.t}</div>}
      </section>

      <section className="panel">
        <h2>A new product</h2>
        <p className="fine">A 0 row for each product chosen, in each HQ chosen. Product Group and Product
          Brand narrow the list of products ("All" over the list ticks every one of a brand). Leave the HQs
          empty for the HQs the employee covers on Employee Terr-PG.</p>
        <div className="grid2 br-form">
          <label><span>Year<b aria-hidden="true">*</b></span>
            {yearSel(zero.year, (v) => setZero((z) => ({ ...z, year: v })))}</label>
          <label><span>Employee<b aria-hidden="true">*</b></span>
            <RefSelect slug="employee" value={zero.employee_id}
                       onChange={(v) => setZero((z) => ({ ...z, employee_id: v }))} /></label>
        </div>
        <div className="grid2 br-form">
          <label><span>Product Group</span>
            <RefSelect slug="product_group" blank="All" value={pg}
                       onChange={(v) => { setPg(v); setBrand(null) }} /></label>
          <label><span>Product Brand</span>
            <RefSelect slug="brand" blank="All" value={brand} params={pg ? { product_group_id: pg } : {}}
                       onChange={setBrand} /></label>
        </div>
        <div className="grid2 assign">
          <div><span className="lbl">Headquarter</span>
            <MultiPick slug="headquarter" keyBy="legacy_id" label="Headquarter" value={zero.hq_ids}
                       onChange={(v) => setZero((z) => ({ ...z, hq_ids: v }))} /></div>
          <div><span className="lbl">Product*</span>
            <MultiPick slug="sku" label="Product" value={zero.product_ids} params={narrow}
                       onChange={(v) => setZero((z) => ({ ...z, product_ids: v }))} /></div>
        </div>
        <div className="actions">
          <button className="btn primary" disabled={busy || !zero.year || !zero.employee_id || !zero.product_ids.length}
                  onClick={() => run('zero', api.budgetZero, zero)}>Make the 0 rows</button>
          <button className="btn" onClick={() => { setZero({ year: '', employee_id: null, hq_ids: [], product_ids: [] }); setPg(null); setBrand(null); setMsg((m) => ({ ...m, zero: null })) }}>Clear</button>
        </div>
        {msg.zero && <div className={`alert ${msg.zero.ok ? 'ok' : 'bad'}`}>{msg.zero.t}</div>}
      </section>
      {err && <div className="alert bad">{err}</div>}
    </div>
  )
}


const MONTH_NAMES = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August',
  'September', 'October', 'November', 'December']

/** Calculate Actuals, as the old screen: a month and a year; every budget row of
 *  the year gets that month's actuals from MAPPING_MASTER and MAPPING_MASTER_MID. */
export function BudgetActuals() {
  const [err, setErr] = useState('')
  const years = useYears(setErr)
  const [month, setMonth] = useState('')
  const [year, setYear] = useState('')
  const [r, setR] = useState(null)
  const [busy, setBusy] = useState(false)

  async function calc() {
    if (!month || !year) { setErr('Select the month and the year.'); return }
    if (!window.confirm(`Work out ${month} ${year}'s actuals on every budget row of ${year}?\n\n`
      + `The month's ACTUAL, ACTUAL_UNITS, MID_ACTUAL, MID_ACTUAL_UNITS and RETURN are replaced.`)) return
    setErr(''); setBusy(true); setR(null)
    try { setR(await api.budgetActuals(year, month)) } catch (e) { setErr(e.message) } finally { setBusy(false) }
  }

  return (
    <div className="page">
      <div className="head"><div>
        <p className="crumb">Budgeting</p>
        <h1>Calculate Actuals</h1>
        <p className="lead">For the month chosen, every budget row of the year gets its sales from
          MAPPING_MASTER (and the mid-month sales from MAPPING_MASTER_MID): by HQ, product group, brand,
          product and category, as the old procedures worked them out.</p>
      </div></div>

      <section className="panel">
        <div className="grid2 de-form">
          <label><span>Month<b aria-hidden="true">*</b></span>
            <select value={month} onChange={(e) => setMonth(e.target.value)}>
              <option value="">-- Select Month --</option>
              {MONTH_NAMES.map((m) => <option key={m} value={m}>{m}</option>)}
            </select></label>
          <label><span>Year<b aria-hidden="true">*</b></span>
            <select value={year} onChange={(e) => setYear(e.target.value)}>
              <option value="">-- Select Year --</option>
              {years.map((y) => <option key={y} value={y}>{y}</option>)}
            </select></label>
        </div>
        <div className="actions">
          <button className="btn primary" disabled={busy} onClick={calc}>{busy ? 'Calculating…' : 'Calculate'}</button>
          <button className="btn" onClick={() => { setMonth(''); setYear(''); setR(null); setErr('') }}>Clear</button>
        </div>
        {err && <div className="alert bad">{err}</div>}
        {r && <>
          <div className="alert ok">{r.message}</div>
          <div className="de-boxes">
            <div className="de-box"><span>Budget rows</span><b>{n(r.rows, 0)}</b></div>
            <div className="de-box"><span>Rows with sales</span><b>{n(r.rows_with_sales, 0)}</b></div>
            <div className="de-box"><span>Actual (lakh, NPR)</span><b>{n(r.actual, 4)}</b></div>
            <div className="de-box"><span>Actual units</span><b>{n(r.units)}</b></div>
            <div className="de-box"><span>Mid actual (lakh, NPR)</span><b>{n(r.mid_actual, 4)}</b></div>
            <div className="de-box"><span>Mid actual units</span><b>{n(r.mid_units)}</b></div>
            <div className="de-box"><span>Returns (INR)</span><b>{n(r.returns)}</b></div>
            <div className={`de-box${r.sales_without_budget_row ? ' warn' : ''}`}><span>Sales with no budget row</span>
              <b>{n(r.sales_without_budget_row, 0)}</b></div>
          </div>
          <p className="fine">The actuals add each employee's row of an HQ: the same sales stand on every
            employee budgeted for that HQ and product, as in the old system.</p>
        </>}
      </section>
    </div>
  )
}

