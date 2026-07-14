import type { Metadata } from "next";
import type { ReactNode } from "react";
import { AppHeader } from "./AppHeader";
import "./globals.css";
import {
  getOptionalCurrentUser,
} from "@/features/auth/server/current-user";

// import {
//   AuthNavigation,
// } from "@/features/auth/components/AuthNavigation";
export const metadata: Metadata = {
  title: "Farm Management System",
  description: "Poultry batch, cost, sales, mortality, and feed tracking.",
};

type RootLayoutProps = Readonly<{
  children: ReactNode;
}>;

export default async function RootLayout({
  children,
}: RootLayoutProps) {
  const initialUser =
    await getOptionalCurrentUser();

  return (
    <html lang="en">
      <body>
        <div className="min-h-screen bg-[var(--page-cream)] text-[var(--navy)]">
          <AppHeader initialUser={initialUser} />
          {children}
        </div>
      </body>
    </html>
  );
}
