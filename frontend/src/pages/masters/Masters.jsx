import { Navigate, Route, Routes } from 'react-router-dom'
import MasterPage from './MasterPage.jsx'
import MasterUpload from './MasterUpload.jsx'
import TerrPgPage from './TerrPgPage.jsx'
import DataError from './DataError.jsx'
import { BudgetReport, BudgetUpload, BudgetZero } from './Budget.jsx'
import { useMasterMeta } from './meta.js'

/** Every master screen. They are chosen from the Masters menu in the top bar,
 *  so each one has the full width. The screens are drawn from the server's
 *  description of each table (api /masters/meta), so a field added on the
 *  server appears here without a code change. */
export default function Masters() {
  const [meta, err] = useMasterMeta()

  if (err) return <div className="page"><div className="alert bad">{err}</div></div>
  if (!meta) return <div className="page muted">Loading the masters…</div>

  return (
    <Routes>
      <Route index element={<Navigate to="upload" replace />} />
      <Route path="upload" element={<MasterUpload meta={meta} />} />
      <Route path="terr-pg/:kind" element={<TerrPgPage meta={meta} />} />
      <Route path="data-error" element={<DataError />} />
      <Route path="budget-upload" element={<BudgetUpload />} />
      <Route path="budget-report" element={<BudgetReport />} />
      <Route path="budget-zero" element={<BudgetZero />} />
      {meta.map((m) => (
        <Route key={m.slug} path={m.slug} element={<MasterPage key={m.slug} spec={m} />} />
      ))}
      <Route path="*" element={<Navigate to="upload" replace />} />
    </Routes>
  )
}
