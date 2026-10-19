import { useEffect, useRef, useState } from 'react';
import { Redirect } from 'expo-router';
import { useSession } from '../src/auth/session';
import { phase6Evidence } from '../src/build-mode.native';
import { Body, Button, Card, ErrorMessage, Loading, Notice, Screen } from '../src/components/ui';
import { financialErrorMessage } from '../src/finance/errors';
import type { FinancialEvidence } from '../src/finance/evidence-store';
import { visibleFinancialPage } from '../src/finance/screen-state';
import { captureGrantedFinancialFixture, verifyGrantedFinancialFixture } from '../src/test/granted-financial-fixture';
import { nativeGrantedFinancialFixturePorts } from '../src/test/native-granted-financial';
import { deviceUnlockOptions } from '../src/auth/device-policy';

export default function FinancialEvidenceCheck() {
  const { session, settings, busy, error: sessionError, financialEvidenceOpen, authorizeFinancialEvidence,
    unlockFinancialEvidence, financialEvidencePage, captureFinancialEvidence, financialEvidenceOwnerCurrent, lock } = useSession();
  const [page, setPage] = useState<{ owner: object; rows: FinancialEvidence[]; after: string | null;
    next: string | null; notice: string } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [fixture, setFixture] = useState<{ owner: object; operationId: string; commandHash: string; outcome: string } | null>(null);
  const [checking, setChecking] = useState(false), [attempt, setAttempt] = useState(0);
  const running = useRef(false), revision = useRef(0), mounted = useRef(true);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  useEffect(() => { revision.current++; }, [session, financialEvidenceOpen]);
  // Owner comparison is synchronous at render, not an after-paint effect. A
  // late page from an old session can NEVER render in a new/unlocked session.
  const visible = visibleFinancialPage(page, session, financialEvidenceOpen);
  const visibleFixture = visibleFinancialPage(fixture, session, financialEvidenceOpen);

  async function run(work: () => Promise<void>) {
    if (running.current || busy) return;
    running.current = true; setChecking(true); setError(null); setAttempt(value => value + 1);
    try { await work(); }
    catch (failure) { if (mounted.current) { setPage(null); setError(financialErrorMessage(failure)); } }
    finally { running.current = false; if (mounted.current) setChecking(false); }
  }
  async function load(cursor: string | null) {
    if (!session) return;
    const generation = revision.current;
    const downloaded = await financialEvidencePage(cursor, session);
    if (!mounted.current || generation !== revision.current) return;
    setPage({ owner: session, rows: downloaded.evidence, after: cursor, next: downloaded.next,
      notice: downloaded.evidence.length ? 'Verified local page only. Every entry below remains unposted local evidence.' :
        'No local financial evidence on this page. This is not a zero farm balance or proof that the farm has no payments.' });
  }
  async function syntheticFixture(mode: 'capture' | 'verify') {
    if (!session) return;
    const owner = session;
    const scope = { enabled: phase6Evidence, environment: settings.environment, apiBaseUrl: settings.apiBaseUrl,
      username: owner.user.username, identity: { ...owner.pointer.identity } };
    const current = () => mounted.current && financialEvidenceOwnerCurrent(owner);
    setPage(null); setFixture(null);
    const ports = await nativeGrantedFinancialFixturePorts(scope, { current,
      capture: value => captureFinancialEvidence(value, owner), page: () => financialEvidencePage(null, owner) });
    const result = await (mode === 'capture' ? captureGrantedFinancialFixture(scope, ports) : verifyGrantedFinancialFixture(scope, ports));
    if (!current()) return;
    setFixture({ owner, operationId: result.descriptor.operation.operation_id, commandHash: result.descriptor.commandHash, outcome: result.outcome });
  }
  if (!phase6Evidence) return <Redirect href="/" />;
  // Private OS prompts may pause Android's activity. Do NOT keep the published
  // farm session visible, waive background locks or redirect away mid-handoff.
  if (!session && busy) return <Loading label="Farm data is locked while private financial authorization completes…" />;
  if (!session) return <Redirect href="/" />;
  return <Screen title="Financial evidence access">
    <Card title="Phase 6 • isolated evidence-only acceptance">
      <Body>Explicit access checks only. No financial upload, posting, reference cache or payment form is enabled here. Do not enter real farm data.</Body>
      <Body>Account: {session.user.username}. Financial storage: {financialEvidenceOpen ? 'unlocked for this session' : 'locked'}.</Body>
      <Body>Online authorization checks Django’s current role, device and session. Cached unlock additionally needs an unexpired original grant. Each private entry locks the main session first. The ordinary prerequisite says “{deviceUnlockOptions('operational').promptMessage}”; separate financial unlock says “{deviceUnlockOptions('financial').promptMessage}”. Complete private prompts only when requested; never share your PIN.</Body>
      <Button disabled={busy || checking} title="Request current financial authorization online" onPress={() => { void run(authorizeFinancialEvidence); }} />
      <Button disabled={busy || checking} title="Unlock this session’s cached financial evidence" onPress={() => { void run(unlockFinancialEvidence); }} />
      <Button disabled={busy || checking} title="Lock farm and financial evidence" onPress={() => { void lock(); }} />
      <ErrorMessage message={error ?? sessionError} announcementKey={attempt} />
    </Card>
    {financialEvidenceOpen && <Card title="Protected local evidence • not posted">
      <Body>At most 25 verified records per page, also bounded by bytes. This page is not a whole-farm total. No amount below changes official cash, stock, costs or profit.</Body>
      <Button disabled={busy || checking} title="Read first local evidence page" onPress={() => { void run(() => load(null)); }} />
      <Button disabled={busy || checking || !visible?.next} title="Read next local evidence page" onPress={() => { if (visible?.next) void run(() => load(visible.next)); }} />
      <Body>{visible ? visible.after ? 'Showing a later local page.' : 'First local page.' : 'No local page read in this session yet.'}</Body><Notice message={visible?.notice ?? null} />
      {(visible?.rows ?? []).map(row => <Card key={row.operation.operation_id} title="Pending local payment evidence — not posted">
        <Body>Provisional operation: {row.operation.operation_id}</Body>
        <Body>Original hash: {row.commandHash}</Body>
        <Body>Payee: {row.operation.payload.payee}</Body>
        <Body>Payment date: {row.operation.payload.payment_date} • {row.operation.payload.currency} {row.operation.payload.total_payment_amount}</Body>
        <Body>Original capture: {row.operation.captured_at}</Body>
      </Card>)}
    </Card>}
    {financialEvidenceOpen && session.user.username === 'mobile-finance-manager' &&
      settings.apiBaseUrl === 'http://10.0.2.2:7075/api/v1' && <Card title="Synthetic granted-storage fixture only">
      <Body>This explicit test captures one fictitious MWK 12.34 entry through the authorized local evidence path. Its invoice and funding references are invented: it is not a real or valid payment, and is never posted or uploaded. No real farm data may be entered here.</Body>
      <Body>The original test operation, payload and hash are retained in a private synthetic descriptor before capture. Retry reuses only that original. Verify reads it without creating or capturing another entry. Missing or changed evidence stops the check; no reset or replacement is offered.</Body>
      <Button disabled={busy || checking} title="Capture or retry original synthetic fixture" onPress={() => { void run(() => syntheticFixture('capture')); }} />
      <Button disabled={busy || checking} title="Verify original synthetic fixture without capture" onPress={() => { void run(() => syntheticFixture('verify')); }} />
      {visibleFixture && <>
        <Notice message={`Synthetic fixture ${visibleFixture.outcome}: exact original operation, complete payload, hash and pending local status match. This is not posting or upload acceptance.`} />
        <Body>Synthetic operation: {visibleFixture.operationId}</Body>
        <Body>Original hash: {visibleFixture.commandHash}</Body>
      </>}
    </Card>}
  </Screen>;
}
