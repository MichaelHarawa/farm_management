import { z } from "zod";

export const inputCostSchema = z
  .object({
    item: z
      .string()
      .trim()
      .min(2, "Item name must contain at least 2 characters.")
      .max(200, "Item name cannot exceed 200 characters."),

    category: z
      .string()
      .trim()
      .min(2, "Category must contain at least 2 characters.")
      .max(200, "Category cannot exceed 200 characters."),

    quantity: z
      .number()
      .int("Quantity must be a whole number.")
      .positive("Quantity must be greater than zero."),

    unit: z
      .number()
      .int("Unit size must be a whole number.")
      .positive("Unit size must be greater than zero."),

    unit_measurement: z.string().min(1, "Select a unit measurement."),

    unit_cost: z
      .number()
      .int("Unit cost must be a whole number.")
      .positive("Unit cost must be greater than zero."),

    purchase_date: z.string().min(1, "Purchase date is required."),
  })
  .superRefine((values, context) => {
    const purchaseDate = new Date(values.purchase_date);

    if (Number.isNaN(purchaseDate.getTime())) {
      context.addIssue({
        code: "custom",
        path: ["purchase_date"],
        message: "Purchase date must be a valid date.",
      });
    }
  });

export type InputCostFormValues = z.infer<
  typeof inputCostSchema
>;
