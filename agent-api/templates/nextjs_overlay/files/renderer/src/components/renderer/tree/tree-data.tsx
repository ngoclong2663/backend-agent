"use client";

import { createContext, Suspense, useContext, useMemo, type ComponentType, type ReactNode } from "react";
import Link from "next/link";
import { useParams, usePathname, useRouter, useSearchParams } from "next/navigation";
import { AssetImage } from "@/components/assets/AssetImage";
import { BackgroundVideo } from "@/components/assets/BackgroundVideo";
import { VideoEmbed } from "@/components/assets/VideoEmbed";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { formatValue } from "@/components/sections/format";
import { site, type TRecord, type TTreeBinding, type TTreeNode } from "../site";
import { controlParams, resolveParams, useSectionRecords } from "../use-section-records";
import { renderNode } from "./TreeRenderer";
import { Chart, Metric } from "./tree-metrics";
import { RecordAction, RecordForm } from "./tree-forms";

/** Props every data component gets: its node (children as written, for templates), the page and its own props. */
export type TDataProps = { node: TTreeNode; pageId: string; children?: ReactNode } & Record<string, unknown>;

export type TCollectionState = {
  binding?: TTreeBinding;
  records: TRecord[];
  total: number;
  isLoading: boolean;
  error: unknown;
  /** The URL-backed controls of a CollectionBrowser (search, filter, sort, page). */
  controls?: TControls;
};

export type TControls = {
  q: string;
  category: string;
  sort: string;
  page: number;
  pageSize: number;
  pages: number;
  categories: string[];
  sortFields: { field: string; label: string }[];
  set: (updates: Record<string, string | number | null>) => void;
};

const CollectionContext = createContext<TCollectionState | null>(null);
const RecordContext = createContext<TRecord | null>(null);

export const useCollection = () => useContext(CollectionContext);
export const useRecord = () => useContext(RecordContext);

function className(props: Record<string, unknown>): string | undefined {
  return typeof props.className === "string" ? props.className : undefined;
}

function staticRecords(binding: TTreeBinding | undefined): TRecord[] | undefined {
  return binding?.operationId ? undefined : (site.collections[binding?.collection ?? ""] ?? []);
}

function shaped(records: TRecord[], props: Record<string, unknown>): TRecord[] {
  let list = records;
  const sortBy = typeof props.sortBy === "string" ? props.sortBy : undefined;
  if (sortBy) {
    const direction = props.order === "desc" ? -1 : 1;
    list = [...list].sort((a, b) => direction * compare(a[sortBy], b[sortBy]));
  }
  const limit = typeof props.limit === "number" ? props.limit : undefined;
  return limit ? list.slice(0, limit) : list;
}

function compare(a: unknown, b: unknown): number {
  if (typeof a === "number" && typeof b === "number") return a - b;
  return String(a ?? "").localeCompare(String(b ?? ""));
}

/** Children rendered once per record, each under its own RecordContext (ItemList, CollectionDetail). */
function Template({ node, pageId, record, index }: { node: TTreeNode; pageId: string; record: TRecord; index: number }) {
  return (
    <RecordContext.Provider value={record}>
      {node.children?.map((child, childIndex) =>
        typeof child === "string" ? child : renderNode(child, pageId, `r${index}-${childIndex}`),
      )}
    </RecordContext.Provider>
  );
}

// -- containers ------------------------------------------------------------------------------------------------------

/** A few records of a collection (`limit`, `sortBy`, `order`): a strip of products, the latest posts. */
function CollectionStrip({ node, pageId, children, ...props }: TDataProps) {
  const binding = node.binding;
  const limit = typeof props.limit === "number" ? props.limit : undefined;
  const sortBy = typeof props.sortBy === "string" ? props.sortBy : undefined;
  const listParams = binding?.operationId
    ? { ...(limit ? { limit } : {}), ...(sortBy ? { sort: props.order === "desc" ? `-${sortBy}` : sortBy } : {}) }
    : undefined;
  const result = useSectionRecords(staticRecords(binding), binding, listParams);
  const records = useMemo(() => (binding?.operationId ? result.records : shaped(result.records, props)), [binding, result.records, props]);
  const state: TCollectionState = { binding, records, total: records.length, isLoading: result.isLoading, error: result.error };
  return (
    <CollectionContext.Provider value={state}>
      <div className={className(props)} data-bga-collection={binding?.collection} data-bga-records={records.length}>
        {children}
      </div>
    </CollectionContext.Provider>
  );
}

/** A browsable collection: search, category filter, sort and pages, kept in the URL. */
function CollectionBrowser(props: TDataProps) {
  return (
    <Suspense fallback={<div className={className(props)} />}>
      <BrowserInner {...props} />
    </Suspense>
  );
}

function BrowserInner({ node, pageId, children, ...props }: TDataProps) {
  const binding = node.binding;
  const searchParams = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const pageSize = typeof props.pageSize === "number" ? props.pageSize : 12;
  const categoryField = typeof props.categoryField === "string" ? props.categoryField : undefined;
  const sortFields = ((props.sortFields as { field: string; label: string }[] | string[] | undefined) ?? []).map((item) =>
    typeof item === "string" ? { field: item, label: item } : item,
  );
  const searchFields = (props.searchFields as string[] | undefined) ?? [];
  const q = searchParams.get("q") ?? "";
  const category = searchParams.get(categoryField ?? "category") ?? "";
  const sort = searchParams.get("sort") ?? "";
  const page = Number(searchParams.get("page") ?? 1) || 1;

  const listParams = binding?.operationId
    ? controlParams(
        { search: true, filters: categoryField ? [categoryField] : [], sort: sortFields.map((s) => s.field), pageSize },
        searchParams,
      )
    : undefined;
  const result = useSectionRecords(staticRecords(binding), binding, listParams);

  const { records, total, categories } = useMemo(() => {
    const all = result.records;
    const categories = categoryField
      ? Array.from(new Set(all.map((r) => String(r[categoryField] ?? "")).filter(Boolean))).sort()
      : [];
    if (binding?.operationId) return { records: all, total: result.total, categories };
    let list = all;
    if (q) {
      const needle = q.toLowerCase();
      const fields = searchFields.length ? searchFields : Object.keys(all[0] ?? {});
      list = list.filter((r) => fields.some((f) => String(r[f] ?? "").toLowerCase().includes(needle)));
    }
    if (category && categoryField) list = list.filter((r) => String(r[categoryField] ?? "") === category);
    if (sort) {
      const field = sort.replace(/^-/, "");
      const direction = sort.startsWith("-") ? -1 : 1;
      list = [...list].sort((a, b) => direction * compare(a[field], b[field]));
    }
    const total = list.length;
    return { records: list.slice((page - 1) * pageSize, page * pageSize), total, categories };
  }, [result.records, result.total, binding, q, category, categoryField, sort, page, pageSize, searchFields]);

  const set = (updates: Record<string, string | number | null>) => {
    const next = new URLSearchParams(searchParams.toString());
    for (const [name, value] of Object.entries(updates)) {
      if (value === null || value === "" || value === undefined) next.delete(name);
      else next.set(name, String(value));
    }
    router.replace(`${pathname}?${next.toString()}`, { scroll: false });
  };
  const controls: TControls = {
    q,
    category,
    sort,
    page,
    pageSize,
    pages: Math.max(1, Math.ceil(total / pageSize)),
    categories,
    sortFields,
    set,
  };
  const state: TCollectionState = { binding, records, total, isLoading: result.isLoading, error: result.error, controls };
  return (
    <CollectionContext.Provider value={state}>
      <div className={className(props)}>{children}</div>
    </CollectionContext.Provider>
  );
}

/** One record, from the route's `id` parameter; its children read it with RecordField and friends. */
function CollectionDetail({ node, pageId, ...props }: TDataProps) {
  const binding = node.binding;
  const route = (useParams() ?? {}) as Record<string, string | string[] | undefined>;
  const id = route.id;
  const wanted = Array.isArray(id) ? id[0] : id;
  const dynamicBinding = binding?.operationId
    ? { ...binding, params: resolveParams({ id: "$route.id", ...(binding.params ?? {}) }, route) }
    : binding;
  const result = useSectionRecords(staticRecords(binding), dynamicBinding);
  const record = binding?.operationId
    ? result.record
    : result.records.find((r) => String(r.id ?? r.slug ?? "") === String(wanted ?? ""));
  const state: TCollectionState = {
    binding,
    records: record ? [record] : [],
    total: record ? 1 : 0,
    isLoading: result.isLoading,
    error: result.error,
  };
  return (
    <CollectionContext.Provider value={state}>
      <div className={className(props)}>
        {record ? <Template node={node} pageId={pageId} record={record} index={0} /> : null}
        {!record && !result.isLoading && (
          <p className="text-sm text-muted-foreground">Not found.</p>
        )}
      </div>
    </CollectionContext.Provider>
  );
}

/** The container's records, each rendered with the children as a template. */
function ItemList({ node, pageId, ...props }: TDataProps) {
  const collection = useCollection();
  if (!collection) return null;
  return (
    <div className={className(props)}>
      {collection.records.map((record, index) => (
        <Template key={String(record.id ?? index)} node={node} pageId={pageId} record={record} index={index} />
      ))}
    </div>
  );
}

// -- record readers --------------------------------------------------------------------------------------------------

function RecordField({ field, format, ...props }: TDataProps) {
  const record = useRecord();
  if (!record || typeof field !== "string") return null;
  const value = record[field];
  const text = formatValue(value, format as "text" | "date" | "datetime" | "badge" | undefined);
  return <span className={className(props)}>{text}</span>;
}

const money = new Intl.NumberFormat(undefined, { style: "currency", currency: "USD", maximumFractionDigits: 2 });

function RecordPrice({ field = "price", currency, ...props }: TDataProps) {
  const record = useRecord();
  if (!record) return null;
  const value = Number(record[String(field)]);
  const formatter =
    typeof currency === "string"
      ? new Intl.NumberFormat(undefined, { style: "currency", currency, maximumFractionDigits: 2 })
      : money;
  return <span className={className(props)}>{Number.isFinite(value) ? formatter.format(value) : "—"}</span>;
}

function RecordImage({ field = "image", altField, ...props }: TDataProps) {
  const record = useRecord();
  if (!record) return null;
  const value = record[String(field)];
  const asset = typeof value === "string" && value.startsWith("asset:") ? value : null;
  if (!asset) return <div className={className(props) ?? "aspect-[4/3] rounded-xl bg-muted"} aria-hidden />;
  return <AssetImage asset={asset} className={className(props)} />;
}

/** Epic 31 (D8): a designed page shows a video only through the library's pieces, bound to a `video` asset. */
function TreeVideoEmbed({ asset, ...props }: TDataProps) {
  return typeof asset === "string" ? <VideoEmbed asset={asset} className={className(props)} /> : null;
}

function TreeBackgroundVideo({ asset, ...props }: TDataProps) {
  return typeof asset === "string" ? <BackgroundVideo asset={asset} className={className(props)} /> : null;
}

function RecordStars({ field = "rating", max = 5, ...props }: TDataProps) {
  const record = useRecord();
  if (!record) return null;
  const value = Math.round(Number(record[String(field)]) || 0);
  const count = typeof max === "number" ? max : 5;
  return (
    <span className={className(props)} aria-label={`${value} of ${count}`}>
      {"★".repeat(Math.min(value, count))}
      <span className="opacity-30">{"★".repeat(Math.max(0, count - value))}</span>
    </span>
  );
}

/** Wraps its children in a link to the record's page (the container's detail route, or `detailSlug`). */
function RecordLink({ node, children, ...props }: TDataProps) {
  const record = useRecord();
  const route = node.binding?.route;
  if (!record || !route) return <span className={className(props)}>{children}</span>;
  const href = route.replace(/\[([a-zA-Z0-9]+)\]/g, (_, param) => encodeURIComponent(String(record[param] ?? record.id ?? "")));
  return (
    <Link href={href} className={className(props)}>
      {children}
    </Link>
  );
}

// -- list controls -----------------------------------------------------------------------------------------------------

function SearchBox({ placeholder, ...props }: TDataProps) {
  const controls = useCollection()?.controls;
  if (!controls) return null;
  return (
    <Input
      type="search"
      className={className(props)}
      placeholder={typeof placeholder === "string" ? placeholder : "Search…"}
      defaultValue={controls.q}
      onChange={(event) => controls.set({ q: event.target.value, page: null })}
      aria-label="Search"
    />
  );
}

function CategoryFilter({ field, label, ...props }: TDataProps) {
  const controls = useCollection()?.controls;
  if (!controls) return null;
  const name = typeof field === "string" ? field : "category";
  return (
    <label className={className(props) ?? "flex items-center gap-2 text-sm"}>
      {typeof label === "string" && <span className="text-muted-foreground">{label}</span>}
      <select
        className="h-9 rounded-md border border-input bg-background px-2 text-sm"
        value={controls.category}
        onChange={(event) => controls.set({ [name]: event.target.value, page: null })}
      >
        <option value="">All</option>
        {controls.categories.map((value) => (
          <option key={value} value={value}>
            {value}
          </option>
        ))}
      </select>
    </label>
  );
}

function SortControl({ label, ...props }: TDataProps) {
  const controls = useCollection()?.controls;
  if (!controls || controls.sortFields.length === 0) return null;
  return (
    <label className={className(props) ?? "flex items-center gap-2 text-sm"}>
      {typeof label === "string" && <span className="text-muted-foreground">{label}</span>}
      <select
        className="h-9 rounded-md border border-input bg-background px-2 text-sm"
        value={controls.sort}
        onChange={(event) => controls.set({ sort: event.target.value, page: null })}
      >
        <option value="">Default</option>
        {controls.sortFields.map((item) => (
          <option key={item.field} value={item.field}>
            {item.label}
          </option>
        ))}
      </select>
    </label>
  );
}

function Pagination(props: TDataProps) {
  const controls = useCollection()?.controls;
  if (!controls || controls.pages <= 1) return null;
  return (
    <nav className={className(props) ?? "flex items-center justify-between gap-2 text-sm"} aria-label="Pages">
      <Button variant="outline" size="sm" disabled={controls.page <= 1} onClick={() => controls.set({ page: controls.page - 1 })}>
        Previous
      </Button>
      <span className="text-muted-foreground">
        Page {controls.page} of {controls.pages}
      </span>
      <Button
        variant="outline"
        size="sm"
        disabled={controls.page >= controls.pages}
        onClick={() => controls.set({ page: controls.page + 1 })}
      >
        Next
      </Button>
    </nav>
  );
}

function ResultCount(props: TDataProps) {
  const collection = useCollection();
  if (!collection) return null;
  return (
    <span className={className(props) ?? "text-sm text-muted-foreground"}>
      {collection.total} {collection.total === 1 ? "result" : "results"}
    </span>
  );
}

// -- states ----------------------------------------------------------------------------------------------------------

function Empty({ children, ...props }: TDataProps) {
  const collection = useCollection();
  if (!collection || collection.isLoading || collection.records.length > 0) return null;
  return <div className={className(props)}>{children}</div>;
}

function Loading({ children, ...props }: TDataProps) {
  const collection = useCollection();
  if (!collection?.isLoading) return null;
  return <div className={className(props)}>{children}</div>;
}

function ErrorState({ children, ...props }: TDataProps) {
  const collection = useCollection();
  if (!collection?.error) return null;
  return <div className={className(props)}>{children}</div>;
}

/** The data components a tree may name (`frontend_spec/trees.py` DATA_COMPONENTS keeps the same list). */
export const DATA_COMPONENTS: Record<string, ComponentType<TDataProps>> = {
  CollectionBrowser,
  CollectionStrip,
  CollectionDetail,
  ItemList,
  RecordField,
  RecordImage,
  VideoEmbed: TreeVideoEmbed,
  BackgroundVideo: TreeBackgroundVideo,
  RecordPrice,
  RecordLink,
  RecordStars,
  SearchBox,
  CategoryFilter,
  FacetFilter: CategoryFilter,
  SortControl,
  Pagination,
  ResultCount,
  Empty,
  Loading,
  Error: ErrorState,
  Metric,
  Chart,
  RecordForm,
  RecordAction,
};
