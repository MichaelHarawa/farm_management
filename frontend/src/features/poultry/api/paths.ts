const POULTRY_ROOT = "/poultry-management";

export const poultryApiPaths = {
  batches: `${POULTRY_ROOT}/`,

  batch: (batchId: number) =>
    `${POULTRY_ROOT}/${batchId}`,

  inputCosts: (batchId: number) =>
    `${POULTRY_ROOT}/${batchId}/input_costs`,

  sales: (batchId: number) =>
    `${POULTRY_ROOT}/${batchId}/sales`,

  mortality: (batchId: number) =>
    `${POULTRY_ROOT}/${batchId}/mortality`,

  feedUsage: (batchId: number) =>
    `${POULTRY_ROOT}/${batchId}/feed_usage`,

  vaccinations: (batchId: number) =>
    `${POULTRY_ROOT}/${batchId}/drugs_vaccine`,
} as const;
