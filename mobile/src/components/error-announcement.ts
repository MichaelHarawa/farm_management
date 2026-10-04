export interface ErrorAnnouncement { message: string | null; attempt?: number }

// A render of the same error is not a new announcement. A new failed submit
// must announce again even if React batches clearing/re-setting identical text.
export function announceErrorChange(
  previous: ErrorAnnouncement | null,
  current: ErrorAnnouncement,
  announce: (message: string) => void,
) {
  if (current.message && (previous?.message !== current.message || previous?.attempt !== current.attempt)) {
    announce(current.message);
  }
  return current;
}
