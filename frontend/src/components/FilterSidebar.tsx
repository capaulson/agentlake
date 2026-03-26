import { useState } from 'react';
import { ChevronDown, ChevronRight, X } from 'lucide-react';
import { cn } from '@/utils/cn';
import { Button } from '@/components/ui/Button';
import { TagPicker } from '@/components/TagPicker';

const CATEGORIES = [
  'technical',
  'business',
  'operational',
  'research',
  'communication',
  'reference',
] as const;

const FILE_TYPES = ['pdf', 'docx', 'txt', 'md', 'html', 'csv', 'json', 'xlsx'] as const;

export interface FilterState {
  categories: string[];
  tagIds: string[];
  dateFrom: string;
  dateTo: string;
  fileTypes: string[];
  entity: string;
  keywordWeight: number;
  semanticWeight: number;
}

const EMPTY_FILTERS: FilterState = {
  categories: [],
  tagIds: [],
  dateFrom: '',
  dateTo: '',
  fileTypes: [],
  entity: '',
  keywordWeight: 50,
  semanticWeight: 50,
};

interface FilterSidebarProps {
  filters: FilterState;
  onChange: (filters: FilterState) => void;
  onApply: () => void;
  className?: string;
}

function Section({
  title,
  children,
  defaultOpen = true,
}: {
  title: string;
  children: React.ReactNode;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="border-b border-surface-700 py-3">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="flex w-full items-center justify-between text-sm font-medium text-zinc-200 hover:text-zinc-100"
      >
        {title}
        {open ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
      </button>
      {open && <div className="mt-3 space-y-2">{children}</div>}
    </div>
  );
}

export function FilterSidebar({ filters, onChange, onApply, className }: FilterSidebarProps) {
  function toggleCategory(cat: string) {
    const next = filters.categories.includes(cat)
      ? filters.categories.filter((c) => c !== cat)
      : [...filters.categories, cat];
    onChange({ ...filters, categories: next });
  }

  function toggleFileType(ft: string) {
    const next = filters.fileTypes.includes(ft)
      ? filters.fileTypes.filter((f) => f !== ft)
      : [...filters.fileTypes, ft];
    onChange({ ...filters, fileTypes: next });
  }

  function clearAll() {
    onChange({ ...EMPTY_FILTERS });
  }

  const hasFilters =
    filters.categories.length > 0 ||
    filters.tagIds.length > 0 ||
    filters.dateFrom !== '' ||
    filters.dateTo !== '' ||
    filters.fileTypes.length > 0 ||
    filters.entity !== '' ||
    filters.keywordWeight !== 50 ||
    filters.semanticWeight !== 50;

  return (
    <div className={cn('space-y-0', className)}>
      <div className="flex items-center justify-between pb-3">
        <h3 className="text-sm font-semibold text-zinc-100">Filters</h3>
        {hasFilters && (
          <button
            type="button"
            onClick={clearAll}
            className="flex items-center gap-1 text-xs text-surface-400 transition-colors hover:text-zinc-200"
          >
            <X className="h-3 w-3" />
            Clear all
          </button>
        )}
      </div>

      {/* Categories */}
      <Section title="Category">
        <div className="space-y-1.5">
          {CATEGORIES.map((cat) => (
            <label key={cat} className="flex cursor-pointer items-center gap-2">
              <input
                type="checkbox"
                checked={filters.categories.includes(cat)}
                onChange={() => toggleCategory(cat)}
                className="h-3.5 w-3.5 rounded border-surface-600 bg-surface-800 text-primary-500 focus:ring-primary-500/30"
              />
              <span className="text-sm capitalize text-surface-300">{cat}</span>
            </label>
          ))}
        </div>
      </Section>

      {/* Tags */}
      <Section title="Tags">
        <TagPicker
          selectedIds={filters.tagIds}
          onChange={(ids) => onChange({ ...filters, tagIds: ids })}
        />
      </Section>

      {/* Date Range */}
      <Section title="Date Range" defaultOpen={false}>
        <div className="space-y-2">
          <div>
            <label className="text-xs text-surface-400">From</label>
            <input
              type="date"
              value={filters.dateFrom}
              onChange={(e) => onChange({ ...filters, dateFrom: e.target.value })}
              className="mt-1 w-full rounded-md border border-surface-700 bg-surface-800 px-2 py-1.5 text-xs text-zinc-100 outline-none focus:border-primary-500"
            />
          </div>
          <div>
            <label className="text-xs text-surface-400">To</label>
            <input
              type="date"
              value={filters.dateTo}
              onChange={(e) => onChange({ ...filters, dateTo: e.target.value })}
              className="mt-1 w-full rounded-md border border-surface-700 bg-surface-800 px-2 py-1.5 text-xs text-zinc-100 outline-none focus:border-primary-500"
            />
          </div>
        </div>
      </Section>

      {/* File Types */}
      <Section title="File Type" defaultOpen={false}>
        <div className="flex flex-wrap gap-1.5">
          {FILE_TYPES.map((ft) => (
            <button
              key={ft}
              type="button"
              onClick={() => toggleFileType(ft)}
              className={cn(
                'rounded-md px-2 py-1 text-xs font-medium uppercase transition-all',
                filters.fileTypes.includes(ft)
                  ? 'bg-primary-500/15 text-primary-400 ring-1 ring-primary-500/30'
                  : 'bg-surface-700 text-surface-400 hover:text-zinc-200',
              )}
            >
              {ft}
            </button>
          ))}
        </div>
      </Section>

      {/* Entity */}
      <Section title="Entity" defaultOpen={false}>
        <input
          type="text"
          value={filters.entity}
          onChange={(e) => onChange({ ...filters, entity: e.target.value })}
          placeholder="Filter by entity..."
          className="w-full rounded-md border border-surface-700 bg-surface-800 px-2.5 py-1.5 text-sm text-zinc-100 placeholder-surface-500 outline-none focus:border-primary-500"
        />
      </Section>

      {/* Weight Sliders */}
      <Section title="Search Weights" defaultOpen={false}>
        <div className="space-y-3">
          <div>
            <div className="flex items-center justify-between text-xs">
              <span className="text-surface-400">Keyword</span>
              <span className="tabular-nums text-surface-300">{filters.keywordWeight}%</span>
            </div>
            <input
              type="range"
              min={0}
              max={100}
              value={filters.keywordWeight}
              onChange={(e) =>
                onChange({
                  ...filters,
                  keywordWeight: Number(e.target.value),
                  semanticWeight: 100 - Number(e.target.value),
                })
              }
              className="mt-1 h-1.5 w-full cursor-pointer appearance-none rounded-full bg-surface-700 accent-primary-500"
            />
          </div>
          <div>
            <div className="flex items-center justify-between text-xs">
              <span className="text-surface-400">Semantic</span>
              <span className="tabular-nums text-surface-300">{filters.semanticWeight}%</span>
            </div>
            <input
              type="range"
              min={0}
              max={100}
              value={filters.semanticWeight}
              onChange={(e) =>
                onChange({
                  ...filters,
                  semanticWeight: Number(e.target.value),
                  keywordWeight: 100 - Number(e.target.value),
                })
              }
              className="mt-1 h-1.5 w-full cursor-pointer appearance-none rounded-full bg-surface-700 accent-primary-500"
            />
          </div>
        </div>
      </Section>

      <div className="pt-4">
        <Button size="sm" onClick={onApply} className="w-full">
          Apply Filters
        </Button>
      </div>
    </div>
  );
}

export { EMPTY_FILTERS };
