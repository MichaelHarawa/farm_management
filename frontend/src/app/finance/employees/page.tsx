import { getEmployees } from "@/features/finance/api/finance";
import { EmployeeCreateDialog } from "@/features/finance/components/FinanceForms";
import {
  EmptyState,
  FinanceNav,
  FinancePageShell,
  Panel,
} from "@/features/finance/components/FinanceUI";
import {
  formatCurrency,
  formatDate,
  formatLabel,
} from "@/features/finance/utils/formatters";

export default async function FinanceEmployeesPage() {
  const employees = await getEmployees("/finance/employees");

  return (
    <FinancePageShell
      eyebrow="Finance / Workforce"
      title="Employees."
      detail="Create system users and employee profiles together, then manage salary and allocation details."
      actions={<FinanceNav />}
    >
      <Panel title="Employee Actions">
        <EmployeeCreateDialog />
      </Panel>

      <Panel title="Employee Register">
        {employees.length ? (
          <div className="overflow-x-auto">
            <table className="min-w-full border-collapse text-sm">
              <thead>
                <tr className="border-b border-[var(--line)] text-left text-[var(--navy-muted)]">
                  <th className="py-3 pr-4">Employee</th>
                  <th className="py-3 pr-4">Role</th>
                  <th className="py-3 pr-4">Salary</th>
                  <th className="py-3 pr-4">Split</th>
                  <th className="py-3 pr-4">Start</th>
                  <th className="py-3 pr-4">Status</th>
                </tr>
              </thead>
              <tbody>
                {employees.map((employee) => (
                  <tr key={employee.id} className="border-b border-[var(--line)]">
                    <td className="py-4 pr-4">
                      <p className="font-extrabold text-[var(--navy)]">
                        {employee.user.full_name}
                      </p>
                      <p className="text-xs text-[var(--navy-muted)]">
                        {employee.employee_number}
                      </p>
                    </td>
                    <td className="py-4 pr-4">{formatLabel(employee.employment_type)}</td>
                    <td className="py-4 pr-4">{formatCurrency(employee.base_monthly_salary)}</td>
                    <td className="py-4 pr-4">
                      {employee.production_percentage}/{employee.administration_percentage}/
                      {employee.selling_percentage}
                    </td>
                    <td className="py-4 pr-4">{formatDate(employee.employment_start_date)}</td>
                    <td className="py-4 pr-4">{employee.is_active ? "Active" : "Inactive"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <EmptyState message="No employees have been created yet." />
        )}
      </Panel>
    </FinancePageShell>
  );
}
