import "server-only";

const BACKEND_API_BASE_URL =
  process.env.BACKEND_API_BASE_URL;

export class BackendApiError extends Error {
  status: number;
  details: unknown;

  constructor(
    message: string,
    status: number,
    details?: unknown
  ) {
    super(message);

    this.name = "BackendApiError";
    this.status = status;
    this.details = details;
  }
}

function getBackendApiBaseUrl(): string {
  if (!BACKEND_API_BASE_URL) {
    throw new Error(
      "BACKEND_API_BASE_URL is not configured."
    );
  }

  return BACKEND_API_BASE_URL.replace(/\/$/, "");
}

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

export async function backendApiFetch<T>(
  path: string,
  options: RequestInit = {}
): Promise<T> {
  const normalizedPath = path.startsWith("/")
    ? path
    : `/${path}`;

  const url =
    `${getBackendApiBaseUrl()}${normalizedPath}`;

  const headers = new Headers(options.headers);

  if (!headers.has("Accept")) {
    headers.set("Accept", "application/json");
  }

  if (
    options.body &&
    !headers.has("Content-Type")
  ) {
    headers.set(
      "Content-Type",
      "application/json"
    );
  }

  const response = await fetch(url, {
    ...options,
    headers,
    cache: "no-store",
  });

  if (response.status === 204) {
    return null as T;
  }

  const responseData =
    await readResponseBody(response);

  if (!response.ok) {
    throw new BackendApiError(
      `Backend request failed with status ${response.status} for ${url}`,
      response.status,
      responseData
    );
  }

  return responseData as T;
}