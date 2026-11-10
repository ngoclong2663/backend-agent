"use client";

import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Switch } from "@/components/ui/switch";
import { listOf, type TAppSection } from "../app";
import { useOperationMutation, useOperationQuery } from "../bindings";
import { errorMessage } from "../errors";
import { signal } from "../signals";

/** Epic 33 (the availability feature): the person's Online switch. Online while they have an availability row; the
 *  switch adds it or removes it. */
export function AppPresence({ section }: { section: TAppSection }) {
  const presence = section.content?.presence;
  const queryClient = useQueryClient();
  const query = useOperationQuery(presence?.list, {});
  const add = useOperationMutation(presence?.create);
  const remove = useOperationMutation(presence?.remove);
  if (!presence) return null;
  const rows = listOf(query.data).records;
  const online = rows.length > 0;
  const pending = add.isPending || remove.isPending || query.isLoading;
  function toggle(next: boolean) {
    const operationId = next ? presence?.create : presence?.remove;
    const handlers = {
      onSuccess: () => {
        if (operationId) signal("operation", { operationId });
        void queryClient.invalidateQueries();
      },
      onError: (error: unknown) => toast.error(errorMessage(operationId, error)),
    };
    if (next) add.mutate({ params: {}, body: {} }, handlers);
    else if (rows[0]) remove.mutate({ params: { id: rows[0].id }, body: {} }, handlers);
  }
  return (
    <div className="bg-card flex items-center justify-between gap-4 rounded-lg border p-4" data-bga-presence>
      <div className="flex flex-col">
        <span className="font-semibold">{online ? "You're online" : "You're offline"}</span>
        <span className="text-muted-foreground text-sm">
          {online ? "New offers reach you." : "Go online to receive offers."}
        </span>
      </div>
      <Switch
        checked={online}
        onCheckedChange={toggle}
        disabled={pending || (!online && !presence.create) || (online && !presence.remove)}
        aria-label={online ? "Go offline" : "Go online"}
        data-bga-action="go-online"
      />
    </div>
  );
}
