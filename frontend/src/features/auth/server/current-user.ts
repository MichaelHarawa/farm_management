import "server-only";

import { cookies } from "next/headers";

import type { AuthUser } from "../types";
import { getDjangoCurrentUser } from "./django-auth";
import { ACCESS_TOKEN_COOKIE } from "./token-cookies";

export async function getOptionalCurrentUser(): Promise<AuthUser | null> {
  const cookieStore = await cookies();
  const accessToken = cookieStore.get(
    ACCESS_TOKEN_COOKIE
  )?.value;

  if (!accessToken) {
    return null;
  }

  try {
    return await getDjangoCurrentUser(
      accessToken
    );
  } catch {
    return null;
  }
}
