import { useRef, useState } from 'react';
import { Redirect, router } from 'expo-router';
import { useSession } from '../src/auth/session';
import { phase5Pilot } from '../src/build-mode.native';
import { Body, Button, Card, Notice, Screen } from '../src/components/ui';
import { continueNativeFinancialProbe, inspectNativeFinancialProbe, missingKeyNativeFinancialProbe,
  prepareNativeFinancialProbe, verifyNativeFinancialProbe } from '../src/test/native-financial';
import { financialProbeFailureMessage } from '../src/test/financial-probe-diagnostics';

export default function NativeFinancialCheck() {
  const { session, busy } = useSession();
  const [result, setResult] = useState('Not run. Existing scratch work is never replaced.');
  const [checking, setChecking] = useState(false);
  const running = useRef(false);
  if (!phase5Pilot) return <Redirect href="/" />;
  if (session) return <Redirect href="/(tabs)/more" />;
  function run(work: () => Promise<string>, privateUnlock = true) {
    if (running.current || busy) return;
    running.current = true; setChecking(true); setResult(privateUnlock ? 'Running. Approve Android PIN prompts privately.' : 'Inspecting scratch metadata only. No PIN is requested.');
    void work().then(setResult).catch(error => setResult(financialProbeFailureMessage(error)))
      .finally(() => { running.current = false; setChecking(false); });
  }
  return <Screen title="Financial scratch storage"><Card title="Local acceptance only • session locked">
    <Body>New random synthetic identities and a separate financial database. No server request or authorization grant. A SQL storage fixture is not a captured payment. Passing this page is not financial workflow acceptance.</Body>
    <Body>Prepare and Verify each require one private device unlock on a PIN-only emulator; the missing-key check requires three. Keep TalkBack off for PIN entry. Failed/cancelled scratch work is retained, never silently reset.</Body>
    <Notice message={result} />
    <Button disabled={checking || busy} title="Inspect financial scratch state (no PIN)" onPress={() => run(inspectNativeFinancialProbe, false)} />
    <Button disabled={checking || busy} title="Prepare financial retained probe" onPress={() => run(prepareNativeFinancialProbe)} />
    <Button disabled={checking || busy} title="Continue retained financial preparation" onPress={() => run(continueNativeFinancialProbe)} />
    <Button disabled={checking || busy} title="Verify retained financial probe" onPress={() => run(verifyNativeFinancialProbe)} />
    <Button disabled={checking || busy} title="Run financial PIN-only missing-key check" onPress={() => run(missingKeyNativeFinancialProbe)} />
    <Button disabled={checking || busy} title="Return to native storage checks" onPress={() => router.replace('/native-storage-check')} />
  </Card></Screen>;
}
