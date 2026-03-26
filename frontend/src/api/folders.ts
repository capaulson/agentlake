import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { apiClient } from '../lib/api';
import type { FileResponse } from './vault';

// ── Types ──────────────────────────────────────────────────────────────────

export interface FolderResponse {
  id: string;
  name: string;
  parent_id: string | null;
  path: string;
  description: string | null;
  created_by: string | null;
  ai_summary_id: string | null;
  file_count: number;
  subfolder_count: number;
  created_at: string;
  updated_at: string;
}

export interface FolderDetailResponse {
  folder: FolderResponse;
  children: FolderResponse[];
  files: FileResponse[];
}

export interface FolderTreeNode {
  folder: FolderResponse;
  children: FolderTreeNode[];
}

export interface FolderCreatePayload {
  name: string;
  parent_id?: string | null;
  description?: string | null;
}

export interface FolderUpdatePayload {
  folderId: string;
  name?: string;
  description?: string;
}

export interface FolderMovePayload {
  folderId: string;
  parent_id: string | null;
}

export interface FileMovePayload {
  fileId: string;
  folder_id: string | null;
}

// ── Envelope types ─────────────────────────────────────────────────────────

interface Envelope<T> {
  data: T;
  meta: {
    request_id: string;
    timestamp: string;
  };
}

// ── Query Keys ─────────────────────────────────────────────────────────────

export const folderKeys = {
  all: ['folders'] as const,
  list: (parentId?: string | null) => [...folderKeys.all, 'list', parentId ?? 'root'] as const,
  detail: (id: string) => [...folderKeys.all, 'detail', id] as const,
  tree: (id: string) => [...folderKeys.all, 'tree', id] as const,
};

// ── Hooks ──────────────────────────────────────────────────────────────────

export function useFolders(parentId?: string | null) {
  return useQuery({
    queryKey: folderKeys.list(parentId),
    queryFn: () => {
      const params: Record<string, string> = {};
      if (parentId) {
        params.parent_id = parentId;
      }
      return apiClient.get<Envelope<FolderResponse[]>>(
        '/vault/folders',
        Object.keys(params).length > 0 ? params : undefined,
      );
    },
  });
}

export function useFolder(id: string) {
  return useQuery({
    queryKey: folderKeys.detail(id),
    queryFn: () =>
      apiClient.get<Envelope<FolderDetailResponse>>(`/vault/folders/${id}`),
    enabled: !!id,
  });
}

export function useFolderTree(id: string) {
  return useQuery({
    queryKey: folderKeys.tree(id),
    queryFn: () =>
      apiClient.get<Envelope<FolderTreeNode>>(`/vault/folders/${id}/tree`),
    enabled: !!id,
  });
}

export function useCreateFolder() {
  const qc = useQueryClient();

  return useMutation({
    mutationFn: (payload: FolderCreatePayload) =>
      apiClient.post<Envelope<FolderResponse>>('/vault/folders', { payload }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: folderKeys.all });
    },
  });
}

export function useUpdateFolder() {
  const qc = useQueryClient();

  return useMutation({
    mutationFn: ({ folderId, ...body }: FolderUpdatePayload) =>
      apiClient.put<Envelope<FolderResponse>>(`/vault/folders/${folderId}`, { payload: body }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: folderKeys.all });
    },
  });
}

export function useMoveFolder() {
  const qc = useQueryClient();

  return useMutation({
    mutationFn: ({ folderId, parent_id }: FolderMovePayload) =>
      apiClient.put<Envelope<FolderResponse>>(`/vault/folders/${folderId}/move`, {
        parent_id,
      }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: folderKeys.all });
    },
  });
}

export function useDeleteFolder() {
  const qc = useQueryClient();

  return useMutation({
    mutationFn: (id: string) =>
      apiClient.delete<Envelope<{ id: string; status: string }>>(`/vault/folders/${id}`),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: folderKeys.all });
    },
  });
}

export function useMoveFile() {
  const qc = useQueryClient();

  return useMutation({
    mutationFn: ({ fileId, folder_id }: FileMovePayload) =>
      apiClient.put<Envelope<FileResponse>>(`/vault/files/${fileId}/move`, {
        folder_id,
      }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: folderKeys.all });
      void qc.invalidateQueries({ queryKey: ['vault'] });
    },
  });
}
