export type BirdType =
  | "broilers"
  | "layers"
  | "local"
  | "kloilers"
  | "mikolongwe";

export type PoultryBatch = {
  id: number;
  batch_id: string;
  bird_type: BirdType;
  entry_date: string;
  expected_maturity_date: string;
  quantity: number;
  created_at: string;
  updated_at: string;
};

export type CreatePoultryBatchPayload = {
  bird_type: BirdType;
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
  created_at: string;
  updated_at: string;
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
