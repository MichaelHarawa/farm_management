import { ApiError } from "./api";
import { ClientApiError } from "./client-api";

function isRecord(
  value: unknown
): value is Record<string, unknown> {
  return (
    typeof value === "object" &&
    value !== null &&
    !Array.isArray(value)
  );
}

export function getApiErrorMessage(
  error: unknown
): string {
  if (
    !(
      error instanceof ApiError ||
      error instanceof ClientApiError
    )
  ) {
    return "An unexpected error occurred. Please try again.";
  }

  const details = error.details;

  if (typeof details === "string") {
    if (details.trim().startsWith("<")) {
      return error.message;
    }

    return details;
  }

  if (isRecord(details)) {
    const messages = Object.entries(details).flatMap(
      ([field, value]) => {
        if (Array.isArray(value)) {
          return value.map(
            (message) => `${field}: ${String(message)}`
          );
        }

        return `${field}: ${String(value)}`;
      }
    );

    if (messages.length > 0) {
      return messages.join(" ");
    }
  }

  return error.message;
}
