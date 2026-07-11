const POULTRY_ROOT = "/poultry-management";

export const poultryApiPaths = {
  batches: `${POULTRY_ROOT}/`,

  batch: (batchId: number) =>
    `${POULTRY_ROOT}/${batchId}`,

  inputCosts: (batchId: number) =>
    `${POULTRY_ROOT}/${batchId}/input_costs`,

  sales: (batchId: number) =>
    `${POULTRY_ROOT}/${batchId}/sales`,
} as const;