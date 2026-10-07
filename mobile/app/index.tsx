import { useState } from 'react';
import { Redirect, router } from 'expo-router';
import { useForm, Controller } from 'react-hook-form';
import { KeyboardAvoidingView } from 'react-native';
import { useSession } from '../src/auth/session';
import { developmentChecksEnabled,phase4Pilot,phase5Pilot } from '../src/build-mode.native';
import { Button, Card, Body, ErrorMessage, Field, Loading, Screen } from '../src/components/ui';
export default function SignIn() {
  const { ready, session, busy, error, signIn, unlock, settings, testControls, switchTestBackend } = useSession();
  const [submitted, setSubmitted] = useState(false);
  const { control, handleSubmit, resetField, formState: { errors } } = useForm({ defaultValues: { username: '', password: '' } });
  if (session) return <Redirect href="/(tabs)/today" />;
  return <KeyboardAvoidingView style={{ flex: 1 }} behavior="height"><Screen title="Your farm, in the field">
    <Body>{settings.environment.toUpperCase()} • {phase5Pilot?'Phase5 synthetic daily poultry pilot':phase4Pilot?'Phase4 synthetic operational pilot':'Android foundation'}</Body>
    {(phase4Pilot||phase5Pilot)&&<Body>Separate test backend: {settings.apiBaseUrl}. No farm financial upload is enabled.</Body>}
    {testControls && <><Body>Test backend: {settings.apiBaseUrl}</Body>
      <Button disabled={!ready || busy} title="Switch synthetic test backend" onPress={() => { void switchTestBackend(); }} /></>}
    {developmentChecksEnabled && <Button disabled={busy} title="Development: native storage checks" onPress={() => router.push('/native-storage-check')} />}
    {!ready ? <Loading /> : <>
      <Card title="Sign in online">
        <Body>First sign-in requires this farm’s Django backend. Your password is not saved on the phone.</Body>
        <Controller control={control} name="username" rules={{ required: true }} render={({ field: { value, onChange } }) =>
          <Field label="Username" value={value} onChangeText={onChange} autoCapitalize="none" autoCorrect={false} autoComplete="username" editable={!busy} />} />
        <Controller control={control} name="password" rules={{ required: true }} render={({ field: { value, onChange } }) =>
          <Field label="Password" value={value} onChangeText={onChange} secureTextEntry autoCapitalize="none" autoComplete="current-password" editable={!busy} />} />
        <ErrorMessage message={submitted && (errors.username || errors.password) ? 'Enter your username and password.' : null} />
        <Button disabled={busy} title={busy ? 'Opening secure session…' : 'Sign in'} onPress={() => {
          setSubmitted(true); void handleSubmit(async (values) => { try { await signIn(values.username.trim(), values.password); } finally { resetField('password'); } })();
        }} />
      </Card>
      <Button disabled={busy} title="Unlock this user’s cached session" onPress={() => { void unlock(); }} />
      <ErrorMessage message={error} />
      <Body>Offline access is time-limited and requires device unlock. {phase5Pilot?'Download batches online first, then retain permitted poultry work offline until Django validates it.':phase4Pilot?'Download batches online first, then retain mortality evidence offline until Django validates it.':'Native operational uploads are disabled in this build.'} No farm totals are inferred from an empty cache.</Body>
    </>}
  </Screen></KeyboardAvoidingView>;
}
