import { Check, AlertCircle, FileSearch, Scissors, Brain, Link, FolderTree, Database } from 'lucide-react';
import { cn } from '@/utils/cn';
import { useProcessingStream } from '@/hooks/useProcessingStream';
import type { LucideIcon } from 'lucide-react';

interface ProcessingProgressProps {
  fileId: string | null;
  className?: string;
}

interface StageConfig {
  id: string;
  label: string;
  icon: LucideIcon;
}

const STAGES: StageConfig[] = [
  { id: 'extract', label: 'Extract', icon: FileSearch },
  { id: 'chunk', label: 'Chunk', icon: Scissors },
  { id: 'summarize', label: 'Summarize', icon: Brain },
  { id: 'cite', label: 'Cite', icon: Link },
  { id: 'classify', label: 'Classify', icon: FolderTree },
  { id: 'store', label: 'Store', icon: Database },
];

function getStageIndex(stage: string): number {
  return STAGES.findIndex((s) => s.id === stage);
}

export function ProcessingProgress({ fileId, className }: ProcessingProgressProps) {
  const state = useProcessingStream(fileId);

  if (!fileId) return null;

  const currentIdx = getStageIndex(state.stage);

  return (
    <div className={cn('rounded-xl border border-surface-700 bg-surface-800/50 p-5', className)}>
      {/* Stage pipeline */}
      <div className="flex items-center justify-between">
        {STAGES.map((stage, idx) => {
          const Icon = stage.icon;
          const isComplete = currentIdx > idx || state.isComplete;
          const isCurrent = currentIdx === idx && !state.isComplete && !state.isError;
          const isError = currentIdx === idx && state.isError;

          return (
            <div key={stage.id} className="flex flex-1 items-center">
              <div className="flex flex-col items-center gap-1.5">
                <div
                  className={cn(
                    'flex h-9 w-9 items-center justify-center rounded-full border-2 transition-all',
                    isComplete && 'border-emerald-500 bg-emerald-500/15',
                    isCurrent && 'border-primary-500 bg-primary-500/15 animate-pulse',
                    isError && 'border-danger-500 bg-danger-500/15',
                    !isComplete && !isCurrent && !isError && 'border-surface-600 bg-surface-800',
                  )}
                >
                  {isComplete ? (
                    <Check className="h-4 w-4 text-emerald-400" />
                  ) : isError ? (
                    <AlertCircle className="h-4 w-4 text-danger-400" />
                  ) : (
                    <Icon
                      className={cn(
                        'h-4 w-4',
                        isCurrent ? 'text-primary-400' : 'text-surface-500',
                      )}
                    />
                  )}
                </div>
                <span
                  className={cn(
                    'text-[10px] font-medium',
                    isComplete && 'text-emerald-400',
                    isCurrent && 'text-primary-400',
                    isError && 'text-danger-400',
                    !isComplete && !isCurrent && !isError && 'text-surface-500',
                  )}
                >
                  {stage.label}
                </span>
              </div>
              {/* Connector line */}
              {idx < STAGES.length - 1 && (
                <div
                  className={cn(
                    'mx-1 h-0.5 flex-1',
                    currentIdx > idx || state.isComplete ? 'bg-emerald-500/40' : 'bg-surface-700',
                  )}
                />
              )}
            </div>
          );
        })}
      </div>

      {/* Progress bar */}
      <div className="mt-4 h-1.5 overflow-hidden rounded-full bg-surface-700">
        <div
          className={cn(
            'h-full rounded-full transition-all duration-500',
            state.isError ? 'bg-danger-500' : state.isComplete ? 'bg-emerald-500' : 'bg-primary-500',
          )}
          style={{ width: `${state.progress}%` }}
        />
      </div>

      {/* Status message */}
      <div className="mt-3 flex items-center justify-between">
        <p
          className={cn(
            'text-sm',
            state.isError ? 'text-danger-400' : state.isComplete ? 'text-emerald-400' : 'text-surface-300',
          )}
        >
          {state.message || (state.isComplete ? 'Processing complete' : 'Waiting...')}
        </p>
        <span className="text-xs tabular-nums text-surface-500">{Math.round(state.progress)}%</span>
      </div>

      {/* Error detail */}
      {state.isError && state.error && (
        <div className="mt-3 rounded-lg border border-danger-800 bg-danger-900/30 px-3 py-2">
          <p className="text-xs text-danger-400">{state.error}</p>
        </div>
      )}
    </div>
  );
}
