"use client";

import { MoreHorizontal } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { Fragment, useEffect, useState } from "react";
import { toast } from "sonner";
import { Button, buttonVariants } from "@/components/ui/button";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { cn } from "@/lib/utils";
import { allowed, pageHref, resolveParams, type TAppAction, type TRecord, type TRouteParams } from "./app";
import { useOperationMutation } from "./bindings";
import { AppFormBody } from "./AppForm";
import { errorMessage } from "./errors";
import { PayAction, useSession } from "./plugins";
import { t } from "./messages";
import { recordOf, signal } from "./signals";

/** A mutation action: confirms first when it says so, opens its form in a dialog when it has one (Story 22.3). */
function useAction(action: TAppAction, record: TRecord | undefined, onClose?: () => void) {
  const route = (useParams() ?? {}) as TRouteParams;
  const router = useRouter();
  const mutation = useOperationMutation(action.operationId);
  const [confirming, setConfirming] = useState(false);
  const [editing, setEditing] = useState(false);
  const params = resolveParams(action.params, route, record);
  const body = resolveParams(action.body, route, record); // `$record.id` / `$route.id` in a body (a like's video)

  function done() {
    if (action.onSuccess?.toast) toast.success(action.onSuccess.toast);
    if (action.onSuccess?.navigate) router.push(pageHref(action.onSuccess.navigate, {}, route));
  }

  function run() {
    mutation.mutate(
      { params, body },
      {
        onSuccess: (result) => {
          // Story 28.1: one signal per successful write (a failure sends none); the form path signals from AppForm
          if (action.operationId) signal("operation", { operationId: action.operationId, record: recordOf(params, result) });
          done();
        },
        onError: (error) => toast.error(errorMessage(action.operationId, error)),
        onSettled: () => onClose?.(),
      },
    );
  }

  function start() {
    if (action.form) {
      setEditing(true);
      signal("dialog", { operationId: action.operationId, form: action.form });
    } else if (action.confirm) {
      setConfirming(true);
      signal("dialog", { operationId: action.operationId });
    } else run();
  }

  const dialogs = (
    <>
      {action.confirm && (
        <AlertDialog
          open={confirming}
          onOpenChange={(next) => {
            setConfirming(next);
            if (!next && !mutation.isPending) onClose?.();
          }}
        >
          <AlertDialogContent>
            <AlertDialogHeader>
              <AlertDialogTitle>{action.label}</AlertDialogTitle>
              <AlertDialogDescription>
                {typeof action.confirm === "string" ? action.confirm : "Are you sure?"}
              </AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogCancel>{t("cancel")}</AlertDialogCancel>
              <AlertDialogAction variant={action.variant === "destructive" ? "destructive" : "default"} onClick={run}>
                {action.label}
              </AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>
      )}
      {action.form && (
        <Dialog
          open={editing}
          onOpenChange={(next) => {
            setEditing(next);
            if (!next) onClose?.();
          }}
        >
          <DialogContent>
            <DialogHeader>
              <DialogTitle>{action.label}</DialogTitle>
              <DialogDescription className="sr-only">{action.label}</DialogDescription>
            </DialogHeader>
            <AppFormBody
              formId={action.form}
              params={params}
              onDone={() => {
                setEditing(false);
                done();
                onClose?.();
              }}
              onCancel={() => {
                setEditing(false);
                onClose?.();
              }}
            />
          </DialogContent>
        </Dialog>
      )}
    </>
  );
  return { start, dialogs, pending: mutation.isPending, open: confirming || editing || mutation.isPending };
}

function ActionButton({ action, record }: { action: TAppAction; record?: TRecord }) {
  if (action.kind === "pay") return <PayAction action={action} record={record} variant={action.variant ?? "default"} />;
  return <PlainActionButton action={action} record={record} />;
}

function PlainActionButton({ action, record }: { action: TAppAction; record?: TRecord }) {
  const route = (useParams() ?? {}) as TRouteParams;
  const { start, dialogs, pending } = useAction(action, record);
  const variant = action.variant ?? "outline";
  if (action.kind === "link" && action.page) {
    const href = pageHref(action.page, resolveParams(action.params, route, record), route);
    return (
      <Link href={href} className={cn(buttonVariants({ variant, size: "sm" }))} data-bga-action={action.id}>
        {action.label}
      </Link>
    );
  }
  return (
    <>
      <Button variant={variant} size="sm" onClick={start} disabled={pending} data-bga-action={action.id}>
        {action.label}
      </Button>
      {dialogs}
    </>
  );
}

/** The actions of a record's page, or of a collection, as buttons: only what the record allows. */
export function ActionButtons({ actions, record }: { actions: TAppAction[]; record?: TRecord }) {
  const session = useSession();
  const shown = actions.filter((action) => allowed(record, action, session));
  if (shown.length === 0) return null;
  return (
    <div className="flex flex-wrap items-center gap-2">
      {shown.map((action) => (
        <ActionButton key={action.id} action={action} record={record} />
      ))}
    </div>
  );
}

/** A row action chosen in the menu, kept outside it: the menu closes on a choice, and a dialog inside it would close
 *  with it before the user could confirm (seen in 22.4: row deletes never ran). Starts on mount; `onClose` when done. */
function ChosenAction({ action, record, onClose }: { action: TAppAction; record: TRecord; onClose: () => void }) {
  const { start, dialogs, open } = useAction(action, record, onClose);
  useEffect(() => {
    start();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  return open ? dialogs : null;
}

/** A row's actions in a menu (keyboard: Enter or Space opens it, arrows move, Escape closes). */
export function RowActions({ actions, record, label }: { actions: TAppAction[]; record: TRecord; label: string }) {
  const route = (useParams() ?? {}) as TRouteParams;
  const router = useRouter();
  const [chosen, setChosen] = useState<TAppAction | null>(null);
  const session = useSession();
  // a payment leaves the page for the checkout: on the record's page, not in a row menu
  const shown = actions.filter((action) => action.kind !== "pay" && allowed(record, action, session));
  if (shown.length === 0) return null;
  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger
          render={
            <Button variant="ghost" size="icon-sm" aria-label={t("actionsFor", { name: label })}>
              <MoreHorizontal aria-hidden />
            </Button>
          }
        />
        <DropdownMenuContent align="end">
          {shown.map((action) => {
            const destructive = action.variant === "destructive";
            return (
              <Fragment key={action.id}>
                {destructive && <DropdownMenuSeparator />}
                <DropdownMenuItem
                  variant={destructive ? "destructive" : "default"}
                  data-bga-action={action.id}
                  onClick={() => {
                    if (action.kind === "link" && action.page) {
                      router.push(pageHref(action.page, resolveParams(action.params, route, record), route));
                    } else setChosen(action);
                  }}
                >
                  {action.label}
                </DropdownMenuItem>
              </Fragment>
            );
          })}
        </DropdownMenuContent>
      </DropdownMenu>
      {chosen && <ChosenAction key={chosen.id} action={chosen} record={record} onClose={() => setChosen(null)} />}
    </>
  );
}
