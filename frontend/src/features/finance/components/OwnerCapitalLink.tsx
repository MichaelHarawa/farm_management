"use client";

import Link from "next/link";
import { useEffect, useState, type ReactNode } from "react";

import { getSession } from "@/features/auth/api/auth-client";
import { canAccessOwnerCapital } from "@/features/auth/utils/permissions";

export function OwnerCapitalLink({
  className,
  children,
}: {
  className?: string;
  children: ReactNode;
}) {
  const [allowed, setAllowed] = useState(false);

  useEffect(() => {
    getSession({ touch: false })
      .then((user) => setAllowed(canAccessOwnerCapital(user)))
      .catch(() => setAllowed(false));
  }, []);

  if (!allowed) return null;
  return <Link href="/finance/owner-capital" className={className}>{children}</Link>;
}
