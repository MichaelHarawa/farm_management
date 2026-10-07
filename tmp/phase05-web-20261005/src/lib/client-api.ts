export class ClientApiError extends Error {
  status: number;
  details: unknown;

  constructor(
    message: string,
    status: number,
    details?: unknown
  ) {
    super(message);

    this.name = "ClientApiError";
    this.status = status;
    this.details = details;
  }
}

type ClientApiOptions =
  RequestInit & {
    retryOnUnauthorized?: boolean;
  };

async function readResponseBody(
  response: Response
): Promise<unknown> {
  const bodyText = await response.text();

  if (!bodyText) {
    return null;
  }

  try {
    return JSON.parse(bodyText) as unknown;
  } catch {
    return bodyText;
  }
}

async function refreshSession(): Promise<boolean> {
  const response = await fetch(
    "/api/auth/session",
    {
      method: "GET",
      credentials: "same-origin",
      cache: "no-store",
      headers: {
        Accept: "application/json",
      },
    }
  );

  return response.ok;
}

export async function clientApiFetch<T>(
  path: string,
  options: ClientApiOptions = {}
): Promise<T> {
  const {
    retryOnUnauthorized = true,
    ...requestOptions
  } = options;

  const headers = new Headers(
    requestOptions.headers
  );

  if (!headers.has("Accept")) {
    headers.set(
      "Accept",
      "application/json"
    );
  }

  if (
    requestOptions.body &&
    !headers.has("Content-Type")
  ) {
    headers.set(
      "Content-Type",
      "application/json"
    );
  }

  const sendRequest = () =>
    fetch(path, {
      ...requestOptions,
      headers,
      credentials: "same-origin",
      cache: "no-store",
    });

  let response = await sendRequest();

  if (
    response.status === 401 &&
    retryOnUnauthorized
  ) {
    const refreshed =
      await refreshSession();

    if (refreshed) {
      response = await sendRequest();
    }
  }

  if (response.status === 204) {
    return null as T;
  }

  const responseData =
    await readResponseBody(response);

  if (!response.ok) {
    let message =
      `Request failed with status ${response.status}.`;

    if (
      typeof responseData === "object" &&
      responseData !== null &&
      "message" in responseData &&
      typeof responseData.message === "string"
    ) {
      message = responseData.message;
    }

    throw new ClientApiError(
      message,
      response.status,
      responseData
    );
  }

  return responseData as T;
}