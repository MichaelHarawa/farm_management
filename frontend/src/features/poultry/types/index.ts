export type BirdType =
  | "broilers"
  | "layers"
  | "local"
  | "kloilers"
  | "mikolongwe";

export type BroilerStrain = "ross308" | "cobb500";

export type ChicksSource = "central_poultry" | "proto" | "other";

export type PoultryBatch = {
  id: number;
  batch_id: string;
  bird_type: BirdType;
  broiler_strain?: BroilerStrain | null;
  source: ChicksSource;
  source_other: string;
  booking_date: string | null;
  estimated_chick_arrival_date: string | null;
  delivery_confirmed_at: string | null;
  supplier_name?: string;
  booking_reference?: string;
  expected_quantity?: number | null;
  actual_quantity_received?: number | null;
  entry_date: string;
  expected_maturity_date: string;
  quantity: number;
  status:
    | "booked"
    | "planned"
    | "delivered"
    | "active"
    | "mature"
    | "selling"
    | "closed";
  target_selling_price: number | null;
  closure_notes: string;
  profitability_finalized_at: string | null;
  created_at: string;
  updated_at: string;
  created_by: string | null;
  created_by_name: string;
};

export type CreatePoultryBatchPayload = {
  bird_type: BirdType;
  broiler_strain?: BroilerStrain | null;
  source: ChicksSource;
  source_other: string;
  booking_date?: string;
  estimated_chick_arrival_date?: string;
  supplier_name?: string;
  booking_reference?: string;
  entry_date: string;
  expected_maturity_date: string;
  quantity: number;
};

export type ConfirmBatchDeliveryPayload = {
  entry_date: string;
  expected_maturity_date?: string;
  quantity?: number;
};

export type InputCost = {
  id: number | string;
  batch: number;
  expenditure: number | null;
  expenditure_reference: string;
  expenditure_payment_status: "unpaid" | "partial" | "paid" | "historical_unassigned";
  expenditure_origin: "batch_cost" | "finance" | "historical_input_cost";
  item: string;
  category: string;
  quantity: number;
  unit_measurement: string;
  unit?: number | null;
  unit_cost: number;
  usd_exchange_rate: number | null;
  usd_equivalent: number | null;
  purchase_date: string;
  notes: string;
  created_at: string;
  updated_at: string;
  created_by: string | null;
  created_by_name: string;
  direct_input_total: number;
  amount_paid: number;
  balance_due: number;
  funding_sources: string[];
};

export type DrugVaccinationType =
  | "gumbolo"
  | "hitchner"
  | "lasota"
  | "other";

export type DrugCategory =
  | "vaccination"
  | "drug"
  | "antibiotic"
  | "vitamin"
  | "dewormer"
  | "other";

export type PoultryVaccination = {
  id: number;
  batch: number;
  vaccination_date: string;
  drug_vaccination_type: DrugVaccinationType;
  other_drug_vaccination: string;
  drug_category: DrugCategory;
  quantity: number;
  description: string;
  timely_status: string;
  reported_by_name: string;
  created_at: string;
  updated_at: string;
  created_by: string | null;
  created_by_name: string;
};

export type ProductType = "live_chicken" | "dressed_chicken" | "eggs" | "manure";

export type PaymentStatus = "paid" | "partial" | "loan" | "unpaid" | "cancelled";

export type PaymentMethod =
  | "cash"
  | "mobile_money"
  | "bank_transfer"
  | "credit";

export type BuyerType =
  | "market_vendor"
  | "retail"
  | "retail_supply"
  | "bulk_order"
  | "other";

export type PoultrySale = {
  id: number;
  batch: number;
  sale_id: string;
  sale_date: string;
  due_date: string | null;
  product_type: ProductType;
  quantity_sold: number;
  unit_price: number;
  usd_exchange_rate: number | null;
  usd_equivalent: number | null;
  buyer_name: string;
  buyer_type: BuyerType;
  buyer_type_other: string;
  payment_status: PaymentStatus;
  payment_method: PaymentMethod;
  amount_paid: number;
  balance: number;
  sold_by_name: string;
  notes: string;
  created_at: string;
  updated_at: string;
  created_by: string | null;
  created_by_name: string;
};

export type PoultryMortality = {
  id: number;
  batch: number;
  mortality_date: string;
  quantity_dead: number;
  age_in_days: number;
  suspected_cause: string;
  description: string;
  action_taken: string;
  reported_by_name: string;
  created_at: string;
  updated_at: string;
  created_by: string | null;
  created_by_name: string;
};

export type FeedType =
  | "pre_starter"
  | "starter"
  | "grower"
  | "finisher"
  | "pullet_starter"
  | "pullet_grower"
  | "layers_marsh"
  | "layers_finisher";

export type FeedSource =
  | "cp_feed"
  | "proto_feed"
  | "concentrates_feed"
  | "self_made";

export type FeedUnitMeasurement = "kg" | "g";

export type PoultryFeedUsage = {
  id: number;
  batch: number;
  initial_age: number;
  feeding_start_date: string;
  feeding_end_date: string;
  feed_type: FeedType;
  feed_source: FeedSource;
  quantity_given: number;
  unit_of_measurement: FeedUnitMeasurement;
  current_number_of_birds: number;
  feed_quantity_kg: number;
  feed_per_live_bird_at_event: number | null;
  population_calculation_version: string;
  population_calculated_at: string | null;
  population_ordering_rule: string;
  notes: string;
  reported_by_name: string;
  created_at: string;
  updated_at: string;
  created_by: string | null;
  created_by_name: string;
};

export type PoultryFeedMetrics = {
  total_feed_kg: string;
  initial_birds: number;
  current_live_birds: number;
  feed_per_bird_started_kg: string | null;
  bird_days: string;
  feed_per_bird_day_kg: string | null;
  stage_feed_kg: Record<string, string>;
  same_timestamp_ordering: string;
  calculation_version: string;
};

export type PaginatedResponse<T> = {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
};

export type CreateInputCostPayload = {
  item: string;
  category_id: number;
  quantity: number;
  unit: number;
  unit_measurement: string;
  unit_cost: number;
  purchase_date: string;
  notes: string;
  payment_status: "paid" | "credit";
  funding_allocations: Array<{
    funding_source: number;
    source_query?: string;
    amount: number;
    classification: string;
  }>;
  idempotency_key: string;
};

export type CreateVaccinationPayload = {
  vaccination_date: string;
  drug_vaccination_type: DrugVaccinationType;
  other_drug_vaccination: string;
  drug_category: DrugCategory;
  quantity: number;
  description: string;
  timely_status: string;
  reported_by_name: string;
};

export type CreateSalePayload = {
  sale_date: string;
  due_date: string | null;
  product_type: ProductType;
  quantity_sold: number;
  unit_price: number;
  buyer_name: string;
  buyer_type: BuyerType;
  buyer_type_other: string;
  payment_status: PaymentStatus;
  payment_method: PaymentMethod;
  amount_paid: number;
  balance: number;
  sold_by_name: string;
  notes: string;
};

export type CreateMortalityPayload = {
  mortality_date: string;
  quantity_dead: number;
  age_in_days: number;
  suspected_cause: string;
  description: string;
  action_taken: string;
  reported_by_name: string;
};

export type CreateFeedUsagePayload = {
  initial_age: number;
  feeding_start_date: string;
  feeding_end_date: string;
  feed_type: FeedType;
  feed_source: FeedSource;
  quantity_given: number;
  unit_of_measurement: FeedUnitMeasurement;
  current_number_of_birds: number;
  notes: string;
  reported_by_name: string;
};

export type PoultryWeightSample = {
  id: number;
  batch: number;
  age_in_days: number;
  sampled_at: string;
  sample_size: number;
  average_weight_g: number;
  notes: string;
  reported_by_name: string;
  created_at: string;
  updated_at: string;
  created_by: string | null;
  created_by_name: string;
};

export type WeightSampleSeriesPoint = {
  age_in_days: number;
  sampled_at: string;
  actual_g: number;
  target_g: number | null;
  deviation_pct: number | null;
  sample_size: number;
  severity: "ok" | "watch" | "action" | "urgent";
};

export type WeightSampleStatus = {
  sample_id: number;
  age_in_days: number;
  sampled_at: string;
  average_weight_g: number;
  sample_size: number;
  target_weight_g: number | null;
  deviation_percent: number | null;
  severity: "ok" | "watch" | "action" | "urgent";
  message: string;
  recommended_actions: string[];
  strain: string;
} | null;

export type WeightSamplesResponse = {
  samples: PoultryWeightSample[];
  latest_status: WeightSampleStatus;
  strain: string;
  series: WeightSampleSeriesPoint[];
};

export type CreateWeightSamplePayload = {
  age_in_days: number;
  sampled_at: string;
  sample_size: number;
  average_weight_g: number;
  notes?: string;
  reported_by_name: string;
};
