"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { Search, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import type { SessionStatus } from "@/lib/api/types";

const STATUSES: ReadonlyArray<SessionStatus> = [
  "idle",
  "running",
  "rescheduling",
  "terminated",
] as const;

export interface SessionFiltersValue {
  agent: string;
  status: SessionStatus | "";
  model: string;
  q: string;
  since: string;
  until: string;
}

export function parseFilters(params: URLSearchParams): SessionFiltersValue {
  const status = params.get("status") ?? "";
  return {
    agent: params.get("agent") ?? "",
    status: (STATUSES as readonly string[]).includes(status) ? (status as SessionStatus) : "",
    model: params.get("model") ?? "",
    q: params.get("q") ?? "",
    since: params.get("since") ?? "",
    until: params.get("until") ?? "",
  };
}

function toQueryString(value: SessionFiltersValue): string {
  const params = new URLSearchParams();
  for (const [k, v] of Object.entries(value)) {
    if (v) params.set(k, v);
  }
  const s = params.toString();
  return s ? `?${s}` : "";
}

export function SessionFilters() {
  const router = useRouter();
  const search = useSearchParams();
  const [value, setValue] = useState<SessionFiltersValue>(() => parseFilters(new URLSearchParams(search?.toString() ?? "")));

  // Keep local state synced if the URL is mutated elsewhere (e.g. browser back).
  useEffect(() => {
    setValue(parseFilters(new URLSearchParams(search?.toString() ?? "")));
  }, [search]);

  const update = useCallback(
    (patch: Partial<SessionFiltersValue>) => {
      setValue((prev) => {
        const next = { ...prev, ...patch };
        router.replace(`/sessions${toQueryString(next)}`);
        return next;
      });
    },
    [router],
  );

  const reset = useCallback(() => {
    setValue({ agent: "", status: "", model: "", q: "", since: "", until: "" });
    router.replace("/sessions");
  }, [router]);

  const hasActive = Boolean(value.agent || value.status || value.model || value.q || value.since || value.until);

  return (
    <form
      role="search"
      className="grid gap-3 md:grid-cols-[1fr_repeat(4,minmax(0,140px))_auto]"
      onSubmit={(e) => e.preventDefault()}
    >
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="filter-q">Search</Label>
        <div className="relative">
          <Search
            className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground"
            aria-hidden="true"
          />
          <Input
            id="filter-q"
            placeholder="Session ID, agent, metadata…"
            value={value.q}
            onChange={(e) => update({ q: e.target.value })}
            className="pl-8"
          />
        </div>
      </div>
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="filter-agent">Agent</Label>
        <Input
          id="filter-agent"
          placeholder="agent_…"
          value={value.agent}
          onChange={(e) => update({ agent: e.target.value })}
        />
      </div>
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="filter-status">Status</Label>
        <Select
          id="filter-status"
          value={value.status}
          onChange={(e) => update({ status: e.target.value as SessionStatus | "" })}
        >
          <option value="">All</option>
          {STATUSES.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </Select>
      </div>
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="filter-model">Model</Label>
        <Input
          id="filter-model"
          placeholder="claude-opus-4-7"
          value={value.model}
          onChange={(e) => update({ model: e.target.value })}
        />
      </div>
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="filter-since">Since</Label>
        <Input
          id="filter-since"
          type="date"
          value={value.since}
          onChange={(e) => update({ since: e.target.value })}
        />
      </div>
      <div className="flex items-end">
        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={reset}
          disabled={!hasActive}
          aria-label="Reset filters"
        >
          <X className="h-4 w-4" />
          <span>Reset</span>
        </Button>
      </div>
    </form>
  );
}
