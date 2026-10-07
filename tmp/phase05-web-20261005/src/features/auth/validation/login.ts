import { z } from "zod";

export const loginSchema = z.object({
  username: z
    .string()
    .trim()
    .min(1, "Username is required.")
    .max(150, "Username cannot exceed 150 characters."),

  password: z
    .string()
    .min(1, "Password is required."),
});

export type LoginFormValues = z.infer<
  typeof loginSchema
>;