"use client";

import * as React from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import type { TenantScope } from "@/lib/tenant";

export interface WorkspaceSwitchDialogProps {
  target: TenantScope;
  onConfirm: () => void;
  onCancel: () => void;
}

/**
 * Confirmação simples antes de trocar de workspace. A consequência é
 * destrutiva (limpa cache → toda navegação refaz) então pedimos confirmação
 * explícita pra evitar misclicks em meio a uma sessão sendo observada.
 */
export function WorkspaceSwitchDialog({
  target,
  onConfirm,
  onCancel,
}: WorkspaceSwitchDialogProps) {
  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open) onCancel();
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Switch workspace?</DialogTitle>
          <DialogDescription>
            Você está prestes a entrar em{" "}
            <span className="font-mono">
              {target.organizationId} / {target.workspaceId}
            </span>
            . Todo o cache local (sessões, eventos, metrics) será limpo e
            você voltará para a lista de sessões.
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button variant="outline" onClick={onCancel} data-testid="workspace-switch-cancel">
            Cancelar
          </Button>
          <Button onClick={onConfirm} data-testid="workspace-switch-confirm">
            Trocar workspace
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
