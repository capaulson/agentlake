import { useMemo } from 'react';
import { cn } from '@/utils/cn';
import { useLLMUsage, type UsageRecord } from '@/api/admin';
import { Spinner } from '@/components/ui/Spinner';

interface TokenUsageChartProps {
  className?: string;
  days?: number;
}

const PROVIDER_COLORS: Record<string, string> = {
  anthropic: '#14b8a6',
  openrouter: '#f59e0b',
  openai: '#3b82f6',
};

function getProviderColor(provider: string): string {
  return PROVIDER_COLORS[provider.toLowerCase()] ?? '#71717a';
}

function formatNumber(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}

function formatCost(n: number): string {
  return `$${n.toFixed(2)}`;
}

interface DailyGroup {
  date: string;
  providers: Record<string, number>;
  total: number;
}

export function TokenUsageChart({ className, days = 14 }: TokenUsageChartProps) {
  const endDate = new Date().toISOString().split('T')[0];
  const startDate = new Date(Date.now() - days * 86400000).toISOString().split('T')[0];

  const { data, isLoading } = useLLMUsage({
    start_date: startDate,
    end_date: endDate,
    group_by: 'day',
  });

  const records: UsageRecord[] = data?.data ?? [];
  const totalCost = data?.meta?.total_cost_usd ?? 0;
  const totalTokens = data?.meta?.total_tokens ?? 0;

  const { dailyGroups, maxTotal, allProviders } = useMemo(() => {
    const grouped: Record<string, Record<string, number>> = {};
    const provSet = new Set<string>();

    for (const r of records) {
      if (!grouped[r.date]) grouped[r.date] = {};
      grouped[r.date][r.provider] = (grouped[r.date][r.provider] ?? 0) + r.total_tokens;
      provSet.add(r.provider);
    }

    const groups: DailyGroup[] = Object.entries(grouped)
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([date, providers]) => ({
        date,
        providers,
        total: Object.values(providers).reduce((s, v) => s + v, 0),
      }));

    const max = Math.max(1, ...groups.map((g) => g.total));

    return { dailyGroups: groups, maxTotal: max, allProviders: Array.from(provSet).sort() };
  }, [records]);

  // Model breakdown
  const modelBreakdown = useMemo(() => {
    const models: Record<string, { tokens: number; cost: number; count: number }> = {};
    for (const r of records) {
      const key = r.purpose || 'other';
      if (!models[key]) models[key] = { tokens: 0, cost: 0, count: 0 };
      models[key].tokens += r.total_tokens;
      models[key].cost += r.cost_usd;
      models[key].count += r.request_count;
    }
    return Object.entries(models)
      .sort(([, a], [, b]) => b.tokens - a.tokens)
      .slice(0, 6);
  }, [records]);

  if (isLoading) {
    return (
      <div className={cn('flex items-center justify-center py-12', className)}>
        <Spinner />
      </div>
    );
  }

  const barWidth = dailyGroups.length > 0 ? Math.max(12, Math.min(40, 600 / dailyGroups.length - 4)) : 20;
  const chartHeight = 160;
  const chartWidth = dailyGroups.length * (barWidth + 4) + 20;

  return (
    <div className={cn('space-y-5', className)}>
      {/* Summary cards */}
      <div className="grid grid-cols-3 gap-3">
        <div className="rounded-lg border border-surface-700 bg-surface-800/50 p-3">
          <p className="text-xs text-surface-400">Total Tokens</p>
          <p className="mt-1 text-lg font-semibold text-zinc-100">{formatNumber(totalTokens)}</p>
        </div>
        <div className="rounded-lg border border-surface-700 bg-surface-800/50 p-3">
          <p className="text-xs text-surface-400">Total Cost</p>
          <p className="mt-1 text-lg font-semibold text-zinc-100">{formatCost(totalCost)}</p>
        </div>
        <div className="rounded-lg border border-surface-700 bg-surface-800/50 p-3">
          <p className="text-xs text-surface-400">Providers</p>
          <p className="mt-1 text-lg font-semibold text-zinc-100">{allProviders.length}</p>
        </div>
      </div>

      {/* Bar chart */}
      {dailyGroups.length > 0 ? (
        <div className="overflow-x-auto">
          <svg width={Math.max(chartWidth, 200)} height={chartHeight + 30} className="w-full">
            {/* Bars */}
            {dailyGroups.map((group, i) => {
              const x = i * (barWidth + 4) + 10;
              let yOffset = 0;

              return (
                <g key={group.date}>
                  {allProviders.map((provider) => {
                    const value = group.providers[provider] ?? 0;
                    const height = (value / maxTotal) * chartHeight;
                    const y = chartHeight - yOffset - height;
                    yOffset += height;

                    return (
                      <rect
                        key={provider}
                        x={x}
                        y={y}
                        width={barWidth}
                        height={Math.max(0, height)}
                        fill={getProviderColor(provider)}
                        rx={2}
                        opacity={0.8}
                      >
                        <title>
                          {group.date} - {provider}: {formatNumber(value)} tokens
                        </title>
                      </rect>
                    );
                  })}
                  {/* Date label */}
                  <text
                    x={x + barWidth / 2}
                    y={chartHeight + 16}
                    textAnchor="middle"
                    fill="#71717a"
                    fontSize="8"
                  >
                    {group.date?.slice(5)}
                  </text>
                </g>
              );
            })}
          </svg>
        </div>
      ) : (
        <div className="flex items-center justify-center py-8 text-sm text-surface-400">
          No usage data available
        </div>
      )}

      {/* Provider legend */}
      <div className="flex items-center gap-4">
        {allProviders.map((provider) => (
          <div key={provider} className="flex items-center gap-1.5">
            <span
              className="h-2.5 w-2.5 rounded-sm"
              style={{ backgroundColor: getProviderColor(provider) }}
            />
            <span className="text-xs capitalize text-surface-400">{provider}</span>
          </div>
        ))}
      </div>

      {/* Model/Purpose breakdown */}
      {modelBreakdown.length > 0 && (
        <div>
          <h4 className="mb-2 text-xs font-medium text-surface-400">By Purpose</h4>
          <div className="space-y-1.5">
            {modelBreakdown.map(([purpose, stats]) => {
              const pct = totalTokens > 0 ? (stats.tokens / totalTokens) * 100 : 0;
              return (
                <div key={purpose} className="flex items-center gap-3">
                  <span className="w-24 truncate text-xs text-surface-300">{purpose}</span>
                  <div className="flex-1">
                    <div className="h-1.5 overflow-hidden rounded-full bg-surface-700">
                      <div
                        className="h-full rounded-full bg-primary-500/60"
                        style={{ width: `${pct}%` }}
                      />
                    </div>
                  </div>
                  <span className="w-16 text-right text-[10px] tabular-nums text-surface-400">
                    {formatNumber(stats.tokens)}
                  </span>
                  <span className="w-12 text-right text-[10px] tabular-nums text-surface-400">
                    {formatCost(stats.cost)}
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
