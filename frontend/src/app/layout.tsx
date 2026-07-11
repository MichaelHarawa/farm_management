import type { Metadata } from "next";
import type { ReactNode } from "react";
import { AppHeader } from "./AppHeader";
import "./globals.css";

export const metadata: Metadata = {
  title: "Farm Management System",
  description: "Poultry batch, cost, sales, mortality, and feed tracking.",
};

type RootLayoutProps = Readonly<{
  children: ReactNode;
}>;

export default function RootLayout({ children }: RootLayoutProps) {
  return (
    <html lang="en">
      <body>
        <div className="min-h-screen bg-[var(--page-cream)] text-[var(--navy)]">
          <AppHeader />
          {children}
        </div>
      </body>
    </html>
  );
}
