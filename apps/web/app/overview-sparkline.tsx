"use client";

import { Line, LineChart } from "recharts";
import type { DotItemDotProps } from "recharts";

import type { OverviewResourceMetric } from "@/lib/api";

const colors = {
  neutral: "var(--color-text-muted)",
  success: "var(--color-success)",
  warning: "var(--color-warning)",
  danger: "var(--color-danger)",
};

export function OverviewSparkline({ metric, label }: { metric: OverviewResourceMetric; label: string }) {
  if (metric.trend.points.length < 2) return null;
  const lastPointIndex = metric.trend.points.length - 1;
  const endpoint = ({ cx, cy, index }: DotItemDotProps) =>
    index === lastPointIndex && cx !== undefined && cy !== undefined ? (
      <circle cx={cx} cy={cy} fill={colors[metric.tone]} r={2.8} stroke="var(--color-surface-1)" strokeWidth={1.4} />
    ) : null;
  return (
    <span aria-label={`${label} 24 小时趋势，${metric.trend.points.length} 个采样点`} className="overview-sparkline" role="img">
      <LineChart accessibilityLayer={false} data={metric.trend.points} height={30} margin={{ top: 3, right: 2, bottom: 3, left: 2 }} width={92}>
        <Line dataKey="value" dot={endpoint} isAnimationActive={false} stroke={colors[metric.tone]} strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.6} type="linear" />
      </LineChart>
    </span>
  );
}
