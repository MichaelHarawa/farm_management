"use client";

import {
  Children,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import { PaginationControls } from "./PaginationControls";

type PaginatedTableBodyProps = {
  children: ReactNode;
  columnCount: number;
  emptyMessage?: string;
  itemLabel?: string;
  pageSize?: number;
};

export function PaginatedTableBody({
  children,
  columnCount,
  emptyMessage = "No records found.",
  itemLabel = "records",
  pageSize = 10,
}: PaginatedTableBodyProps) {
  const [currentPage, setCurrentPage] = useState(1);
  const rows = useMemo(
    () => Children.toArray(children).filter(Boolean),
    [children]
  );
  const totalPages = Math.max(1, Math.ceil(rows.length / pageSize));
  const safePage = Math.min(currentPage, totalPages);
  const startIndex = (safePage - 1) * pageSize;
  const pageRows = rows.slice(startIndex, startIndex + pageSize);

  return (
    <>
      <tbody>
        {pageRows.length ? (
          pageRows
        ) : (
          <tr>
            <td
              colSpan={columnCount}
              className="px-5 py-10 text-center text-sm text-[var(--navy-muted)]"
            >
              {emptyMessage}
            </td>
          </tr>
        )}
      </tbody>
      {rows.length > pageSize ? (
        <tfoot>
          <tr>
            <td colSpan={columnCount} className="border-t border-[var(--line)] px-4 py-4">
              <PaginationControls
                currentPage={safePage}
                totalPages={totalPages}
                totalItems={rows.length}
                pageSize={pageSize}
                itemLabel={itemLabel}
                onPageChange={setCurrentPage}
              />
            </td>
          </tr>
        </tfoot>
      ) : null}
    </>
  );
}
