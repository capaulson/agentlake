import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { apiClient } from '../lib/api';

// ── Types ──────────────────────────────────────────────────────────────────

export type SearchType = 'keyword' | 'semantic' | 'hybrid';

export interface SearchParams {
  q: string;
  search_type?: SearchType;
  category?: string;
  tags?: string[];
  limit?: number;
  cursor?: string;
}

export interface SearchResult {
  id: string;
  title: string;
  summary: string;
  snippet: string;
  score: number;
  category: string;
  source_file_id: string;
  version: number;
  entities: Array<{ name: string; type: string }>;
  created_at: string;
}

// The API wraps search results in a ResponseEnvelope: {data: {results, total, ...}, meta: {...}}
interface SearchDataPayload {
  results: SearchResult[];
  total: number;
  search_time_ms: number;
  query: string;
  mode: string;
}

export interface SearchResponse {
  data: SearchDataPayload;
  meta: {
    request_id: string;
    timestamp: string;
  };
}

export interface DocumentResponse {
  id: string;
  source_file_id: string;
  title: string;
  category: string;
  body_markdown: string;
  summary: string;
  frontmatter: Record<string, unknown>;
  entities: EntityRef[];
  chunks: ChunkResponse[];
  citations: CitationResponse[];
  version: number;
  is_current: boolean;
  processing_version: number;
  created_at: string;
  updated_at: string;
}

export interface ChunkResponse {
  id: string;
  chunk_index: number;
  content: string;
  summary: string | null;
  source_locator: string;
  token_count: number;
}

export interface EntityRef {
  name: string;
  type: string;
}

export interface CitationResponse {
  id: string;
  document_id: string;
  citation_index: number;
  source_file_id: string;
  chunk_index: number;
  source_locator: string;
  quote_snippet: string | null;
  download_url: string | null;
  created_at: string;
}

export interface DocumentListParams {
  limit?: number;
  cursor?: string;
  sort_by?: 'created_at' | 'title' | 'category';
  sort_order?: 'asc' | 'desc';
  category?: string;
  tag?: string;
}

export interface DocumentListResponse {
  data: DocumentResponse[];
  meta: {
    request_id: string;
    timestamp: string;
    next_cursor: string | null;
    total_count: number;
  };
}

export interface DocumentEditPayload {
  documentId: string;
  body_markdown: string;
  justification: string;
}

export interface DiffLogEntry {
  id: string;
  document_id: string;
  before_text: string;
  after_text: string;
  justification: string;
  changed_by: string;
  created_at: string;
}

export interface DocumentHistoryResponse {
  data: DiffLogEntry[];
  meta: {
    request_id: string;
    timestamp: string;
  };
}

export interface CitationListResponse {
  data: CitationResponse[];
  meta: {
    request_id: string;
    timestamp: string;
  };
}

// ── Query Keys ─────────────────────────────────────────────────────────────

export const queryKeys = {
  all: ['query'] as const,
  search: (params: SearchParams) => [...queryKeys.all, 'search', params] as const,
  documents: () => [...queryKeys.all, 'documents'] as const,
  documentList: (params?: DocumentListParams) =>
    [...queryKeys.documents(), params] as const,
  document: (id: string) => [...queryKeys.documents(), id] as const,
  documentHistory: (id: string) =>
    [...queryKeys.document(id), 'history'] as const,
  citations: (documentId: string) =>
    [...queryKeys.document(documentId), 'citations'] as const,
};

// ── Helpers ────────────────────────────────────────────────────────────────

function searchToStringParams(params: SearchParams): Record<string, string> {
  const out: Record<string, string> = { q: params.q };
  if (params.search_type) out.search_type = params.search_type;
  if (params.category) out.category = params.category;
  if (params.tags && params.tags.length > 0) out.tags = params.tags.join(',');
  if (params.limit !== undefined) out.limit = String(params.limit);
  if (params.cursor) out.cursor = params.cursor;
  return out;
}

function toStringParams(
  params?: DocumentListParams,
): Record<string, string> | undefined {
  if (!params) return undefined;
  const out: Record<string, string> = {};
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null) {
      out[k] = String(v);
    }
  }
  return Object.keys(out).length > 0 ? out : undefined;
}

// ── Hooks ──────────────────────────────────────────────────────────────────

export function useSearch(params: SearchParams) {
  return useQuery({
    queryKey: queryKeys.search(params),
    queryFn: () =>
      apiClient.get<SearchResponse>('/query/search', searchToStringParams(params)),
    enabled: params.q.length > 0,
  });
}

export function useDocuments(params?: DocumentListParams) {
  return useQuery({
    queryKey: queryKeys.documentList(params),
    queryFn: () =>
      apiClient.get<DocumentListResponse>(
        '/query/documents',
        toStringParams(params),
      ),
  });
}

export function useDocumentsByFile(fileId: string | null) {
  return useQuery({
    queryKey: ['documents-by-file', fileId],
    queryFn: () =>
      apiClient.get<DocumentListResponse>('/query/documents', {
        source_file_id: fileId!,
        limit: '20',
      }),
    enabled: !!fileId,
  });
}

export function useDocument(id: string) {
  return useQuery({
    queryKey: queryKeys.document(id),
    queryFn: () =>
      apiClient.get<{ data: DocumentResponse }>(`/query/documents/${id}`),
    enabled: !!id,
  });
}

export function useDocumentHistory(id: string) {
  return useQuery({
    queryKey: queryKeys.documentHistory(id),
    queryFn: () =>
      apiClient.get<DocumentHistoryResponse>(
        `/query/documents/${id}/history`,
      ),
    enabled: !!id,
  });
}

export function useEditDocument() {
  const qc = useQueryClient();

  return useMutation({
    mutationFn: ({ documentId, body_markdown, justification }: DocumentEditPayload) =>
      apiClient.put<{ data: DocumentResponse }>(
        `/query/documents/${documentId}`,
        { body_markdown, justification },
      ),
    onSuccess: (_data, variables) => {
      void qc.invalidateQueries({
        queryKey: queryKeys.document(variables.documentId),
      });
      void qc.invalidateQueries({
        queryKey: queryKeys.documentHistory(variables.documentId),
      });
      void qc.invalidateQueries({ queryKey: queryKeys.documents() });
    },
  });
}

export function useCitations(documentId: string) {
  return useQuery({
    queryKey: queryKeys.citations(documentId),
    queryFn: () =>
      apiClient.get<CitationListResponse>(
        `/query/documents/${documentId}/citations`,
      ),
    enabled: !!documentId,
  });
}
