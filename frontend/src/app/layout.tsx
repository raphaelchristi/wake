/**
 * STUB — owned by dashboard-shell.
 *
 * Minimal root layout so the replay slice's Next.js build succeeds in
 * isolation. The shell slice ships the real layout (theme provider, query
 * client, auth gate, nav shell, fonts, globals.css). When dashboard-shell
 * merges into main, this file is expected to be REPLACED by the shell's
 * full implementation.
 *
 * TODO(dashboard-shell merge): delete this stub.
 */
import type { ReactNode } from "react";

export const metadata = {
  title: "Wake Dashboard",
  description: "Operator UI for Wake.",
};

export default function RootLayout({
  children,
}: {
  children: ReactNode;
}): React.ReactElement {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
