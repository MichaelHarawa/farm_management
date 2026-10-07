import { clientApiFetch } from "@/lib/client-api";
import type {
  CreateVaccinationPayload,
  PoultryVaccination,
} from "../types";

export async function createBatchVaccination(
  batchId: number,
  payload: CreateVaccinationPayload
): Promise<PoultryVaccination> {
  return clientApiFetch<PoultryVaccination>(
    `/api/poultry/batches/${batchId}/vaccinations`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    }
  );
}
