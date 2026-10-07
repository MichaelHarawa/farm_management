import type { OperationalPoultryBatch, PoultryMortality } from "../types";

// The worker API deliberately omits financial fields. Never cast its positive
// projection to the full financial Batch shape or fill missing amounts with 0.
export function OperationalBatchDetailView({ batch, mortalities }: {
  batch: OperationalPoultryBatch;
  mortalities: PoultryMortality[];
}) {
  return <main className="mx-auto max-w-6xl space-y-6 px-4 py-8">
    <header>
      <h1 className="text-3xl font-bold">{batch.batch_id}</h1>
      <p className="mt-2">Confirmed operational records · {batch.status}</p>
      <p className="mt-2 text-sm">These records come from Django. Pending phone drafts are not included. Financial information is not available to this role.</p>
    </header>
    <section aria-label="Confirmed flock balance" className="grid gap-4 sm:grid-cols-3">
      {[["Initial birds", batch.initial_birds], ["Confirmed mortality", batch.total_mortality], ["Remaining birds", batch.remaining_birds]].map(([label,value]) =>
        <div key={String(label)} className="rounded-xl border bg-white p-5"><h2 className="font-semibold">{label}</h2><p className="mt-2 text-2xl">{value}</p></div>)}
    </section>
    <section className="rounded-xl border bg-white p-5" aria-labelledby="mortality-heading">
      <h2 id="mortality-heading" className="text-xl font-semibold">Confirmed mortality entries</h2>
      <p className="my-3 text-sm">{mortalities.length} entries returned by the server. Event times below are shown in UTC; the phone displays farm time.</p>
      <div className="overflow-x-auto"><table className="w-full text-left">
        <caption className="sr-only">Server-confirmed mortality, excluding unsent or rejected phone records</caption>
        <thead><tr>{["Record", "Event time (UTC)", "Birds", "Cause", "Description", "Action", "Reporter"].map(label=><th key={label} scope="col" className="border-b p-2">{label}</th>)}</tr></thead>
        <tbody>{mortalities.map(row=><tr key={row.id}>
          <th scope="row" className="border-b p-2">{row.id}</th>
          <td className="border-b p-2">{row.mortality_date}</td><td className="border-b p-2">{row.quantity_dead}</td>
          <td className="border-b p-2">{row.suspected_cause}</td><td className="border-b p-2">{row.description}</td>
          <td className="border-b p-2">{row.action_taken}</td><td className="border-b p-2">{row.reported_by_name}</td>
        </tr>)}</tbody>
      </table></div>
      {!mortalities.length&&<p className="mt-3">No mortality entries were returned for this batch.</p>}
    </section>
  </main>;
}
