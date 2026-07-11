import { z } from "zod";

export const saleSchema = z
  .object({
    sale_date: z.string().min(1, "Sale date is required."),

    product_type: z.enum(["live_chicken", "dressed_chicken", "eggs", "manure"]),

    quantity_sold: z
      .number()
      .int("Quantity must be a whole number.")
      .positive("Quantity must be greater than zero."),

    unit_price: z
      .number()
      .int("Unit price must be a whole number.")
      .positive("Unit price must be greater than zero."),

    buyer_name: z
      .string()
      .trim()
      .min(2, "Buyer name must contain at least 2 characters.")
      .max(200, "Buyer name cannot exceed 200 characters."),

    buyer_type: z.enum([
      "market_vendor",
      "retail",
      "retail_supply",
      "bulk_order",
    ]),

    payment_status: z.enum(["paid", "partial", "loan", "unpaid", "cancelled"]),

    payment_method: z.enum(["cash", "mobile_money", "bank_transfer", "credit"]),

    amount_paid: z
      .number()
      .int("Amount paid must be a whole number.")
      .min(0, "Amount paid cannot be negative."),

    sold_by_name: z
      .string()
      .trim()
      .min(2, "Seller name must contain at least 2 characters.")
      .max(200, "Seller name cannot exceed 200 characters."),

    notes: z
      .string()
      .trim()
      .min(2, "Notes must contain at least 2 characters.")
      .max(1000, "Notes cannot exceed 1,000 characters."),
  })
  .superRefine((values, context) => {
    const saleTotal = values.quantity_sold * values.unit_price;

    if (values.amount_paid > saleTotal) {
      context.addIssue({
        code: "custom",
        path: ["amount_paid"],
        message: "Amount paid cannot exceed the sale total.",
      });
    }
  });

export type SaleFormValues = z.infer<typeof saleSchema>;
