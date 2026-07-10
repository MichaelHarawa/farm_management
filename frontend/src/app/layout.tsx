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
          <div className="h-9 border-b border-black/30 bg-[#2c2c2c]" />

          <header className="border-b border-[var(--line)] bg-[var(--surface-cream)]">
            <div className="mx-auto flex max-w-7xl items-center justify-between px-5 py-5 sm:px-8">
              <Link href="/" className="flex items-center gap-3">
                <div className="flex h-8 w-8 items-center justify-center rounded-full bg-[var(--navy)] text-xs font-bold text-[var(--surface-cream)]">
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
                className="rounded-full bg-[var(--navy)] px-5 py-2 text-[0.68rem] font-bold uppercase tracking-[0.2em] text-[var(--surface-cream)] transition hover:bg-[var(--navy-soft)]"
              >
                Open Data
              </Link>
            </div>
          </header>

          {children}
        </div>
      </body>
    </html>
  );
}