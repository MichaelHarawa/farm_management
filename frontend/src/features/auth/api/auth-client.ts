import type {
  AuthUser,
  LoginPayload,
  SessionResponse,
} from "../types";

export class AuthClientError extends Error {
  status: number;

  constructor(
    message: string,
    status: number
  ) {
    super(message);

    this.name = "AuthClientError";
    this.status = status;
  }
}

type ErrorResponse = {
  message?: string;
};

async function readJsonBody(
  response: Response
): Promise<unknown> {
  const responseText =
    await response.text();

  if (!responseText) {
    return null;
  }

  try {
    return JSON.parse(
      responseText
    ) as unknown;
  } catch {
    return null;
  }
}

function getErrorMessage(
  data: unknown,
  fallback: string
): string {
  if (
    typeof data === "object" &&
    data !== null &&
    "message" in data
  ) {
    const message = (
      data as ErrorResponse
    ).message;

    if (message) {
      return message;
    }
  }

  return fallback;
}

export async function login(
  payload: LoginPayload
): Promise<AuthUser> {
  const response = await fetch(
    "/api/auth/login",
    {
      method: "POST",
      headers: {
        "Content-Type":
          "application/json",
        Accept: "application/json",
      },
      credentials: "same-origin",
      body: JSON.stringify(payload),
    }
  );

  const data =
    await readJsonBody(response);

  if (!response.ok) {
    throw new AuthClientError(
      getErrorMessage(
        data,
        "Login failed."
      ),
      response.status
    );
  }

  return (
    data as SessionResponse
  ).user;
}

type GetSessionOptions = {
  touch?: boolean;
};

export async function getSession(
  options: GetSessionOptions = {}
): Promise<AuthUser | null> {
  const path =
    options.touch === false
      ? "/api/auth/session?touch=0"
      : "/api/auth/session";
  const response = await fetch(
    path,
    {
      headers: {
        Accept: "application/json",
      },
      credentials: "same-origin",
      cache: "no-store",
    }
  );

  if (response.status === 401) {
    return null;
  }

  const data =
    await readJsonBody(response);

  if (!response.ok) {
    throw new AuthClientError(
      getErrorMessage(
        data,
        "The session could not be loaded."
      ),
      response.status
    );
  }

  return (
    data as SessionResponse
  ).user;
}

export async function logout(): Promise<void> {
  const response = await fetch(
    "/api/auth/logout",
    {
      method: "POST",
      credentials: "same-origin",
    }
  );

  if (
    !response.ok &&
    response.status !== 204
  ) {
    throw new AuthClientError(
      "Logout failed.",
      response.status
    );
  }
}
