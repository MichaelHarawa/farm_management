import { z } from "zod";

export const feedUsageSchema = z
  .object({
    initial_age: z
      .number()
      .int("Initial age must be a whole number.")
      .min(0, "Initial age cannot be negative."),

    feeding_start_date: z.string().min(1, "Feeding start date is required."),

    feeding_end_date: z.string().min(1, "Feeding end date is required."),

    feed_type: z.enum([
      "pre_starter",
      "starter",
      "grower",
      "finisher",
      "pullet_starter",
      "pullet_grower",
      "layers_marsh",
      "layers_finisher",
    ]),

    feed_source: z.enum([
      "cp_feed",
      "proto_feed",
      "concentrates_feed",
      "self_made",
    ]),

    quantity_given: z
      .number()
      .int("Quantity must be a whole number.")
      .positive("Quantity must be greater than zero."),

    unit_of_measurement: z.enum(["kg", "g"]),

    current_number_of_birds: z
      .number()
      .int("Current birds must be a whole number.")
      .min(0, "Current birds cannot be negative."),

    notes: z
      .string()
      .trim()
      .min(2, "Notes must contain at least 2 characters.")
      .max(1000, "Notes cannot exceed 1,000 characters."),

    reported_by_name: z
      .string()
      .trim()
      .min(2, "Reporter name must contain at least 2 characters.")
      .max(200, "Reporter name cannot exceed 200 characters."),
  })
  .superRefine((values, context) => {
    const startDate = new Date(values.feeding_start_date);
    const endDate = new Date(values.feeding_end_date);

    if (Number.isNaN(startDate.getTime())) {
      context.addIssue({
        code: "custom",
        path: ["feeding_start_date"],
        message: "Feeding start date must be a valid date.",
      });
    }

    if (Number.isNaN(endDate.getTime())) {
      context.addIssue({
        code: "custom",
        path: ["feeding_end_date"],
        message: "Feeding end date must be a valid date.",
      });
    }

    if (
      !Number.isNaN(startDate.getTime()) &&
      !Number.isNaN(endDate.getTime()) &&
      endDate < startDate
    ) {
      context.addIssue({
        code: "custom",
        path: ["feeding_end_date"],
        message: "Feeding end date must be on or after the start date.",
      });
    }
  });

export type FeedUsageFormValues = z.infer<typeof feedUsageSchema>;
