"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { ArrowRight, Eye, EyeOff, LockKeyhole, UserRound } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useForm, type SubmitHandler } from "react-hook-form";

import { login } from "../api/auth-client";
import { loginSchema, type LoginFormValues } from "../validation/login";

type LoginFormProps = {
  redirectTo: string;
};

export function LoginForm({ redirectTo }: LoginFormProps) {
  const router = useRouter();
  const [serverError, setServerError] = useState<string | null>(null);
  const [showPassword, setShowPassword] = useState(false);
  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<LoginFormValues>({
    resolver: zodResolver(loginSchema),
    defaultValues: { username: "", password: "" },
    mode: "onBlur",
  });

  const onSubmit: SubmitHandler<LoginFormValues> = async (values) => {
    setServerError(null);

    try {
      await login(values);
      router.replace(redirectTo);
      router.refresh();
    } catch (error) {
      setServerError(error instanceof Error ? error.message : "Login failed.");
    }
  };

  return (
    <form onSubmit={handleSubmit(onSubmit)} noValidate className="grid gap-5">
      <div>
        <label
          htmlFor="username"
          className="text-xs font-extrabold uppercase tracking-[0.16em] text-[var(--navy)]"
        >
          Username
        </label>
        <div className="relative mt-2">
          <UserRound
            className="pointer-events-none absolute left-4 top-1/2 size-5 -translate-y-1/2 text-[var(--navy-muted)]"
            aria-hidden="true"
          />
          <input
            id="username"
            type="text"
            autoComplete="username"
            autoCapitalize="none"
            spellCheck={false}
            aria-invalid={Boolean(errors.username)}
            aria-describedby={errors.username ? "username-error" : undefined}
            {...register("username")}
            className="min-h-14 w-full rounded-xl border border-[var(--line)] bg-white py-3 pl-12 pr-4 text-base text-[var(--navy)] outline-none transition placeholder:text-[var(--navy-muted)]/70 focus:border-[var(--gold)] focus:ring-4 focus:ring-[var(--gold)]/20"
            placeholder="Enter your username"
          />
        </div>
        {errors.username ? (
          <p id="username-error" className="mt-2 text-sm font-semibold text-red-700">
            {errors.username.message}
          </p>
        ) : null}
      </div>

      <div>
        <label
          htmlFor="password"
          className="text-xs font-extrabold uppercase tracking-[0.16em] text-[var(--navy)]"
        >
          Password
        </label>
        <div className="relative mt-2">
          <LockKeyhole
            className="pointer-events-none absolute left-4 top-1/2 size-5 -translate-y-1/2 text-[var(--navy-muted)]"
            aria-hidden="true"
          />
          <input
            id="password"
            type={showPassword ? "text" : "password"}
            autoComplete="current-password"
            aria-invalid={Boolean(errors.password)}
            aria-describedby={errors.password ? "password-error" : undefined}
            {...register("password")}
            className="min-h-14 w-full rounded-xl border border-[var(--line)] bg-white py-3 pl-12 pr-14 text-base text-[var(--navy)] outline-none transition placeholder:text-[var(--navy-muted)]/70 focus:border-[var(--gold)] focus:ring-4 focus:ring-[var(--gold)]/20"
            placeholder="Enter your password"
          />
          <button
            type="button"
            onClick={() => setShowPassword((visible) => !visible)}
            aria-label={showPassword ? "Hide password" : "Show password"}
            aria-pressed={showPassword}
            className="absolute right-2 top-1/2 grid size-10 -translate-y-1/2 place-items-center rounded-lg text-[var(--navy-muted)] transition hover:bg-[var(--gold-soft)] hover:text-[var(--navy)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--gold)]"
          >
            {showPassword ? (
              <EyeOff className="size-5" aria-hidden="true" />
            ) : (
              <Eye className="size-5" aria-hidden="true" />
            )}
          </button>
        </div>
        {errors.password ? (
          <p id="password-error" className="mt-2 text-sm font-semibold text-red-700">
            {errors.password.message}
          </p>
        ) : null}
      </div>

      {serverError ? (
        <div
          role="alert"
          className="rounded-xl border border-red-300 bg-red-50 px-4 py-3 text-sm font-semibold text-red-800"
        >
          {serverError}
        </div>
      ) : null}

      <button
        type="submit"
        disabled={isSubmitting}
        className="group mt-1 inline-flex min-h-14 w-full items-center justify-center gap-3 rounded-xl bg-[var(--gold)] px-6 text-sm font-extrabold uppercase tracking-[0.16em] text-[var(--navy)] shadow-[0_12px_28px_rgba(242,189,66,0.24)] transition hover:-translate-y-0.5 hover:brightness-95 focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-[var(--gold)]/35 disabled:cursor-not-allowed disabled:translate-y-0 disabled:opacity-60"
      >
        {isSubmitting ? "Signing in…" : "Sign in"}
        {!isSubmitting ? (
          <ArrowRight
            className="size-4 transition-transform group-hover:translate-x-0.5"
            aria-hidden="true"
          />
        ) : null}
      </button>
    </form>
  );
}
