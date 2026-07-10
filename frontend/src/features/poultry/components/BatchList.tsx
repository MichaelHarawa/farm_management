import Link from "next/link";
import type { PoultryBatch } from "../types";

type BatchListProps = {
  batches: PoultryBatch[];
};

function formatDate(value: string): string {
  return new Intl.DateTimeFormat("en", {
    year: "numeric",
    month: "short",
    day: "2-digit",
  }).format(new Date(value));
}

export function BatchList({ batches }: BatchListProps) {
  if (batches.length === 0) {
    return (
      <div className="rounded-lg border border-dashed border-gray-300 p-6 text-center">
        <h2 className="text-lg font-semibold text-gray-900">
          No poultry batches yet
        </h2>
        <p className="mt-2 text-sm text-gray-600">
          Once you create a batch, it will appear here.
        </p>
      </div>
    );
  }

  return (
    <div className="overflow-hidden rounded-lg border border-gray-200 bg-white">
      <table className="min-w-full divide-y divide-gray-200">
        <thead className="bg-gray-50">
          <tr>
            <th className="px-4 py-3 text-left text-sm font-semibold text-gray-700">
              Batch ID
            </th>
            <th className="px-4 py-3 text-left text-sm font-semibold text-gray-700">
              Bird Type
            </th>
            <th className="px-4 py-3 text-right text-sm font-semibold text-gray-700">
              Quantity
            </th>
            <th className="px-4 py-3 text-left text-sm font-semibold text-gray-700">
              Entry Date
            </th>
            <th className="px-4 py-3 text-left text-sm font-semibold text-gray-700">
              Maturity Date
            </th>
            <th className="px-4 py-3 text-right text-sm font-semibold text-gray-700">
              Action
            </th>
          </tr>
        </thead>

        <tbody className="divide-y divide-gray-200">
          {batches.map((batch) => (
            <tr key={batch.id} className="hover:bg-gray-50">
              <td className="px-4 py-3 text-sm font-medium text-gray-900">
                {batch.batch_id}
              </td>
              <td className="px-4 py-3 text-sm capitalize text-gray-700">
                {batch.bird_type}
              </td>
              <td className="px-4 py-3 text-right text-sm text-gray-700">
                {batch.quantity.toLocaleString()}
              </td>
              <td className="px-4 py-3 text-sm text-gray-700">
                {formatDate(batch.entry_date)}
              </td>
              <td className="px-4 py-3 text-sm text-gray-700">
                {formatDate(batch.expected_maturity_date)}
              </td>
              <td className="px-4 py-3 text-right text-sm">
                <Link
                  href={`/poultry/batches/${batch.id}`}
                  className="font-medium text-blue-600 hover:text-blue-800"
                >
                  View details
                </Link>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}