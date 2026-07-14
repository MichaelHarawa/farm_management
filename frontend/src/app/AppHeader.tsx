import Image from "next/image";
import Link from "next/link";

import { AuthNavigation } from "@/features/auth/components/AuthNavigation";
import type {
  AuthUser,
} from "@/features/auth/types";

type AppHeaderProps = {
  initialUser: AuthUser | null;
};

export function AppHeader({
  initialUser,
}: AppHeaderProps) {
  return (
    <header className="border-b border-[var(--line)] bg-[var(--surface-cream)]">
      <div className="grid w-full grid-cols-[auto_1fr_auto] items-center gap-4 px-5 py-4 sm:px-8">
        <Link
          href="/"
          className="flex items-center gap-3 text-[var(--navy)]"
        >
          <span className="grid size-10 place-items-center overflow-hidden rounded-full bg-white ring-1 ring-[var(--line)]">
            <Image
              src="/assets/images/hames%20farms%20logo.png"
              alt="Farmnotes logo"
              width={40}
              height={40}
              className="size-full object-contain"
              priority
            />
          </span>

          <span className="text-label tracking-[0.22em]">
            FARMNOTES
          </span>
        </Link>

        <nav className="flex items-center justify-center gap-8">
          <Link
            href="/"
            className="hidden text-xs font-bold uppercase tracking-[0.16em] text-[var(--navy-muted)] transition hover:text-[var(--navy)] sm:inline"
          >
            Modules
          </Link>

          <Link
            href="/poultry"
            className="hidden text-xs font-bold uppercase tracking-[0.16em] text-[var(--navy-muted)] transition hover:text-[var(--navy)] sm:inline"
          >
            Poultry
          </Link>
        </nav>

        <div className="flex justify-end">
          <AuthNavigation
            key={initialUser?.id ?? "anonymous"}
            initialUser={initialUser}
          />
        </div>
      </div>
    </header>
  );
}
