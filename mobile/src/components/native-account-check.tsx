import React, { useEffect, useRef, useState } from 'react';
import { useSession } from '../auth/session';
import { accountProbeAvailable, prepareAccountFixture, rememberEnvironmentOrigin, verifyEnvironmentIsolation, verifyEnvironmentReturn,
  verifyRetainedDraft, verifyViewerIsolation, verifyWorkerReturn } from '../test/native-account';
import { Body, Button, Card, ErrorMessage } from './ui';

export function NativeAccountCheck() {
  const { session, busy, settings } = useSession();
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const inFlight = useRef(false);
  const mounted = useRef(true);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  if (!accountProbeAvailable(settings, session) || !session) return null;
  const current = session;
  async function run(probe: typeof prepareAccountFixture) {
    if (inFlight.current) return;
    inFlight.current = true;
    setRunning(true); setResult(null); setError(null);
    try {
      const message = await probe(settings, current);
      if (mounted.current) setResult(message);
    } catch {
      if (mounted.current) setError('CHECK NOT PASSED: verify the test account and sequence. Existing records are retained. No raw storage or authentication details are shown.');
    } finally {
      inFlight.current = false;
      if (mounted.current) setRunning(false);
    }
  }
  const disabled = busy || running;
  return <Card title="Development: native account isolation">
    <Body>Local synthetic backend only. Prepare as worker, use Sign out / switch account to test viewer, then return to worker. This retains one clearly synthetic quarantined record in the worker cache. It makes no server record changes and uses the already unlocked store.</Body>
    {current.user.username === 'mobile-test-worker' ? <>
      <Button title="Prepare worker isolation fixture" disabled={disabled} onPress={() => { void run(prepareAccountFixture); }} />
      <Button title="Verify returned worker fixture" disabled={disabled} onPress={() => { void run(verifyWorkerReturn); }} />
      <Button title="Verify exact retained draft" disabled={disabled} onPress={() => { void run(verifyRetainedDraft); }} />
      {settings.apiBaseUrl.includes(':7071/') ? <>
        <Button title="Remember backend A origin" disabled={disabled} onPress={() => { void run(rememberEnvironmentOrigin); }} />
        <Button title="Verify backend A return" disabled={disabled} onPress={() => { void run(verifyEnvironmentReturn); }} />
      </> : <Button title="Verify backend B isolation" disabled={disabled} onPress={() => { void run(verifyEnvironmentIsolation); }} />}
    </> : <Button title="Verify viewer isolation" disabled={disabled} onPress={() => { void run(verifyViewerIsolation); }} />}
    {running && <Body>Checking the current account’s local store…</Body>}
    {result && <Body>{result}</Body>}
    <ErrorMessage message={error} />
    <Body>Use the same running test backend for all three steps. Physical-device, biometric and environment-switch checks are separate.</Body>
  </Card>;
}
