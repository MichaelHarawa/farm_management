// Run ONLY through phase03_local_backend.py: a fresh synthetic PostgreSQL farm.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { randomUUID } from 'node:crypto';
import { ApiError, AuthClient, httpTransport, type Credentials } from '../src/auth/client';
import { capabilitiesSchema, registrationSchema, tokenPairSchema, userSchema } from '../src/protocol';
test('actual Django HTTP: login, bound registration, me, capabilities, rotating refresh, logout and revocation', async () => {
  const base = process.env.MOBILE_TEST_API;
  const password = process.env.MOBILE_TEST_PASSWORD;
  assert.ok(base?.startsWith('http://127.0.0.1:') && password, 'Use the guarded synthetic-backend runner.');
  const transport = httpTransport(base!);
  const login = tokenPairSchema.extend({ user: userSchema }).parse(await transport('/auth/login', { username: 'mobile-test-worker', password }));
  const installation = randomUUID();
  const register = async (access: string, id = installation) => registrationSchema.parse(await transport('/mobile-sync/devices', { installation_id: id, app_version: '0.3.0-test', platform: 'android', protocol_version: 1, device_label: 'Synthetic HTTP client' }, access));
  const registration = await register(login.access);
  let stored: Credentials = { refresh: registration.refresh, rotation: 'ready' }; let rotations = 0; let denied = 0;
  const client = new AuthClient(async (path, body, access) => { if (path === '/auth/refresh') rotations++; return transport(path, body, access); },
    { async read() { return stored; }, async write(value) { stored = value; } }, async () => { denied++; });
  const users = await Promise.all(Array.from({ length: 20 }, () => client.read('/auth/me')));
  assert.equal(rotations, 1);
  assert.ok(users.every((value) => userSchema.parse(value).id === login.user.id));
  const capabilities = capabilitiesSchema.parse(await client.read('/mobile-sync/capabilities'));
  assert.equal(capabilities.device_id, registration.device_id);
  assert.equal(capabilities.commands['poultry.mortality.record']?.available, true);
  assert.equal(capabilities.commands.finance?.available, false);
  await assert.rejects(transport('/auth/refresh', { refresh: registration.refresh }), (error: unknown) => error instanceof ApiError && error.status === 401);
  const viewerLogin = tokenPairSchema.extend({ user: userSchema }).parse(await transport('/auth/login', { username: 'mobile-test-viewer', password }));
  const viewer = await register(viewerLogin.access, randomUUID());
  const viewerCapabilities = capabilitiesSchema.parse(await transport('/mobile-sync/capabilities', undefined, viewer.access));
  assert.equal(viewerCapabilities.commands['poultry.mortality.record']?.available, false);
  assert.ok(viewer.device_id !== registration.device_id);
  await assert.rejects(transport('/finance/dashboard', undefined, viewer.access), (error: unknown) => error instanceof ApiError && error.status === 403);
  await transport('/auth/logout', { refresh: viewer.refresh });
  await assert.rejects(transport('/auth/refresh', { refresh: viewer.refresh }), (error: unknown) => error instanceof ApiError && error.status === 401);
  // Recover current bound access without decoding/trusting JWT claims as authentication.
  const rotated = tokenPairSchema.parse(await transport('/auth/refresh', { refresh: stored.refresh }));
  await transport(`/mobile-sync/devices/${registration.device_id}/revoke`, { reason: 'Synthetic integration check' }, rotated.access);
  client.setAccess(rotated.access);
  await assert.rejects(client.read('/auth/me'), (error: unknown) => error instanceof ApiError && error.status === 403);
  assert.equal(denied, 1); assert.equal(rotations, 1);
  await assert.rejects(register(login.access), (error: unknown) => error instanceof ApiError && error.status === 403);
});
