import { BatchList } from "@/features/poultry/components/BatchList";
import { getPoultryBatches } from "@/features/poultry/api/batches";

export default async function PoultryPage() {
  const batches = await getPoultryBatches();

  return (
    <main>
      <section className="border-b border-[var(--line)] bg-[var(--surface-cream)]">
        <div className="mx-auto grid max-w-7xl gap-8 px-5 py-8 sm:px-8 lg:grid-cols-[1.1fr_0.9fr]">
          <div>
            <p className="text-label text-[var(--navy-muted)]">
              Poultry Intelligence / Live Batch Data
            </p>

            <h1 className="font-display mt-4 max-w-4xl text-5xl leading-none text-[var(--navy)] sm:text-6xl">
              Poultry batch register.
            </h1>

            <p className="mt-5 max-w-2xl text-base leading-7 text-[var(--navy-soft)]">
              Track poultry batches from placement to sales. Open a batch to
              manage input costs, sales, mortalities, and feed records.
            </p>
          </div>

          <div className="flex items-end justify-start lg:justify-end">
            <div className="grid w-full max-w-md grid-cols-3 border-y border-[var(--line)] py-4">
              <div>
                <p className="font-display text-3xl font-bold text-[var(--navy)]">
                  {batches.length}
                </p>
                <p className="text-label mt-1 text-[var(--navy-muted)]">
                  Live Batches
                </p>
              </div>

              <div className="border-l border-[var(--line)] pl-6">
                <p className="font-display text-3xl font-bold text-[var(--navy)]">
                  {batches
                    .reduce((total, batch) => total + batch.quantity, 0)
                    .toLocaleString()}
                </p>
                <p className="text-label mt-1 text-[var(--navy-muted)]">
                  Birds
                </p>
              </div>

              <div className="border-l border-[var(--line)] pl-6">
                <p className="font-display text-3xl font-bold text-[var(--navy)]">
                  01
                </p>
                <p className="text-label mt-1 text-[var(--navy-muted)]">
                  Module
                </p>
              </div>
            </div>
          </div>
        </div>
      </section>

      <section className="bg-[var(--navy)] px-5 py-8 sm:px-8">
        <div className="mx-auto max-w-7xl">
          <BatchList batches={batches} />
        </div>
      </section>
    </main>
  );
}
