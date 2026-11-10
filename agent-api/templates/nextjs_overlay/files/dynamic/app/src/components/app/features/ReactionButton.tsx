"use client";

import { useQueryClient } from "@tanstack/react-query";
import { ArrowBigUp, Bookmark, CircleCheck, Heart, UserCheck, UserPlus } from "lucide-react";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { resolveParams, type TAppAction, type TRecord, type TRouteParams } from "../app";
import { useOperationMutation } from "../bindings";
import { errorMessage } from "../errors";
import { recordOf, signal } from "../signals";

const ICONS = { like: Heart, save: Bookmark, upvote: ArrowBigUp, follow: UserPlus, complete: CircleCheck } as const;
// what the button says once done (a follow reads "Following"); the others keep their label and fill their icon
const DONE: Record<string, string> = { follow: "Following", complete: "Completed" };

/** Epic 33 (the reactions feature): a like, save or upvote as a toggle. It shows whether the person already did it
 *  (the record's own-row field, `myLikeId`) and the count, changes both at once on a tap, and undoes on a second tap. */
export function ReactionButton({ action, record }: { action: TAppAction; record?: TRecord }) {
  const route = (useParams() ?? {}) as TRouteParams;
  const queryClient = useQueryClient();
  const add = useOperationMutation(action.operationId);
  const remove = useOperationMutation(action.undoOperationId);
  const mine = (action.state ? record?.[action.state] : null) as string | null | undefined;
  const count = Number((action.count ? record?.[action.count] : 0) ?? 0);
  const [optimistic, setOptimistic] = useState<{ on: boolean; count: number } | null>(null);
  useEffect(() => setOptimistic(null), [mine, count]); // the server's answer replaces the guess
  const on = optimistic?.on ?? Boolean(mine);
  const shown = optimistic?.count ?? count;
  const kind = (action.reaction ?? "like") as keyof typeof ICONS;
  const Icon = on && kind === "follow" ? UserCheck : (ICONS[kind] ?? Heart);
  const pending = add.isPending || remove.isPending;

  function toggle() {
    if (pending) return;
    const undo = on && Boolean(mine);
    const operationId = undo ? action.undoOperationId : action.operationId;
    setOptimistic({ on: !on, count: Math.max(0, shown + (on ? -1 : 1)) });
    const handlers = {
      onSuccess: (result: unknown) => {
        if (operationId) signal("operation", { operationId, record: undo ? mine : recordOf({}, result) });
        void queryClient.invalidateQueries(); // the record's count and own-row field come back from the server
      },
      onError: (error: unknown) => {
        setOptimistic(null);
        toast.error(errorMessage(operationId, error));
      },
    };
    if (undo) remove.mutate({ params: { id: mine }, body: {} }, handlers);
    else add.mutate({ params: {}, body: resolveParams(action.body, route, record) ?? {} }, handlers);
  }

  return (
    <Button
      variant={on ? "default" : "outline"}
      size="sm"
      aria-pressed={on}
      onClick={toggle}
      disabled={pending}
      data-bga-action={action.id}
      data-bga-reaction={action.reaction ?? "like"}
      className="gap-1.5"
    >
      <Icon className={cn("size-4", on && "fill-current")} aria-hidden />
      <span>{on && DONE[kind] ? DONE[kind] : action.label}</span>
      {action.count && <span className="tabular-nums">{shown}</span>}
    </Button>
  );
}
