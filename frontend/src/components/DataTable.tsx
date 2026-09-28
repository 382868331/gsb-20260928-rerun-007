import { DataRow } from "../types";

export function DataTable({ columns, rows, highlightSources }: {
  columns: string[];
  rows: DataRow[];
  highlightSources?: Set<string>;
}) {
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>#</th>
            {columns.map((column) => <th key={column}>{column}</th>)}
            <th>来源原记录</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => {
            const marked = highlightSources && row.sources.some((id) => highlightSources.has(id));
            return (
              <tr key={index} className={marked ? "marked" : undefined}>
                <td>{index + 1}</td>
                {columns.map((column) => (
                  <td key={column}>{formatCell(row.values[column])}</td>
                ))}
                <td className="sources">{row.sources.join(", ") || "—"}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function formatCell(value: unknown) {
  if (value === null || value === undefined) return "∅";
  if (typeof value === "number") return Number.isInteger(value) ? value : value.toFixed(4).replace(/0+$/, "").replace(/\.$/, "");
  return String(value);
}
