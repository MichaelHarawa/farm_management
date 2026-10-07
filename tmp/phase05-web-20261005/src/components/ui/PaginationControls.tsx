"use client";

type PaginationControlsProps = {
  currentPage: number;
  totalPages: number;
  totalItems: number;
  pageSize: number;
  onPageChange: (page: number) => void;
  itemLabel?: string;
  className?: string;
};

export function PaginationControls({
  currentPage,
  totalPages,
  totalItems,
  pageSize,
  onPageChange,
  itemLabel = "records",
  className = "",
}: PaginationControlsProps) {
  if (totalItems <= pageSize) {
    return null;
  }

  const first = (currentPage - 1) * pageSize + 1;
  const last = Math.min(currentPage * pageSize, totalItems);

  return (
    <nav
      aria-label={`${itemLabel} pagination`}
      className={`flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between ${className}`}
    >
      <p className="text-xs font-semibold text-[var(--navy-muted)]" aria-live="polite">
        Showing {first}-{last} of {totalItems} {itemLabel}
      </p>
      <div className="grid w-full grid-cols-[1fr_auto_1fr] items-center gap-2 sm:w-auto">
        <button
          type="button"
          className="btn-ghost btn-sm w-full"
          disabled={currentPage <= 1}
          onClick={() => onPageChange(Math.max(1, currentPage - 1))}
        >
          Previous
        </button>
        <span className="min-w-16 text-center text-xs font-extrabold text-[var(--navy)]">
          {currentPage} / {totalPages}
        </span>
        <button
          type="button"
          className="btn-ghost btn-sm w-full"
          disabled={currentPage >= totalPages}
          onClick={() => onPageChange(Math.min(totalPages, currentPage + 1))}
        >
          Next
        </button>
      </div>
    </nav>
  );
}
