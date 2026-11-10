"use client";

import { useParams } from "next/navigation";
import { CartesianGrid, Line, LineChart, XAxis, YAxis } from "recharts";
import { ChartContainer, ChartTooltip, ChartTooltipContent, type ChartConfig } from "@/components/ui/chart";
import { listOf, resolveParams, type TAppSection, type TRouteParams } from "../app";
import { useOperationQuery } from "../bindings";

const HOUR = 3600 * 1000;

/** Epic 33 (the telemetry feature): readings over time, one small line chart per measure, over the last hours up to
 *  the newest reading (24 by default), each with its latest value. */
export function AppChart({ section }: { section: TAppSection }) {
  const chart = section.content?.chart;
  const route = (useParams() ?? {}) as TRouteParams;
  const params = { ...(resolveParams(section.data?.params, route, undefined) ?? {}), limit: 200 };
  const query = useOperationQuery(section.data?.operationId, params);
  if (!chart) return null;
  const rows = listOf(query.data).records
    .map((row) => ({ row, at: new Date(String(row[chart.time] ?? "")).getTime() }))
    .filter((item) => !Number.isNaN(item.at))
    .sort((a, b) => a.at - b.at);
  const end = rows.length ? rows[rows.length - 1].at : Date.now();
  const window = rows.filter((item) => item.at >= end - (chart.hours ?? 24) * HOUR);
  return (
    <div className="flex flex-col gap-3" data-bga-chart>
      <h2 className="text-base font-semibold">{section.content?.title ?? `Last ${chart.hours ?? 24} hours`}</h2>
      {window.length === 0 && <p className="text-muted-foreground text-sm">No readings yet.</p>}
      <div className="grid gap-4 sm:grid-cols-2">
        {window.length > 0 &&
          chart.series.map((series) => {
            const data = window
              .map((item) => ({ at: item.at, value: Number(item.row[series.field]) }))
              .filter((point) => Number.isFinite(point.value));
            if (data.length === 0) return null;
            const latest = data[data.length - 1].value;
            const config: ChartConfig = { value: { label: series.label, color: "var(--chart-1)" } };
            return (
              <div key={series.field} className="bg-card flex flex-col gap-2 rounded-lg border p-4">
                <div className="flex items-baseline justify-between gap-2">
                  <span className="text-sm font-medium">{series.label}</span>
                  <span className="tabular-nums text-lg font-semibold">
                    {latest.toLocaleString()}
                    {series.unit ? <span className="text-muted-foreground ml-1 text-xs">{series.unit}</span> : null}
                  </span>
                </div>
                <ChartContainer config={config} className="h-32 w-full">
                  <LineChart data={data}>
                    <CartesianGrid vertical={false} />
                    <XAxis
                      dataKey="at"
                      type="number"
                      domain={["dataMin", "dataMax"]}
                      tickFormatter={(at: number) => new Date(at).toLocaleTimeString([], { hour: "2-digit" })}
                      tickLine={false}
                      axisLine={false}
                    />
                    <YAxis width={36} tickLine={false} axisLine={false} />
                    <ChartTooltip content={<ChartTooltipContent hideLabel />} />
                    <Line dataKey="value" stroke="var(--color-value)" strokeWidth={2} dot={false} />
                  </LineChart>
                </ChartContainer>
              </div>
            );
          })}
      </div>
    </div>
  );
}
