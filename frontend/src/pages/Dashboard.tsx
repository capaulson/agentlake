import { useNavigate } from '@tanstack/react-router';
import {
  FileText,
  Files,
  Coins,
  DollarSign,
  Activity,
  ArrowRight,
} from 'lucide-react';
import { cn } from '@/utils/cn';
import { useDiscoverStats, useDiscoverCategories } from '@/api/discover';
import { useFiles } from '@/api/vault';
import { useDashboardFeed } from '@/hooks/useDashboardFeed';
import { SearchBar } from '@/components/SearchBar';
import { Badge } from '@/components/ui/Badge';
import { Spinner } from '@/components/ui/Spinner';
import { formatRelative } from '@/utils/formatDate';
import { formatBytes } from '@/utils/formatBytes';
import type { SearchType } from '@/api/query';
import type { LucideIcon } from 'lucide-react';

interface StatCardProps {
  icon: LucideIcon;
  label: string;
  value: string | number;
  subValue?: string;
  pulse?: boolean;
  color?: string;
}

function StatCard({ icon: Icon, label, value, subValue, pulse, color = 'text-primary-500' }: StatCardProps) {
  return (
    <div className="rounded-xl border border-surface-700 bg-surface-800/50 p-5 transition-all hover:border-surface-600">
      <div className="flex items-center gap-3">
        <div className={cn('rounded-lg bg-surface-800 p-2', color)}>
          <Icon className="h-5 w-5" />
        </div>
        <span className="text-sm font-medium text-surface-400">{label}</span>
        {pulse && (
          <span className="relative flex h-2 w-2">
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-primary-400 opacity-75" />
            <span className="relative inline-flex h-2 w-2 rounded-full bg-primary-500" />
          </span>
        )}
      </div>
      <p className="mt-3 text-3xl font-bold tabular-nums text-zinc-100">{value}</p>
      {subValue && <p className="mt-1 text-xs text-surface-500">{subValue}</p>}
    </div>
  );
}

function CategoryBar({ category, count, max }: { category: string; count: number; max: number }) {
  const pct = max > 0 ? (count / max) * 100 : 0;
  return (
    <div className="flex items-center gap-3">
      <span className="w-28 truncate text-sm capitalize text-surface-300">{category}</span>
      <div className="flex-1">
        <div className="h-2 overflow-hidden rounded-full bg-surface-700">
          <div
            className="h-full rounded-full bg-primary-500/70 transition-all duration-500"
            style={{ width: `${pct}%` }}
          />
        </div>
      </div>
      <span className="w-8 text-right text-xs tabular-nums text-surface-400">{count}</span>
    </div>
  );
}

export default function Dashboard() {
  const navigate = useNavigate();
  const { data: statsData, isLoading: statsLoading } = useDiscoverStats();
  const { data: catData } = useDiscoverCategories();
  const { data: recentFilesData } = useFiles({ limit: 8, sort_by: 'created_at', sort_order: 'desc' });
  const { stats: liveStats, isConnected } = useDashboardFeed();

  const stats = statsData?.data;
  const categories = catData?.data ?? [];
  const recentFiles = recentFilesData?.data ?? [];
  const maxCatCount = Math.max(1, ...categories.map((c) => c.count));

  // Use live stats when available, fallback to API stats
  const totalFiles = liveStats?.total_files ?? stats?.total_files ?? 0;
  const totalDocs = liveStats?.total_documents ?? stats?.total_documents ?? 0;
  const tokensToday = liveStats?.tokens_today ?? 0;
  const costToday = liveStats?.cost_today_usd ?? 0;

  function handleSearch(query: string, type: SearchType) {
    if (query.trim()) {
      void navigate({ to: '/search', search: { q: query, type } });
    }
  }

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-bold text-zinc-100">Dashboard</h1>
        <p className="mt-1 text-surface-400">Overview of your data lake</p>
      </div>

      {/* Quick search */}
      <SearchBar onSearch={handleSearch} placeholder="Quick search..." />

      {/* Stats */}
      {statsLoading ? (
        <div className="flex justify-center py-8">
          <Spinner />
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <StatCard
            icon={Files}
            label="Total Files"
            value={totalFiles.toLocaleString()}
            subValue={stats ? `${formatBytes(stats.storage_bytes)} stored` : undefined}
            pulse={isConnected}
          />
          <StatCard
            icon={FileText}
            label="Total Documents"
            value={totalDocs.toLocaleString()}
            subValue={`${stats?.total_entities ?? 0} entities`}
            pulse={isConnected}
            color="text-emerald-500"
          />
          <StatCard
            icon={Coins}
            label="Tokens Today"
            value={tokensToday >= 1000 ? `${(tokensToday / 1000).toFixed(1)}K` : tokensToday}
            pulse={isConnected}
            color="text-amber-500"
          />
          <StatCard
            icon={DollarSign}
            label="Cost Today"
            value={`$${costToday.toFixed(2)}`}
            pulse={isConnected}
            color="text-sky-500"
          />
        </div>
      )}

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        {/* Recent files */}
        <div className="lg:col-span-2">
          <div className="rounded-xl border border-surface-700 bg-surface-800/50">
            <div className="flex items-center justify-between border-b border-surface-700 px-5 py-4">
              <h2 className="text-base font-semibold text-zinc-100">Recent Files</h2>
              <button
                type="button"
                onClick={() => void navigate({ to: '/vault' })}
                className="flex items-center gap-1 text-xs text-primary-400 transition-colors hover:text-primary-300"
              >
                View all <ArrowRight className="h-3 w-3" />
              </button>
            </div>
            <div className="divide-y divide-surface-700/50">
              {recentFiles.length === 0 && (
                <div className="px-5 py-8 text-center text-sm text-surface-400">
                  No files uploaded yet. Upload documents to get started.
                </div>
              )}
              {recentFiles.map((file) => (
                <div key={file.id} className="flex items-center gap-4 px-5 py-3 transition-colors hover:bg-surface-800/30">
                  <FileText className="h-4 w-4 shrink-0 text-surface-400" />
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm text-zinc-200">{file.filename}</p>
                    <p className="text-xs text-surface-500">
                      {formatBytes(file.size_bytes)} &middot; {formatRelative(file.created_at)}
                    </p>
                  </div>
                  <Badge
                    variant={
                      file.status === 'processed'
                        ? 'success'
                        : file.status === 'failed'
                          ? 'danger'
                          : file.status === 'processing'
                            ? 'warning'
                            : 'info'
                    }
                  >
                    {file.status}
                  </Badge>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Category distribution */}
        <div>
          <div className="rounded-xl border border-surface-700 bg-surface-800/50 p-5">
            <h2 className="mb-4 text-base font-semibold text-zinc-100">Categories</h2>
            {categories.length === 0 ? (
              <p className="py-4 text-center text-sm text-surface-400">No categories yet</p>
            ) : (
              <div className="space-y-3">
                {categories.map((cat) => (
                  <CategoryBar
                    key={cat.category}
                    category={cat.category}
                    count={cat.count}
                    max={maxCatCount}
                  />
                ))}
              </div>
            )}
          </div>

          {/* Processing queue status */}
          <div className="mt-4 rounded-xl border border-surface-700 bg-surface-800/50 p-5">
            <div className="flex items-center gap-2">
              <Activity className="h-4 w-4 text-primary-500" />
              <h2 className="text-base font-semibold text-zinc-100">Processing Queue</h2>
            </div>
            <div className="mt-3 grid grid-cols-2 gap-3">
              <div>
                <p className="text-xs text-surface-400">Active</p>
                <p className="text-lg font-semibold tabular-nums text-zinc-100">
                  {liveStats?.processing_active ?? stats?.processing_queue_depth ?? 0}
                </p>
              </div>
              <div>
                <p className="text-xs text-surface-400">Pending</p>
                <p className="text-lg font-semibold tabular-nums text-zinc-100">
                  {liveStats?.queue_depth ?? 0}
                </p>
              </div>
            </div>
            {isConnected && (
              <div className="mt-3 flex items-center gap-1.5">
                <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
                <span className="text-[10px] text-surface-500">Live</span>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
