"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const navigationItems = [
  {
    label: "Modules",
    href: "/",
  },
  {
    label: "Poultry",
    href: "/poultry",
  },
];

export function AppHeader() {
  const pathname = usePathname();
  const isLandingPage = pathname === "/";

  if (pathname.startsWith("/poultry/batches/")) {
    return null;
  }

  return (
    <header className="border-b border-[var(--line)] bg-[var(--surface-cream)]">
      <div className="mx-auto grid max-w-7xl grid-cols-[1fr_auto_1fr] items-center px-5 py-3 sm:px-8">
        <Link href="/" className="flex items-center gap-3 justify-self-start">
          <div className="flex h-7 w-7 items-center justify-center rounded-full bg-[var(--navy)] text-[0.68rem] font-bold text-[var(--surface-cream)]">
            F
          </div>

          <span className="text-label text-[var(--navy)]">Farmnotes</span>
        </Link>

        <nav className="hidden items-center gap-8 justify-self-center md:flex">
          {navigationItems.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              className="text-label text-[var(--navy)] transition hover:text-[var(--gold)]"
            >
              {item.label}
            </Link>
          ))}
        </nav>

        <div className="justify-self-end">
          {isLandingPage ? (
          <span className="rounded-full bg-[var(--navy)] px-4 py-1.5 text-[0.68rem] font-bold uppercase tracking-[0.18em] text-[var(--surface-cream)]">
            System v1.0
          </span>
          ) : null}
        </div>
      </div>
    </header>
  );
}
