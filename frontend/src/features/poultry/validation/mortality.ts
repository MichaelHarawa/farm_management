import { z } from "zod";

export function createMortalitySchema(maxAvailableBirds: number) {
  return z.object({
    quantity_dead: z
      .number()
      .int("Quantity must be a whole number.")
      .positive("Quantity must be greater than zero.")
      .max(
        maxAvailableBirds,
        `Mortality cannot exceed ${maxAvailableBirds.toLocaleString()} available live birds.`
      ),

    age_in_days: z
      .number()
      .int("Age must be a whole number.")
      .min(0, "Age cannot be negative."),

    suspected_cause: z
      .string()
      .trim()
      .min(2, "Suspected cause must contain at least 2 characters.")
      .max(200, "Suspected cause cannot exceed 200 characters."),

    description: z
      .string()
      .trim()
      .min(2, "Description must contain at least 2 characters.")
      .max(1000, "Description cannot exceed 1,000 characters."),

    action_taken: z
      .string()
      .trim()
      .min(2, "Action taken must contain at least 2 characters.")
      .max(1000, "Action taken cannot exceed 1,000 characters."),

    reported_by_name: z
      .string()
      .trim()
      .min(2, "Reporter name must contain at least 2 characters.")
      .max(200, "Reporter name cannot exceed 200 characters."),
  });
}

export type MortalityFormValues = z.infer<
  ReturnType<typeof createMortalitySchema>
>;
