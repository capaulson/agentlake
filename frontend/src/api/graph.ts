import { useQuery } from '@tanstack/react-query';
import { apiClient } from '../lib/api';

// ── Types ──────────────────────────────────────────────────────────────────

export interface EntityResponse {
  id: string;
  name: string;
  type: string;
  properties: Record<string, string | number | boolean>;
  document_count: number;
  created_at: string;
}

export interface RelationshipResponse {
  id: string;
  source_id: string;
  target_id: string;
  relationship_type: string;
  properties: Record<string, string | number | boolean>;
}

export interface NeighborResponse {
  entity: EntityResponse;
  relationship: RelationshipResponse;
  direction: 'incoming' | 'outgoing';
}

export interface GraphPathResponse {
  nodes: EntityResponse[];
  edges: RelationshipResponse[];
  total_hops: number;
}

export interface GraphSearchParams {
  q: string;
  entity_type?: string;
  limit?: number;
  cursor?: string;
}

export interface EntityListResponse {
  data: EntityResponse[];
  meta: {
    request_id: string;
    timestamp: string;
    next_cursor: string | null;
    total_count: number;
  };
}

export interface NeighborListResponse {
  data: NeighborResponse[];
  meta: {
    request_id: string;
    timestamp: string;
  };
}

export interface GraphPathResponseEnvelope {
  data: GraphPathResponse;
  meta: {
    request_id: string;
    timestamp: string;
  };
}

export interface EntityDocumentsResponse {
  data: EntityDocumentRef[];
  meta: {
    request_id: string;
    timestamp: string;
  };
}

export interface EntityDocumentRef {
  document_id: string;
  title: string;
  category: string;
  mention_count: number;
}

export interface GraphStatsResponse {
  data: {
    total_entities: number;
    total_relationships: number;
    entity_types: Record<string, number>;
    relationship_types: Record<string, number>;
  };
  meta: {
    request_id: string;
    timestamp: string;
  };
}

// ── Query Keys ─────────────────────────────────────────────────────────────

export const graphKeys = {
  all: ['graph'] as const,
  search: (params: GraphSearchParams) =>
    [...graphKeys.all, 'search', params] as const,
  entity: (id: string) => [...graphKeys.all, 'entity', id] as const,
  neighbors: (id: string, depth?: number) =>
    [...graphKeys.all, 'neighbors', id, depth] as const,
  path: (fromId: string, toId: string) =>
    [...graphKeys.all, 'path', fromId, toId] as const,
  entityDocuments: (id: string) =>
    [...graphKeys.all, 'entity-documents', id] as const,
  stats: () => [...graphKeys.all, 'stats'] as const,
};

// ── Helpers ────────────────────────────────────────────────────────────────

function searchToStringParams(params: GraphSearchParams): Record<string, string> {
  const out: Record<string, string> = { q: params.q };
  if (params.entity_type) out.entity_type = params.entity_type;
  if (params.limit !== undefined) out.limit = String(params.limit);
  if (params.cursor) out.cursor = params.cursor;
  return out;
}

// ── Hooks ──────────────────────────────────────────────────────────────────

export function useGraphSearch(params: GraphSearchParams) {
  return useQuery({
    queryKey: graphKeys.search(params),
    queryFn: () =>
      apiClient.get<EntityListResponse>(
        '/graph/search',
        searchToStringParams(params),
      ),
    enabled: params.q.length > 0,
  });
}

export function useEntity(id: string) {
  return useQuery({
    queryKey: graphKeys.entity(id),
    queryFn: () =>
      apiClient.get<{ data: EntityResponse }>(`/graph/entities/${id}`),
    enabled: !!id,
  });
}

export function useEntityNeighbors(id: string, depth?: number) {
  return useQuery({
    queryKey: graphKeys.neighbors(id, depth),
    queryFn: () => {
      const params: Record<string, string> = {};
      if (depth !== undefined) params.depth = String(depth);
      return apiClient.get<NeighborListResponse>(
        `/graph/entities/${id}/neighbors`,
        Object.keys(params).length > 0 ? params : undefined,
      );
    },
    enabled: !!id,
  });
}

export function useGraphPath(fromId: string, toId: string) {
  return useQuery({
    queryKey: graphKeys.path(fromId, toId),
    queryFn: () =>
      apiClient.get<GraphPathResponseEnvelope>('/graph/path', {
        from: fromId,
        to: toId,
      }),
    enabled: !!fromId && !!toId,
  });
}

export function useEntityDocuments(id: string) {
  return useQuery({
    queryKey: graphKeys.entityDocuments(id),
    queryFn: () =>
      apiClient.get<EntityDocumentsResponse>(
        `/graph/entities/${id}/documents`,
      ),
    enabled: !!id,
  });
}

export function useGraphStats() {
  return useQuery({
    queryKey: graphKeys.stats(),
    queryFn: () => apiClient.get<GraphStatsResponse>('/graph/stats'),
  });
}
