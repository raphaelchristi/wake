import { Badge } from "@/components/ui/badge";
import type { SessionStatus } from "@/lib/api/types";

const STATUS_LABEL: Record<SessionStatus, string> = {
  idle: "Idle",
  running: "Running",
  rescheduling: "Rescheduling",
  terminated: "Terminated",
};

const STATUS_VARIANT: Record<SessionStatus, "success" | "warning" | "muted" | "danger"> = {
  idle: "muted",
  running: "success",
  rescheduling: "warning",
  terminated: "danger",
};

export function SessionStatusBadge({ status }: { status: SessionStatus }) {
  return (
    <Badge variant={STATUS_VARIANT[status]} aria-label={`Status: ${STATUS_LABEL[status]}`}>
      {STATUS_LABEL[status]}
    </Badge>
  );
}
