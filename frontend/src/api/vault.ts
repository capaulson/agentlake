import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { apiClient } from '../lib/api';

// ── Types ──────────────────────────────────────────────────────────────────

export interface FileResponse {
  id: string;
  filename: string;
  original_filename: string;
  content_type: string;
  size_bytes: number;
  sha256_hash: string;
  status: 'pending' | 'uploaded' | 'processing' | 'processed' | 'failed' | 'deleting';
  tags: TagResponse[];
  uploaded_by: string | null;
  error_message: string | null;
  folder_id: string | null;
  created_at: string;
  updated_at: string;
  processing_started_at: string | null;
  processing_completed_at: string | null;
}

export interface FileListParams {
  limit?: number;
  cursor?: string;
  sort_by?: 'created_at' | 'filename' | 'size_bytes';
  sort_order?: 'asc' | 'desc';
  status?: FileResponse['status'];
  tag?: string;
  q?: string;
}

export interface FileListResponse {
  data: FileResponse[];
  meta: {
    request_id: string;
    timestamp: string;
    next_cursor: string | null;
    total_count: number;
  };
}

export interface TagResponse {
  id: string;
  name: string;
  description: string | null;
  is_system: boolean;
  file_count: number;
  created_at: string;
}

export interface TagCreate {
  name: string;
  color?: string;
}

export interface TagListResponse {
  data: TagResponse[];
  meta: {
    request_id: string;
    timestamp: string;
  };
}

export interface UpdateFileTagsPayload {
  fileId: string;
  tag_ids: string[];
}

export interface UploadFileResponse {
  data: {
    file: FileResponse;
    processing_task_id: string | null;
  };
  meta: {
    request_id: string;
    timestamp: string;
  };
}

// ── Query Keys ─────────────────────────────────────────────────────────────

export const vaultKeys = {
  all: ['vault'] as const,
  files: () => [...vaultKeys.all, 'files'] as const,
  fileList: (params?: FileListParams) => [...vaultKeys.files(), params] as const,
  file: (id: string) => [...vaultKeys.files(), id] as const,
  tags: () => [...vaultKeys.all, 'tags'] as const,
};

// ── Helpers ────────────────────────────────────────────────────────────────

function toStringParams(params?: FileListParams): Record<string, string> | undefined {
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

export function useFiles(params?: FileListParams) {
  return useQuery({
    queryKey: vaultKeys.fileList(params),
    queryFn: () =>
      apiClient.get<FileListResponse>('/vault/files', toStringParams(params)),
  });
}

export function useFile(id: string) {
  return useQuery({
    queryKey: vaultKeys.file(id),
    queryFn: () =>
      apiClient.get<{ data: FileResponse }>(`/vault/files/${id}`),
    enabled: !!id,
  });
}

export function useUploadFile() {
  const qc = useQueryClient();

  return useMutation({
    mutationFn: async (formData: FormData) => {
      const apiKey = localStorage.getItem('agentlake-api-key');
      const headers: Record<string, string> = {};
      if (apiKey) {
        headers['X-API-Key'] = apiKey;
      }
      // Upload uses FormData, so we bypass apiClient to avoid JSON Content-Type
      const response = await fetch(
        `${import.meta.env.VITE_API_URL ?? '/api/v1'}/vault/upload`,
        {
          method: 'POST',
          headers,
          body: formData,
        },
      );
      if (!response.ok) {
        const body = await response.json().catch(() => ({
          type: 'about:blank',
          title: response.statusText,
          status: response.status,
          detail: `Upload failed with status ${response.status}`,
        }));
        throw new Error(body.detail ?? 'Upload failed');
      }
      return response.json() as Promise<UploadFileResponse>;
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: vaultKeys.files() });
    },
  });
}

export function useDeleteFile() {
  const qc = useQueryClient();

  return useMutation({
    mutationFn: (id: string) =>
      apiClient.delete<void>(`/vault/files/${id}`),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: vaultKeys.files() });
    },
  });
}

export function useTags() {
  return useQuery({
    queryKey: vaultKeys.tags(),
    queryFn: () => apiClient.get<TagListResponse>('/vault/tags'),
  });
}

export function useCreateTag() {
  const qc = useQueryClient();

  return useMutation({
    mutationFn: (payload: TagCreate) =>
      apiClient.post<{ data: TagResponse }>('/vault/tags', payload),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: vaultKeys.tags() });
    },
  });
}

export function useUpdateFileTags() {
  const qc = useQueryClient();

  return useMutation({
    mutationFn: ({ fileId, tag_ids }: UpdateFileTagsPayload) =>
      apiClient.put<{ data: FileResponse }>(`/vault/files/${fileId}/tags`, {
        tag_ids,
      }),
    onSuccess: (_data, variables) => {
      void qc.invalidateQueries({ queryKey: vaultKeys.file(variables.fileId) });
      void qc.invalidateQueries({ queryKey: vaultKeys.files() });
    },
  });
}

export function useReprocessFile() {
  const qc = useQueryClient();

  return useMutation({
    mutationFn: (id: string) =>
      apiClient.post<{ data: FileResponse }>(`/vault/reprocess/${id}`),
    onSuccess: (_data, id) => {
      void qc.invalidateQueries({ queryKey: vaultKeys.file(id) });
      void qc.invalidateQueries({ queryKey: vaultKeys.files() });
    },
  });
}
