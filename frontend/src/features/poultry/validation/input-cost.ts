import { z } from "zod";

const fundingAllocationSchema = z.object({
  funding_source: z.number().int().positive("Select a funding source."),
  source_query: z.string().optional(),
  amount: z.number().positive("Funding amount must be greater than zero."),
  classification: z.string(),
});

export const inputCostSchema = z
  .object({
    item: z.string().trim().min(2, "Item name must contain at least 2 characters.").max(200),
    category_id: z.number().int().positive("Select a category."),
    quantity: z.number().int("Number of items must be a whole number.").positive(),
    unit: z.number().int("Size per item must be a whole number.").positive(),
    unit_measurement: z.string().min(1, "Select a unit measurement."),
    unit_cost: z.number().positive("Price per measurement unit must be greater than zero."),
    purchase_date: z.string().min(1, "Purchase date is required."),
    notes: z.string().trim().min(2, "Notes must contain at least 2 characters.").max(1000),
    payment_status: z.enum(["paid", "credit"]),
    funding_allocations: z.array(fundingAllocationSchema),
    idempotency_key: z.string().min(8),
  })
  .superRefine((values, context) => {
    const purchaseDate = new Date(values.purchase_date);
    if (Number.isNaN(purchaseDate.getTime())) {
      context.addIssue({ code: "custom", path: ["purchase_date"], message: "Purchase date must be valid." });
    }

    const total = values.quantity * values.unit * values.unit_cost;
    const funded = values.funding_allocations.reduce((sum, row) => sum + row.amount, 0);
    if (values.payment_status === "paid" && values.funding_allocations.length === 0) {
      context.addIssue({ code: "custom", path: ["funding_allocations"], message: "Select where this payment came from." });
    } else if (values.payment_status === "paid" && Math.abs(total - funded) >= 0.01) {
      context.addIssue({ code: "custom", path: ["funding_allocations"], message: "Funding sources must equal the calculated total." });
    }
    if (values.payment_status === "credit" && values.funding_allocations.length > 0) {
      context.addIssue({ code: "custom", path: ["funding_allocations"], message: "Credit purchases are funded only when payment is recorded." });
    }
  });

export type InputCostFormValues = z.infer<typeof inputCostSchema>;
