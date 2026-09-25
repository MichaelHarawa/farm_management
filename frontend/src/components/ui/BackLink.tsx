import { ChevronLeft } from "lucide-react";
import Link from "next/link";

type BackLinkProps = {
  href: string;
  children: string;
  className?: string;
  prefetch?: boolean;
};

export function BackLink({
  href,
  children,
  className = "",
  prefetch,
}: BackLinkProps) {
  return (
    <Link
      href={href}
      prefetch={prefetch}
      aria-label={`Back to ${children}`}
      title={`Back to ${children}`}
      className={`group inline-grid size-10 shrink-0 place-items-center rounded-full border border-white/30 bg-[var(--navy)] !text-[var(--surface-cream)] shadow-[0_4px_12px_rgba(15,23,42,0.28)] transition duration-200 hover:-translate-x-0.5 hover:bg-[var(--navy-soft)] hover:!text-white hover:shadow-[0_6px_16px_rgba(15,23,42,0.34)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--gold)] focus-visible:ring-offset-2 active:translate-x-0 active:scale-95 sm:size-11 ${className}`}
    >
      <ChevronLeft aria-hidden="true" className="size-5 !text-[var(--surface-cream)] transition-transform group-hover:-translate-x-0.5 group-hover:!text-white sm:size-6" strokeWidth={2.75} />
      <span className="sr-only">Back to {children}</span>
    </Link>
  );
}
