"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useRouter } from "next/navigation";
import { useState } from "react";

import {
  useForm,
  type SubmitHandler,
} from "react-hook-form";

import { login } from "../api/auth-client";

import {
  loginSchema,
  type LoginFormValues,
} from "../validation/login";

type LoginFormProps = {
  redirectTo: string;
};

export function LoginForm({
  redirectTo,
}: LoginFormProps) {
  const router = useRouter();

  const [serverError, setServerError] =
    useState<string | null>(null);

  const {
    register,
    handleSubmit,
    formState: {
      errors,
      isSubmitting,
    },
  } = useForm<LoginFormValues>({
    resolver: zodResolver(loginSchema),

    defaultValues: {
      username: "",
      password: "",
    },

    mode: "onBlur",
  });

  const onSubmit: SubmitHandler<
    LoginFormValues
  > = async (values) => {
    setServerError(null);

    try {
      await login(values);

      router.replace(redirectTo);
      router.refresh();
    } catch (error) {
      setServerError(
        error instanceof Error
          ? error.message
          : "Login failed."
      );
    }
  };

  return (
    <form
      onSubmit={handleSubmit(onSubmit)}
      noValidate
      className="grid gap-6"
    >
      <div>
        <label
          htmlFor="username"
          className="text-label text-[var(--navy-muted)]"
        >
          Username
        </label>

        <input
          id="username"
          type="text"
          autoComplete="username"
          aria-invalid={
            Boolean(errors.username)
          }
          aria-describedby={
            errors.username
              ? "username-error"
              : undefined
          }
          {...register("username")}
          className="form-input mt-2"
        />

        {errors.username ? (
          <p
            id="username-error"
            className="mt-2 text-sm text-red-700"
          >
            {errors.username.message}
          </p>
        ) : null}
      </div>

      <div>
        <label
          htmlFor="password"
          className="text-label text-[var(--navy-muted)]"
        >
          Password
        </label>

        <input
          id="password"
          type="password"
          autoComplete="current-password"
          aria-invalid={
            Boolean(errors.password)
          }
          aria-describedby={
            errors.password
              ? "password-error"
              : undefined
          }
          {...register("password")}
          className="form-input mt-2"
        />

        {errors.password ? (
          <p
            id="password-error"
            className="mt-2 text-sm text-red-700"
          >
            {errors.password.message}
          </p>
        ) : null}
      </div>

      {serverError ? (
        <div
          role="alert"
          className="rounded-xl border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-800"
        >
          {serverError}
        </div>
      ) : null}

      <button
        type="submit"
        disabled={isSubmitting}
        className="rounded-full bg-[var(--gold)] px-6 py-3 text-[0.72rem] font-bold uppercase tracking-[0.18em] text-[var(--navy)] transition hover:brightness-95 disabled:cursor-not-allowed disabled:opacity-60"
      >
        {isSubmitting
          ? "Signing in..."
          : "Sign in"}
      </button>
    </form>
  );
}