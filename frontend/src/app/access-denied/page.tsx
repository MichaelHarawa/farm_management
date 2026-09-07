import { LockKeyhole } from "lucide-react";
import Link from "next/link";

export default function AccessDeniedPage() {
  return (
    <main className="grid min-h-[75vh] place-items-center bg-[var(--page-cream)] px-5 py-12">
      <section className="w-full max-w-2xl rounded-2xl border border-[var(--line)] bg-[var(--surface-cream)] p-8 text-center shadow-[var(--shadow-card)] sm:p-12">
        <span className="mx-auto grid size-16 place-items-center rounded-full bg-[var(--gold-soft)] text-[var(--navy)]">
          <LockKeyhole className="size-7" aria-hidden="true" />
        </span>
        <p className="text-label mt-6 text-[var(--navy-muted)]">Access control</p>
        <h1 className="font-display mt-3 text-4xl">This workspace is restricted.</h1>
        <p className="mx-auto mt-4 max-w-xl leading-7 text-[var(--navy-muted)]">
          Your account is signed in, but its current role does not include this workspace.
          Ask a system administrator to assign the appropriate role; finance records are not
          opened automatically to general-worker accounts.
        </p>
        <div className="mt-8 flex flex-wrap justify-center gap-3">
          <Link href="/poultry" className="finance-button">Return to poultry</Link>
          <Link href="/" className="inline-flex items-center rounded-xl border border-[var(--line)] px-5 py-3 text-sm font-bold">Go to modules</Link>
        </div>
      </section>
    </main>
  );
}
