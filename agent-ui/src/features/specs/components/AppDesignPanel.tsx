"use client";

import { Check, Palette, PanelLeft, Users } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Stack } from "@/components/layout/Stack";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { ENTITY_AXES, editAppDesign, readAppDesign, shuffleAppDesign, type TEntityAxis } from "../lib/app-design";
import { useDesignPlugins } from "../hooks/use-spec-queries";
import type { TDesignPlugin } from "../types";

type AppDesignPanelProps = {
  specText: string;
  onApply: (text: string) => void;
};

function Choice({
  label,
  value,
  options,
  onChange,
  bold = false,
}: {
  label: string;
  value: string;
  options: TDesignPlugin[];
  onChange: (value: string) => void;
  bold?: boolean;
}) {
  const names = options.map((option) => option.name);
  const known = names.includes(value) ? value : (names[0] ?? value);
  return (
    <label className="flex items-center justify-between gap-2">
      <span className={cn(bold && "font-medium")}>{label}</span>
      <Select value={known} onValueChange={(next) => next && onChange(String(next))}>
        <SelectTrigger size="sm" className="w-40" aria-label={label}>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {options.map((option) => (
            <SelectItem key={option.name} value={option.name} title={option.choose}>
              {option.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </label>
  );
}

/**
 * Epic 23 (Stories 23.6, 23.7): an app draft's design brief in the editor: pick one of the three looks, the shell,
 * the home and each entity's view, detail, card and filters. Each is a spec edit the app kit reads (no model call, no
 * other screen changes). Epic 30 (Stories 30.2, 30.7): the choices come from the design plugin registry.
 */
export function AppDesignPanel({ specText, onApply }: AppDesignPanelProps) {
  const design = readAppDesign(specText);
  const registry = useDesignPlugins().data ?? {};
  if (!design) return null;
  const apply = (next: string | null) => {
    if (next !== null) onApply(next);
  };
  const plugins = (kind: string): TDesignPlugin[] => registry[kind] ?? [];
  const names = (kind: string) => plugins(kind).map((plugin) => plugin.name);
  const family = (recipe: string) => plugins("recipe").find((plugin) => plugin.name === recipe)?.family ?? "custom";
  return (
    <Stack gap="md" className="text-sm">
      {design.requested && (
        <div className="flex flex-col gap-1.5 rounded-lg border p-3">
          <span className="font-medium">From the requirement</span>
          {design.requested.words && <span className="text-xs text-muted-foreground">“{design.requested.words}”</span>}
          <span className="flex flex-wrap items-center gap-2 text-xs">
            {design.requested.colors.map((color) => (
              <span key={color.name} className="flex items-center gap-1">
                <span className="size-3.5 rounded-sm border" style={{ backgroundColor: color.value }} aria-hidden />
                {color.name} {color.value}
              </span>
            ))}
            {design.requested.others.map((item) => (
              <Badge key={item} variant="outline">
                {item}
              </Badge>
            ))}
          </span>
        </div>
      )}
      <div className="flex flex-col gap-2">
        <span className="flex items-center gap-1.5 text-muted-foreground">
          <Palette className="size-4" aria-hidden /> Looks
        </span>
        <div className="grid gap-2">
          {design.looks.map((look) => {
            const picked = look.recipe === design.recipe;
            return (
              <button
                key={look.recipe}
                type="button"
                aria-pressed={picked}
                onClick={() => apply(editAppDesign(specText, { recipe: look.recipe }))}
                className={cn(
                  "flex items-start gap-3 rounded-lg border p-3 text-left transition-colors hover:bg-accent",
                  picked && "border-primary bg-accent",
                )}
              >
                <span className="flex size-5 shrink-0 items-center justify-center rounded-full border">
                  {picked && <Check className="size-3.5" aria-hidden />}
                </span>
                <span className="flex min-w-0 flex-col gap-0.5">
                  <span className="flex items-center gap-2 font-medium capitalize">
                    {look.recipe}
                    <Badge variant="outline">{family(look.recipe)}</Badge>
                  </span>
                  {look.reason && <span className="text-xs text-muted-foreground">{look.reason}</span>}
                </span>
              </button>
            );
          })}
        </div>
      </div>
      <div className="flex flex-col gap-2">
        <span className="flex items-center gap-1.5 text-muted-foreground">
          <PanelLeft className="size-4" aria-hidden /> Layout
          {design.archetype && <Badge variant="secondary">{design.archetype}</Badge>}
        </span>
        <Button type="button" variant="outline" size="sm" className="self-start" onClick={() => apply(shuffleAppDesign(specText, registry))}>
          Try another layout
        </Button>
        <Choice label="Shell" value={design.shell ?? "sidebar"} options={plugins("shell")} onChange={(shell) => apply(editAppDesign(specText, { shell }, names("shell")))} />
        <Choice label="Home" value={design.homeView ?? "dashboard"} options={plugins("home")} onChange={(homeView) => apply(editAppDesign(specText, { homeView }, names("home")))} />
        {design.views.map((entity) => (
          <div key={entity.entity} className="flex flex-col gap-1.5 rounded-lg border p-2">
            <span className={cn("text-xs text-muted-foreground", entity.entity === design.mainEntity && "font-medium text-foreground")}>{entity.entity}</span>
            {ENTITY_AXES.filter((axis) => plugins(axis.kind).length > 0).map((axis) => {
              const current = axis.key === "view" ? entity.view : (entity[axis.key] ?? plugins(axis.kind)[0]?.name ?? "");
              const onChange = (value: string) => apply(editAppDesign(specText, { entity: entity.entity, axis: axis.key as TEntityAxis, value }, names(axis.kind)));
              return <Choice key={axis.key} label={axis.label} value={current} options={plugins(axis.kind)} onChange={onChange} />;
            })}
          </div>
        ))}
      </div>
      {design.areas.length > 0 && (
        <div className="flex flex-col gap-1">
          <span className="flex items-center gap-1.5 text-muted-foreground">
            <Users className="size-4" aria-hidden /> Areas
          </span>
          {design.areas.map((area) => (
            <span key={area.id}>
              {area.label} <span className="text-muted-foreground">({area.roles.join(", ")})</span>
            </span>
          ))}
        </div>
      )}
      {design.replaced.length > 0 && (
        <details className="text-xs text-muted-foreground">
          <summary className="cursor-pointer">Changed by code ({design.replaced.length})</summary>
          <ul className="mt-1 list-disc pl-4">
            {design.replaced.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        </details>
      )}
      <p className="text-xs text-muted-foreground">Looks, the shell, the home and the views change without a model call.</p>
    </Stack>
  );
}
