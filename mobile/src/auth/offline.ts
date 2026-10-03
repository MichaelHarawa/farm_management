export interface OfflineClock { validatedLocalMs: number; validatedServerMs: number; highWaterMs: number; operationalDays: number; sensitiveHours: number }
export function offlineAccess(clock: OfflineClock, now: number, sensitive = false): { allowed: boolean; cutoff: number; reason?: string } {
  const duration = sensitive ? Math.min(clock.sensitiveHours, 24) * 3600_000 : Math.min(clock.operationalDays, 7) * 86400_000;
  const cutoff = clock.validatedServerMs + duration;
  if (![clock.validatedLocalMs, clock.validatedServerMs, clock.highWaterMs, now, duration].every(Number.isFinite) || duration <= 0) return { allowed: false, cutoff, reason: 'invalid_clock' };
  if (now < clock.highWaterMs - 2000 || now < clock.validatedLocalMs) return { allowed: false, cutoff, reason: 'clock_rollback' };
  const estimatedServerMs = clock.validatedServerMs + now - clock.validatedLocalMs;
  return estimatedServerMs < cutoff ? { allowed: true, cutoff } : { allowed: false, cutoff, reason: 'offline_window_expired' };
}
