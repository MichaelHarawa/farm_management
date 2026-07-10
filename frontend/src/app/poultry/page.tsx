import { BatchList } from "@/features/poultry/components/BatchList";
import { getPoultryBatches } from "@/features/poultry/api/batches";

export default async function PoultryPage() {
  const batches = await getPoultryBatches();

  return (
    <main className="mx-auto max-w-6xl px-6 py-8">
      <div className="mb-6">
        <p className="text-sm font-medium text-blue-600">Poultry Management</p>
        <h1 className="mt-2 text-3xl font-bold tracking-tight text-gray-900">
          Poultry Batches
        </h1>
        <p className="mt-2 text-gray-600">
          View all poultry batches and open a batch to manage input costs,
          sales, mortalities, and feed tracking.
        </p>
      </div>

      <BatchList batches={batches} />
    </main>
  );
}