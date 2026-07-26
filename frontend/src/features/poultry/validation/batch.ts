import { z } from "zod";

export const batchSchema = z
  .object({
    bird_type: z.enum(["broilers", "layers", "local", "kloilers", "mikolongwe"]),

    source: z.enum(["proto", "central_poultry", "other"]),

    source_other: z.string().trim().optional(),

    entry_date: z.string().min(1, "Entry date is required."),

    expected_maturity_date: z
      .string()
      .min(1, "Expected maturity date is required."),

    quantity: z
      .number()
      .int("Quantity must be a whole number.")
      .positive("Quantity must be greater than zero."),
  })
  .superRefine((values, context) => {
    const entryDate = new Date(values.entry_date);
    const maturityDate = new Date(values.expected_maturity_date);

    if (
      values.source === "other" &&
      (!values.source_other || values.source_other.trim().length < 2)
    ) {
      context.addIssue({
        code: "custom",
        path: ["source_other"],
        message: "Enter the source name.",
      });
    }

    if (Number.isNaN(entryDate.getTime())) {
      context.addIssue({
        code: "custom",
        path: ["entry_date"],
        message: "Entry date must be a valid date.",
      });
    }

    if (Number.isNaN(maturityDate.getTime())) {
      context.addIssue({
        code: "custom",
        path: ["expected_maturity_date"],
        message: "Expected maturity date must be a valid date.",
      });
    }

    if (
      !Number.isNaN(entryDate.getTime()) &&
      !Number.isNaN(maturityDate.getTime()) &&
      maturityDate <= entryDate
    ) {
      context.addIssue({
        code: "custom",
        path: ["expected_maturity_date"],
        message: "Expected maturity date must be after the entry date.",
      });
    }
  });

export type BatchFormValues = z.infer<typeof batchSchema>;

export const bookingSchema = z
  .object({
    bird_type: z.enum(["broilers", "layers", "local", "kloilers", "mikolongwe"]),

    source: z.enum(["proto", "central_poultry", "other"]),

    source_other: z.string().trim().optional(),

    booking_date: z.string().min(1, "Booking date is required."),

    estimated_chick_arrival_date: z
      .string()
      .min(1, "Expected delivery date is required."),

    quantity: z
      .number()
      .int("Quantity must be a whole number.")
      .positive("Quantity must be greater than zero."),
  })
  .superRefine((values, context) => {
    const bookingDate = new Date(values.booking_date);
    const arrivalDate = new Date(values.estimated_chick_arrival_date);

    if (
      values.source === "other" &&
      (!values.source_other || values.source_other.trim().length < 2)
    ) {
      context.addIssue({
        code: "custom",
        path: ["source_other"],
        message: "Enter the source name.",
      });
    }

    if (Number.isNaN(bookingDate.getTime())) {
      context.addIssue({
        code: "custom",
        path: ["booking_date"],
        message: "Booking date must be a valid date.",
      });
    }

    if (Number.isNaN(arrivalDate.getTime())) {
      context.addIssue({
        code: "custom",
        path: ["estimated_chick_arrival_date"],
        message: "Expected delivery must be a valid date.",
      });
    }

    if (
      !Number.isNaN(bookingDate.getTime()) &&
      !Number.isNaN(arrivalDate.getTime()) &&
      arrivalDate < bookingDate
    ) {
      context.addIssue({
        code: "custom",
        path: ["estimated_chick_arrival_date"],
        message: "Expected delivery cannot be before the booking date.",
      });
    }
  });

export const deliverySchema = z
  .object({
    entry_date: z.string().min(1, "Delivery date is required."),

    expected_maturity_date: z
      .string()
      .min(1, "Expected maturity date is required."),

    quantity: z
      .number()
      .int("Quantity must be a whole number.")
      .positive("Quantity must be greater than zero."),
  })
  .superRefine((values, context) => {
    const entryDate = new Date(values.entry_date);
    const maturityDate = new Date(values.expected_maturity_date);

    if (Number.isNaN(entryDate.getTime())) {
      context.addIssue({
        code: "custom",
        path: ["entry_date"],
        message: "Delivery date must be a valid date.",
      });
    }

    if (Number.isNaN(maturityDate.getTime())) {
      context.addIssue({
        code: "custom",
        path: ["expected_maturity_date"],
        message: "Expected maturity date must be a valid date.",
      });
    }

    if (
      !Number.isNaN(entryDate.getTime()) &&
      !Number.isNaN(maturityDate.getTime()) &&
      maturityDate <= entryDate
    ) {
      context.addIssue({
        code: "custom",
        path: ["expected_maturity_date"],
        message: "Expected maturity date must be after the delivery date.",
      });
    }
  });

export type BookingFormValues = z.infer<typeof bookingSchema>;
export type DeliveryFormValues = z.infer<typeof deliverySchema>;
