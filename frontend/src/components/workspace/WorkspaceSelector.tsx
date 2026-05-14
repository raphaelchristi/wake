"use client";

import * as React from "react";
import { Check, ChevronsUpDown } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { setTenantScope, type TenantScope } from "@/lib/tenant";
import { useTenantScope } from "@/hooks/useTenantScope";

import { WorkspaceSwitchDialog } from "./WorkspaceSwitchDialog";

export interface WorkspaceOption extends TenantScope {
  /** Label opcional para mostrar no menu (fallback: `org / ws`). */
  label?: string;
}

/**
 * Fonte mock: enquanto o backend Wake não expõe `/v1/workspaces`, deixamos
 * a lista hardcoded com o tenant default + qualquer scope já gravado no
 * localStorage. O usuário pode adicionar workspaces via login form ou
 * digitando no dialog "Switch workspace".
 */
export const MOCK_WORKSPACE_OPTIONS: WorkspaceOption[] = [
  { organizationId: "default", workspaceId: "default", label: "default / default" },
];

export interface WorkspaceSelectorProps {
  /** Override pra storybook / testes. */
  options?: WorkspaceOption[];
  /** Override pra storybook / testes: aborta o `setTenantScope`. */
  onSelect?: (next: WorkspaceOption) => void;
  /** Aceita className extra pra alinhar no topbar. */
  className?: string;
}

export function WorkspaceSelector({
  options = MOCK_WORKSPACE_OPTIONS,
  onSelect,
  className,
}: WorkspaceSelectorProps) {
  const current = useTenantScope();
  const [open, setOpen] = React.useState(false);
  const [pending, setPending] = React.useState<TenantScope | null>(null);
  const containerRef = React.useRef<HTMLDivElement>(null);

  // Fecha o popover ao clicar fora.
  React.useEffect(() => {
    if (!open) return;
    function handler(event: MouseEvent) {
      if (!containerRef.current) return;
      if (!containerRef.current.contains(event.target as Node)) {
        setOpen(false);
      }
    }
    window.addEventListener("mousedown", handler);
    return () => window.removeEventListener("mousedown", handler);
  }, [open]);

  // Lista de opções inclui sempre o tenant atual mesmo que não esteja no
  // mock — assim o usuário vê onde está logado.
  const optionsWithCurrent = React.useMemo<WorkspaceOption[]>(() => {
    const exists = options.some(
      (o) =>
        o.organizationId === current.organizationId &&
        o.workspaceId === current.workspaceId,
    );
    if (exists) return options;
    return [{ ...current, label: `${current.organizationId} / ${current.workspaceId}` }, ...options];
  }, [options, current]);

  function startSwitch(option: WorkspaceOption) {
    setOpen(false);
    // Se for o mesmo escopo, no-op.
    if (
      option.organizationId === current.organizationId &&
      option.workspaceId === current.workspaceId
    ) {
      return;
    }
    if (onSelect) {
      onSelect(option);
      return;
    }
    setPending({
      organizationId: option.organizationId,
      workspaceId: option.workspaceId,
    });
  }

  function commitSwitch() {
    if (!pending) return;
    setTenantScope(pending);
    setPending(null);
  }

  function cancelSwitch() {
    setPending(null);
  }

  return (
    <div ref={containerRef} className={cn("relative", className)}>
      <Button
        type="button"
        variant="outline"
        size="sm"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label="Workspace selector"
        data-testid="workspace-selector-trigger"
        onClick={() => setOpen((v) => !v)}
        className="gap-2"
      >
        <span className="font-mono text-xs">
          {current.organizationId}
          <span className="px-1 text-muted-foreground">/</span>
          {current.workspaceId}
        </span>
        <ChevronsUpDown className="h-3 w-3 opacity-60" aria-hidden="true" />
      </Button>

      {open && (
        <div
          role="listbox"
          aria-label="Workspaces"
          data-testid="workspace-selector-menu"
          className="absolute right-0 z-50 mt-1 w-64 overflow-hidden rounded-md border border-border bg-popover p-1 text-popover-foreground shadow-lg"
        >
          {optionsWithCurrent.map((option) => {
            const active =
              option.organizationId === current.organizationId &&
              option.workspaceId === current.workspaceId;
            const key = `${option.organizationId}/${option.workspaceId}`;
            return (
              <button
                key={key}
                type="button"
                role="option"
                aria-selected={active}
                data-testid={`workspace-option-${key}`}
                onClick={() => startSwitch(option)}
                className={cn(
                  "flex w-full items-center justify-between gap-2 rounded px-2 py-1.5 text-left text-sm hover:bg-accent",
                  active && "bg-accent",
                )}
              >
                <span className="font-mono text-xs">
                  {option.label ?? `${option.organizationId} / ${option.workspaceId}`}
                </span>
                {active && <Check className="h-3 w-3" aria-hidden="true" />}
              </button>
            );
          })}
        </div>
      )}

      {pending && (
        <WorkspaceSwitchDialog
          target={pending}
          onConfirm={commitSwitch}
          onCancel={cancelSwitch}
        />
      )}
    </div>
  );
}
