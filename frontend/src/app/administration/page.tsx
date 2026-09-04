"use client";
/* eslint-disable react-hooks/set-state-in-effect */

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";

import { clientApiFetch } from "@/lib/client-api";
import { getApiErrorMessage } from "@/lib/errors";

type Role = { slug: string; name: string };
type SystemUser = {
  id: string; username: string; email: string; full_name: string; first_name: string;
  last_name: string; job_title: string; department: string; roles: Role[];
  is_active: boolean; is_staff: boolean; last_login: string | null; date_joined: string;
  employee_number?: string | null;
};
type Employee = { id: number; employee_number: string; user: { id: string } | null };
type AuditEvent = { id: number; action: string; details: Record<string, unknown>; performed_by: string; created_at: string };

const ROLE_OPTIONS: Role[] = [
  { slug: "admin", name: "Administrator" },
  { slug: "farm_manager", name: "Farm Manager" },
  { slug: "farm_supervisor", name: "Farm Supervisor" },
  { slug: "director", name: "Director" },
  { slug: "stake_holder", name: "Stakeholder (read only)" },
  { slug: "general_worker", name: "General Worker" },
];

const initialForm = { username: "", email: "", first_name: "", last_name: "", job_title: "", department: "", password: "", role_slugs: ["general_worker"], employee_profile_id: "" };

export default function AdministrationPage() {
  const [users, setUsers] = useState<SystemUser[]>([]);
  const [employees, setEmployees] = useState<Employee[]>([]);
  const [form, setForm] = useState(initialForm);
  const [showCreate, setShowCreate] = useState(false);
  const [history, setHistory] = useState<{ user: SystemUser; events: AuditEvent[] } | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [accountRows, employeeRows] = await Promise.all([
        clientApiFetch<SystemUser[] | { results: SystemUser[] }>("/api/administration/users/"),
        clientApiFetch<Employee[] | { results: Employee[] }>("/api/finance/employees/"),
      ]);
      setUsers(Array.isArray(accountRows) ? accountRows : accountRows.results);
      setEmployees((Array.isArray(employeeRows) ? employeeRows : employeeRows.results).filter((employee) => !employee.user));
      setError(null);
    } catch (requestError) {
      setError(getApiErrorMessage(requestError));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const createUser = async (event: React.FormEvent) => {
    event.preventDefault();
    setBusy(true);
    try {
      await clientApiFetch("/api/administration/users/", {
        method: "POST",
        body: JSON.stringify({ ...form, employee_profile_id: form.employee_profile_id ? Number(form.employee_profile_id) : null }),
      });
      setForm(initialForm);
      setShowCreate(false);
      await load();
    } catch (requestError) { setError(getApiErrorMessage(requestError)); }
    finally { setBusy(false); }
  };

  const toggleActive = async (user: SystemUser) => {
    setBusy(true);
    try {
      await clientApiFetch(`/api/administration/users/${user.id}/`, { method: "PATCH", body: JSON.stringify({ is_active: !user.is_active }) });
      await load();
    } catch (requestError) { setError(getApiErrorMessage(requestError)); }
    finally { setBusy(false); }
  };

  const resetPassword = async (user: SystemUser) => {
    const temporaryPassword = window.prompt(`Enter a temporary password for ${user.username} (at least 8 characters):`);
    if (!temporaryPassword) return;
    try {
      await clientApiFetch(`/api/administration/users/${user.id}/reset-password/`, { method: "POST", body: JSON.stringify({ temporary_password: temporaryPassword }) });
      window.alert("Temporary password set. Share it with the user through a secure channel.");
    } catch (requestError) { setError(getApiErrorMessage(requestError)); }
  };

  const showHistory = async (user: SystemUser) => {
    try {
      const events = await clientApiFetch<AuditEvent[]>(`/api/administration/users/${user.id}/history/`);
      setHistory({ user, events });
    } catch (requestError) { setError(getApiErrorMessage(requestError)); }
  };

  return <main className="min-h-screen bg-[var(--page-cream)] px-5 py-10 sm:px-8">
    <div className="mx-auto max-w-7xl">
      <Link href="/" className="text-sm font-bold underline">← Home</Link>
      <div className="mt-5 flex flex-wrap items-end justify-between gap-4"><div><p className="text-label text-[var(--navy-muted)]">Administration / System access</p><h1 className="font-display mt-3 text-5xl text-[var(--navy)]">System users.</h1><p className="mt-4 max-w-2xl text-[var(--navy-soft)]">Technical account access, roles, activation, password resets, and audit history. Financial operations remain in Finance.</p></div><button onClick={() => setShowCreate(true)} className="finance-button text-[var(--navy)]">Create system user</button></div>
      {error ? <p role="alert" className="mt-5 rounded-lg bg-red-50 p-4 text-red-800">{error}</p> : null}
      <section className="mt-8 overflow-x-auto rounded-xl border border-[var(--line)] bg-white"><table className="min-w-[1000px] w-full text-sm"><thead className="bg-[#f6f3eb] text-left"><tr><th className="p-3">User</th><th className="p-3">Roles</th><th className="p-3">Employee link</th><th className="p-3">Last login</th><th className="p-3">Status</th><th className="p-3">Actions</th></tr></thead><tbody>
        {loading ? <tr><td colSpan={6} className="p-8 text-center">Loading system users…</td></tr> : null}
        {!loading && !users.length ? <tr><td colSpan={6} className="p-8 text-center">No system users found.</td></tr> : null}
        {users.map((user) => <tr key={user.id} className="border-t"><td className="p-3"><strong>{user.full_name}</strong><br/><span className="text-[var(--navy-muted)]">{user.username} · {user.email}</span></td><td className="p-3">{user.roles.map((role) => role.name).join(", ") || "No role"}</td><td className="p-3">{user.employee_number || "Not linked"}</td><td className="p-3">{user.last_login ? new Date(user.last_login).toLocaleString() : "Never"}</td><td className="p-3">{user.is_active ? "Active" : "Inactive"}</td><td className="p-3"><div className="flex flex-wrap gap-2"><button disabled={busy} onClick={() => void toggleActive(user)} className="rounded border px-3 py-2 font-bold">{user.is_active ? "Deactivate" : "Activate"}</button><button onClick={() => void resetPassword(user)} className="rounded border px-3 py-2 font-bold">Reset password</button><button onClick={() => void showHistory(user)} className="rounded border px-3 py-2 font-bold">Audit history</button></div></td></tr>)}
      </tbody></table></section>
    </div>

    {showCreate ? <div className="fixed inset-0 z-50 grid place-items-center bg-[#151f36]/45 p-4" role="dialog" aria-modal="true"><form onSubmit={createUser} className="max-h-[90vh] w-full max-w-3xl overflow-y-auto rounded-2xl bg-white p-6"><div className="flex justify-between"><div><p className="finance-eyebrow">Technical access</p><h2 className="mt-2 text-2xl font-extrabold">Create system user</h2></div><button type="button" onClick={() => setShowCreate(false)} aria-label="Close" className="text-2xl">×</button></div><div className="mt-6 grid gap-4 sm:grid-cols-2">
      {(["username", "email", "first_name", "last_name", "job_title", "department", "password"] as const).map((field) => <label key={field} className="text-sm font-bold">{field.replaceAll("_", " ")}<input required={["username", "email", "password"].includes(field)} type={field === "password" ? "password" : field === "email" ? "email" : "text"} value={form[field]} onChange={(event) => setForm({ ...form, [field]: event.target.value })} className="form-input mt-2 w-full" /></label>)}
      <label className="text-sm font-bold">Optional employee link<select value={form.employee_profile_id} onChange={(event) => setForm({ ...form, employee_profile_id: event.target.value })} className="form-input mt-2 w-full"><option value="">No employee link</option>{employees.map((employee) => <option key={employee.id} value={employee.id}>{employee.employee_number}</option>)}</select></label>
    </div><fieldset className="mt-5"><legend className="text-sm font-bold">System roles</legend><div className="mt-2 grid gap-2 sm:grid-cols-2">{ROLE_OPTIONS.map((role) => <label key={role.slug} className="flex items-center gap-2 rounded border p-3"><input type="checkbox" checked={form.role_slugs.includes(role.slug)} onChange={(event) => setForm({ ...form, role_slugs: event.target.checked ? [...form.role_slugs, role.slug] : form.role_slugs.filter((slug) => slug !== role.slug) })}/>{role.name}</label>)}</div></fieldset><div className="mt-6 flex justify-end gap-3"><button type="button" onClick={() => setShowCreate(false)} className="rounded border px-5 py-3 font-bold">Cancel</button><button disabled={busy} className="finance-button text-[var(--navy)]">{busy ? "Creating…" : "Create user"}</button></div></form></div> : null}

    {history ? <div className="fixed inset-0 z-50 grid place-items-center bg-[#151f36]/45 p-4" role="dialog" aria-modal="true"><section className="max-h-[80vh] w-full max-w-2xl overflow-y-auto rounded-2xl bg-white p-6"><div className="flex justify-between"><h2 className="text-2xl font-extrabold">Audit history · {history.user.username}</h2><button onClick={() => setHistory(null)} aria-label="Close" className="text-2xl">×</button></div><div className="mt-5 grid gap-3">{history.events.map((event) => <article key={event.id} className="rounded border p-4"><strong>{event.action.replaceAll("_", " ")}</strong><p className="text-sm text-[var(--navy-muted)]">{new Date(event.created_at).toLocaleString()} by {event.performed_by}</p></article>)}{!history.events.length ? <p>No account changes recorded.</p> : null}</div></section></div> : null}
  </main>;
}
