import { router } from 'expo-router';
import { useSession } from '../../src/auth/session';
import { Body, Button, Card, Screen } from '../../src/components/ui';
import { NativeAccountCheck } from '../../src/components/native-account-check';
import { NativePoultryCheck } from '../../src/components/native-poultry-check';
import { developmentChecksEnabled,phase4Pilot } from '../../src/build-mode.native';
export default function More() {
  const { session, busy, lock, signOut, settings, testControls, switchTestBackend, testRefresh } = useSession();
  return <Screen title="More"><Card title="Account & deployment"><Body>{session?.user.username} • {settings.environment}</Body>
    <Body>{settings.apiBaseUrl}</Body><Body>Roles: {session?.user.roles.map((role) => role.name).join(', ')}</Body><Body>Capabilities are cached evidence, not permission to bypass server rules.</Body></Card>
    <Button disabled={busy} title="Lock local session" onPress={() => { void lock(); }} />
    <Button disabled={busy} title="Sign out / switch account" onPress={() => { void signOut(); }} />
    {phase4Pilot&&<Button disabled={busy} title="Phase4 native acceptance checks" onPress={()=>router.push('/native-sync-check')}/>}
    <NativePoultryCheck />
    {developmentChecksEnabled && <NativeAccountCheck />}
    {testControls && <Card title="Synthetic backend acceptance controls">
      <Body>Only the two owned test APIs on ports7071/7072. Switching locks the current session and requires online sign-in; original encrypted work is retained. Refresh calls Django and may require reauthentication.</Body>
      <Button disabled={busy} title="Switch synthetic test backend" onPress={() => { void switchTestBackend(); }} />
      <Button disabled={busy} title="Test real token refresh" onPress={() => { void testRefresh(); }} />
    </Card>}
    <Body>Sign-out retains encrypted drafts for their original user. Phone loss, uninstall or an invalidated encryption key can make never-uploaded work unrecoverable. Android backup is excluded. Sensitive finance/payroll access is not delivered.</Body>
    {developmentChecksEnabled && <Card title="Development-only native storage check"><Body>Lock this session first, then test a separate synthetic database. Android PIN dialogs must not keep a user’s farm session unlocked in the background.</Body>
      <Button disabled={busy} title="Lock session & open native storage checks" onPress={() => {
        void lock().then(() => router.push('/native-storage-check')).catch(() => {});
      }} /></Card>}
  </Screen>;
}
