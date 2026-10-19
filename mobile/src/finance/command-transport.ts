/** Exact explicit financial POST/status surface, never a generic upload allowlist. */
import { z } from 'zod';
import { uuid } from '../protocol';
import { financialUUIDEnvelope } from './uuid-commands';

export const financialCommandRoot = '/mobile-sync/finance/commands';
export const financialCommandCapabilitiesPath = financialCommandRoot + '/capabilities';
export const financialCommandOptions = z.strictObject({ financialCommands: z.literal(1) });
export const financialCommandIdentity = z.strictObject({ actorId: uuid, deploymentId: uuid, deviceId: uuid });
export const financialCommandResponseBytes = 128 * 1024;

export function financialCommandStatusPath(operationId: string) {
  return `${financialCommandRoot}/${uuid.parse(operationId)}`;
}
export function isFinancialCommandRequest(path: string, body: unknown): boolean {
  if (path === financialCommandRoot) return body !== undefined && financialUUIDEnvelope.safeParse(body).success;
  if (path === financialCommandCapabilitiesPath) return body === undefined;
  if (body !== undefined || typeof path !== 'string' || !path.startsWith(financialCommandRoot + '/')) return false;
  try { return financialCommandStatusPath(path.slice(financialCommandRoot.length + 1)) === path; }
  catch { return false; }
}
