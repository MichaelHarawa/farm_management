import { z } from "zod";

export const vaccinationSchema = z
  .object({
    vaccination_date: z.string().min(1, "Vaccination date is required."),

    drug_vaccination_type: z.enum(["gumbolo", "hitchner", "lasota", "other"]),

    other_drug_vaccination: z.string().trim().max(
      200,
      "Other vaccination name cannot exceed 200 characters."
    ),

    drug_category: z.enum([
      "vaccination",
      "drug",
      "antibiotic",
      "vitamin",
      "dewormer",
      "other",
    ]),

    quantity: z
      .number()
      .int("Quantity must be a whole number.")
      .positive("Quantity must be greater than zero."),

    description: z
      .string()
      .trim()
      .min(2, "Description must contain at least 2 characters.")
      .max(1000, "Description cannot exceed 1,000 characters."),

    reported_by_name: z
      .string()
      .trim()
      .min(2, "Reporter name must contain at least 2 characters.")
      .max(200, "Reporter name cannot exceed 200 characters."),
  })
  .superRefine((values, context) => {
    const vaccinationDate = new Date(values.vaccination_date);

    if (Number.isNaN(vaccinationDate.getTime())) {
      context.addIssue({
        code: "custom",
        path: ["vaccination_date"],
        message: "Vaccination date must be a valid date.",
      });
    }

    if (
      values.drug_vaccination_type === "other" &&
      values.other_drug_vaccination.trim().length < 2
    ) {
      context.addIssue({
        code: "custom",
        path: ["other_drug_vaccination"],
        message: "Enter the vaccination or drug name.",
      });
    }
  });

export type VaccinationFormValues = z.infer<typeof vaccinationSchema>;
