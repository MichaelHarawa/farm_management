import { redirect } from "next/navigation";

export default function LegacyFinanceExpensesPage() {
  redirect("/finance/expenditures?legacy=shared-expenses");
}
