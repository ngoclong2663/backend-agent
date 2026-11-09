"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation } from "@tanstack/react-query";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useMemo } from "react";
import { Controller, useForm } from "react-hook-form";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Field, FieldContent, FieldDescription, FieldError, FieldLabel } from "@/components/ui/field";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";
import { cn } from "cn";
import { compactValues } from "@/lib/form-utils";
import { app, pageHref, resolveParams, type TAppSection, type TFormField, type TRouteParams } from "./app";
import { useOperationMutation, useOperationQuery } from "./bindings";
import { errorMessage, fieldErrors } from "./errors";
import { FieldInput, isWide } from "./form/FieldInput";
import { isBlank, registerForm } from "./form/registry";
import { formSchemas } from "./form-schemas";
import { t } from "./messages";
import { recordOf, signal } from "./signals";

type TValues = Record<string, unknown>;

type AppFormBodyProps = {
  formId: string;
  /** The operation's path parameters, resolved (a dialog on a record's page passes the record's). */
  params?: Record<string, unknown>;
  onDone?: (result: unknown) => void;
  onCancel?: () => void;
  /** Story 22.7: sends the form itself (sign-in keeps the token or sets the cookie) instead of its operation. */
  submit?: (body: Record<string, unknown>) => Promise<unknown>;
  submitLabel?: string;
};

/** A form on its operation's request (Story 22.3 writes the fields, Story 22.5 the kit): one input per field kind
 *  (`form/`), the generated Zod schema validates, hidden fields take their route values, short fields share a row when
 *  the form is wide enough; an edit form loads its record, sends only what changed and cannot submit unchanged; server
 *  errors show on their field (else a toast). */
export function AppFormBody({ formId, params, onDone, onCancel, submit, submitLabel }: AppFormBodyProps) {
  const form = app.forms[formId];
  const route = (useParams() ?? {}) as TRouteParams;
  const schema = formSchemas[formId];
  const fixed = useMemo(
    () =>
      resolveParams(
        Object.fromEntries((form?.fields ?? []).filter((f) => f.value !== undefined).map((f) => [f.name, f.value])),
        route,
      ),
    [form, route],
  );
  const defaults = useMemo(() => ({ ...(schema?.defaults ?? {}), ...fixed }), [schema, fixed]);
  const methods = useForm<TValues>({
    resolver: schema ? zodResolver(schema.schema as never) : undefined,
    defaultValues: defaults,
  });
  const load = useOperationQuery(form?.load?.operationId, resolveParams(form?.load?.params, route));
  const operation = useOperationMutation(submit ? undefined : form?.operationId);
  const own = useMutation({ mutationFn: (variables: { body: Record<string, unknown> }) => submit!(variables.body) });
  const mutation = submit ? own : operation;
  const record = load.data && typeof load.data === "object" ? (load.data as TValues) : undefined;

  useEffect(() => {
    if (load.data && typeof load.data === "object") {
      // An empty optional field arrives as `null`; the form (and its schema) treat it as not given.
      const loaded = Object.entries(load.data as TValues).filter(([, value]) => value !== null);
      methods.reset({ ...defaults, ...Object.fromEntries(loaded) });
    }
  }, [load.data, defaults, methods]);
  // Story 28.3: the tour fills this form through the registry (never submits it)
  useEffect(
    () =>
      registerForm(formId, {
        getValues: () => methods.getValues() as Record<string, unknown>,
        setValue: (name, value, options) => methods.setValue(name, value as never, options),
        trigger: (name) => methods.trigger(name as never),
      }),
    [formId, methods],
  );

  if (!form) return null;
  if (form.load && load.isLoading) {
    return (
      <div className="flex flex-col gap-4" aria-busy="true">
        {form.fields.slice(0, 4).map((field) => (
          <Skeleton key={field.name} className="h-14 w-full" />
        ))}
      </div>
    );
  }
  const visible = form.fields.filter((field) => !field.hidden);
  const names = form.fields.map((field) => field.name);
  const shownNames = visible.map((field) => field.name);

  function onSubmit(values: TValues) {
    const patch = Boolean(form.load);
    const dirty = methods.formState.dirtyFields as Record<string, unknown>;
    // An edit sends only what changed; a cleared optional field (no value after the schema) is sent as null.
    const body = patch
      ? Object.fromEntries(names.filter((name) => dirty[name]).map((name) => [name, values[name] ?? null]))
      : compactValues(Object.fromEntries(Object.entries(values).filter(([name]) => names.includes(name))));
    mutation.mutate(
      { params: params ?? resolveParams(form.params, route), body },
      {
        onSuccess: (result) => {
          // Story 28.1: exactly one signal per successful submit, with the operation and the record it made or changed
          signal("operation", {
            operationId: form.operationId,
            form: formId,
            record: recordOf(params ?? resolveParams(form.params, route), result),
          });
          if (form.onSuccess?.toast) toast.success(form.onSuccess.toast);
          onDone?.(result);
        },
        onError: (error) => {
          // an error on a field the user cannot see (a parent from the route: "the workshop is full") is a toast
          const byField = fieldErrors(form.operationId, error, shownNames);
          for (const [name, message] of Object.entries(byField)) methods.setError(name, { message });
          if (Object.keys(byField).length === 0) toast.error(errorMessage(form.operationId, error));
          signal("error", { operationId: form.operationId, form: formId, fields: Object.keys(byField) });
        },
      },
    );
  }

  const editing = Boolean(form.load);
  const unchanged = editing && !methods.formState.isDirty;
  return (
    <form onSubmit={methods.handleSubmit(onSubmit)} noValidate className="@container flex flex-col gap-6" data-bga-form={formId}>
      {/* fields may shrink below their content (a long date truncates) so nothing passes the form's edge */}
      <div className="grid gap-x-4 gap-y-5 @lg:grid-cols-2">
        {visible.map((field) => (
          <Controller
            key={field.name}
            control={methods.control}
            name={field.name}
            render={({ field: control, fieldState }) => (
              <FormField
                formId={formId}
                field={field}
                value={control.value}
                onChange={control.onChange}
                onBlur={control.onBlur}
                record={record}
                error={fieldState.error?.message}
                wide={isWide(field.type) || visible.length === 1}
              />
            )}
          />
        ))}
      </div>
      <div className="flex flex-col-reverse gap-2 sm:flex-row sm:items-center sm:justify-end">
        {onCancel && (
          <Button type="button" variant="ghost" onClick={onCancel}>
            Cancel
          </Button>
        )}
        <Button
          type="submit"
          disabled={mutation.isPending || unchanged}
          aria-busy={mutation.isPending || undefined}
          data-bga-action="submit"
        >
          {mutation.isPending && <Spinner data-icon="inline-start" />}
          {submitLabel ?? form.submitLabel ?? t("save")}
        </Button>
      </div>
    </form>
  );
}

/** One field: label (required marked), its input, then its error, else its help. A switch sits beside its label. */
function FormField({ formId, field, value, onChange, onBlur, error, wide, record }: {
  formId: string;
  field: TFormField;
  value: unknown;
  onChange: (value: unknown) => void;
  onBlur: () => void;
  error?: string;
  wide: boolean;
  record?: TValues;
}) {
  const id = `${formId}-${field.name}`;
  const invalid = Boolean(error);
  const filled = !isBlank(value) && !invalid;
  useEffect(() => {
    // Story 28.1: a field that went from empty to a valid value (debounced; the value itself is never sent)
    if (!filled) return;
    const timer = setTimeout(() => signal("field", { form: formId, field: field.name }), 300);
    return () => clearTimeout(timer);
  }, [filled, formId, field.name]);
  const label = (
    <FieldLabel htmlFor={id}>
      <span>
        {field.label ?? field.name}
        {field.required && field.type !== "boolean" && (
          <span className="text-destructive" aria-hidden>
            {" *"}
          </span>
        )}
      </span>
    </FieldLabel>
  );
  const note = error ? <FieldError>{error}</FieldError> : field.help ? <FieldDescription>{field.help}</FieldDescription> : null;
  const input = <FieldInput field={field} id={id} value={value} onChange={onChange} onBlur={onBlur} invalid={invalid} record={record} />;
  if (field.type === "boolean") {
    return (
      <Field orientation="horizontal" data-invalid={invalid || undefined} className={cn("min-w-0 self-end", wide && "@lg:col-span-2")}>
        {input}
        <FieldContent>
          {label}
          {note}
        </FieldContent>
      </Field>
    );
  }
  return (
    <Field data-invalid={invalid || undefined} className={cn("min-w-0", wide && "@lg:col-span-2")}>
      {label}
      {input}
      {note}
    </Field>
  );
}

/** A form page: the page title, the form in a card, back to where it came from on cancel; on success to the record's
 *  page (the new record's id fills the route) or the page the planner named. */
export function AppForm({ section, title }: { section: TAppSection; title: string }) {
  const router = useRouter();
  const route = (useParams() ?? {}) as TRouteParams;
  const formId = section.form ?? "";
  const form = app.forms[formId];
  if (!form) return null;
  const target = form.onSuccess?.navigate;
  return (
    <div className="mx-auto flex w-full max-w-2xl flex-col gap-6">
      <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
      <Card>
        <CardContent>
          <AppFormBody
            formId={formId}
            onCancel={() => router.back()}
            onDone={(result) => {
              if (!target) return;
              // The target's parameters come from the current route when it has them (a task added on its project's
              // page goes back to that project), else from the new record (a new deck opens its own page).
              const pattern = app.routes[target] ?? target;
              const needed = [...pattern.matchAll(/\[([A-Za-z0-9_]+)\]/g)].map((match) => match[1]);
              const fromRoute = needed.every((name) => route[name] !== undefined);
              const id = (result as { id?: unknown } | null)?.id;
              router.push(pageHref(target, fromRoute || id === undefined ? {} : { id }, route));
            }}
          />
        </CardContent>
      </Card>
    </div>
  );
}
