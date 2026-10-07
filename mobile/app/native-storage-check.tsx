import { useRef, useState } from 'react';
import { Redirect, router } from 'expo-router';
import { useSession } from '../src/auth/session';
import { developmentChecksEnabled,phase5Pilot } from '../src/build-mode.native';
import { Body, Button, Card, Screen } from '../src/components/ui';
import { runNativeMissingKeyProbe, runNativeStorageProbe, verifyNativeCrashProbe } from '../src/test/native-storage';
import {runNativePoultryUpgradeProbe} from '../src/test/native-poultry';

export default function NativeStorageCheck() {
  const { session, busy } = useSession();
  const [probe, setProbe] = useState('Not run');
  const [checking, setChecking] = useState(false);
  const running = useRef(false);
  // No user repository is exposed here. Do not exempt PIN activities from
  // SessionProvider's normal background-lock policy merely to run a probe.
  if (!developmentChecksEnabled) return <Redirect href="/" />;
  if (session) return <Redirect href="/(tabs)/more" />;
  function run(work: () => Promise<string>) {
    if (running.current || busy) return;
    running.current = true; setChecking(true); setProbe('Running… Approve Android unlock prompts privately.');
    void work().then(setProbe).catch(() => setProbe('FAILED: native storage is not verified. Preserve app files and any retained synthetic probe.'))
      .finally(() => { running.current = false; setChecking(false); });
  }
  return <Screen title="Native storage checks"><Card title="Development only • session locked">
    <Body>Uses a newly owned synthetic database, never a user’s farm records. Normal/restart preparation asks for device unlock twice, missing-key recovery three times, and restart verification once. No uploads run.</Body>
    <Body>{probe}</Body>
    <Button disabled={checking || busy} title="Run SQLCipher storage probe" onPress={() => run(() => runNativeStorageProbe())} />
    {phase5Pilot&&<Button disabled={checking || busy} title="Run Phase5 schema2 upgrade probe" onPress={()=>run(runNativePoultryUpgradeProbe)}/>}
    <Button disabled={checking || busy} title="Run PIN-only missing-key probe" onPress={() => run(runNativeMissingKeyProbe)} />
    <Button disabled={checking || busy} title="Prepare retained process-death probe" onPress={() => run(() => runNativeStorageProbe(true))} />
    <Button disabled={checking || busy} title="Verify retained process-death probe" onPress={() => run(verifyNativeCrashProbe)} />
    <Button disabled={checking || busy} title="Return to sign-in" onPress={() => router.replace('/')} />
  </Card></Screen>;
}
