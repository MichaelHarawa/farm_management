const POULTRY_ROOT = "/poultry-management";

export const poultryApiPaths = {
  batches: `${POULTRY_ROOT}/`,

  batch: (batchId: number) =>
    `${POULTRY_ROOT}/${batchId}`,

  markDelivered: (batchId: number) =>
    `${POULTRY_ROOT}/${batchId}/mark-delivered`,

  confirmDelivery: (batchId: number) =>
    `${POULTRY_ROOT}/${batchId}/confirm-delivery`,

  inputCosts: (batchId: number) =>
    `${POULTRY_ROOT}/${batchId}/input_costs`,

  feedInputCosts: (batchId: number) =>
    `${POULTRY_ROOT}/${batchId}/feed_input_costs`,

  sales: (batchId: number) =>
    `${POULTRY_ROOT}/${batchId}/sales`,

  mortality: (batchId: number) =>
    `${POULTRY_ROOT}/${batchId}/mortality`,

  feedUsage: (batchId: number) =>
    `${POULTRY_ROOT}/${batchId}/feed_usage`,

  feedMetrics: (batchId: number) =>
    `${POULTRY_ROOT}/${batchId}/feed-metrics`,

  vaccinations: (batchId: number) =>
    `${POULTRY_ROOT}/${batchId}/drugs_vaccine`,

  weightSamples: (batchId: number) =>
    `${POULTRY_ROOT}/${batchId}/weight_samples`,
} as const;
