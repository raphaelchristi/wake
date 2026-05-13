// TODO: dashboard-shell slice owns the canonical root layout — it will
// wire QueryClientProvider, Tailwind/global CSS, fonts, and the dark-mode
// toggle. This minimal stub lets the metrics-vault slice's `pnpm build`
// succeed before the shell merges. On merge the shell file overwrites
// this file. Keep it boring.
import type { ReactNode } from "react";

export const metadata = {
  title: "Wake Dashboard",
  description: "Operator UI for Wake.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
