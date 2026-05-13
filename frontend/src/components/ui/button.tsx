/**
 * STUB — owned by dashboard-shell.
 *
 * Minimal Button so the replay slice compiles + renders. When dashboard-shell
 * merges, the full shadcn primitive (with variants, asChild, Radix Slot, ring
 * tokens, etc.) takes over. We keep the same prop surface (`variant`,
 * `size`, `disabled`, all standard <button> props) so consumers don't break.
 *
 * TODO(dashboard-shell merge): replace with shadcn/ui Button.
 */
"use client";

import * as React from "react";
import { clsx } from "clsx";

export type ButtonVariant = "default" | "secondary" | "ghost" | "outline" | "destructive";
export type ButtonSize = "default" | "sm" | "lg" | "icon";

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
}

const variantClasses: Record<ButtonVariant, string> = {
  default: "bg-blue-600 text-white hover:bg-blue-700",
  secondary: "bg-slate-200 text-slate-900 hover:bg-slate-300 dark:bg-slate-700 dark:text-slate-100",
  ghost: "bg-transparent hover:bg-slate-100 dark:hover:bg-slate-800",
  outline: "border border-slate-300 dark:border-slate-700 bg-transparent",
  destructive: "bg-red-600 text-white hover:bg-red-700",
};

const sizeClasses: Record<ButtonSize, string> = {
  default: "h-9 px-4 text-sm",
  sm: "h-8 px-3 text-xs",
  lg: "h-10 px-6 text-base",
  icon: "h-9 w-9",
};

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant = "default", size = "default", ...props }, ref) => (
    <button
      ref={ref}
      className={clsx(
        "inline-flex items-center justify-center rounded-md font-medium transition-colors",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500",
        "disabled:opacity-50 disabled:pointer-events-none",
        variantClasses[variant],
        sizeClasses[size],
        className,
      )}
      {...props}
    />
  ),
);
Button.displayName = "Button";
