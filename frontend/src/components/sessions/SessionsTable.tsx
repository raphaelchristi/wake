"use client";

import { type Session } from "@/lib/api/types";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

import { SessionRow } from "./SessionRow";

interface SessionsTableProps {
  sessions: Session[];
  isLoading?: boolean;
  emptyMessage?: string;
}

export function SessionsTable({
  sessions,
  isLoading = false,
  emptyMessage = "No sessions match the current filters.",
}: SessionsTableProps) {
  return (
    <div className="rounded-lg border border-border bg-card">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="w-[14ch]">Session</TableHead>
            <TableHead className="w-[14ch]">Agent</TableHead>
            <TableHead className="w-[10ch]">Status</TableHead>
            <TableHead>Model</TableHead>
            <TableHead className="w-[14ch]">Created</TableHead>
            <TableHead className="w-[10ch]">Duration</TableHead>
            <TableHead className="w-[8ch] text-right">Events</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {isLoading && sessions.length === 0 ? (
            <TableRow>
              <TableCell colSpan={7} className="py-10 text-center text-sm text-muted-foreground">
                Loading sessions…
              </TableCell>
            </TableRow>
          ) : sessions.length === 0 ? (
            <TableRow>
              <TableCell colSpan={7} className="py-10 text-center text-sm text-muted-foreground">
                {emptyMessage}
              </TableCell>
            </TableRow>
          ) : (
            sessions.map((session) => <SessionRow key={session.id} session={session} />)
          )}
        </TableBody>
      </Table>
    </div>
  );
}
