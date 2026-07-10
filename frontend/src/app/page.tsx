import Link from "next/link";

export default function HomePage() {
  return (
    <main className="mx-auto max-w-5xl px-6 py-12">
      <section className="rounded-2xl border border-gray-200 bg-white p-8 shadow-sm">
        <p className="text-sm font-medium text-blue-600">
          Farm Management System
        </p>

        <h1 className="mt-3 text-4xl font-bold tracking-tight text-gray-900">
          Manage farm production for profitability
        </h1>

        <p className="mt-4 max-w-2xl text-gray-600">
          The system contains poultry batches, input costs, sales, mortalities, and feed
          tracking. More farm modules to be added later.
        </p>

        <div className="mt-8">
          <Link
            href="/poultry"
            className="inline-flex rounded-lg bg-blue-600 px-5 py-3 text-sm font-semibold text-white hover:bg-blue-700"
          >
            Open Poultry Module
          </Link>
        </div>
      </section>
    </main>
  );
}