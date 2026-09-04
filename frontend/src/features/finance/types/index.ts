export type DecimalString = string;

export type PaginatedResponse<T> = {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
};

export type FinanceRole = {
  slug: string;
  name: string;
};

export type FinanceUserSummary = {
  id: string;
  username: string;
  email: string;
  first_name: string;
  last_name: string;
  full_name: string;
  is_active: boolean;
  roles: FinanceRole[];
};

export type EmployeeProfile = {
  id: number;
  user: FinanceUserSummary | null;
  display_name: string;
  employee_number: string;
  employment_type: "permanent" | "contract" | "temporary";
  job_title: string;
  department: string;
  employment_start_date: string;
  employment_end_date: string | null;
  base_monthly_salary: DecimalString;
  standard_working_hours_per_day: DecimalString;
  standard_working_days_per_week: DecimalString;
  production_percentage: DecimalString;
  administration_percentage: DecimalString;
  selling_percentage: DecimalString;
  is_active: boolean;
  created_at: string;
  updated_at: string;
};

export type AccountingPeriod = {
  id: number;
  period_start: string;
  period_end: string;
  status: "open" | "closed";
  closed_at: string | null;
  closed_by: string | null;
  notes: string;
};

export type PayrollEntry = {
  id: number;
  accounting_period: number;
  employee: number;
  employee_name: string;
  gross_salary: DecimalString;
  employer_costs: DecimalString;
  deductions: DecimalString;
  total_employer_cost: DecimalString;
  production_percentage: DecimalString;
  administration_percentage: DecimalString;
  selling_percentage: DecimalString;
  production_amount: DecimalString;
  administration_amount: DecimalString;
  selling_amount: DecimalString;
  payment_status: string;
  payment_date: string | null;
  net_salary_payable: DecimalString;
  amount_paid: DecimalString;
  outstanding_salary: DecimalString;
  cost_allocation_plan: Array<{
    beneficiary_type: "batch" | "administration";
    batch: number | null;
    amount: DecimalString;
  }>;
  payments: PayrollPayment[];
};

export type PayrollPayment = {
  id: number;
  amount: DecimalString;
  payment_date: string;
  payment_method: string;
  external_reference: string;
  status: "posted" | "reversed";
  funding_allocations: Array<{
    id: number;
    funding_source: number;
    funding_source_name: string;
    amount: DecimalString;
  }>;
};

export type AdHocLabourPayment = {
  id: number;
  worker_name: string;
  task_description: string;
  work_date: string;
  hours_worked: DecimalString;
  payment_amount: DecimalString;
  cost_scope: string;
  batch: number | null;
  accounting_period: number | null;
  payment_status: string;
  workflow_status: "draft" | "approved" | "posted" | "partially_paid" | "paid" | "reversed";
  expenditure: number | null;
};

export type SharedExpense = {
  id: number;
  description: string;
  category: string;
  expense_date: string;
  accounting_period: number;
  amount: DecimalString;
  scope: string;
  directly_assigned_batch: number | null;
  allocation_method: string;
  payment_status: string;
  supplier: string;
  is_capital_expenditure: boolean;
};

export type SharedConsumableLot = {
  id: number;
  item: string;
  category: string;
  purchase_date: string;
  supplier: string;
  invoice_reference: string;
  quantity_purchased: DecimalString;
  unit_of_measurement: string;
  total_purchase_cost: DecimalString;
  unit_cost: DecimalString;
  expiry_date: string | null;
  storage_location: string;
  quantity_available: DecimalString;
  payment_status: string;
  payment_date: string | null;
  usd_exchange_rate: DecimalString | null;
  usd_equivalent: DecimalString | null;
  is_expired: boolean;
};

export type ConsumableUsage = {
  id: number;
  consumable_lot: number;
  usage_date: string;
  accounting_period: number;
  quantity_used: DecimalString;
  batch: number | null;
  poultry_house: string;
  usage_scope: string;
  allocation_driver: string;
  task_or_purpose: string;
  recognized_cost: DecimalString;
  locked: boolean;
};

export type AssetCategory = {
  id: number;
  name: string;
  code: string;
  default_useful_life_months: number;
  default_residual_value_percentage: DecimalString;
  default_depreciation_method: string;
  default_production_scope: string;
  default_allocation_driver: string;
  capitalization_threshold: DecimalString;
  requires_serial_number: boolean;
  is_active: boolean;
};

export type Asset = {
  id: string;
  asset_code: string;
  name: string;
  asset_category: number;
  category_other: string;
  purchase_date: string;
  available_for_use_date: string | null;
  purchase_price: DecimalString;
  delivery_cost: DecimalString;
  installation_cost: DecimalString;
  non_refundable_tax_cost: DecimalString;
  other_capitalized_cost: DecimalString;
  total_capitalized_cost: DecimalString;
  residual_value: DecimalString;
  recognized_impairment_amount: DecimalString;
  useful_life_months: number;
  depreciation_method: string;
  depreciation_unit: string;
  estimated_total_lifetime_units: DecimalString | null;
  status: string;
  location: string;
  custodian: string;
  condition: string;
  disposal_date: string | null;
  disposal_proceeds: DecimalString;
  disposal_gain_loss: DecimalString;
  production_scope: string;
  production_percentage: DecimalString;
  administration_percentage: DecimalString;
  selling_percentage: DecimalString;
  default_allocation_driver: string;
  fallback_allocation_driver: string;
  supplier: string;
  usd_exchange_rate: DecimalString | null;
  usd_equivalent: DecimalString | null;
};

export type AssetDepreciationEntry = {
  id: number;
  asset: string;
  accounting_period: number;
  period_depreciation: DecimalString;
  closing_carrying_amount: DecimalString;
  locked: boolean;
};

export type FinanceWarning = {
  code: string;
  severity: "info" | "warning" | "critical";
  message: string;
  solution: string;
  action_label: string;
  action_href: string;
};

export type AssetLifecycleEvent = {
  id: number;
  asset: string;
  event_type: string;
  event_date: string;
  reason: string;
  details: Record<string, unknown>;
  created_by_name: string;
};

export type StockMovement = {
  id: number;
  movement_type: string;
  movement_date: string;
  item: number;
  item_name: string;
  lot: number | null;
  batch: number | null;
  batch_code: string | null;
  quantity: DecimalString;
  unit_cost: DecimalString;
  total_cost: DecimalString;
  reference: string;
  reason: string;
};

export type BatchProfitabilityReport = {
  batch: number;
  batch_id: string;
  status: string;
  profitability_status:
    | "booked"
    | "provisional"
    | "pending_finalization"
    | "final";
  calculation_basis?: "current_unfinalized" | "final_snapshot";
  included_in_portfolio_summary: boolean;
  revenue: DecimalString;
  cash_collected: DecimalString;
  accounts_receivable: DecimalString;
  direct_batch_cost: DecimalString;
  allocated_production_cost: DecimalString;
  total_production_cost: DecimalString;
  batch_gross_profit: DecimalString;
  batch_gross_margin_percent: DecimalString | null;
  selling_cost: DecimalString;
  central_selling_cost: DecimalString;
  total_selling_cost: DecimalString;
  allocated_administration_cost: DecimalString;
  allocated_finance_cost: DecimalString;
  allocated_tax: DecimalString;
  total_attributed_cost: DecimalString;
  management_net_position: DecimalString;
  management_net_margin_percent: DecimalString | null;
  management_cost_breakdown: BatchManagementCostLine[];
  actual_result_basis: "actual_to_date" | "final_actual";
  result_interpretation: string;
  forecast_revenue_at_completion: DecimalString;
  forecast_cost_at_completion: DecimalString;
  forecast_final_profit: DecimalString;
  forecast_basis: string;
  allocation_trace: Array<{
    source_period: number;
    period_start: string;
    period_end: string;
    administration_driver: string;
    administration_numerator: DecimalString;
    administration_denominator: DecimalString;
    administration_percentage: DecimalString;
    selling_finance_tax_driver: string;
    selling_numerator: DecimalString;
    selling_denominator: DecimalString;
    selling_percentage: DecimalString;
    calculation_version: string;
  }>;
  fully_loaded_batch_profit: DecimalString;
  fully_loaded_margin_percent: DecimalString | null;
  birds_placed: number;
  valid_bird_units_sold: number;
  remaining_live_birds: number;
  profit_per_bird_sold: DecimalString | null;
  mortality: number;
  mortality_rate_percent: DecimalString | null;
  collection_rate_percent: DecimalString | null;
  provisional_saleable_birds: number;
  provisional_cost_per_saleable_bird: DecimalString | null;
  final_cost_per_bird_sold: DecimalString | null;
  break_even_selling_price_per_remaining_bird: DecimalString | null;
  additional_revenue_required_to_break_even: DecimalString;
  active_batch_cost_exposure: DecimalString;

  // Revenue utilization (funding side)
  available_batch_cash?: DecimalString;
  cash_used_from_batch?: DecimalString;
};


export type BatchPortfolioSummary = {
  revenue: DecimalString;
  cash_collected: DecimalString;
  accounts_receivable: DecimalString;
  direct_batch_cost: DecimalString;
  allocated_production_cost: DecimalString;
  total_production_cost: DecimalString;
  batch_gross_profit: DecimalString;
  batch_gross_margin_percent: DecimalString | null;
  selling_cost: DecimalString;
  central_selling_cost: DecimalString;
  total_selling_cost: DecimalString;
  allocated_administration_cost: DecimalString;
  allocated_finance_cost: DecimalString;
  allocated_tax: DecimalString;
  total_attributed_cost: DecimalString;
  management_net_position: DecimalString;
  management_net_margin_percent: DecimalString | null;
  management_cost_breakdown: BatchManagementCostLine[];
  forecast_revenue_at_completion: DecimalString;
  forecast_cost_at_completion: DecimalString;
  forecast_final_profit: DecimalString;
  fully_loaded_batch_profit: DecimalString;
  fully_loaded_margin_percent: DecimalString | null;
  birds_placed: number;
  valid_bird_units_sold: number;
  remaining_live_birds: number;
  mortality: number;
  mortality_rate_percent: DecimalString | null;
  collection_rate_percent: DecimalString | null;
  profit_per_bird_sold: DecimalString | null;
  production_cost_per_saleable_bird: DecimalString | null;
  break_even_selling_price_per_remaining_bird: DecimalString | null;
  additional_revenue_required_to_break_even: DecimalString;
  active_batch_cost_exposure: DecimalString;
};

export type BatchManagementCostComponent = {
  label: string;
  amount: DecimalString;
};

export type BatchManagementCostLine = {
  key: string;
  label: string;
  amount: DecimalString;
  basis: string;
  components?: BatchManagementCostComponent[];
};

export type BatchPortfolioReport = {
  analysis_basis: "lifecycle_management_cost";
  calculation_version: string;
  selected_batch_ids: number[];
  selected_batch_count: number;
  included_batch_count: number;
  profitability_status:
    | "empty"
    | "booked"
    | "provisional"
    | "pending_finalization"
    | "final"
    | "mixed";
  summary: BatchPortfolioSummary;
  results: BatchProfitabilityReport[];
  warnings: FinanceWarning[];
};

export type MonthlyReport = {
  period: number;
  period_start: string;
  period_end: string;
  status: string;
  reporting_basis: string;
  as_of: string;
  snapshot_version: number | null;
  reporting_policy: string | null;
  revenue: Record<string, DecimalString>;
  collections: {
    cash_received: DecimalString;
    credit_sales: DecimalString;
    accounts_receivable: DecimalString;
    collection_rate_percent: DecimalString | null;
    collection_overpayment: DecimalString;
    roll_forward: Record<string, DecimalString>;
  };
  production: Record<string, DecimalString | null>;
  operating_costs: Record<string, DecimalString>;
  other_costs: Record<string, DecimalString>;
  cash_flow: {
    opening_cash: DecimalString;
    cash_received: DecimalString;
    cash_paid: DecimalString;
    capital_expenditure_paid: DecimalString;
    asset_purchases: DecimalString;
    reserve_contributions: DecimalString;
    reserve_withdrawals: DecimalString;
    disposal_proceeds: DecimalString;
    operating: Record<string, DecimalString>;
    investing: Record<string, DecimalString>;
    financing: Record<string, DecimalString>;
    net_cash_movement: DecimalString;
    closing_cash: DecimalString;
    reconciles: boolean;
  };
  deferred_balances: Record<string, DecimalString | null>;
  asset_reporting: Record<string, DecimalString | number | null>;
  statement_of_financial_position: {
    cash: DecimalString;
    receivables: DecimalString;
    consumable_inventory: DecimalString;
    poultry_wip_management_cost: DecimalString;
    fixed_assets_net: DecimalString;
    total_assets: DecimalString;
    supplier_payables: DecimalString;
    payroll_and_statutory_liabilities: DecimalString;
    loans: DecimalString;
    total_liabilities: DecimalString;
    owner_contributed_equity: DecimalString;
    net_assets: DecimalString;
    basis: string;
  };
  ageing: {
    payables: Record<string, DecimalString>;
    receivables: { total: DecimalString; note: string };
  };
  comparatives: Record<string, DecimalString>;
  close_readiness: {
    unresolved_warning_count: number;
    is_closed: boolean;
    checklist: string[];
  };
  operational_metrics: Record<string, DecimalString | number | null>;
  warnings: FinanceWarning[];
};

export type FinanceDashboard = {
  active_batches: number;
  active_batch_cost_exposure: DecimalString;
  closed_batch_profit: DecimalString;
  receivables: DecimalString;
  current_cash: DecimalString;
  mtd_net_result: DecimalString;
  ytd_revenue: DecimalString;
  overdue_receivables: DecimalString;
  supplier_payables: DecimalString;
  payroll_liabilities: DecimalString;
  inventory_value: DecimalString;
  fixed_asset_carrying_amount: DecimalString;
  poultry_wip_management_cost: DecimalString;
  active_batch_forecast_profit: DecimalString;
  active_batch_forecast_margin_percent: DecimalString | null;
  low_stock_count: number;
  expiring_stock_count: number;
  period_status: "open" | "closed" | null;
  close_readiness: MonthlyReport["close_readiness"] | Record<string, never>;
  latest_month: MonthlyReport | null;
  warnings: FinanceWarning[];
};

export type ReceivableSale = {
  id: number;
  sale_id: string;
  batch: number;
  batch_id: string;
  buyer_name: string;
  sale_date: string;
  due_date: string | null;
  age_days: number;
  days_overdue: number;
  sale_total: DecimalString;
  amount_paid: DecimalString;
  balance: DecimalString;
  payment_status: string;
  receivable_status: "unpaid" | "partially_paid" | "paid" | "overdue" | "cancelled";
  is_overdue: boolean;
  payments: SalePayment[];
};

export type SalePayment = {
  id: number;
  payment_reference: string;
  amount: DecimalString;
  payment_date: string;
  payment_method: string;
  external_reference: string;
  received_by_name: string;
  notes: string;
  status: "posted" | "reversed";
  reversed_at: string | null;
  reversal_reason: string;
};

export type ReceivablesReport = {
  total_receivable: DecimalString;
  count: number;
  page: number;
  page_size: number;
  pages: number;
  next: number | null;
  previous: number | null;
  results: ReceivableSale[];
};

export type Expenditure = {
  id: number;
  expenditure_date: string;
  amount: DecimalString;
  category: string;
  accounting_nature: string;
  other_nature_detail?: string;
  description: string;
  payee?: string;
  payment_method?: string;
  reference_number?: string;
  expenditure_reference?: string;
  external_reference?: string;
  status: "draft" | "posted" | "void";
  payment_status?: "unpaid" | "partial" | "paid" | "historical_unassigned";
  origin?: "batch_cost" | "finance" | "historical_input_cost";
  idempotency_key?: string | null;
  farm_module?: string;
  notes?: string;
  created_at: string;
  updated_at: string;
  funding_allocations?: Array<{
    id?: number;
    funding_source: number;
    funding_source_display?: string;
    funding_batch?: number | null;
    amount: DecimalString;
    classification?: string;
  }>;
  total_funded?: DecimalString;
  amount_paid?: DecimalString;
  balance_due?: DecimalString;
  funding_status?: "funded" | "partially_funded" | "unfunded" | "reversed";
  beneficiary_type?: string;
  beneficiary_detail?: string;
  cost_allocation_plan?: CostAllocationInput[];
  beneficiary_batches?: Array<{
    id: number;
    batch_id: string;
    amount: DecimalString;
  }>;
};

export type BatchRevenueUtilization = {
  batch_id: number;
  batch_code: string;
  cash_collected: DecimalString;
  gross_collections: DecimalString;
  refunds: DecimalString;
  cash_used: DecimalString;
  available_cash: DecimalString;
  utilization_percent: DecimalString | null;
  by_category: Record<string, DecimalString>;
  by_accounting_nature: Record<string, DecimalString>;
  beneficiary_modules: string[];
  transaction_page?: {
    count: number; page: number; page_size: number; pages: number;
    next: number | null; previous: number | null;
  };
  transactions: Array<{
    allocation_id: number;
    expenditure_id: number;
    expenditure_reference: string;
    date: string;
    description: string;
    amount: DecimalString;
    total_expenditure: DecimalString;
    category: string;
    accounting_nature: string;
    beneficiary: string;
    funding_source: string;
    status: string;
    remaining_cash_after: DecimalString;
  }>;
};

export type FundingSource = {
  id: number;
  source_type: string;
  batch: number | null;
  description: string;
  notes?: string;
  is_active?: boolean;
  available_balance?: DecimalString | null;
  display_name: string;
  batch_code: string | null;
};

export type FundingAllocationInput = {
  funding_source: number;
  amount: DecimalString;
  classification?: string;
};

export type CostAllocationInput = {
  batch: number;
  amount: DecimalString;
};

export type CrossBatchFlow = {
  funding_batch_id: number;
  funding_batch_code: string;
  expenditure_id: number;
  expenditure_desc: string;
  amount_funded: DecimalString;
  allocated_to_batch_id: number;
  allocated_amount: DecimalString;
  date: string;
};
