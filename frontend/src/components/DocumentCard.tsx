import { Link } from '@tanstack/react-router';
import { FileText } from 'lucide-react';
import { cn } from '@/utils/cn';
import type { SearchResult } from '@/api/query';

interface DocumentCardProps {
  result: SearchResult;
  className?: string;
}

const CATEGORY_COLORS: Record<string, string> = {
  technical: 'bg-sky-900/50 text-sky-400 border border-sky-800',
  business: 'bg-amber-900/50 text-amber-400 border border-amber-800',
  operational: 'bg-emerald-900/50 text-emerald-400 border border-emerald-800',
  research: 'bg-violet-900/50 text-violet-400 border border-violet-800',
  communication: 'bg-pink-900/50 text-pink-400 border border-pink-800',
  reference: 'bg-zinc-700 text-zinc-300',
};

function ScoreBar({ score }: { score: number }) {
  // Scores from RRF are typically 0-5 range, normalize
  const normalized = Math.min(score / 5, 1);
  const pct = Math.round(normalized * 100);
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-16 overflow-hidden rounded-full bg-zinc-700">
        <div
          className={cn(
            'h-full rounded-full transition-all',
            pct >= 80 ? 'bg-emerald-500' : pct >= 50 ? 'bg-amber-500' : 'bg-zinc-500',
          )}
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="text-[10px] text-zinc-500">{score.toFixed(2)}</span>
    </div>
  );
}

export function DocumentCard({ result, className }: DocumentCardProps) {
  const docId = result.id;
  const entities = result.entities ?? [];

  return (
    <Link
      to="/documents/$id"
      params={{ id: docId }}
      className={cn(
        'group block rounded-xl border border-zinc-800 bg-zinc-900/50 p-5 transition-all hover:border-teal-500/40 hover:bg-zinc-900',
        className,
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <FileText className="h-4 w-4 shrink-0 text-teal-500" />
            <h3 className="truncate text-base font-semibold text-zinc-100 group-hover:text-teal-400 transition-colors">
              {result.title}
            </h3>
          </div>

          <div className="mt-2 flex flex-wrap items-center gap-2">
            <span
              className={cn(
                'inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-medium',
                CATEGORY_COLORS[result.category] ?? CATEGORY_COLORS.reference,
              )}
            >
              {result.category}
            </span>
            {entities.slice(0, 3).map((ent) => (
              <span
                key={ent.name}
                className="inline-flex items-center rounded-full bg-zinc-800 px-2 py-0.5 text-[10px] text-zinc-400"
              >
                {ent.name}
              </span>
            ))}
          </div>
        </div>
        <ScoreBar score={result.score} />
      </div>

      {/* Snippet with HTML highlighting */}
      {result.snippet && (
        <p
          className="mt-3 line-clamp-3 text-sm leading-relaxed text-zinc-300"
          dangerouslySetInnerHTML={{ __html: result.snippet }}
        />
      )}

      {/* Summary fallback when no snippet */}
      {!result.snippet && result.summary && (
        <p className="mt-3 line-clamp-2 text-sm leading-relaxed text-zinc-400">
          {result.summary?.slice(0, 200)}
        </p>
      )}

      {/* Footer */}
      <div className="mt-3 flex items-center gap-3 text-[10px] text-zinc-500">
        <span>v{result.version}</span>
        <span>{new Date(result.created_at).toLocaleDateString()}</span>
      </div>
    </Link>
  );
}
