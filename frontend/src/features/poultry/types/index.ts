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

export type PaginatedResponse<T> = {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
};