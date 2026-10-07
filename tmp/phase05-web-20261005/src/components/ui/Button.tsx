import type { ButtonHTMLAttributes, ReactNode } from "react";

type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";
type ButtonSize = "md" | "sm";

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: ButtonVariant;
  size?: ButtonSize;
  pill?: boolean;
  children: ReactNode;
};

const variantClass: Record<ButtonVariant, string> = {
  primary: "btn-primary",
  secondary: "btn-secondary",
  ghost: "btn btn-ghost",
  danger: "btn btn-danger",
};

export function Button({
  variant = "primary",
  size = "md",
  pill = false,
  className = "",
  type = "button",
  children,
  ...props
}: ButtonProps) {
  const classes = [
    variantClass[variant],
    size === "sm" ? "btn-sm" : "",
    pill ? "btn-pill" : "",
    className,
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <button type={type} className={classes} {...props}>
      {children}
    </button>
  );
}
