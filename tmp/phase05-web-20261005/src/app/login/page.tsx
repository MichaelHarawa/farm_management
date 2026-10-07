import type { Metadata } from "next";
import Image from "next/image";
import Link from "next/link";
import { ArrowLeft, ShieldCheck } from "lucide-react";

import { LoginForm } from "@/features/auth/components/LoginForm";
import { getSafeInternalPath } from "@/features/auth/utils/redirects";

export const metadata: Metadata = {
  title: "Sign in | Farmnotes",
  description: "Secure access to the Farmnotes workspace.",
};

type LoginPageProps = {
  searchParams: Promise<{
    next?: string | string[];
  }>;
};

export default async function LoginPage({ searchParams }: LoginPageProps) {
  const { next } = await searchParams;
  const redirectTo = getSafeInternalPath(next);

  return (
    <main className="relative isolate min-h-[calc(100svh-65px)] overflow-hidden bg-[var(--navy)] px-4 py-7 sm:min-h-[calc(100svh-73px)] sm:px-8 sm:py-10">
      <div
        aria-hidden="true"
        className="absolute -left-32 top-24 -z-10 size-[28rem] rounded-full opacity-35 [background-image:radial-gradient(circle,rgba(242,189,66,0.55)_2px,transparent_2px)] [background-size:18px_18px] [mask-image:radial-gradient(circle,black_20%,transparent_70%)]"
      />
      <div
        aria-hidden="true"
        className="absolute -bottom-40 -right-32 -z-10 size-[34rem] rounded-full opacity-25 [background-image:radial-gradient(circle,rgba(255,255,255,0.6)_2px,transparent_2px)] [background-size:20px_20px] [mask-image:radial-gradient(circle,black_18%,transparent_70%)]"
      />
      <div
        aria-hidden="true"
        className="absolute inset-x-0 top-0 -z-20 h-64 bg-[radial-gradient(circle_at_top,rgba(34,52,95,0.95),transparent_68%)]"
      />

      <div className="mx-auto flex w-full max-w-6xl items-center justify-between">
        <Link
          href="/"
          className="group inline-flex min-h-11 items-center gap-2 rounded-full border border-white/80 bg-[var(--surface-cream)] px-4 text-sm font-extrabold !text-[var(--navy)] shadow-[0_8px_24px_rgba(4,10,28,0.28)] transition hover:border-[var(--gold)] hover:bg-[var(--gold-soft)] focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-[var(--gold)]/35"
        >
          <ArrowLeft
            className="size-4 transition-transform group-hover:-translate-x-0.5"
            aria-hidden="true"
          />
          Back to home
        </Link>

        <span className="hidden items-center gap-2 text-xs font-bold uppercase tracking-[0.16em] text-white/65 sm:inline-flex">
          <ShieldCheck className="size-4 text-[var(--gold)]" aria-hidden="true" />
          Secure workspace
        </span>
      </div>

      <div className="mx-auto flex min-h-[calc(100svh-160px)] w-full max-w-6xl items-center justify-center py-7 sm:min-h-[calc(100svh-180px)] sm:py-10">
        <section className="w-full max-w-[34rem] overflow-hidden rounded-[1.75rem] border border-white/70 bg-[var(--surface-white)] shadow-[0_32px_90px_rgba(4,10,28,0.38)] sm:rounded-[2rem]">
          <div className="px-6 pb-5 pt-7 text-center sm:px-10 sm:pb-7 sm:pt-9">
            <div className="mx-auto grid size-20 place-items-center overflow-hidden rounded-2xl border border-[var(--line)] bg-[var(--surface-cream)] shadow-sm sm:size-24">
              <Image
                src="/assets/images/hames%20farms%20logo.png"
                alt="Farmnotes"
                width={96}
                height={96}
                className="size-full scale-[2.2] object-contain object-[center_42%]"
                unoptimized
                priority
              />
            </div>

            <p className="mt-5 text-xs font-extrabold uppercase tracking-[0.24em] text-[#397246]">
              Farmnotes
            </p>
            <h1 className="mt-2 text-3xl font-extrabold tracking-[-0.035em] text-[var(--navy)] sm:text-4xl">
              Welcome back
            </h1>
            <p className="mx-auto mt-3 max-w-sm text-sm leading-6 text-[var(--navy-muted)]">
              Sign in to continue managing farm operations and performance.
            </p>
          </div>

          <div className="border-t border-[var(--line)] bg-[var(--surface-cream)]/55 px-6 py-6 sm:px-10 sm:py-8">
            <LoginForm redirectTo={redirectTo} />
          </div>

          <div className="flex items-center justify-center gap-2 border-t border-[var(--line)] px-6 py-4 text-xs font-semibold text-[var(--navy-muted)]">
            <ShieldCheck className="size-4 text-[#397246]" aria-hidden="true" />
            Authorized users only
          </div>
        </section>
      </div>
    </main>
  );
}
