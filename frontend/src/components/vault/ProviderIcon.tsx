import * as React from "react";

import { cn } from "@/lib/utils";

export type VaultProvider = "github" | "slack" | "notion" | "custom" | string;

export interface ProviderIconProps extends React.SVGAttributes<SVGSVGElement> {
  provider: VaultProvider;
  size?: number;
}

/**
 * Inline brand glyphs for the four supported OAuth providers (GitHub /
 * Slack / Notion) and a generic "custom" fallback. We ship SVGs inline
 * instead of pulling icon packages so the dashboard stays bundle-tight
 * and renders the same shape in dark/light mode by using currentColor.
 */
export function ProviderIcon({
  provider,
  size = 16,
  className,
  ...rest
}: ProviderIconProps) {
  const slug = String(provider).toLowerCase();
  const common = {
    width: size,
    height: size,
    "aria-hidden": true,
    className: cn("inline-block align-text-bottom", className),
    ...rest,
  } as const;

  if (slug === "github") {
    return (
      <svg viewBox="0 0 16 16" fill="currentColor" {...common}>
        <path d="M8 0C3.58 0 0 3.58 0 8a8 8 0 0 0 5.47 7.59c.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2 .37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8 8 0 0 0 16 8c0-4.42-3.58-8-8-8z" />
      </svg>
    );
  }
  if (slug === "slack") {
    return (
      <svg viewBox="0 0 60 60" fill="currentColor" {...common}>
        <path
          d="M22 35a5 5 0 1 1-5-5h5v5zm3 0a5 5 0 1 1 10 0v13a5 5 0 1 1-10 0V35z"
          fill="#E01E5A"
        />
        <path
          d="M30 22a5 5 0 1 1 5-5v5h-5zm0 3a5 5 0 1 1 0 10H17a5 5 0 1 1 0-10h13z"
          fill="#36C5F0"
        />
        <path
          d="M43 30a5 5 0 1 1 5 5h-5v-5zm-3 0a5 5 0 1 1-10 0V17a5 5 0 1 1 10 0v13z"
          fill="#2EB67D"
        />
        <path
          d="M30 43a5 5 0 1 1-5 5v-5h5zm0-3a5 5 0 1 1 0-10h13a5 5 0 1 1 0 10H30z"
          fill="#ECB22E"
        />
      </svg>
    );
  }
  if (slug === "notion") {
    return (
      <svg viewBox="0 0 24 24" fill="currentColor" {...common}>
        <path d="M4.459 4.208a2.16 2.16 0 0 1 1.557-.733l11.51-.825c1.398-.099 1.789.066 2.667.74l3.685 2.587c.601.45.866.582.866 1.066v14.05c0 .867-.299 1.39-1.398 1.456l-13.376.792c-.799.066-1.165-.05-1.566-.55l-2.711-3.518c-.435-.6-.625-1.05-.625-1.583V5.99c0-.733.299-1.349 1.391-1.782zm9.844 1.41v12.516c0 .299.166.4.466.367l.799-.05c.299-.034.4-.2.4-.5V7.073c0-.299-.133-.466-.4-.433l-.866.05c-.299.034-.4.166-.4.433zm-2.798.5l-3.685.232c-.299.034-.4.166-.4.466v10.832c0 .299.166.434.466.4l3.685-.2c.366-.034.433-.2.433-.5V6.485c0-.299-.133-.4-.5-.367z" />
      </svg>
    );
  }
  // generic: a small key glyph
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" {...common}>
      <path d="m21 2-2 2m-7.61 7.61a5.5 5.5 0 1 1-7.778 7.778 5.5 5.5 0 0 1 7.777-7.777zm0 0L15.5 7.5m0 0 3 3L22 7l-3-3m-3.5 3.5L19 4" />
    </svg>
  );
}
