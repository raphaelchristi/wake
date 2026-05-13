"use client";

import Link from "next/link";

import { TableCell, TableRow } from "@/components/ui/table";
import type { Session } from "@/lib/api/types";
import { durationLabel, relativeTime, shortId } from "@/lib/format";

import { SessionStatusBadge } from "./SessionStatusBadge";

interface SessionRowProps {
  session: Session;
  /** Optional pre-computed event count if available — defaults to "—". */
  eventCount?: number | null;
}

export function SessionRow({ session, eventCount = null }: SessionRowProps) {
  const created = new Date(session.created_at);
  const updated = new Date(session.updated_at);
  const durationSec =
    !Number.isNaN(updated.getTime()) && !Number.isNaN(created.getTime())
      ? Math.max(0, (updated.getTime() - created.getTime()) / 1000)
      : null;

  const href = `/sessions/${encodeURIComponent(session.id)}`;
  const model = session.metadata?.["model"] ?? "—";

  return (
    <TableRow
      className="cursor-pointer"
      data-testid={`session-row-${session.id}`}
      onClick={(event) => {
        // Honour cmd/ctrl-click to open in a new tab; Link handles it natively.
        if (event.target instanceof HTMLAnchorElement) return;
        window.location.assign(href);
      }}
    >
      <TableCell className="font-mono text-xs">
        <Link href={href} className="hover:underline">
          {shortId(session.id)}
        </Link>
      </TableCell>
      <TableCell className="font-mono text-xs">{shortId(session.agent_id)}</TableCell>
      <TableCell>
        <SessionStatusBadge status={session.status} />
      </TableCell>
      <TableCell className="text-sm text-muted-foreground">{model}</TableCell>
      <TableCell className="whitespace-nowrap text-sm text-muted-foreground">
        {relativeTime(created)}
      </TableCell>
      <TableCell className="whitespace-nowrap text-sm text-muted-foreground">
        {durationLabel(durationSec)}
      </TableCell>
      <TableCell className="text-right text-sm tabular-nums text-muted-foreground">
        {eventCount ?? "—"}
      </TableCell>
    </TableRow>
  );
}
