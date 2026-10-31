# Context Pack for `ProductGrid`

Read `.bga/context.md` first: it has the APIs, types, primitives and an example you need. Read another file only if the pack lacks something.

## Data API

### `src/components/renderer/site.ts`
```typescript
import data from "@/content/site.json";
import type { TValueFormat } from "@/components/sections/format";

export type TRecord = Record<string, unknown>;

export type TColumn = { key: string; label: string; format?: TValueFormat };

/** A link from a record to the page that shows it: `params` maps the route's parameters to record fields. */
export type TRecordLink = { route: string; params: Record<string, string> };

/** Where a data section's records come from: a content collection (static) or an API operation (dynamic). */
export type TBinding = {
  collection?: string;
  operationId?: string;
  action?: string;
  params?: Record<string, unknown>;
  columns?: TColumn[];
  link?: TRecordLink;
};

export type TStates = { loading?: string; empty?: string; error?: string; emptyImage?: string };

export type TFormFieldDef = {
  name: string;
  type: string;
  label: string;
  required?: boolean;
  hidden?: boolean;
  value?: unknown;
  values?: string[];
  placeholder?: string;
};

export type TFormDef = {
  operationId?: string | null;
  params: Record<string, unknown>;
  fields: TFormFieldDef[];
  submitLabel: string;
  onSuccess: { toast?: string; navigate?: string };
};

export type TSiteSection = {
  id: string;
  component: string;
  content?: Record<string, unknown>;
  data?: TBinding;
  states?: TStates;
  form?: string;
  children?: TSiteSection[];
};

export type TSitePage = { title: string; sections: TSiteSection[] };

export type TSite = {
  pages: Record<string, TSitePage>;
  collections: Record<string, TRecord[]>;
  forms: Record<string, TFormDef>;
};

/** The FrontendSpec pages, content collections and forms, validated when the spec was (Story 17.1). */
export const site = data as TSite;

```

### `src/components/renderer/use-section-records.ts`
```typescript
"use client";

import { useParams } from "next/navigation";
import { useOperationQuery } from "./bindings";
import type { TBinding, TRecord, TRecordLink } from "./site";

type TRouteParams = Record<string, string | string[] | undefined>;

/** `$route.<name>` values become the current route's parameters; everything else stays as written. */
export function resolveParams(params: Record<string, unknown>, route: TRouteParams): Record<string, unknown> {
  return Object.fromEntries(
    Object.entries(params).map(([name, value]) => {
      if (typeof value === "string" && value.startsWith("$route.")) {
        const resolved = route[value.slice("$route.".length)];
        return [name, Array.isArray(resolved) ? resolved[0] : resolved];
      }
      return [name, value];
    }),
  );
}

/** The href of a record's own page, or undefined when the site has none. */
export function recordHref(link: TRecordLink | undefined, record: TRecord): string | undefined {
  if (!link) return undefined;
  return Object.entries(link.params).reduce(
    (href, [param, field]) => href.replace(`[${param}]`, encodeURIComponent(String(record[field] ?? ""))),
    link.route,
  );
}

/**
 * A data section's records: the content collection's `items` (static, already in the page) or the response of its
 * operation (dynamic: the generated client, on mocks or the live backend). `record` is set for get operations.
 */
export function useSectionRecords(items: TRecord[] | undefined, binding: TBinding | undefined) {
  const route = useParams<TRouteParams>() ?? {};
  const operationId = binding?.operationId;
  const query = useOperationQuery(operationId, resolveParams(binding?.params ?? {}, route));
  if (!operationId) {
    return { records: items ?? [], record: undefined, isLoading: false, error: null };
  }
  const data = query.data as { items?: TRecord[] } | TRecord | undefined;
  const list = data && Array.isArray((data as { items?: TRecord[] }).items) ? (data as { items: TRecord[] }).items : [];
  const record = binding?.action === "get" ? (data as TRecord | undefined) : undefined;
  return { records: list, record, isLoading: query.isLoading, error: query.error };
}

```

### `src/components/renderer/bindings.ts`
```typescript
// Operations known to bindings.ts:
// cartItem.create, cartItem.delete, cartItem.list, cartItem.update, category.list, contactMessage.create, product.get, product.list

/** A data section's records: the operation's response (disabled without an operation). */
export function useOperationQuery(operationId: string | undefined, params: TParams)

/** A form's operation; on success the lists of the same resource refresh. */
export function useOperationMutation(operationId: string | undefined)
```

### `src/components/sections/format.ts`
```typescript
export type TValueFormat = "text" | "date" | "datetime" | "badge" | "image";

const dateFormat = new Intl.DateTimeFormat("en", { dateStyle: "medium" });
const dateTimeFormat = new Intl.DateTimeFormat("en", { dateStyle: "medium", timeStyle: "short" });

/** How a record field is shown in cards, lists, tables and detail views. */
export function formatValue(value: unknown, format: TValueFormat = "text"): string {
  if (value === null || value === undefined || value === "") return "—";
  if (Array.isArray(value)) return value.map((item) => formatValue(item)).join(", ");
  if (typeof value === "object") return JSON.stringify(value);
  if (format === "date") return dateFormat.format(new Date(`${String(value).slice(0, 10)}T00:00:00`));
  if (format === "datetime") return dateTimeFormat.format(new Date(String(value)));
  if (format === "badge") return String(value).replaceAll("_", " ").toLowerCase();
  return String(value);
}

```

### `src/components/sections/QueryState.tsx`
```typescript
import type { ReactNode } from "react";
import { AlertCircle } from "lucide-react";
import { AssetImage } from "@/components/assets/AssetImage";
import { Skeleton } from "@/components/ui/skeleton";

type QueryStateProps = {
  isLoading: boolean;
  error: Error | null;
  isEmpty: boolean;
  emptyText?: string;
  emptyImage?: string;
  errorText?: string;
  children: ReactNode;
};

/** The loading, error and empty states every data section shows (FrontendSpec `states`). */
export function QueryState({ isLoading, error, isEmpty, emptyText, emptyImage, errorText, children }: QueryStateProps) {
  if (isLoading) {
    return (
      <div className="flex flex-col gap-2" aria-busy="true">
        <Skeleton className="h-8 w-full" />
        <Skeleton className="h-8 w-full" />
        <Skeleton className="h-8 w-2/3" />
      </div>
    );
  }
  if (error) {
    return (
      <p role="alert" className="flex items-center gap-2 text-destructive">
        <AlertCircle className="size-4" aria-hidden /> {errorText ?? error.message}
      </p>
    );
  }
  if (isEmpty) {
    return (
      <div className="flex flex-col items-center gap-4 py-6 text-center">
        {emptyImage && <AssetImage asset={emptyImage} className="max-w-xs" />}
        <p className="text-muted-foreground">{emptyText ?? "Nothing here yet"}</p>
      </div>
    );
  }
  return children;
}

```

### `src/components/assets/AssetImage.tsx`
```typescript
import { assets } from "@/assets";
import { cn } from "@/lib/utils";

const RATIOS: Record<string, string> = {
  "16:9": "aspect-video",
  "4:3": "aspect-[4/3]",
  "1:1": "aspect-square",
  "3:4": "aspect-[3/4]",
  "21:9": "aspect-[21/9]",
};

type AssetImageProps = {
  asset: string;
  className?: string;
  /** Above the fold: load right away instead of lazily. */
  priority?: boolean;
};

/**
 * A FrontendSpec asset (`asset:<id>`, Story 15.1) from the generated registry (`src/assets/index.ts`): a drawn SVG
 * component, an uploaded file, a linked image, a lucide icon, or a themed placeholder panel with the alt text.
 * `data-bga-asset` lets the checks find each asset on its page.
 */
export function AssetImage({ asset, className, priority = false }: AssetImageProps) {
  const id = asset.replace(/^asset:/, "");
  const entry = assets[id];
  const decorative = entry?.decorative ?? false;
  const label = decorative ? undefined : (entry?.alt ?? id);
  const frame = cn("relative w-full overflow-hidden rounded-xl", RATIOS[entry?.aspectRatio ?? "16:9"], className);

  if (entry?.mode === "icon" && entry.component) {
    const Icon = entry.component;
    return (
      <span
        data-bga-asset={id}
        role={label ? "img" : undefined}
        aria-label={label}
        aria-hidden={decorative || undefined}
        className={cn("inline-flex size-6", className)}
      >
        <Icon className="size-full" />
      </span>
    );
  }
  if (entry?.mode === "svg-component" && entry.component) {
    const Drawing = entry.component;
    return (
      <div data-bga-asset={id} className={frame}>
        <Drawing className="size-full" />
      </div>
    );
  }
  if ((entry?.mode === "public-file" || entry?.mode === "remote") && entry.src) {
    return (
      <div data-bga-asset={id} className={frame}>
        {/* eslint-disable-next-line @next/next/no-img-element -- static export: images are served as they are */}
        <img
          src={entry.src}
          alt={label ?? ""}
          aria-hidden={decorative || undefined}
          width={entry.width}
          height={entry.height}
          loading={priority ? "eager" : "lazy"}
          referrerPolicy={entry.mode === "remote" ? "no-referrer" : undefined}
          className="size-full object-cover"
        />
      </div>
    );
  }
  return (
    <div
      data-bga-asset={id}
      role={label ? "img" : undefined}
      aria-label={label}
      aria-hidden={decorative || undefined}
      className={cn(frame, "bg-gradient-to-br from-primary/30 via-accent to-secondary")}
    />
  );
}

// Available asset ids: hero, shop-front

```

## UI Primitives

### `src/components/ui/card.tsx`
```typescript
function Card({
  className,
  size = "default",
  ...props
}: React.ComponentProps<"div"> & { size?: "default" | "sm" })

function CardHeader({ className, ...props }: React.ComponentProps<"div">)

function CardTitle({ className, ...props }: React.ComponentProps<"div">)

function CardDescription({ className, ...props }: React.ComponentProps<"div">)

function CardAction({ className, ...props }: React.ComponentProps<"div">)

function CardContent({ className, ...props }: React.ComponentProps<"div">)

function CardFooter({ className, ...props }: React.ComponentProps<"div">)

export {
  Card,
  CardHeader,
  CardFooter,
  CardTitle,
  CardAction,
  CardDescription,
  CardContent,
}
```

### `src/components/ui/badge.tsx`
```typescript
import { mergeProps } from "@base-ui/react/merge-props"
import { useRender } from "@base-ui/react/use-render"
import { cva, type VariantProps } from "class-variance-authority"
import { cn } from "cn"

const badgeVariants = cva(
  "group/badge inline-flex h-5 w-fit shrink-0 items-center justify-center gap-1 overflow-hidden rounded-4xl border border-transparent px-2 py-0.5 text-xs font-medium whitespace-nowrap transition-all focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50 has-data-[icon=inline-end]:pr-1.5 has-data-[icon=inline-start]:pl-1.5 aria-invalid:border-destructive aria-invalid:ring-destructive/20 dark:aria-invalid:ring-destructive/40 [&>svg]:pointer-events-none [&>svg]:size-3!",
  {
    variants: {
      variant: {
        default: "bg-primary text-primary-foreground [a]:hover:bg-primary/80",
        secondary:
          "bg-secondary text-secondary-foreground [a]:hover:bg-secondary/80",
        destructive:
          "bg-destructive/10 text-destructive focus-visible:ring-destructive/20 dark:bg-destructive/20 dark:focus-visible:ring-destructive/40 [a]:hover:bg-destructive/20",
        outline:
          "border-border text-foreground [a]:hover:bg-muted [a]:hover:text-muted-foreground",
        ghost:
          "hover:bg-muted hover:text-muted-foreground dark:hover:bg-muted/50",
        link: "text-primary underline-offset-4 hover:underline",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  }
)

function Badge({
  className,
  variant = "default",
  render,
  ...props
}: useRender.ComponentProps<"span"> & VariantProps<typeof badgeVariants>) {
  return useRender({
    defaultTagName: "span",
    props: mergeProps<"span">(
      {
        className: cn(badgeVariants({ variant }), className),
      },
      props
    ),
    render,
    state: {
      slot: "badge",
      variant,
    },
  })
}

export { Badge, badgeVariants }

```

### `src/components/ui/pagination.tsx`
```typescript
function Pagination({ className, ...props }: React.ComponentProps<"nav">)

function PaginationContent({
  className,
  ...props
}: React.ComponentProps<"ul">)

function PaginationItem({ ...props }: React.ComponentProps<"li">)

type PaginationLinkProps = {
  isActive?: boolean
} & Pick<React.ComponentProps<typeof Button>, "size"> &

function PaginationLink({
  className,
  isActive,
  size = "icon",
  ...props
}: PaginationLinkProps)

function PaginationPrevious({
  className,
  text = "Previous",
  ...props
}: React.ComponentProps<typeof PaginationLink> & { text?: string })

function PaginationNext({
  className,
  text = "Next",
  ...props
}: React.ComponentProps<typeof PaginationLink> & { text?: string })

function PaginationEllipsis({
  className,
  ...props
}: React.ComponentProps<"span">)

export {
  Pagination,
  PaginationContent,
  PaginationEllipsis,
  PaginationItem,
  PaginationLink,
  PaginationNext,
  PaginationPrevious,
}
```

### `src/components/ui/skeleton.tsx`
```typescript
import { cn } from "cn"

function Skeleton({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="skeleton"
      className={cn("animate-pulse rounded-md bg-muted", className)}
      {...props}
    />
  )
}

export { Skeleton }

```

## Example Section Pattern

### `src/components/sections/CardGrid.tsx`
```typescript
"use client";

import Link from "next/link";
import { Grid } from "@/components/layout/Grid";
import { Section } from "@/components/layout/Section";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import type { TBinding, TColumn, TRecord, TStates } from "@/components/renderer/site";
import { recordHref, useSectionRecords } from "@/components/renderer/use-section-records";
import { AssetImage } from "./AssetImage";
import { formatValue } from "./format";
import { QueryState } from "./QueryState";
import { cardClass } from "./styles";
import type { TCardGridContent } from "./types";

type CardGridProps = TCardGridContent & {
  items?: TRecord[];
  columns?: TColumn[];
  binding?: TBinding;
  states?: TStates;
};

/** Records as cards: image fields first, the first other field as the title; linked to the record's page. */
export function CardGrid({ title, description, cardStyle, items, columns = [], binding, states }: CardGridProps) {
  const { records, isLoading, error } = useSectionRecords(items, binding);
  const images = columns.filter((column) => column.format === "image");
  const [heading, ...rest] = columns.filter((column) => column.format !== "image");
  return (
    <Section title={title} description={description}>
      <QueryState isLoading={isLoading} error={error} isEmpty={records.length === 0} emptyText={states?.empty} emptyImage={states?.emptyImage} errorText={states?.error}>
        <Grid columns={3}>
          {records.map((record, index) => {
            const href = recordHref(binding?.link, record);
            const card = (
              <Card
                className={cn(
                  cardClass(cardStyle),
                  "h-full",
                  href && "transition-transform duration-200 hover:-translate-y-0.5 motion-reduce:transition-none motion-reduce:hover:translate-y-0",
                )}
              >
                {images.map((column) => (
                  <AssetImage key={column.key} asset={String(record[column.key] ?? "")} />
                ))}
                <CardHeader>{heading && <CardTitle>{formatValue(record[heading.key], heading.format)}</CardTitle>}</CardHeader>
                {rest.length > 0 && (
                  <CardContent className="flex flex-col gap-1 text-sm text-muted-foreground">
                    {rest.map((column) => (
                      <span key={column.key}>{formatValue(record[column.key], column.format)}</span>
                    ))}
                  </CardContent>
                )}
              </Card>
            );
            const key = String(record.id ?? index);
            return href ? (
              <Link key={key} href={href}>
                {card}
              </Link>
            ) : (
              <div key={key}>{card}</div>
            );
          })}
        </Grid>
      </QueryState>
    </Section>
  );
}

```

## Mock API & Fixtures

First fixture record for binding entity `Product`:
```json
{
  "id": "8d2e7a40-1f3b-4c55-8e6a-2b9f4c3d0001",
  "categoryId": "5b0f3c9e-6c1a-4d3e-9a51-0c7d2a1e0001",
  "name": "House blend, 250 g",
  "description": "Medium roast, chocolate and hazelnut.",
  "price": 9.5,
  "imageUrl": null,
  "stock": 40,
  "createdAt": "2026-01-01T09:00:00Z"
}
```
