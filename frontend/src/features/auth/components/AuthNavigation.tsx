"use client";

import {
  LockKeyhole,
  LogOut,
  Mail,
} from "lucide-react";
import Link from "next/link";
import {
  usePathname,
  useRouter,
} from "next/navigation";
import {
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import {
  getSession,
  logout,
} from "../api/auth-client";

import type {
  AuthUser,
} from "../types";

type AuthNavigationProps = {
  initialUser: AuthUser | null;
};

function getInitials(user: AuthUser): string {
  const source =
    user.full_name ||
    `${user.first_name} ${user.last_name}` ||
    user.username;

  const initials = source
    .trim()
    .split(/\s+/)
    .slice(0, 2)
    .map((part) => part[0])
    .join("")
    .toUpperCase();

  return initials || "FN";
}

function getRoleLabel(user: AuthUser): string {
  return (
    user.roles[0]?.name ||
    user.job_title ||
    "Farm user"
  );
}

export function AuthNavigation({
  initialUser,
}: AuthNavigationProps) {
  const router = useRouter();
  const pathname = usePathname();
  const panelRef =
    useRef<HTMLDivElement | null>(null);

  const [user, setUser] =
    useState<
      AuthUser | null | undefined
    >(initialUser);

  const [isLoggingOut, setIsLoggingOut] =
    useState(false);

  const [isMenuOpen, setIsMenuOpen] =
    useState(false);

  const currentDate = useMemo(
    () =>
      new Intl.DateTimeFormat(
        "en-US",
        {
          weekday: "long",
          month: "long",
          day: "numeric",
          year: "numeric",
        }
      ).format(new Date()),
    []
  );

  useEffect(() => {
    let isActive = true;

    async function loadSession() {
      try {
        const sessionUser =
          await getSession();

        if (isActive && sessionUser) {
          setUser(sessionUser);
        }
      } catch {
        if (isActive && !initialUser) {
          setUser(null);
        }
      }
    }

    void loadSession();

    return () => {
      isActive = false;
    };
  }, [initialUser]);

  useEffect(() => {
    if (!isMenuOpen) {
      return;
    }

    function handlePointerDown(
      event: PointerEvent
    ) {
      if (
        panelRef.current &&
        !panelRef.current.contains(
          event.target as Node
        )
      ) {
        setIsMenuOpen(false);
      }
    }

    function handleKeyDown(
      event: KeyboardEvent
    ) {
      if (event.key === "Escape") {
        setIsMenuOpen(false);
      }
    }

    document.addEventListener(
      "pointerdown",
      handlePointerDown
    );
    document.addEventListener(
      "keydown",
      handleKeyDown
    );

    return () => {
      document.removeEventListener(
        "pointerdown",
        handlePointerDown
      );
      document.removeEventListener(
        "keydown",
        handleKeyDown
      );
    };
  }, [isMenuOpen]);

  async function handleLogout() {
    setIsLoggingOut(true);

    try {
      await logout();
    } finally {
      setIsMenuOpen(false);
      setUser(null);
      router.replace("/login");
      router.refresh();
      setIsLoggingOut(false);
    }
  }

  if (user === undefined) {
    return (
      <div
        aria-hidden="true"
        className="h-11 w-36 animate-pulse rounded-full border border-[var(--line)] bg-white/55 shadow-sm"
      />
    );
  }

  if (user === null) {
    if (pathname === "/login") {
      return (
        <div className="inline-flex items-center gap-2 rounded-full border border-[var(--line)] bg-white/70 px-4 py-3 text-[0.68rem] font-bold uppercase tracking-[0.16em] text-[var(--navy)] shadow-sm">
          <LockKeyhole
            aria-hidden="true"
            className="size-4 text-[var(--gold)]"
          />
          <span className="hidden sm:inline">
            Secure access
          </span>
        </div>
      );
    }

    return (
      <Link
        href="/login"
        className="inline-flex items-center gap-2 rounded-full bg-[var(--gold)] px-5 py-3 text-[0.68rem] font-bold uppercase tracking-[0.18em] text-[var(--navy)] shadow-sm transition hover:bg-[var(--gold-soft)]"
      >
        <LockKeyhole
          aria-hidden="true"
          className="size-4"
        />
        Sign in
      </Link>
    );
  }

  return (
    <div
      ref={panelRef}
      className="relative flex items-center gap-3"
    >
      <div className="hidden rounded-full bg-white/65 px-5 py-3 text-sm font-semibold text-[var(--navy)] shadow-sm ring-1 ring-[var(--line)] md:block">
        {currentDate}
      </div>

      <button
        type="button"
        onClick={() =>
          setIsMenuOpen((value) => !value)
        }
        aria-expanded={isMenuOpen}
        aria-label="Open account menu"
        className="grid size-11 place-items-center rounded-full bg-[var(--navy)] text-sm font-black uppercase tracking-[0.04em] text-[var(--surface-cream)] shadow-sm ring-4 ring-[var(--gold-soft)] transition hover:bg-[var(--navy-soft)]"
      >
        {getInitials(user)}
      </button>

      {isMenuOpen ? (
        <div className="absolute right-0 top-[calc(100%+0.85rem)] z-50 w-[min(22rem,calc(100vw-2rem))] rounded-[1.5rem] border border-[var(--line)] bg-white p-6 text-center shadow-[0_24px_70px_rgba(15,23,42,0.16)]">
          <div className="mx-auto grid size-16 place-items-center rounded-full bg-[var(--navy)] text-lg font-black uppercase tracking-[0.04em] text-[var(--surface-cream)] ring-4 ring-[var(--surface-cream-soft)]">
            {getInitials(user)}
          </div>

          <p className="mt-5 text-xl font-bold text-[var(--navy)]">
            {user.full_name || user.username}
          </p>

          <p className="mt-3 flex items-center justify-center gap-2 text-sm text-[var(--navy-muted)]">
            <Mail
              aria-hidden="true"
              className="size-4"
            />
            <span className="break-all">
              {user.email ||
                `${user.username}@farmnotes.local`}
            </span>
          </p>

          <p className="mt-5 text-xs font-semibold uppercase tracking-[0.14em] text-[var(--navy-soft)]">
            {getRoleLabel(user)}
          </p>

          <div className="mt-6 border-t border-[var(--line)] pt-5">
            <button
              type="button"
              onClick={handleLogout}
              disabled={isLoggingOut}
              className="mx-auto inline-flex items-center justify-center gap-2 rounded-full px-5 py-3 text-base font-semibold text-[var(--navy)] transition hover:bg-[var(--surface-cream-soft)] disabled:cursor-not-allowed disabled:opacity-60"
            >
              <LogOut
                aria-hidden="true"
                className="size-5"
              />
              {isLoggingOut
                ? "Signing out..."
                : "Logout"}
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
