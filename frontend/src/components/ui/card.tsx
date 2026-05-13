/**
 * STUB — owned by dashboard-shell. See button.tsx for context.
 * TODO(dashboard-shell merge): replace with shadcn/ui Card.
 */
"use client";

import * as React from "react";
import { clsx } from "clsx";

export const Card = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => (
    <div
      ref={ref}
      className={clsx(
        "rounded-lg border border-slate-200 bg-white text-slate-900 shadow-sm",
        "dark:border-slate-800 dark:bg-slate-950 dark:text-slate-50",
        className,
      )}
      {...props}
    />
  ),
);
Card.displayName = "Card";

export const CardHeader = React.forwardRef<
  HTMLDivElement,
  React.HTMLAttributes<HTMLDivElement>
>(({ className, ...props }, ref) => (
  <div ref={ref} className={clsx("flex flex-col space-y-1.5 p-4", className)} {...props} />
));
CardHeader.displayName = "CardHeader";

export const CardTitle = React.forwardRef<
  HTMLHeadingElement,
  React.HTMLAttributes<HTMLHeadingElement>
>(({ className, ...props }, ref) => (
  <h3
    ref={ref}
    className={clsx("text-sm font-semibold leading-none tracking-tight", className)}
    {...props}
  />
));
CardTitle.displayName = "CardTitle";

export const CardContent = React.forwardRef<
  HTMLDivElement,
  React.HTMLAttributes<HTMLDivElement>
>(({ className, ...props }, ref) => (
  <div ref={ref} className={clsx("p-4 pt-0", className)} {...props} />
));
CardContent.displayName = "CardContent";
