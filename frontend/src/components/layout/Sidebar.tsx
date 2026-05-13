"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Activity, KeyRound, ListTree, Waves } from "lucide-react";

import { cn } from "@/lib/utils";

const NAV = [
  { href: "/sessions", label: "Sessions", icon: ListTree },
  { href: "/metrics", label: "Metrics", icon: Activity },
  { href: "/vault", label: "Vault", icon: KeyRound },
] as const;

export function Sidebar() {
  const pathname = usePathname();
  return (
    <aside className="hidden w-56 shrink-0 border-r border-border bg-sidebar/60 md:flex md:flex-col">
      <div className="flex h-14 items-center gap-2 border-b border-border px-4">
        <Waves className="h-5 w-5 text-primary" aria-hidden="true" />
        <span className="text-sm font-semibold tracking-wide">Wake</span>
      </div>
      <nav className="flex-1 space-y-1 px-2 py-4" aria-label="Primary">
        {NAV.map(({ href, label, icon: Icon }) => {
          const active = pathname?.startsWith(href);
          return (
            <Link
              key={href}
              href={href}
              className={cn(
                "flex items-center gap-2 rounded-md px-3 py-2 text-sm font-medium text-muted-foreground transition-colors hover:bg-accent hover:text-foreground",
                active && "bg-accent text-foreground",
              )}
              data-active={active ? "true" : undefined}
            >
              <Icon className="h-4 w-4" aria-hidden="true" />
              <span>{label}</span>
            </Link>
          );
        })}
      </nav>
      <div className="border-t border-border px-4 py-3 text-xs text-muted-foreground">
        Wake Dashboard · v0.5
      </div>
    </aside>
  );
}
