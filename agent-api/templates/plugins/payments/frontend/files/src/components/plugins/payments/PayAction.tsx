"use client";

import { CreditCard } from "lucide-react";
import { useParams } from "next/navigation";
import { toast } from "sonner";
import { app, resolveParams, type TRouteParams } from "@/components/app/app";
import { useOperationMutation } from "@/components/app/bindings";
import { errorMessage } from "@/components/app/errors";
import type { TPayAction } from "@/components/app/plugin-types";
import { recordOf, signal } from "@/components/app/signals";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";

/** Where the return pages find the payment (the provider appends nothing to the return URLs). */
export const PAYMENT_KEY = "bga.payment";

/** Pay (Story 22.7): starts the checkout for this record and goes to the provider's page; it comes back to the
 *  success or cancel page, which follows the payment until it settles. Shown while the record allows `pay`. */
export const PayAction: TPayAction = ({ action, record, variant }) => {
  const route = (useParams() ?? {}) as TRouteParams;
  const checkout = useOperationMutation(action.operationId);
  function pay() {
    const origin = window.location.origin;
    const body = {
      successUrl: `${origin}${app.routes["payments-success"] ?? "/payments/success"}`,
      cancelUrl: `${origin}${app.routes["payments-cancel"] ?? "/payments/cancel"}`,
    };
    checkout.mutate(
      { params: resolveParams(action.params, route, record), body },
      {
        onSuccess: (result) => {
          const payment = result as { paymentId?: string; checkoutUrl?: string | null };
          // Story 28.1: the checkout started (the payment itself settles through the provider)
          if (action.operationId) signal("operation", { operationId: action.operationId, record: recordOf(resolveParams(action.params, route, record), result) });
          try {
            sessionStorage.setItem(PAYMENT_KEY, JSON.stringify({ paymentId: payment.paymentId, back: window.location.pathname }));
          } catch {
            // the return page then reads the payment from its address only
          }
          if (payment.checkoutUrl) window.location.assign(payment.checkoutUrl);
        },
        onError: (error) => toast.error(errorMessage(action.operationId, error)),
      },
    );
  }
  return (
    <Button size="sm" variant={variant ?? "default"} onClick={pay} disabled={checkout.isPending} data-bga-action={action.id}>
      {checkout.isPending ? <Spinner data-icon="inline-start" /> : <CreditCard data-icon="inline-start" aria-hidden />}
      {action.label}
    </Button>
  );
};
