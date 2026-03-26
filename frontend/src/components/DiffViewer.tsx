import { useState } from 'react';
import { ChevronDown, ChevronUp, User, Clock, MessageSquare } from 'lucide-react';
import { cn } from '@/utils/cn';
import { formatRelative } from '@/utils/formatDate';
import type { DiffLogEntry } from '@/api/query';

interface DiffViewerProps {
  entry: DiffLogEntry;
  className?: string;
  defaultExpanded?: boolean;
}

interface DiffLine {
  type: 'unchanged' | 'added' | 'removed';
  text: string;
}

function computeDiff(before: string, after: string): DiffLine[] {
  const beforeLines = before.split('\n');
  const afterLines = after.split('\n');
  const lines: DiffLine[] = [];

  let bi = 0;
  let ai = 0;

  while (bi < beforeLines.length || ai < afterLines.length) {
    if (bi < beforeLines.length && ai < afterLines.length) {
      if (beforeLines[bi] === afterLines[ai]) {
        lines.push({ type: 'unchanged', text: beforeLines[bi] });
        bi++;
        ai++;
      } else {
        // Simple diff: show removed then added
        lines.push({ type: 'removed', text: beforeLines[bi] });
        lines.push({ type: 'added', text: afterLines[ai] });
        bi++;
        ai++;
      }
    } else if (bi < beforeLines.length) {
      lines.push({ type: 'removed', text: beforeLines[bi] });
      bi++;
    } else {
      lines.push({ type: 'added', text: afterLines[ai] });
      ai++;
    }
  }

  return lines;
}

export function DiffViewer({ entry, className, defaultExpanded = false }: DiffViewerProps) {
  const [expanded, setExpanded] = useState(defaultExpanded);
  const diffLines = computeDiff(entry.before_text, entry.after_text);

  return (
    <div className={cn('rounded-lg border border-surface-700 bg-surface-800/50', className)}>
      {/* Header */}
      <button
        type="button"
        onClick={() => setExpanded(!expanded)}
        className="flex w-full items-center justify-between px-4 py-3 text-left transition-colors hover:bg-surface-800"
      >
        <div className="flex items-center gap-4 text-sm">
          <div className="flex items-center gap-1.5 text-surface-300">
            <User className="h-3.5 w-3.5" />
            <span>{entry.changed_by}</span>
          </div>
          <div className="flex items-center gap-1.5 text-surface-400">
            <Clock className="h-3.5 w-3.5" />
            <span>{formatRelative(entry.created_at)}</span>
          </div>
        </div>
        {expanded ? (
          <ChevronUp className="h-4 w-4 text-surface-400" />
        ) : (
          <ChevronDown className="h-4 w-4 text-surface-400" />
        )}
      </button>

      {expanded && (
        <div className="border-t border-surface-700">
          {/* Justification */}
          <div className="flex items-start gap-2 border-b border-surface-700/50 bg-surface-800/30 px-4 py-2.5">
            <MessageSquare className="mt-0.5 h-3.5 w-3.5 shrink-0 text-surface-400" />
            <p className="text-sm text-surface-300 italic">{entry.justification}</p>
          </div>

          {/* Side by side */}
          <div className="grid grid-cols-2 divide-x divide-surface-700">
            <div className="p-3">
              <p className="mb-2 text-xs font-medium text-danger-400">Before</p>
              <pre className="max-h-64 overflow-auto whitespace-pre-wrap text-xs leading-relaxed text-surface-300">
                {entry.before_text}
              </pre>
            </div>
            <div className="p-3">
              <p className="mb-2 text-xs font-medium text-emerald-400">After</p>
              <pre className="max-h-64 overflow-auto whitespace-pre-wrap text-xs leading-relaxed text-surface-300">
                {entry.after_text}
              </pre>
            </div>
          </div>

          {/* Unified diff */}
          <div className="border-t border-surface-700 p-3">
            <p className="mb-2 text-xs font-medium text-surface-400">Diff</p>
            <div className="max-h-64 overflow-auto rounded-md bg-surface-900 p-2 font-mono text-xs leading-relaxed">
              {diffLines.map((line, i) => (
                <div
                  key={i}
                  className={cn(
                    'px-2',
                    line.type === 'added' && 'bg-emerald-500/10 text-emerald-400',
                    line.type === 'removed' && 'bg-danger-500/10 text-danger-400',
                    line.type === 'unchanged' && 'text-surface-400',
                  )}
                >
                  <span className="mr-2 select-none">
                    {line.type === 'added' ? '+' : line.type === 'removed' ? '-' : ' '}
                  </span>
                  {line.text || '\u00A0'}
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
