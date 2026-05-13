// TODO: dashboard-shell slice owns the canonical shadcn Button. Stub for
// typechecking — shell merge replaces with the full variant system.
import * as React from "react";
import { cn } from "@/lib/utils";

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: "default" | "outline" | "ghost" | "destructive";
  size?: "default" | "sm" | "lg" | "icon";
}

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant = "default", size = "default", ...props }, ref) => {
    const variantClass =
      variant === "outline"
        ? "border border-input bg-background hover:bg-accent"
        : variant === "ghost"
          ? "hover:bg-accent"
          : variant === "destructive"
            ? "bg-destructive text-destructive-foreground hover:bg-destructive/90"
            : "bg-primary text-primary-foreground hover:bg-primary/90";
    const sizeClass =
      size === "sm"
        ? "h-8 rounded px-3 text-xs"
        : size === "lg"
          ? "h-10 rounded px-6"
          : size === "icon"
            ? "h-9 w-9 rounded"
            : "h-9 rounded px-4 py-2";
    return (
      <button
        ref={ref}
        className={cn("inline-flex items-center justify-center font-medium", variantClass, sizeClass, className)}
        {...props}
      />
    );
  },
);
Button.displayName = "Button";
