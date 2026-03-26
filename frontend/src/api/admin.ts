import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { apiClient } from '../lib/api';

// ── Types ──────────────────────────────────────────────────────────────────

export interface ApiKeyResponse {
  id: string;
  name: string;
  prefix: string;
  role: string;
  scopes: string[];
  is_active: boolean;
  last_used_at: string | null;
  expires_at: string | null;
  created_at: string;
}

export interface ApiKeyCreatePayload {
  name: string;
  scopes: string[];
  expires_in_days?: number;
}

export interface ApiKeyCreatedResponse {
  data: ApiKeyResponse & {
    /** The full key — only returned once at creation time. */
    key: string;
  };
  meta: {
    request_id: string;
    timestamp: string;
  };
}

export interface ApiKeyListResponse {
  data: ApiKeyResponse[];
  meta: {
    request_id: string;
    timestamp: string;
  };
}

export interface UsageParams {
  start_date?: string;
  end_date?: string;
  provider?: string;
  purpose?: string;
  group_by?: 'day' | 'provider' | 'purpose';
}

export interface UsageRecord {
  date: string;
  provider: string;
  purpose: string;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  cost_usd: number;
  request_count: number;
}

export interface UsageResponse {
  data: UsageRecord[];
  meta: {
    request_id: string;
    timestamp: string;
    total_cost_usd: number;
    total_tokens: number;
  };
}

export interface QueueStatusResponse {
  data: {
    pending: number;
    active: number;
    completed_today: number;
    failed_today: number;
    workers: number;
  };
  meta: {
    request_id: string;
    timestamp: string;
  };
}

// ── Query Keys ─────────────────────────────────────────────────────────────

export const adminKeys = {
  all: ['admin'] as const,
  apiKeys: () => [...adminKeys.all, 'api-keys'] as const,
  llmUsage: (params?: UsageParams) =>
    [...adminKeys.all, 'llm-usage', params] as const,
  queueStatus: () => [...adminKeys.all, 'queue-status'] as const,
};

// ── Helpers ────────────────────────────────────────────────────────────────

function usageToStringParams(
  params?: UsageParams,
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

export function useApiKeys() {
  return useQuery({
    queryKey: adminKeys.apiKeys(),
    queryFn: () => apiClient.get<ApiKeyListResponse>('/admin/api-keys'),
  });
}

export function useCreateApiKey() {
  const qc = useQueryClient();

  return useMutation({
    mutationFn: (payload: ApiKeyCreatePayload) =>
      apiClient.post<ApiKeyCreatedResponse>('/admin/api-keys', payload),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: adminKeys.apiKeys() });
    },
  });
}

export function useDeleteApiKey() {
  const qc = useQueryClient();

  return useMutation({
    mutationFn: (id: string) =>
      apiClient.delete<void>(`/admin/api-keys/${id}`),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: adminKeys.apiKeys() });
    },
  });
}

export function useLLMUsage(params?: UsageParams) {
  return useQuery({
    queryKey: adminKeys.llmUsage(params),
    queryFn: () =>
      apiClient.get<UsageResponse>(
        '/admin/llm-usage',
        usageToStringParams(params),
      ),
  });
}

export function useQueueStatus() {
  return useQuery({
    queryKey: adminKeys.queueStatus(),
    queryFn: () => apiClient.get<QueueStatusResponse>('/admin/queue-status'),
    refetchInterval: 5_000,
  });
}
