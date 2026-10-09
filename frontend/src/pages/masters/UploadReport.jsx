/** What an upload did (or, on a check, would do), sheet by sheet. */
export default function UploadReport({ report }) {
  if (!report) return null
  const total = (k) => report.tables.reduce((a, t) => a + t[k], 0)
  return (
    <>
      <div className={`alert ${report.dry_run ? 'info' : 'ok'}`} role="status">
        {report.dry_run
          ? <><b>Checked, nothing saved yet.</b> {total('added')} rows would be added, {total('updated')} updated
              and {total('unchanged')} are already as stored
              {total('skipped') ? `; ${total('skipped')} would be left out (reasons below)` : ''}.
              {total('added') + total('updated') ? ' If that is right, import.' : ' There is nothing to import.'}</>
          : <><b>Imported.</b> {total('added')} rows added, {total('updated')} updated, {total('unchanged')} already as stored
              {total('skipped') ? `, ${total('skipped')} left out (reasons below)` : ''}.</>}
      </div>
      {report.files.filter((f) => !f.master).map((f, i) => (
        <div key={i} className="alert warn">{f.file}{f.sheet ? ` › ${f.sheet}` : ''}: {f.note}</div>
      ))}
      <div className="scroll report">
        <table>
          <thead><tr><th>Sheet</th><th>Read into</th><th className="r">Rows</th><th className="r">Added</th>
            <th className="r">Updated</th><th className="r">Unchanged</th><th className="r">Left out</th></tr></thead>
          <tbody>{report.tables.map((t, i) => (
            <tr key={i}>
              <td className="wrap">{t.sheet}
                {t.errors.length > 0 && <ul className="errs">{t.errors.map((e, j) => <li key={j}>{e}</li>)}</ul>}
                {t.warnings.length > 0 && <ul className="errs w">{t.warnings.map((e, j) => <li key={j}>{e}</li>)}</ul>}
                {t.ignored.length > 0 && <ul className="errs i">{t.ignored.slice(0, 6).map((e, j) => <li key={j}>{e}</li>)}
                  {t.ignored.length > 6 && <li>and {t.ignored.length - 6} more columns read past</li>}</ul>}
              </td>
              <td><b>{t.master}</b></td>
              <td className="n">{t.rows}</td><td className="n add">{t.added}</td>
              <td className="n">{t.updated}</td><td className="n">{t.unchanged}</td>
              <td className={`n ${t.skipped ? 'skip' : ''}`}>{t.skipped}</td>
            </tr>
          ))}</tbody>
        </table>
      </div>
    </>
  )
}
