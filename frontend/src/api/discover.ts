import { useQuery } from '@tanstack/react-query';
import { apiClient } from '../lib/api';

// ── Types ──────────────────────────────────────────────────────────────────

export interface DiscoverOverview {
  total_files: number;
  total_documents: number;
  total_entities: number;
  categories: CategoryCount[];
  recent_documents: DiscoverDocument[];
  top_tags: TagCount[];
}

export interface CategoryCount {
  category: string;
  count: number;
}

export interface TagCount {
  tag: string;
  count: number;
}

export interface DiscoverDocument {
  id: string;
  title: string;
  category: string;
  summary: string;
  created_at: string;
}

export interface DiscoverOverviewResponse {
  data: DiscoverOverview;
  meta: {
    request_id: string;
    timestamp: string;
  };
}

export interface SchemaField {
  name: string;
  type: string;
  required: boolean;
  description: string;
}

export interface SchemaResponse {
  data: {
    fields: SchemaField[];
    categories: string[];
  };
  meta: {
    request_id: string;
    timestamp: string;
  };
}

export interface DiscoverStatsResponse {
  data: {
    total_files: number;
    total_documents: number;
    total_entities: number;
    total_citations: number;
    storage_bytes: number;
    processing_queue_depth: number;
  };
  meta: {
    request_id: string;
    timestamp: string;
  };
}

export interface DiscoverTagsResponse {
  data: TagCount[];
  meta: {
    request_id: string;
    timestamp: string;
  };
}

export interface DiscoverCategoriesResponse {
  data: CategoryCount[];
  meta: {
    request_id: string;
    timestamp: string;
  };
}

// ── Query Keys ─────────────────────────────────────────────────────────────

export const discoverKeys = {
  all: ['discover'] as const,
  overview: () => [...discoverKeys.all, 'overview'] as const,
  schema: () => [...discoverKeys.all, 'schema'] as const,
  stats: () => [...discoverKeys.all, 'stats'] as const,
  tags: () => [...discoverKeys.all, 'tags'] as const,
  categories: () => [...discoverKeys.all, 'categories'] as const,
};

// ── Hooks ──────────────────────────────────────────────────────────────────

export function useDiscover() {
  return useQuery({
    queryKey: discoverKeys.overview(),
    queryFn: () => apiClient.get<DiscoverOverviewResponse>('/discover'),
  });
}

export function useDiscoverSchema() {
  return useQuery({
    queryKey: discoverKeys.schema(),
    queryFn: () => apiClient.get<SchemaResponse>('/discover/schema'),
  });
}

export function useDiscoverStats() {
  return useQuery({
    queryKey: discoverKeys.stats(),
    queryFn: () => apiClient.get<DiscoverStatsResponse>('/discover/stats'),
  });
}

export function useDiscoverTags() {
  return useQuery({
    queryKey: discoverKeys.tags(),
    queryFn: () => apiClient.get<DiscoverTagsResponse>('/discover/tags'),
  });
}

export function useDiscoverCategories() {
  return useQuery({
    queryKey: discoverKeys.categories(),
    queryFn: () =>
      apiClient.get<DiscoverCategoriesResponse>('/discover/categories'),
  });
}
