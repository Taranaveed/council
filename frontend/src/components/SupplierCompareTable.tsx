export type SupplierCompareRow = {
  rank?: number;
  vendor?: string;
  title?: string;
  link?: string;
  unit_price?: string;
  currency?: string;
  moq?: number | string | null;
  origin?: string;
  risk_score?: number;
  risk_reasons?: string[];
  landed_mid?: string | null;
  best_pick?: boolean;
};

type Props = {
  rows: SupplierCompareRow[];
  emptyMessage?: string;
};

/** Phase 2 — side-by-side supplier decision table. */
export function SupplierCompareTable({
  rows,
  emptyMessage = 'No suppliers to compare yet.',
}: Props) {
  if (!rows.length) {
    return <p className="dash-meta">{emptyMessage}</p>;
  }

  return (
    <div className="compare-table">
      <div className="compare-table__head">
        <p className="compare-table__title">Supplier comparison</p>
        <p className="compare-table__hint">
          Risk is 1–10 (lower is safer). Landed mid is an estimate — verify on the product page.
        </p>
      </div>
      <div className="compare-table__scroll">
        <table>
          <thead>
            <tr>
              <th>#</th>
              <th>Vendor</th>
              <th>Unit</th>
              <th>MOQ</th>
              <th>Origin</th>
              <th>Risk</th>
              <th>Landed mid</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => {
              const risk = typeof r.risk_score === 'number' ? r.risk_score : null;
              const tone =
                risk == null ? '' : risk <= 3 ? 'ok' : risk <= 6 ? 'mid' : 'bad';
              return (
                <tr key={`${r.vendor}-${r.link}-${i}`} className={r.best_pick ? 'is-best' : ''}>
                  <td>{r.rank ?? i + 1}</td>
                  <td>
                    <strong>{r.vendor || 'Seller'}</strong>
                    {r.best_pick ? <span className="compare-table__pick">Best</span> : null}
                    {r.title ? <span className="compare-table__sub">{r.title}</span> : null}
                    {r.risk_reasons?.length ? (
                      <span className="compare-table__sub">{r.risk_reasons.slice(0, 2).join(' · ')}</span>
                    ) : null}
                  </td>
                  <td>{r.unit_price || 'n/a'}</td>
                  <td>{r.moq ?? '—'}</td>
                  <td className="compare-table__origin">{r.origin || '—'}</td>
                  <td>
                    {risk != null ? (
                      <span className={`compare-table__risk compare-table__risk--${tone}`}>
                        {risk}/10
                      </span>
                    ) : (
                      '—'
                    )}
                  </td>
                  <td>{r.landed_mid || '—'}</td>
                  <td>
                    {r.link ? (
                      <a href={r.link} target="_blank" rel="noreferrer" className="compare-table__open">
                        Open
                      </a>
                    ) : null}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
