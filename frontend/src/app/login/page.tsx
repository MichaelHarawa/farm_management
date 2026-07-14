import type { Metadata } from "next";
import Link from "next/link";

import { LoginForm } from "@/features/auth/components/LoginForm";

export const metadata: Metadata = {
  title:
    "Sign in | Farm Management System",
  description:
    "Sign in to manage poultry operations.",
};

type LoginPageProps = {
  searchParams: Promise<{
    next?: string | string[];
  }>;
};

function getSafeRedirect(
  value: string | string[] | undefined
): string {
  if (
    typeof value === "string" &&
    value.startsWith("/") &&
    !value.startsWith("//")
  ) {
    return value;
  }

  return "/poultry";
}

export default async function LoginPage({
  searchParams,
}: LoginPageProps) {
  const { next } = await searchParams;

  const redirectTo =
    getSafeRedirect(next);

  return (
    <main className="min-h-[calc(100vh-8rem)] bg-[var(--navy)] px-5 py-12 sm:px-8">
      <div className="mx-auto grid max-w-6xl overflow-hidden rounded-[2rem] border border-[var(--line)] bg-[var(--surface-cream)] shadow-[var(--shadow-card)] lg:grid-cols-[1.05fr_0.95fr]">
        <section className="flex flex-col justify-between border-b border-[var(--line)] p-8 sm:p-12 lg:border-b-0 lg:border-r">
          <div>
            <p className="text-label text-[var(--navy-muted)]">
              Farm Management / Secure Access
            </p>

            <h1 className="font-display mt-6 text-6xl leading-[0.92] tracking-[-0.06em] text-[var(--navy)] sm:text-7xl">
              Return to the farm workspace.
            </h1>

            <p className="mt-7 max-w-xl text-base leading-7 text-[var(--navy-soft)]">
              Sign in to manage poultry batches,
              input costs, sales, feed usage,
              mortalities and production
              performance.
            </p>
          </div>

          <Link
            href="/"
            className="text-label mt-12 text-[var(--navy-muted)] transition hover:text-[var(--gold)]"
          >
            ← Return home
          </Link>
        </section>

        <section className="flex items-center p-8 sm:p-12">
          <div className="w-full">
            <p className="text-label text-[var(--navy-muted)]">
              Account Login
            </p>

            <h2 className="font-display mt-3 text-4xl tracking-[-0.04em] text-[var(--navy)]">
              Sign in.
            </h2>

            <p className="mt-3 text-sm leading-6 text-[var(--navy-muted)]">
              Use the account credentials created
              in the Django administration system.
            </p>

            <div className="mt-8">
              <LoginForm
                redirectTo={redirectTo}
              />
            </div>
          </div>
        </section>
      </div>
    </main>
  );
}