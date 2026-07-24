export type BirdType =
  | "broilers"
  | "layers"
  | "local"
  | "kloilers"
  | "mikolongwe";

export type ChicksSource = "central_poultry" | "proto" | "other";

export type PoultryBatch = {
  id: number;
  batch_id: string;
  bird_type: BirdType;
  source: ChicksSource;
  source_other: string;
  booking_date: string | null;
  estimated_chick_arrival_date: string | null;
  entry_date: string;
  expected_maturity_date: string;
  quantity: number;
  status: "planned" | "active" | "mature" | "selling" | "closed";
  target_selling_price: number | null;
  closure_notes: string;
  created_at: string;
  updated_at: string;
  created_by: string | null;
  created_by_name: string;
};

export type CreatePoultryBatchPayload = {
  bird_type: BirdType;
  source: ChicksSource;
  source_other: string;
  entry_date: string;
  expected_maturity_date: string;
  quantity: number;
};

export type InputCost = {
  id: number;
  batch: number;
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
  | "bulk_order";

export type PoultrySale = {
  id: number;
  batch: number;
  sale_id: string;
  sale_date: string;
  product_type: ProductType;
  quantity_sold: number;
  unit_price: number;
  usd_exchange_rate: number | null;
  usd_equivalent: number | null;
  buyer_name: string;
  buyer_type: BuyerType;
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
  notes: string;
  reported_by_name: string;
  created_at: string;
  updated_at: string;
  created_by: string | null;
  created_by_name: string;
};

export type PaginatedResponse<T> = {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
};

export type CreateInputCostPayload = {
  item: string;
  category: string;
  quantity: number;
  unit: number;
  unit_measurement: string;
  unit_cost: number;
  purchase_date: string;
  notes: string;
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
  product_type: ProductType;
  quantity_sold: number;
  unit_price: number;
  buyer_name: string;
  buyer_type: BuyerType;
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
