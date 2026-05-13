"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";

import { AppShell } from "@/components/layout/AppShell";
import { isAuthenticated } from "@/lib/auth";

export default function AuthedLayout({ children }: { children: ReactNode }) {
  const router = useRouter();
  const [ready, setReady] = useState(false);

  useEffect(() => {
    if (!isAuthenticated()) {
      router.replace("/login");
      return;
    }
    setReady(true);
  }, [router]);

  if (!ready) {
    // Render an inert shell so the layout is consistent. The redirect lands
    // almost immediately, so this only flashes for ~1 frame.
    return (
      <AppShell>
        <div className="py-12 text-sm text-muted-foreground">Authenticating…</div>
      </AppShell>
    );
  }

  return <AppShell>{children}</AppShell>;
}
