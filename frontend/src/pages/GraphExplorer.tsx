import { useState, useEffect, useCallback } from 'react';
import { useRef } from 'react';
import {
  GitBranch,
  Search,
  X,
  FileText,
  ChevronRight,
  Loader2,
} from 'lucide-react';
import { Link } from '@tanstack/react-router';
import { cn } from '@/utils/cn';
import {
  useGraphSearch,
  useGraphStats,
  useEntityDocuments,
  type EntityResponse,
  type RelationshipResponse,
  type GraphSearchParams,
} from '@/api/graph';
import { GraphVisualization } from '@/components/GraphVisualization';
import { Badge } from '@/components/ui/Badge';
import { Spinner } from '@/components/ui/Spinner';

const ENTITY_TYPES = ['person', 'organization', 'product', 'technology', 'location', 'event'] as const;

const TYPE_COLORS: Record<string, string> = {
  person: 'bg-green-900/50 text-green-400 border border-green-800',
  organization: 'bg-blue-900/50 text-blue-400 border border-blue-800',
  product: 'bg-teal-900/50 text-teal-400 border border-teal-800',
  technology: 'bg-amber-900/50 text-amber-400 border border-amber-800',
  location: 'bg-purple-900/50 text-purple-400 border border-purple-800',
  event: 'bg-red-900/50 text-red-400 border border-red-800',
};

export default function GraphExplorer() {
  const searchInputRef = useRef<HTMLInputElement>(null);

  const [searchQuery, setSearchQuery] = useState('');
  const [activeSearch, setActiveSearch] = useState('');
  const [typeFilter, setTypeFilter] = useState<string>('');
  const [selectedEntity, setSelectedEntity] = useState<EntityResponse | null>(null);
  const [selectedEdge, setSelectedEdge] = useState<RelationshipResponse | null>(null);

  const searchParams: GraphSearchParams = {
    q: activeSearch,
    entity_type: typeFilter || undefined,
    limit: 50,
  };

  const { data: searchData, isLoading: searchLoading } = useGraphSearch(searchParams);
  const { data: statsData } = useGraphStats();
  const { data: entityDocsData } = useEntityDocuments(selectedEntity?.name ?? '');

  const entities: EntityResponse[] = searchData?.data ?? [];
  const entityDocs = entityDocsData?.data ?? [];
  const graphStats = statsData?.data;

  // Derive edges from search results (we get entities, edges come from neighbors)
  const [graphEdges] = useState<RelationshipResponse[]>([]);

  // Cmd+G shortcut
  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key === 'g') {
        e.preventDefault();
        searchInputRef.current?.focus();
      }
    }
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, []);

  function handleSearch() {
    setActiveSearch(searchQuery);
    setSelectedEntity(null);
    setSelectedEdge(null);
  }

  const handleNodeSelect = useCallback((entity: EntityResponse | null) => {
    setSelectedEntity(entity);
    setSelectedEdge(null);
  }, []);

  const handleEdgeSelect = useCallback((edge: RelationshipResponse | null) => {
    setSelectedEdge(edge);
    setSelectedEntity(null);
  }, []);

  return (
    <div className="flex h-[calc(100vh-7.5rem)] gap-4">
      {/* Left sidebar - Search & Filters */}
      <div className="flex w-72 shrink-0 flex-col gap-4">
        {/* Search */}
        <div className="rounded-xl border border-surface-700 bg-surface-800/50 p-4">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-surface-400" />
            <input
              ref={searchInputRef}
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') handleSearch();
              }}
              placeholder="Search entities..."
              className="w-full rounded-lg border border-surface-700 bg-surface-800 py-2 pl-9 pr-8 text-sm text-zinc-100 placeholder-surface-500 outline-none transition-colors focus:border-primary-500"
            />
            {searchQuery && (
              <button
                type="button"
                onClick={() => {
                  setSearchQuery('');
                  setActiveSearch('');
                }}
                className="absolute right-2.5 top-1/2 -translate-y-1/2 text-surface-400 hover:text-zinc-100"
              >
                <X className="h-3.5 w-3.5" />
              </button>
            )}
          </div>
          <p className="mt-1.5 text-[10px] text-surface-500">
            {navigator.platform.includes('Mac') ? '\u2318' : 'Ctrl'}+G to focus
          </p>
        </div>

        {/* Entity type filter */}
        <div className="rounded-xl border border-surface-700 bg-surface-800/50 p-4">
          <h3 className="mb-2 text-xs font-semibold text-zinc-300">Entity Type</h3>
          <div className="space-y-1">
            <button
              type="button"
              onClick={() => setTypeFilter('')}
              className={cn(
                'w-full rounded-md px-2.5 py-1.5 text-left text-xs transition-colors',
                !typeFilter
                  ? 'bg-primary-500/15 text-primary-400'
                  : 'text-surface-400 hover:bg-surface-800 hover:text-zinc-200',
              )}
            >
              All types
            </button>
            {ENTITY_TYPES.map((type) => (
              <button
                key={type}
                type="button"
                onClick={() => setTypeFilter(typeFilter === type ? '' : type)}
                className={cn(
                  'w-full rounded-md px-2.5 py-1.5 text-left text-xs capitalize transition-colors',
                  typeFilter === type
                    ? 'bg-primary-500/15 text-primary-400'
                    : 'text-surface-400 hover:bg-surface-800 hover:text-zinc-200',
                )}
              >
                {type}
                {graphStats?.entity_types?.[type] !== undefined && (
                  <span className="ml-1 text-zinc-500">({graphStats.entity_types[type]})</span>
                )}
              </button>
            ))}
          </div>
        </div>

        {/* Graph stats */}
        {graphStats && (
          <div className="rounded-xl border border-surface-700 bg-surface-800/50 p-4">
            <h3 className="mb-2 text-xs font-semibold text-zinc-300">Graph Stats</h3>
            <div className="space-y-1.5 text-xs">
              <div className="flex justify-between">
                <span className="text-surface-400">Entities</span>
                <span className="tabular-nums text-zinc-200">{graphStats.total_entities}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-surface-400">Relationships</span>
                <span className="tabular-nums text-zinc-200">{graphStats.total_relationships}</span>
              </div>
            </div>
          </div>
        )}

        {/* Search results list */}
        {activeSearch && (
          <div className="min-h-0 flex-1 overflow-y-auto rounded-xl border border-surface-700 bg-surface-800/50">
            <div className="sticky top-0 border-b border-surface-700 bg-surface-800/90 px-4 py-2 backdrop-blur-sm">
              <p className="text-xs text-surface-400">
                {searchLoading ? (
                  <span className="flex items-center gap-1">
                    <Loader2 className="h-3 w-3 animate-spin" />
                    Searching...
                  </span>
                ) : (
                  `${entities.length} entities`
                )}
              </p>
            </div>
            <div className="divide-y divide-surface-700/50">
              {entities.map((entity) => (
                <button
                  key={entity.id}
                  type="button"
                  onClick={() => setSelectedEntity(entity)}
                  className={cn(
                    'w-full px-4 py-2.5 text-left transition-colors hover:bg-surface-800/50',
                    selectedEntity?.id === entity.id && 'bg-primary-500/5',
                  )}
                >
                  <p className="text-sm text-zinc-200">{entity.name}</p>
                  <div className="mt-1 flex items-center gap-2">
                    <span
                      className={cn(
                        'rounded-full px-1.5 py-0.5 text-[9px] font-medium capitalize',
                        TYPE_COLORS[entity.type] ?? 'bg-zinc-700 text-zinc-300',
                      )}
                    >
                      {entity.type}
                    </span>
                    <span className="text-[10px] text-surface-500">
                      {entity.document_count} doc{entity.document_count !== 1 ? 's' : ''}
                    </span>
                  </div>
                </button>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Graph visualization */}
      <div className="flex-1 overflow-hidden rounded-xl border border-surface-700 bg-surface-800/50">
        {!activeSearch ? (
          <div className="flex h-full flex-col items-center justify-center">
            <GitBranch className="h-16 w-16 text-surface-600" />
            <p className="mt-4 text-lg font-medium text-zinc-200">
              Knowledge Graph
            </p>
            <p className="mt-2 text-sm text-surface-400">
              Search for entities to visualize the graph
            </p>
          </div>
        ) : searchLoading ? (
          <div className="flex h-full items-center justify-center">
            <Spinner size="lg" />
          </div>
        ) : entities.length === 0 ? (
          <div className="flex h-full flex-col items-center justify-center">
            <Search className="h-12 w-12 text-surface-600" />
            <p className="mt-4 text-zinc-200">No entities found</p>
            <p className="mt-1 text-sm text-surface-400">Try a different search query</p>
          </div>
        ) : (
          <GraphVisualization
            initialNodes={entities}
            initialEdges={graphEdges}
            onNodeSelect={handleNodeSelect}
            onEdgeSelect={handleEdgeSelect}
          />
        )}
      </div>

      {/* Right sidebar - Detail panel */}
      {(selectedEntity || selectedEdge) && (
        <div className="w-72 shrink-0 space-y-4 overflow-y-auto">
          {selectedEntity && (
            <>
              <div className="rounded-xl border border-surface-700 bg-surface-800/50 p-4">
                <div className="flex items-center justify-between">
                  <h3 className="text-base font-semibold text-zinc-100">{selectedEntity.name}</h3>
                  <button
                    type="button"
                    onClick={() => setSelectedEntity(null)}
                    className="text-surface-400 hover:text-zinc-200"
                  >
                    <X className="h-4 w-4" />
                  </button>
                </div>
                <span
                  className={cn(
                    'mt-2 inline-flex rounded-full px-2 py-0.5 text-[10px] font-medium capitalize',
                    TYPE_COLORS[selectedEntity.type] ?? 'bg-zinc-700 text-zinc-300',
                  )}
                >
                  {selectedEntity.type}
                </span>

                {/* Properties */}
                {Object.keys(selectedEntity.properties).length > 0 && (
                  <div className="mt-3 space-y-1.5 border-t border-surface-700 pt-3">
                    {Object.entries(selectedEntity.properties).map(([key, value]) => (
                      <div key={key} className="text-xs">
                        <span className="text-surface-500">{key}: </span>
                        <span className="text-surface-300">{String(value)}</span>
                      </div>
                    ))}
                  </div>
                )}

                <div className="mt-3 text-xs text-surface-500">
                  {selectedEntity.document_count} document{selectedEntity.document_count !== 1 ? 's' : ''}
                </div>
              </div>

              {/* Entity documents */}
              <div className="rounded-xl border border-surface-700 bg-surface-800/50 p-4">
                <h3 className="mb-2 text-sm font-semibold text-zinc-100">Documents</h3>
                {entityDocs.length === 0 ? (
                  <p className="text-xs text-surface-400">No documents found</p>
                ) : (
                  <div className="space-y-1.5">
                    {entityDocs.map((doc) => (
                      <Link
                        key={doc.document_id}
                        to="/documents/$id"
                        params={{ id: doc.document_id }}
                        className="flex items-center gap-2 rounded-md px-2 py-1.5 text-sm transition-colors hover:bg-surface-800"
                      >
                        <FileText className="h-3.5 w-3.5 shrink-0 text-surface-400" />
                        <span className="min-w-0 flex-1 truncate text-zinc-200">{doc.title}</span>
                        <ChevronRight className="h-3 w-3 shrink-0 text-surface-500" />
                      </Link>
                    ))}
                  </div>
                )}
              </div>
            </>
          )}

          {selectedEdge && (
            <div className="rounded-xl border border-surface-700 bg-surface-800/50 p-4">
              <div className="flex items-center justify-between">
                <h3 className="text-base font-semibold text-zinc-100">Relationship</h3>
                <button
                  type="button"
                  onClick={() => setSelectedEdge(null)}
                  className="text-surface-400 hover:text-zinc-200"
                >
                  <X className="h-4 w-4" />
                </button>
              </div>
              <Badge variant="default" className="mt-2">
                {selectedEdge.relationship_type}
              </Badge>
              <div className="mt-3 space-y-1.5 text-xs">
                <div>
                  <span className="text-surface-500">Source: </span>
                  <span className="text-surface-300">{selectedEdge.source_id?.slice(0, 12)}...</span>
                </div>
                <div>
                  <span className="text-surface-500">Target: </span>
                  <span className="text-surface-300">{selectedEdge.target_id?.slice(0, 12)}...</span>
                </div>
              </div>
              {Object.keys(selectedEdge.properties).length > 0 && (
                <div className="mt-3 space-y-1.5 border-t border-surface-700 pt-3">
                  {Object.entries(selectedEdge.properties).map(([key, value]) => (
                    <div key={key} className="text-xs">
                      <span className="text-surface-500">{key}: </span>
                      <span className="text-surface-300">{String(value)}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
