import Link from "next/link";

export default function PoultryGuidesPage() {
  return (
    <main className="min-h-screen bg-[#f6f3eb] text-[#151926]">
      <div className="mx-auto max-w-5xl px-5 py-10 sm:px-8">
        <Link href="/poultry" className="text-sm font-bold uppercase tracking-wide text-[#747b8d] hover:text-[#151926]">
          ← Back to Poultry Register
        </Link>

        <h1 className="mt-6 text-5xl font-extrabold tracking-[-0.02em]">System Guide</h1>
        <p className="mt-3 max-w-2xl text-lg text-[#747b8d]">
          Zero-knowledge walkthrough for Poultry + Finance modules. Click sections to expand.
        </p>

        {/* Table of Contents */}
        <div className="mt-8 rounded-xl border border-[#ddd7c9] bg-white p-6">
          <div className="text-sm font-bold uppercase tracking-widest text-[#e1aa3f] mb-3">Table of Contents</div>
          <ul className="grid gap-x-8 gap-y-1 text-sm md:grid-cols-2">
            <li><a href="#getting-started" className="hover:underline">Getting Started</a></li>
            <li><a href="#poultry-batches" className="hover:underline">Poultry: Adding Batches</a></li>
            <li><a href="#poultry-recording" className="hover:underline">Poultry: Recording Daily Data</a></li>
            <li><a href="#poultry-growth" className="hover:underline">Poultry: Growth Tracking</a></li>
            <li><a href="#poultry-dashboard" className="hover:underline">Poultry: Flock Dashboard</a></li>
            <li><a href="#finance-overview" className="hover:underline">Finance: Overview (Zero Knowledge)</a></li>
            <li><a href="#finance-employees" className="hover:underline">Finance: Employees &amp; Salaries</a></li>
            <li><a href="#finance-payroll" className="hover:underline">Finance: Payroll</a></li>
            <li><a href="#finance-labour" className="hover:underline">Finance: Ad-hoc Labour</a></li>
            <li><a href="#finance-assets" className="hover:underline">Finance: Recording Assets</a></li>
            <li><a href="#finance-consumables" className="hover:underline">Finance: Consumables</a></li>
            <li><a href="#finance-costs" className="hover:underline">Finance: Recording Costs</a></li>
            <li><a href="#finance-sales" className="hover:underline">Finance: Sales &amp; Collections</a></li>
            <li><a href="#finance-reports" className="hover:underline">Finance: Reports &amp; Profitability</a></li>
            <li><a href="#best-practices" className="hover:underline">Best Practices &amp; Tips</a></li>
          </ul>
        </div>

        <div className="mt-8 space-y-4">
          {/* Getting Started */}
          <details id="getting-started" className="group rounded-2xl border border-[#ddd7c9] bg-white p-6 open:shadow-sm">
            <summary className="cursor-pointer text-xl font-bold list-none flex items-center justify-between">
              Getting Started
              <span className="text-xs font-normal text-[#747b8d] group-open:hidden">Click to expand</span>
            </summary>
            <div className="mt-4 text-[#747b8d] space-y-2">
              <p>The system is split into two main areas: <strong>Poultry</strong> (flock tracking) and <strong>Finance</strong> (money tracking).</p>
              <p>Start at <Link href="/poultry" className="font-bold text-[#151926] hover:underline">/poultry</Link> for the main register. Use the top cards to jump between Flock Dashboard, Finance, and this Guide.</p>
              <p>All data lives in &quot;batches&quot; (production cycles). You record activities inside each batch&apos;s detail view.</p>
            </div>
          </details>

          {/* Poultry Batches */}
          <details id="poultry-batches" className="group rounded-2xl border border-[#ddd7c9] bg-white p-6 open:shadow-sm">
            <summary className="cursor-pointer text-xl font-bold list-none flex items-center justify-between">
              Poultry: Adding Batches
              <span className="text-xs font-normal text-[#747b8d] group-open:hidden">Click to expand</span>
            </summary>
            <div className="mt-4 text-[#747b8d] space-y-2">
              <ul className="list-disc pl-5 space-y-1">
                <li>Click yellow &quot;Add batch&quot; button.</li>
                <li>Select bird type. For broilers, pick strain (Ross 308 or Cobb 500) — this powers growth targets.</li>
                <li>Enter dates and quantity. Use &quot;Book chicks&quot; dialog for future placements.</li>
              </ul>
              <p className="text-sm text-[#e1aa3f]">Tip: Confirm delivery on a batch to activate it for recording.</p>
            </div>
          </details>

          {/* Poultry Recording */}
          <details id="poultry-recording" className="group rounded-2xl border border-[#ddd7c9] bg-white p-6 open:shadow-sm">
            <summary className="cursor-pointer text-xl font-bold list-none flex items-center justify-between">
              Poultry: Recording Daily Data
              <span className="text-xs font-normal text-[#747b8d] group-open:hidden">Click to expand</span>
            </summary>
            <div className="mt-4 text-[#747b8d]">
              <p className="mb-3">Click any batch in the list to open its tabs:</p>
              <ul className="grid gap-2 md:grid-cols-2 text-sm">
                <li><strong>Costs</strong> — Feed, drugs, transport, etc.</li>
                <li><strong>Sales</strong> — Birds sold, payments, balances.</li>
                <li><strong>Mortality</strong> — Dead birds + cause + action.</li>
                <li><strong>Feed</strong> — Quantities given + source + bird count.</li>
                <li><strong>Vaccination</strong> — Schedule drugs and check timeliness.</li>
                <li><strong>Growth</strong> — Weigh-ins vs breed targets.</li>
              </ul>
            </div>
          </details>

          {/* Growth */}
          <details id="poultry-growth" className="group rounded-2xl border border-[#ddd7c9] bg-white p-6 open:shadow-sm">
            <summary className="cursor-pointer text-xl font-bold list-none flex items-center justify-between">
              Poultry: Growth Tracking
              <span className="text-xs font-normal text-[#747b8d] group-open:hidden">Click to expand</span>
            </summary>
            <div className="mt-4 text-[#747b8d] space-y-2">
              <p>Weigh a sample of birds (8–10 minimum) at a known age. The system compares against Ross 308 / Cobb 500 curves and shows:</p>
              <ul className="list-disc pl-5">
                <li>Deviation % from target</li>
                <li>Severity badge (ok / watch / action / urgent)</li>
                <li>Recommended actions</li>
              </ul>
              <p className="text-sm text-[#e1aa3f]">Early alerts help you intervene before losses grow.</p>
            </div>
          </details>

          {/* Dashboard */}
          <details id="poultry-dashboard" className="group rounded-2xl border border-[#ddd7c9] bg-white p-6 open:shadow-sm">
            <summary className="cursor-pointer text-xl font-bold list-none flex items-center justify-between">
              Poultry: Flock Dashboard
              <span className="text-xs font-normal text-[#747b8d] group-open:hidden">Click to expand</span>
            </summary>
            <div className="mt-4 text-[#747b8d]">
              <p>Visit <Link href="/poultry/dashboard" className="font-bold text-[#151926] hover:underline">/poultry/dashboard</Link> for:</p>
              <ul className="list-disc pl-5 mt-2 text-sm">
                <li>Live filters (bird type / status)</li>
                <li>KPIs and pie/bar charts for status &amp; types</li>
                <li>Illustrative bars for sales, mortality causes, feed types</li>
                <li>Simple trendline for growth performance</li>
              </ul>
            </div>
          </details>

          {/* Finance Overview */}
          <details id="finance-overview" className="group rounded-2xl border border-[#ddd7c9] bg-white p-6 open:shadow-sm">
            <summary className="cursor-pointer text-xl font-bold list-none flex items-center justify-between">
              Finance: Overview (Zero Knowledge)
              <span className="text-xs font-normal text-[#747b8d] group-open:hidden">Click to expand</span>
            </summary>
            <div className="mt-4 text-[#747b8d] space-y-3">
              <p>The Finance module tracks all money flowing in and out of your farm — separate from but linked to your poultry batches.</p>
              <p><strong>Key ideas:</strong></p>
              <ul className="list-disc pl-5 text-sm">
                <li><strong>Input Costs</strong> = money you spend (feed, chicks, medicine, labour...)</li>
                <li><strong>Sales / Revenue</strong> = money you receive from selling products</li>
                <li><strong>Profitability</strong> = Revenue − Costs (calculated automatically per batch or overall)</li>
                <li><strong>Accounting Periods</strong> = time windows (e.g. monthly) used for payroll, depreciation, and expense recognition.</li>
              </ul>
              <p>Go to <Link href="/finance" className="font-bold text-[#151926] hover:underline">/finance</Link> to see the workspace. Use the nav bar at top to switch between Employees, Assets, Consumables, Labour, Payroll, and Expenditures.</p>
              <p className="text-sm">Everything is allocated either directly to a poultry batch or shared (then split by rules like bird-days or salary percentages).</p>
            </div>
          </details>

          {/* Finance Employees */}
          <details id="finance-employees" className="group rounded-2xl border border-[#ddd7c9] bg-white p-6 open:shadow-sm">
            <summary className="cursor-pointer text-xl font-bold list-none flex items-center justify-between">
              Finance: Employees &amp; Salaries
              <span className="text-xs font-normal text-[#747b8d] group-open:hidden">Click to expand</span>
            </summary>
            <div className="mt-4 text-[#747b8d] space-y-3">
              <p>Employees are system users who also have salary profiles. Salaries can be split across production, administration, and selling activities.</p>
              <p><strong>How to add an employee (with salary):</strong></p>
              <ol className="list-decimal pl-5 text-sm space-y-1">
                <li>Go to <Link href="/finance/employees" className="font-bold text-[#151926] hover:underline">/finance/employees</Link></li>
                <li>Click “Create Employee”</li>
                <li>Fill username, email, name, temporary password (they can change later)</li>
                <li>Set Employee number, Employment type (e.g. full-time)</li>
                <li>Choose or type Job title / Role (this also sets system permissions)</li>
                <li>Choose Department (production, admin, etc.)</li>
                <li>Enter Employment start date</li>
                <li>Enter Base monthly salary</li>
                <li>Set the three split percentages (must add to 100%): Production / Administration / Selling</li>
                <li>Save. The employee appears in the register with salary and split shown.</li>
              </ol>
              <p className="text-sm">These splits are used when allocating payroll costs to different parts of the business.</p>
            </div>
          </details>

          {/* Finance Payroll */}
          <details id="finance-payroll" className="group rounded-2xl border border-[#ddd7c9] bg-white p-6 open:shadow-sm">
            <summary className="cursor-pointer text-xl font-bold list-none flex items-center justify-between">
              Finance: Payroll
              <span className="text-xs font-normal text-[#747b8d] group-open:hidden">Click to expand</span>
            </summary>
            <div className="mt-4 text-[#747b8d] space-y-3">
              <p>Payroll turns employee salaries into actual expense entries for an accounting period. It can allocate the production portion based on bird activity.</p>
              <p><strong>Steps:</strong></p>
              <ol className="list-decimal pl-5 text-sm space-y-1">
                <li>Make sure you have an open Accounting Period (create one from Payroll or Assets pages if needed).</li>
                <li>Go to <Link href="/finance/payroll" className="font-bold text-[#151926] hover:underline">/finance/payroll</Link></li>
                <li>Click actions to “Generate Payroll” for the current period.</li>
                <li>The system creates entries for each active employee’s salary for that month.</li>
                <li>Production portions are allocated using bird-days (how many birds were on the farm during the period).</li>
              </ol>
              <p className="text-sm">After generation, the costs flow into monthly reports and batch profitability calculations.</p>
            </div>
          </details>

          {/* Finance Labour */}
          <details id="finance-labour" className="group rounded-2xl border border-[#ddd7c9] bg-white p-6 open:shadow-sm">
            <summary className="cursor-pointer text-xl font-bold list-none flex items-center justify-between">
              Finance: Ad-hoc Labour
              <span className="text-xs font-normal text-[#747b8d] group-open:hidden">Click to expand</span>
            </summary>
            <div className="mt-4 text-[#747b8d] space-y-3">
              <p>Use this for temporary workers, day labour, or one-off tasks that are not on the regular payroll.</p>
              <p><strong>How to record:</strong></p>
              <ol className="list-decimal pl-5 text-sm space-y-1">
                <li>Go to <Link href="/finance/labour" className="font-bold text-[#151926] hover:underline">/finance/labour</Link></li>
                <li>Click “Record Labour” (requires an open Accounting Period)</li>
                <li>Enter worker name, task description, date, amount paid</li>
                <li>Choose Cost Scope (Production, Administration, Selling)</li>
                <li>Optionally link to a specific active batch</li>
                <li>Save. It appears in the ledger and is allocated accordingly.</li>
              </ol>
              <p className="text-sm">This is separate from regular employee salaries.</p>
            </div>
          </details>

          {/* Finance Assets */}
          <details id="finance-assets" className="group rounded-2xl border border-[#ddd7c9] bg-white p-6 open:shadow-sm">
            <summary className="cursor-pointer text-xl font-bold list-none flex items-center justify-between">
              Finance: Recording Assets
              <span className="text-xs font-normal text-[#747b8d] group-open:hidden">Click to expand</span>
            </summary>
            <div className="mt-4 text-[#747b8d] space-y-3">
              <p>Assets are durable items (equipment, buildings, vehicles) that are capitalized instead of expensed immediately. They depreciate over time.</p>
              <p><strong>Steps to record an asset:</strong></p>
              <ol className="list-decimal pl-5 text-sm space-y-1">
                <li>First create an Asset Category if none exist (button on the Assets page).</li>
                <li>Go to <Link href="/finance/assets" className="font-bold text-[#151926] hover:underline">/finance/assets</Link></li>
                <li>Click “Create Asset”</li>
                <li>Fill name, choose category, purchase date, capitalized cost, depreciation method (e.g. straight-line), useful life in years/months</li>
                <li>Set available-for-use date</li>
                <li>Save. It appears in the Asset Register.</li>
              </ol>
              <p className="text-sm">Depreciation is run per Accounting Period. Use the buttons in the Depreciation panel to generate entries for the period.</p>
              <p className="text-sm">Assets help separate capital spending from operating profit.</p>
            </div>
          </details>

          {/* Finance Consumables */}
          <details id="finance-consumables" className="group rounded-2xl border border-[#ddd7c9] bg-white p-6 open:shadow-sm">
            <summary className="cursor-pointer text-xl font-bold list-none flex items-center justify-between">
              Finance: Consumables
              <span className="text-xs font-normal text-[#747b8d] group-open:hidden">Click to expand</span>
            </summary>
            <div className="mt-4 text-[#747b8d] space-y-3">
              <p>Consumables (feed, medicine, packaging, etc.) are purchased as “lots” (inventory) and only become an expense when actually used on the farm.</p>
              <p><strong>Two-step process:</strong></p>
              <ol className="list-decimal pl-5 text-sm space-y-1">
                <li><strong>Create a Lot</strong> (purchase): Go to Consumables → “Create Consumable Lot”. Enter item, category, quantity, unit cost, purchase date, payment status.</li>
                <li><strong>Record Usage</strong>: Click “Record Usage”. Select the lot, choose accounting period and (optionally) a batch, enter how much was used and on what date.</li>
              </ol>
              <p className="text-sm">The system tracks remaining stock and automatically recognizes the expense in the correct period/batch.</p>
            </div>
          </details>

          {/* Finance Costs */}
          <details id="finance-costs" className="group rounded-2xl border border-[#ddd7c9] bg-white p-6 open:shadow-sm">
            <summary className="cursor-pointer text-xl font-bold list-none flex items-center justify-between">
              Finance: Recording Costs
              <span className="text-xs font-normal text-[#747b8d] group-open:hidden">Click to expand</span>
            </summary>
            <div className="mt-4 text-[#747b8d]">
              <p>From Finance page or batch Costs tab:</p>
              <ol className="list-decimal pl-5 text-sm space-y-1">
                <li>Click &quot;Add input cost&quot;</li>
                <li>Choose category (feed, drug, transport...)</li>
                <li>Enter item, quantity, unit cost, date, and optional notes</li>
                <li>Save — it automatically updates batch and overall profitability</li>
              </ol>
            </div>
          </details>

          {/* Finance Sales */}
          <details id="finance-sales" className="group rounded-2xl border border-[#ddd7c9] bg-white p-6 open:shadow-sm">
            <summary className="cursor-pointer text-xl font-bold list-none flex items-center justify-between">
              Finance: Sales &amp; Collections
              <span className="text-xs font-normal text-[#747b8d] group-open:hidden">Click to expand</span>
            </summary>
            <div className="mt-4 text-[#747b8d]">
              <p>Record every sale so you know what’s paid vs outstanding.</p>
              <ul className="list-disc pl-5 text-sm">
                <li>Product type (live chicken, dressed, eggs...)</li>
                <li>Quantity, price, amount paid, balance, buyer details</li>
                <li>Payment status &amp; method</li>
              </ul>
              <p className="mt-2 text-sm">The system shows collection rate and receivables automatically.</p>
            </div>
          </details>

          {/* Finance Reports */}
          <details id="finance-reports" className="group rounded-2xl border border-[#ddd7c9] bg-white p-6 open:shadow-sm">
            <summary className="cursor-pointer text-xl font-bold list-none flex items-center justify-between">
              Finance: Reports &amp; Profitability
              <span className="text-xs font-normal text-[#747b8d] group-open:hidden">Click to expand</span>
            </summary>
            <div className="mt-4 text-[#747b8d]">
              <p>Visit Finance pages for:</p>
              <ul className="list-disc pl-5 text-sm">
                <li>Monthly views (with profit path charts)</li>
                <li>Batch profitability reports (select batches to compare revenue, costs, margins, collections, mortality)</li>
                <li>Charts showing costs vs revenue over time</li>
                <li>Receivables tracking</li>
              </ul>
              <p className="mt-2 text-sm text-[#e1aa3f]">Profitability is calculated per batch after you mark it final.</p>
            </div>
          </details>

          {/* Best Practices */}
          <details id="best-practices" className="group rounded-2xl border border-[#ddd7c9] bg-white p-6 open:shadow-sm">
            <summary className="cursor-pointer text-xl font-bold list-none flex items-center justify-between">
              Best Practices &amp; Tips
              <span className="text-xs font-normal text-[#747b8d] group-open:hidden">Click to expand</span>
            </summary>
            <div className="mt-4 text-[#747b8d]">
              <ul className="list-disc pl-5 space-y-1 text-sm">
                <li>Record daily — small consistent entries beat big catch-ups.</li>
                <li>Use the Growth tab early and often for broilers.</li>
                <li>Always note who did what (reported by field).</li>
                <li>Close batches only after final sales and review.</li>
                <li>Finance and Poultry data work together — costs and sales on batches feed the finance reports.</li>
                <li>Always create an Accounting Period before recording payroll, labour, consumable usage, or depreciation.</li>
                <li>Use salary splits and cost scopes consistently so allocations make sense in reports.</li>
              </ul>
            </div>
          </details>
        </div>

        <div className="mt-10 text-center text-sm text-[#747b8d]">
          Start simple: add one batch, create an employee or asset, record a few activities, then explore the Flock Dashboard and Finance reports.
          <br />
          <Link href="/poultry" className="mt-2 inline-block font-bold text-[#151926] hover:underline">Return to live register →</Link>
        </div>
      </div>
    </main>
  );
}
