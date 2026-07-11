import type { Metadata } from "next";
import type { ReactNode } from "react";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: "Farm Management System",
  description: "Poultry batch, cost, sales, mortality, and feed tracking.",
};

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

type RootLayoutProps = Readonly<{
  children: ReactNode;
}>;

export default function RootLayout({ children }: RootLayoutProps) {
  return (
    <html lang="en">
      <body>
        <div className="min-h-screen bg-[var(--page-cream)] text-[var(--navy)]">
          <header className="border-b border-[var(--line)] bg-[var(--surface-cream)]">
            <div className="mx-auto flex max-w-7xl items-center justify-between px-5 py-3 sm:px-8">
              <Link href="/" className="flex items-center gap-3">
                <div className="flex h-7 w-7 items-center justify-center rounded-full bg-[var(--navy)] text-[0.68rem] font-bold text-[var(--surface-cream)]">
                  F
                </div>

                <span className="text-label text-[var(--navy)]">
                  Farmnotes
                </span>
              </Link>

              <nav className="hidden items-center gap-8 md:flex">
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

              <Link
                href="/poultry"
                className="rounded-full bg-[var(--navy)] px-4 py-1.5 text-[0.68rem] font-bold uppercase tracking-[0.18em] text-[var(--surface-cream)] transition hover:bg-[var(--navy-soft)]"
              >
                Open Poultry
              </Link>
            </div>
          </header>

          {children}
        </div>
      </body>
    </html>
  );
}
