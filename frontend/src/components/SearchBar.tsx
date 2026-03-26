import { useState, useRef, useEffect, useCallback } from 'react';
import { Search, X } from 'lucide-react';
import { cn } from '@/utils/cn';
import type { SearchType } from '@/api/query';

interface SearchBarProps {
  onSearch: (query: string, type: SearchType) => void;
  initialQuery?: string;
  initialType?: SearchType;
  placeholder?: string;
  className?: string;
  autoFocus?: boolean;
}

const SEARCH_TYPES: { value: SearchType; label: string }[] = [
  { value: 'hybrid', label: 'Hybrid' },
  { value: 'keyword', label: 'Keyword' },
  { value: 'semantic', label: 'Semantic' },
];

export function SearchBar({
  onSearch,
  initialQuery = '',
  initialType = 'hybrid',
  placeholder = 'Search documents...',
  className,
  autoFocus = false,
}: SearchBarProps) {
  const [query, setQuery] = useState(initialQuery);
  const [searchType, setSearchType] = useState<SearchType>(initialType);
  const inputRef = useRef<HTMLInputElement>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const triggerSearch = useCallback(
    (q: string, t: SearchType) => {
      if (debounceRef.current) {
        clearTimeout(debounceRef.current);
      }
      debounceRef.current = setTimeout(() => {
        onSearch(q, t);
      }, 300);
    },
    [onSearch],
  );

  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault();
        inputRef.current?.focus();
      }
    }
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, []);

  useEffect(() => {
    if (autoFocus) {
      inputRef.current?.focus();
    }
  }, [autoFocus]);

  function handleQueryChange(value: string) {
    setQuery(value);
    triggerSearch(value, searchType);
  }

  function handleTypeChange(type: SearchType) {
    setSearchType(type);
    if (query.trim()) {
      triggerSearch(query, type);
    }
  }

  function handleClear() {
    setQuery('');
    onSearch('', searchType);
    inputRef.current?.focus();
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === 'Enter') {
      if (debounceRef.current) {
        clearTimeout(debounceRef.current);
      }
      onSearch(query, searchType);
    }
  }

  return (
    <div className={cn('space-y-3', className)}>
      <div className="relative">
        <Search className="absolute left-4 top-1/2 h-5 w-5 -translate-y-1/2 text-surface-400" />
        <input
          ref={inputRef}
          type="text"
          value={query}
          onChange={(e) => handleQueryChange(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={placeholder}
          className="w-full rounded-xl border border-surface-700 bg-surface-800/50 py-3 pl-12 pr-24 text-zinc-100 placeholder-surface-500 outline-none transition-colors focus:border-primary-500 focus:ring-1 focus:ring-primary-500"
        />
        <div className="absolute right-3 top-1/2 flex -translate-y-1/2 items-center gap-2">
          {query && (
            <button
              type="button"
              onClick={handleClear}
              className="rounded-md p-1 text-surface-400 transition-colors hover:text-zinc-100"
              aria-label="Clear search"
            >
              <X className="h-4 w-4" />
            </button>
          )}
          <kbd className="hidden rounded-md border border-surface-600 bg-surface-800 px-1.5 py-0.5 text-[10px] font-medium text-surface-400 sm:inline-block">
            {navigator.platform.includes('Mac') ? '\u2318' : 'Ctrl'}K
          </kbd>
        </div>
      </div>

      <div className="flex items-center gap-1">
        {SEARCH_TYPES.map((st) => (
          <button
            key={st.value}
            type="button"
            onClick={() => handleTypeChange(st.value)}
            className={cn(
              'rounded-lg px-3 py-1.5 text-xs font-medium transition-all',
              searchType === st.value
                ? 'bg-primary-500/15 text-primary-400 ring-1 ring-primary-500/30'
                : 'text-surface-400 hover:bg-surface-800 hover:text-zinc-200',
            )}
          >
            {st.label}
          </button>
        ))}
      </div>
    </div>
  );
}
