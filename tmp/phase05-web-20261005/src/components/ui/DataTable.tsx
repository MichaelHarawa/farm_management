"use client";

import { useMemo, useState, type ReactNode } from "react";

export type DataTableColumn<T> = {
  key: string;
  header: string;
  cell: (row: T) => ReactNode;
  sortValue?: (row: T) => string | number;
  className?: string;
};

type DataTableProps<T> = {
  columns: Array<DataTableColumn<T>>;
  rows: T[];
  rowKey: (row: T) => string | number;
  emptyMessage?: string;
  searchPlaceholder?: string;
  pageSize?: number;
  exportFileName?: string;
  toolbar?: ReactNode;
};

export function DataTable<T>({
  columns,
  rows,
  rowKey,
  emptyMessage = "No records found.",
  searchPlaceholder = "Search table…",
  pageSize = 10,
  exportFileName,
  toolbar,
}: DataTableProps<T>) {
  const [filterValue, setFilterValue] = useState("");
  const [currentPage, setCurrentPage] = useState(1);

  const filteredRows = useMemo(() => {
    const query = filterValue.trim().toLowerCase();
    if (!query) {
      return rows;
    }

    return rows.filter((row) =>
      columns.some((column) => {
        const raw = column.sortValue?.(row);
        if (raw !== undefined && raw !== null) {
          return String(raw).toLowerCase().includes(query);
        }

        const rendered = column.cell(row);
        if (typeof rendered === "string" || typeof rendered === "number") {
          return String(rendered).toLowerCase().includes(query);
        }

        return false;
      })
    );
  }, [columns, filterValue, rows]);

  const totalPages = Math.max(1, Math.ceil(filteredRows.length / pageSize));
  const safePage = Math.min(currentPage, totalPages);
  const startIndex = (safePage - 1) * pageSize;
  const pageRows = filteredRows.slice(startIndex, startIndex + pageSize);

  function exportCsv() {
    if (!exportFileName) {
      return;
    }

    const csvRows = [
      columns.map((column) => column.header),
      ...filteredRows.map((row) =>
        columns.map((column) => {
          const value = column.sortValue?.(row);
          if (value !== undefined && value !== null) {
            return String(value);
          }
          const rendered = column.cell(row);
          return typeof rendered === "string" || typeof rendered === "number"
            ? String(rendered)
            : "";
        })
      ),
    ].map((row) =>
      row.map((cell) => `"${String(cell).replace(/"/g, '""')}"`).join(",")
    );

    const blob = new Blob([csvRows.join("\n")], {
      type: "text/csv;charset=utf-8",
    });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `${exportFileName}.csv`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  }

  return (
    <div className="grid gap-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <label className="flex min-w-0 flex-1 items-center gap-3">
          <span className="text-label text-[var(--navy-muted)]">Filter</span>
          <input
            type="search"
            value={filterValue}
            onChange={(event) => {
              setFilterValue(event.target.value);
              setCurrentPage(1);
            }}
            placeholder={searchPlaceholder}
            className="form-input min-h-10 flex-1"
          />
        </label>

        <div className="flex flex-wrap items-center gap-2">
          {toolbar}
          {exportFileName ? (
            <button
              type="button"
              onClick={exportCsv}
              disabled={filteredRows.length === 0}
              className="btn-secondary btn-sm"
            >
              Export CSV
            </button>
          ) : null}
        </div>
      </div>

      <div className="data-table-wrap">
        <table className="data-table">
          <thead>
            <tr>
              {columns.map((column) => (
                <th key={column.key} className={column.className}>
                  {column.header}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {pageRows.length === 0 ? (
              <tr>
                <td
                  colSpan={columns.length}
                  className="px-5 py-10 text-center text-[var(--navy-muted)]"
                >
                  {rows.length === 0
                    ? emptyMessage
                    : "No records match the current filter."}
                </td>
              </tr>
            ) : (
              pageRows.map((row) => (
                <tr key={rowKey(row)}>
                  {columns.map((column) => (
                    <td key={column.key} className={column.className}>
                      {column.cell(row)}
                    </td>
                  ))}
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {filteredRows.length > pageSize ? (
        <div className="flex flex-wrap items-center justify-between gap-3 text-sm text-[var(--navy-muted)]">
          <p>
            Showing {startIndex + 1}–
            {Math.min(startIndex + pageSize, filteredRows.length)} of{" "}
            {filteredRows.length}
          </p>
          <div className="flex items-center gap-2">
            <button
              type="button"
              className="btn-ghost btn-sm"
              disabled={safePage <= 1}
              onClick={() => setCurrentPage((page) => Math.max(1, page - 1))}
            >
              Previous
            </button>
            <span className="min-w-16 text-center font-bold text-[var(--navy)]">
              {safePage} / {totalPages}
            </span>
            <button
              type="button"
              className="btn-ghost btn-sm"
              disabled={safePage >= totalPages}
              onClick={() =>
                setCurrentPage((page) => Math.min(totalPages, page + 1))
              }
            >
              Next
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
