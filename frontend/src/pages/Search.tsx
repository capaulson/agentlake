import { useState, useCallback } from 'react';
import { Search as SearchIcon, Filter, Loader2, Sparkles, List } from 'lucide-react';
import { cn } from '@/utils/cn';
import { useSearch, type SearchType, type SearchParams, type SearchResult } from '@/api/query';
import { useSearchStream } from '@/hooks/useSearchStream';
import { SearchBar } from '@/components/SearchBar';
import { DocumentCard } from '@/components/DocumentCard';
import { AgenticSearch } from '@/components/AgenticSearch';
import { FilterSidebar, EMPTY_FILTERS, type FilterState } from '@/components/FilterSidebar';
import { Button } from '@/components/ui/Button';

export default function Search() {
  // Read ?q= from URL to auto-populate from Knowledge page links
  const initialQ = typeof window !== 'undefined'
    ? new URLSearchParams(window.location.search).get('q') ?? ''
    : '';

  const [mode, setMode] = useState<'search' | 'ask'>('ask');
  const [query, setQuery] = useState(initialQ);
  const [searchType, setSearchType] = useState<SearchType>('hybrid');
  const [filters, setFilters] = useState<FilterState>({ ...EMPTY_FILTERS });
  const [showFilters, setShowFilters] = useState(true);
  const [useStreaming, setUseStreaming] = useState(false);
  const [cursor, setCursor] = useState<string | undefined>();
  const [activeParams, setActiveParams] = useState<SearchParams | null>(null);

  // Standard search
  const searchParams: SearchParams = {
    q: query,
    search_type: searchType,
    category: filters.categories.length === 1 ? filters.categories[0] : undefined,
    tags: filters.tagIds.length > 0 ? filters.tagIds : undefined,
    limit: 20,
    cursor,
  };
  const { data: searchData, isLoading, isFetching } = useSearch(
    activeParams ?? searchParams,
  );

  // Streaming search
  const streamState = useSearchStream(
    useStreaming && activeParams ? activeParams : null,
  );

  const results: SearchResult[] = useStreaming
    ? streamState.results
    : searchData?.data?.results ?? [];
  const totalCount = useStreaming
    ? streamState.totalCount
    : searchData?.data?.total ?? null;
  const searchTime = useStreaming
    ? streamState.searchTime
    : searchData?.data?.search_time_ms ?? null;
  const isSearching = useStreaming
    ? streamState.isStreaming
    : isLoading || isFetching;
  const nextCursor = null; // cursor pagination not in search response yet

  const handleSearch = useCallback(
    (q: string, type: SearchType) => {
      setQuery(q);
      setSearchType(type);
      setCursor(undefined);
      if (q.trim()) {
        setActiveParams({
          q,
          search_type: type,
          category: filters.categories.length === 1 ? filters.categories[0] : undefined,
          tags: filters.tagIds.length > 0 ? filters.tagIds : undefined,
          limit: 20,
        });
      } else {
        setActiveParams(null);
      }
    },
    [filters],
  );

  function handleApplyFilters() {
    if (query.trim()) {
      setActiveParams({
        q: query,
        search_type: searchType,
        category: filters.categories.length === 1 ? filters.categories[0] : undefined,
        tags: filters.tagIds.length > 0 ? filters.tagIds : undefined,
        limit: 20,
      });
    }
  }

  function handleLoadMore() {
    if (nextCursor) {
      setCursor(nextCursor);
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-zinc-100">Search</h1>
          <p className="mt-1 text-zinc-400">
            {mode === 'ask'
              ? 'Ask questions and get AI-synthesized answers with sources'
              : 'Search across all documents with keyword, semantic, or hybrid search'}
          </p>
        </div>

        {/* Mode toggle */}
        <div className="flex rounded-lg border border-zinc-800 bg-zinc-900 p-0.5">
          <button
            type="button"
            onClick={() => setMode('ask')}
            className={cn(
              'flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-all',
              mode === 'ask'
                ? 'bg-teal-500/15 text-teal-400'
                : 'text-zinc-500 hover:text-zinc-300',
            )}
          >
            <Sparkles className="h-3.5 w-3.5" />
            Ask AI
          </button>
          <button
            type="button"
            onClick={() => setMode('search')}
            className={cn(
              'flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-all',
              mode === 'search'
                ? 'bg-teal-500/15 text-teal-400'
                : 'text-zinc-500 hover:text-zinc-300',
            )}
          >
            <List className="h-3.5 w-3.5" />
            Search
          </button>
        </div>
      </div>

      {/* Agentic search mode */}
      {mode === 'ask' && <AgenticSearch initialQuestion={initialQ || undefined} />}

      {/* Standard search mode */}
      {mode === 'search' && <>

      {/* Search bar + controls */}
      <div className="flex items-start gap-4">
        <div className="flex-1">
          <SearchBar
            onSearch={handleSearch}
            initialQuery={query}
            initialType={searchType}
            autoFocus
          />
        </div>
        <div className="flex items-center gap-2 pt-1">
          <button
            type="button"
            onClick={() => setShowFilters(!showFilters)}
            className={cn(
              'rounded-lg p-2.5 transition-all',
              showFilters
                ? 'bg-primary-500/15 text-primary-400'
                : 'text-surface-400 hover:bg-surface-800 hover:text-zinc-100',
            )}
            title="Toggle filters"
          >
            <Filter className="h-5 w-5" />
          </button>
          <label className="flex cursor-pointer items-center gap-2 rounded-lg px-3 py-2 text-xs text-surface-400 hover:text-zinc-200">
            <input
              type="checkbox"
              checked={useStreaming}
              onChange={(e) => setUseStreaming(e.target.checked)}
              className="h-3 w-3 rounded border-surface-600 bg-surface-800 text-primary-500"
            />
            Stream
          </label>
        </div>
      </div>

      {/* Main content */}
      <div className="flex gap-6">
        {/* Filter sidebar */}
        {showFilters && (
          <div className="w-64 shrink-0">
            <div className="sticky top-0 rounded-xl border border-surface-700 bg-surface-800/50 p-4">
              <FilterSidebar
                filters={filters}
                onChange={setFilters}
                onApply={handleApplyFilters}
              />
            </div>
          </div>
        )}

        {/* Results */}
        <div className="min-w-0 flex-1">
          {/* Result meta */}
          {activeParams && (
            <div className="mb-4 flex items-center gap-3 text-sm text-surface-400">
              {totalCount !== null && (
                <span>
                  {totalCount.toLocaleString()} result{totalCount !== 1 ? 's' : ''}
                </span>
              )}
              {searchTime !== null && (
                <span className="text-surface-500">&middot; {searchTime}ms</span>
              )}
              {isSearching && (
                <span className="flex items-center gap-1.5">
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  Searching...
                </span>
              )}
            </div>
          )}

          {/* Loading skeleton */}
          {isSearching && results.length === 0 && (
            <div className="space-y-3">
              {Array.from({ length: 5 }).map((_, i) => (
                <div
                  key={i}
                  className="animate-pulse rounded-xl border border-surface-700 bg-surface-800/50 p-5"
                >
                  <div className="h-4 w-2/3 rounded bg-surface-700" />
                  <div className="mt-3 h-3 w-1/2 rounded bg-surface-700" />
                  <div className="mt-2 h-3 w-full rounded bg-surface-700" />
                </div>
              ))}
            </div>
          )}

          {/* Results list */}
          {results.length > 0 && (
            <div className="space-y-3">
              {results.map((result) => (
                <DocumentCard key={result.id} result={result} />
              ))}
            </div>
          )}

          {/* Load more */}
          {nextCursor && !isSearching && (
            <div className="mt-6 flex justify-center">
              <Button variant="secondary" onClick={handleLoadMore}>
                Load More
              </Button>
            </div>
          )}

          {/* Empty state */}
          {!isSearching && activeParams && results.length === 0 && (
            <div className="rounded-xl border border-surface-700 bg-surface-800/50 p-12 text-center">
              <SearchIcon className="mx-auto h-12 w-12 text-surface-600" />
              <p className="mt-4 text-lg font-medium text-zinc-200">No results found</p>
              <p className="mt-2 text-sm text-surface-400">
                Try different keywords or adjust your filters
              </p>
            </div>
          )}

          {/* Initial empty state */}
          {!activeParams && (
            <div className="rounded-xl border border-surface-700 bg-surface-800/50 p-12 text-center">
              <SearchIcon className="mx-auto h-12 w-12 text-surface-600" />
              <p className="mt-4 text-lg font-medium text-zinc-200">
                Enter a query to search your documents
              </p>
              <p className="mt-2 text-sm text-surface-400">
                Use Cmd+K to quickly focus the search bar
              </p>
            </div>
          )}
        </div>
      </div>
      </>}
    </div>
  );
}
