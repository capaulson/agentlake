import { useState, useCallback } from 'react';
import {
  FolderOpen,
  FolderPlus,
  Grid3X3,
  List,
  Download,
  RotateCcw,
  Trash2,
  FileText,
  FileSpreadsheet,
  FileCode,
  File,
  Search,
  X,
  ChevronRight,
  ChevronDown,
  Folder as FolderIcon,
  Pencil,
  Upload,
  Home,
  Sparkles,
} from 'lucide-react';
import { cn } from '@/utils/cn';
import {
  useFiles,
  useDeleteFile,
  useReprocessFile,
  useUploadFile,
  type FileResponse,
  type FileListParams,
} from '@/api/vault';
import {
  useFolders,
  useFolder,
  useCreateFolder,
  useUpdateFolder,
  useDeleteFolder,
  type FolderResponse,
} from '@/api/folders';
import { useDocumentsByFile, useDocument } from '@/api/query';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Modal } from '@/components/ui/Modal';
import { Spinner } from '@/components/ui/Spinner';
import { MarkdownRenderer } from '@/components/MarkdownRenderer';
import { formatBytes } from '@/utils/formatBytes';
import { formatRelative } from '@/utils/formatDate';
import type { LucideIcon } from 'lucide-react';

type ViewMode = 'grid' | 'list';
type StatusFilter = FileResponse['status'] | 'all';
type SortField = 'created_at' | 'filename' | 'size_bytes';

function getFileIcon(contentType: string): LucideIcon {
  if (contentType.includes('pdf') || contentType.includes('document')) return FileText;
  if (contentType.includes('spreadsheet') || contentType.includes('csv') || contentType.includes('excel'))
    return FileSpreadsheet;
  if (contentType.includes('json') || contentType.includes('html') || contentType.includes('xml'))
    return FileCode;
  return File;
}

// ── Folder Tree Sidebar ──────────────────────────────────────────────────

function FolderTreeItem({
  folder,
  currentFolderId,
  onSelect,
  depth = 0,
}: {
  folder: FolderResponse;
  currentFolderId: string | null;
  onSelect: (id: string | null) => void;
  depth?: number;
}) {
  const [expanded, setExpanded] = useState(false);
  const { data: childrenData } = useFolders(expanded ? folder.id : undefined);
  const children = childrenData?.data ?? [];
  const isActive = currentFolderId === folder.id;
  const hasChildren = folder.subfolder_count > 0;

  return (
    <div>
      <button
        type="button"
        onClick={() => {
          onSelect(folder.id);
          if (hasChildren) setExpanded(!expanded);
        }}
        className={cn(
          'group flex w-full items-center gap-1.5 rounded-lg px-2 py-1.5 text-left text-sm transition-colors',
          isActive
            ? 'bg-teal-500/15 text-teal-400'
            : 'text-zinc-400 hover:bg-zinc-800/60 hover:text-zinc-200',
        )}
        style={{ paddingLeft: `${depth * 16 + 8}px` }}
      >
        {hasChildren ? (
          expanded ? (
            <ChevronDown className="h-3.5 w-3.5 shrink-0 text-zinc-500" />
          ) : (
            <ChevronRight className="h-3.5 w-3.5 shrink-0 text-zinc-500" />
          )
        ) : (
          <span className="w-3.5 shrink-0" />
        )}
        <FolderIcon
          className={cn(
            'h-4 w-4 shrink-0',
            isActive ? 'text-teal-400' : 'text-zinc-500 group-hover:text-zinc-400',
          )}
        />
        <span className="truncate">{folder.name}</span>
        {folder.file_count > 0 && (
          <span className="ml-auto text-[10px] text-zinc-600">{folder.file_count}</span>
        )}
      </button>
      {expanded && children.length > 0 && (
        <div>
          {children.map((child) => (
            <FolderTreeItem
              key={child.id}
              folder={child}
              currentFolderId={currentFolderId}
              onSelect={onSelect}
              depth={depth + 1}
            />
          ))}
        </div>
      )}
    </div>
  );
}

// ── Breadcrumb ───────────────────────────────────────────────────────────

function Breadcrumb({
  path,
  onNavigate,
}: {
  path: string | null;
  onNavigate: (folderId: string | null) => void;
}) {
  // path is like "/Partners/Acme Corp/Notes" — we show clickable segments
  // For now, only the root segment is clickable to go home since we don't
  // have folder IDs for intermediate segments without extra API calls.
  // The full breadcrumb works via the path string.
  const segments = path ? path.split('/').filter(Boolean) : [];

  return (
    <nav className="flex items-center gap-1 text-sm">
      <button
        type="button"
        onClick={() => onNavigate(null)}
        className="flex items-center gap-1 rounded px-1.5 py-0.5 text-zinc-400 transition-colors hover:bg-zinc-800 hover:text-zinc-200"
      >
        <Home className="h-3.5 w-3.5" />
        <span>Vault</span>
      </button>
      {segments.map((seg, i) => (
        <span key={`${seg}-${i}`} className="flex items-center gap-1">
          <ChevronRight className="h-3.5 w-3.5 text-zinc-600" />
          <span
            className={cn(
              'rounded px-1.5 py-0.5',
              i === segments.length - 1
                ? 'font-medium text-zinc-200'
                : 'text-zinc-400',
            )}
          >
            {seg}
          </span>
        </span>
      ))}
    </nav>
  );
}

// ── Folder Grid Card ─────────────────────────────────────────────────────

function FolderGridCard({
  folder,
  onClick,
  onContextMenu,
}: {
  folder: FolderResponse;
  onClick: () => void;
  onContextMenu: (e: React.MouseEvent) => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      onContextMenu={onContextMenu}
      className="flex flex-col items-center gap-2 rounded-xl border border-zinc-700/50 bg-zinc-800/30 p-4 text-center transition-all hover:border-teal-500/30 hover:bg-zinc-800/60"
    >
      <FolderIcon className="h-10 w-10 text-teal-500/70" />
      <p className="w-full truncate text-sm font-medium text-zinc-200">{folder.name}</p>
      <div className="flex items-center gap-2 text-[10px] text-zinc-500">
        {folder.subfolder_count > 0 && <span>{folder.subfolder_count} folders</span>}
        {folder.file_count > 0 && <span>{folder.file_count} files</span>}
      </div>
    </button>
  );
}

// ── File Grid Card ───────────────────────────────────────────────────────

function FileGridCard({
  file,
  onView,
}: {
  file: FileResponse;
  onView: (f: FileResponse) => void;
}) {
  const Icon = getFileIcon(file.content_type);
  return (
    <button
      type="button"
      onClick={() => onView(file)}
      className="flex flex-col items-center gap-3 rounded-xl border border-surface-700 bg-surface-800/50 p-5 text-center transition-all hover:border-primary-500/40 hover:bg-surface-800"
    >
      <Icon className="h-10 w-10 text-surface-400" />
      <div className="w-full min-w-0">
        <p className="truncate text-sm font-medium text-zinc-200">{file.filename}</p>
        <p className="mt-1 text-xs text-surface-500">{formatBytes(file.size_bytes)}</p>
      </div>
      <Badge
        variant={
          file.status === 'processed'
            ? 'success'
            : file.status === 'failed'
              ? 'danger'
              : file.status === 'processing'
                ? 'warning'
                : 'info'
        }
      >
        {file.status}
      </Badge>
      <p className="text-[10px] text-surface-500">{formatRelative(file.created_at)}</p>
    </button>
  );
}

// ── Context Menu ─────────────────────────────────────────────────────────

function ContextMenu({
  x,
  y,
  items,
  onClose,
}: {
  x: number;
  y: number;
  items: Array<{ label: string; icon: LucideIcon; onClick: () => void; danger?: boolean }>;
  onClose: () => void;
}) {
  return (
    <>
      <div className="fixed inset-0 z-40" onClick={onClose} onContextMenu={(e) => { e.preventDefault(); onClose(); }} />
      <div
        className="fixed z-50 min-w-[160px] rounded-lg border border-zinc-700 bg-zinc-800 py-1 shadow-xl"
        style={{ left: x, top: y }}
      >
        {items.map((item) => {
          const Icon = item.icon;
          return (
            <button
              key={item.label}
              type="button"
              onClick={() => {
                item.onClick();
                onClose();
              }}
              className={cn(
                'flex w-full items-center gap-2 px-3 py-1.5 text-sm transition-colors',
                item.danger
                  ? 'text-red-400 hover:bg-red-500/10'
                  : 'text-zinc-300 hover:bg-zinc-700',
              )}
            >
              <Icon className="h-3.5 w-3.5" />
              {item.label}
            </button>
          );
        })}
      </div>
    </>
  );
}

// ── AI Summary Card ──────────────────────────────────────────────────────

function AISummaryCard({ summaryId }: { summaryId: string }) {
  const { data: docData, isLoading } = useDocument(summaryId);
  const [collapsed, setCollapsed] = useState(false);

  if (isLoading) {
    return (
      <div className="flex items-center gap-2 rounded-xl border border-teal-500/20 bg-teal-950/20 p-4">
        <Spinner size="sm" />
        <span className="text-xs text-zinc-500">Loading AI summary...</span>
      </div>
    );
  }

  const doc = docData?.data;
  if (!doc) return null;

  return (
    <div className="rounded-xl border border-teal-500/20 bg-teal-950/20 overflow-hidden">
      <button
        type="button"
        onClick={() => setCollapsed(!collapsed)}
        className="flex w-full items-center justify-between px-4 py-3 text-left hover:bg-teal-900/10 transition-colors"
      >
        <div className="flex items-center gap-2">
          <Sparkles className="h-4 w-4 text-teal-400" />
          <span className="text-sm font-medium text-teal-300">AI Summary</span>
        </div>
        <ChevronDown
          className={cn('h-4 w-4 text-teal-500 transition-transform', collapsed && '-rotate-90')}
        />
      </button>
      {!collapsed && (
        <div className="border-t border-teal-500/10 px-4 py-3">
          <div className="prose prose-invert prose-sm max-w-none">
            <MarkdownRenderer content={doc.body_markdown ?? doc.summary ?? ''} />
          </div>
        </div>
      )}
    </div>
  );
}

// ── Main VaultBrowser ────────────────────────────────────────────────────

export default function VaultBrowser() {
  const [viewMode, setViewMode] = useState<ViewMode>('list');
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all');
  const [sortBy, setSortBy] = useState<SortField>('created_at');
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('desc');
  const [search, setSearch] = useState('');
  const [cursor, setCursor] = useState<string | undefined>();
  const [selectedFile, setSelectedFile] = useState<FileResponse | null>(null);
  const [deleteConfirm, setDeleteConfirm] = useState<FileResponse | null>(null);

  // Folder state
  const [currentFolderId, setCurrentFolderId] = useState<string | null>(null);
  const [showCreateFolder, setShowCreateFolder] = useState(false);
  const [newFolderName, setNewFolderName] = useState('');
  const [newFolderDesc, setNewFolderDesc] = useState('');
  const [contextMenu, setContextMenu] = useState<{
    x: number;
    y: number;
    type: 'folder' | 'file';
    item: FolderResponse | FileResponse;
  } | null>(null);
  const [renamingFolder, setRenamingFolder] = useState<FolderResponse | null>(null);
  const [renameValue, setRenameValue] = useState('');
  const [deleteFolderConfirm, setDeleteFolderConfirm] = useState<FolderResponse | null>(null);

  const deleteMutation = useDeleteFile();
  const reprocessMutation = useReprocessFile();
  const createFolderMutation = useCreateFolder();
  const updateFolderMutation = useUpdateFolder();
  const deleteFolderMutation = useDeleteFolder();
  const uploadMutation = useUploadFile();

  // Data: root-level folders or children of current folder
  const { data: foldersData, isLoading: foldersLoading } = useFolders(currentFolderId);
  const folders = foldersData?.data ?? [];

  // Data: current folder detail (for breadcrumb and AI summary)
  const { data: folderDetailData } = useFolder(currentFolderId ?? '');
  const currentFolder = folderDetailData?.data?.folder ?? null;
  const folderFiles = folderDetailData?.data?.files ?? [];

  // Root-level folders for sidebar
  const { data: rootFoldersData } = useFolders(null);
  const rootFolders = rootFoldersData?.data ?? [];

  // Files (for root or filtered view when searching)
  const params: FileListParams = {
    limit: 24,
    sort_by: sortBy,
    sort_order: sortOrder,
    ...(statusFilter !== 'all' && { status: statusFilter }),
    ...(search.trim() && { q: search.trim() }),
    ...(cursor && { cursor }),
  };
  const { data: filesData, isLoading: filesLoading } = useFiles(params);

  // When viewing a specific folder, use folderDetail files; when at root with no search, use API files
  const isSearching = !!search.trim();
  const displayFiles = currentFolderId && !isSearching ? folderFiles : (filesData?.data ?? []);
  const displayFolders = isSearching ? [] : folders;
  const isLoading = currentFolderId ? foldersLoading : filesLoading;
  const nextCursor = filesData?.meta?.next_cursor ?? null;

  // Navigation
  const navigateToFolder = useCallback((folderId: string | null) => {
    setCurrentFolderId(folderId);
    setCursor(undefined);
  }, []);

  // Create folder
  async function handleCreateFolder() {
    if (!newFolderName.trim()) return;
    await createFolderMutation.mutateAsync({
      name: newFolderName.trim(),
      parent_id: currentFolderId,
      description: newFolderDesc.trim() || null,
    });
    setShowCreateFolder(false);
    setNewFolderName('');
    setNewFolderDesc('');
  }

  // Rename folder
  async function handleRenameFolder() {
    if (!renamingFolder || !renameValue.trim()) return;
    await updateFolderMutation.mutateAsync({
      folderId: renamingFolder.id,
      name: renameValue.trim(),
    });
    setRenamingFolder(null);
    setRenameValue('');
  }

  // Delete folder
  async function handleDeleteFolder() {
    if (!deleteFolderConfirm) return;
    await deleteFolderMutation.mutateAsync(deleteFolderConfirm.id);
    setDeleteFolderConfirm(null);
    if (currentFolderId === deleteFolderConfirm.id) {
      navigateToFolder(null);
    }
  }

  function handleDelete(file: FileResponse) {
    setDeleteConfirm(file);
  }

  async function confirmDelete() {
    if (!deleteConfirm) return;
    await deleteMutation.mutateAsync(deleteConfirm.id);
    setDeleteConfirm(null);
    setSelectedFile(null);
  }

  async function handleReprocess(file: FileResponse) {
    await reprocessMutation.mutateAsync(file.id);
  }

  function handleDownload(file: FileResponse) {
    const baseUrl = import.meta.env.VITE_API_URL ?? '/api/v1';
    window.open(`${baseUrl}/vault/files/${file.id}/download`, '_blank');
  }

  function handleFolderContextMenu(e: React.MouseEvent, folder: FolderResponse) {
    e.preventDefault();
    setContextMenu({ x: e.clientX, y: e.clientY, type: 'folder', item: folder });
  }

  // Upload handler
  async function handleUploadFiles(fileList: FileList) {
    for (let i = 0; i < fileList.length; i++) {
      const f = fileList[i];
      const formData = new FormData();
      formData.append('file', f);
      if (currentFolderId) {
        formData.append('folder_id', currentFolderId);
      }
      try {
        await uploadMutation.mutateAsync(formData);
      } catch {
        // handled by mutation
      }
    }
  }

  return (
    <div className="flex h-full gap-0">
      {/* ── Left Sidebar: Folder Tree ──────────────────────────────────── */}
      <div className="w-64 shrink-0 border-r border-zinc-800 bg-zinc-900/50">
        <div className="flex items-center justify-between border-b border-zinc-800 px-3 py-3">
          <h2 className="text-xs font-semibold uppercase tracking-wider text-zinc-500">Folders</h2>
          <button
            type="button"
            onClick={() => setShowCreateFolder(true)}
            className="rounded-md p-1 text-zinc-500 transition-colors hover:bg-zinc-800 hover:text-teal-400"
            title="New Folder"
          >
            <FolderPlus className="h-4 w-4" />
          </button>
        </div>
        <div className="overflow-y-auto p-2" style={{ maxHeight: 'calc(100vh - 140px)' }}>
          {/* Root */}
          <button
            type="button"
            onClick={() => navigateToFolder(null)}
            className={cn(
              'flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-sm transition-colors',
              currentFolderId === null
                ? 'bg-teal-500/15 text-teal-400'
                : 'text-zinc-400 hover:bg-zinc-800/60 hover:text-zinc-200',
            )}
          >
            <Home className="h-4 w-4" />
            <span>All Files</span>
          </button>

          <div className="my-1.5 border-t border-zinc-800/50" />

          {rootFolders.map((folder) => (
            <FolderTreeItem
              key={folder.id}
              folder={folder}
              currentFolderId={currentFolderId}
              onSelect={navigateToFolder}
            />
          ))}
        </div>
      </div>

      {/* ── Main Content ───────────────────────────────────────────────── */}
      <div className="flex-1 overflow-y-auto p-6 space-y-5">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <Breadcrumb path={currentFolder?.path ?? null} onNavigate={navigateToFolder} />
            <h1 className="mt-1 text-xl font-bold text-zinc-100">
              {currentFolder?.name ?? 'Vault'}
            </h1>
            {currentFolder?.description && (
              <p className="mt-0.5 text-sm text-zinc-400">{currentFolder.description}</p>
            )}
          </div>
          <div className="flex items-center gap-2">
            <Button
              variant="secondary"
              size="sm"
              onClick={() => setShowCreateFolder(true)}
            >
              <FolderPlus className="h-4 w-4" />
              New Folder
            </Button>
            <label>
              <Button
                variant="primary"
                size="sm"
                onClick={() => {
                  const input = document.createElement('input');
                  input.type = 'file';
                  input.multiple = true;
                  input.onchange = (e) => {
                    const files = (e.target as HTMLInputElement).files;
                    if (files && files.length > 0) {
                      void handleUploadFiles(files);
                    }
                  };
                  input.click();
                }}
                loading={uploadMutation.isPending}
              >
                <Upload className="h-4 w-4" />
                Upload
              </Button>
            </label>
          </div>
        </div>

        {/* AI Summary Card */}
        {currentFolder?.ai_summary_id && (
          <AISummaryCard summaryId={currentFolder.ai_summary_id} />
        )}

        {/* Controls */}
        <div className="flex flex-wrap items-center gap-3">
          <div className="relative flex-1">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-surface-400" />
            <input
              type="text"
              value={search}
              onChange={(e) => {
                setSearch(e.target.value);
                setCursor(undefined);
              }}
              placeholder="Search files..."
              className="w-full rounded-lg border border-surface-700 bg-surface-800 py-2 pl-9 pr-8 text-sm text-zinc-100 placeholder-surface-500 outline-none transition-colors focus:border-primary-500"
            />
            {search && (
              <button
                type="button"
                onClick={() => {
                  setSearch('');
                  setCursor(undefined);
                }}
                className="absolute right-2.5 top-1/2 -translate-y-1/2 text-surface-400 hover:text-zinc-100"
              >
                <X className="h-3.5 w-3.5" />
              </button>
            )}
          </div>

          <select
            value={statusFilter}
            onChange={(e) => {
              setStatusFilter(e.target.value as StatusFilter);
              setCursor(undefined);
            }}
            className="rounded-lg border border-surface-700 bg-surface-800 px-3 py-2 text-sm text-zinc-100 outline-none focus:border-primary-500"
          >
            <option value="all">All Status</option>
            <option value="uploaded">Uploaded</option>
            <option value="processing">Processing</option>
            <option value="processed">Processed</option>
            <option value="failed">Failed</option>
          </select>

          <select
            value={`${sortBy}-${sortOrder}`}
            onChange={(e) => {
              const [field, order] = e.target.value.split('-') as [SortField, 'asc' | 'desc'];
              setSortBy(field);
              setSortOrder(order);
              setCursor(undefined);
            }}
            className="rounded-lg border border-surface-700 bg-surface-800 px-3 py-2 text-sm text-zinc-100 outline-none focus:border-primary-500"
          >
            <option value="created_at-desc">Newest First</option>
            <option value="created_at-asc">Oldest First</option>
            <option value="filename-asc">Name A-Z</option>
            <option value="filename-desc">Name Z-A</option>
            <option value="size_bytes-desc">Largest First</option>
            <option value="size_bytes-asc">Smallest First</option>
          </select>

          <div className="flex rounded-lg border border-surface-700 bg-surface-800">
            <button
              type="button"
              onClick={() => setViewMode('grid')}
              className={cn(
                'rounded-l-lg px-2.5 py-2 transition-colors',
                viewMode === 'grid'
                  ? 'bg-primary-500/15 text-primary-400'
                  : 'text-surface-400 hover:text-zinc-100',
              )}
            >
              <Grid3X3 className="h-4 w-4" />
            </button>
            <button
              type="button"
              onClick={() => setViewMode('list')}
              className={cn(
                'rounded-r-lg px-2.5 py-2 transition-colors',
                viewMode === 'list'
                  ? 'bg-primary-500/15 text-primary-400'
                  : 'text-surface-400 hover:text-zinc-100',
              )}
            >
              <List className="h-4 w-4" />
            </button>
          </div>
        </div>

        {/* Loading */}
        {isLoading && (
          <div className="flex justify-center py-12">
            <Spinner />
          </div>
        )}

        {/* Subfolders */}
        {!isLoading && displayFolders.length > 0 && (
          <div>
            <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-zinc-500">
              Folders ({displayFolders.length})
            </h3>
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6">
              {displayFolders.map((folder) => (
                <FolderGridCard
                  key={folder.id}
                  folder={folder}
                  onClick={() => navigateToFolder(folder.id)}
                  onContextMenu={(e) => handleFolderContextMenu(e, folder)}
                />
              ))}
            </div>
          </div>
        )}

        {/* Empty state */}
        {!isLoading && displayFolders.length === 0 && displayFiles.length === 0 && (
          <div className="rounded-xl border border-surface-700 bg-surface-800/50 p-12 text-center">
            <FolderOpen className="mx-auto h-12 w-12 text-surface-600" />
            <p className="mt-4 text-lg font-medium text-zinc-200">
              {search || statusFilter !== 'all'
                ? 'No files match your filters'
                : currentFolderId
                  ? 'This folder is empty'
                  : 'No files yet'}
            </p>
            <p className="mt-2 text-sm text-surface-400">
              {search || statusFilter !== 'all'
                ? 'Try adjusting your filters'
                : 'Upload files or create folders to get started'}
            </p>
          </div>
        )}

        {/* Files section */}
        {!isLoading && displayFiles.length > 0 && (
          <div>
            {displayFolders.length > 0 && (
              <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-zinc-500">
                Files ({displayFiles.length})
              </h3>
            )}

            {/* Grid view */}
            {viewMode === 'grid' && (
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6">
                {displayFiles.map((file) => (
                  <FileGridCard key={file.id} file={file} onView={setSelectedFile} />
                ))}
              </div>
            )}

            {/* List view */}
            {viewMode === 'list' && (
              <div className="rounded-xl border border-surface-700 bg-surface-800/50">
                <table className="w-full">
                  <thead>
                    <tr className="border-b border-surface-700">
                      <th className="px-4 py-3 text-left text-xs font-medium text-surface-400">Name</th>
                      <th className="px-4 py-3 text-left text-xs font-medium text-surface-400">Size</th>
                      <th className="px-4 py-3 text-left text-xs font-medium text-surface-400">Type</th>
                      <th className="px-4 py-3 text-left text-xs font-medium text-surface-400">Status</th>
                      <th className="px-4 py-3 text-left text-xs font-medium text-surface-400">Tags</th>
                      <th className="px-4 py-3 text-left text-xs font-medium text-surface-400">Date</th>
                      <th className="px-4 py-3 text-right text-xs font-medium text-surface-400">Actions</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-surface-700/50">
                    {displayFiles.map((file) => {
                      const Icon = getFileIcon(file.content_type);
                      return (
                        <tr
                          key={file.id}
                          className="cursor-pointer transition-colors hover:bg-surface-800/30"
                          onClick={() => setSelectedFile(file)}
                        >
                          <td className="px-4 py-3">
                            <div className="flex items-center gap-2">
                              <Icon className="h-4 w-4 shrink-0 text-surface-400" />
                              <span className="max-w-[200px] truncate text-sm text-zinc-200">
                                {file.filename}
                              </span>
                            </div>
                          </td>
                          <td className="px-4 py-3 text-sm text-surface-300">
                            {formatBytes(file.size_bytes)}
                          </td>
                          <td className="px-4 py-3 text-xs text-surface-400">
                            {file.content_type.split('/').pop()}
                          </td>
                          <td className="px-4 py-3">
                            <Badge
                              variant={
                                file.status === 'processed'
                                  ? 'success'
                                  : file.status === 'failed'
                                    ? 'danger'
                                    : file.status === 'processing'
                                      ? 'warning'
                                      : 'info'
                              }
                            >
                              {file.status}
                            </Badge>
                          </td>
                          <td className="px-4 py-3">
                            <div className="flex gap-1">
                              {(file.tags ?? []).slice(0, 2).map((tag) => (
                                <Badge key={tag.id} variant="default" className="text-[10px]">
                                  {tag.name}
                                </Badge>
                              ))}
                              {(file.tags ?? []).length > 2 && (
                                <span className="text-[10px] text-surface-500">
                                  +{(file.tags ?? []).length - 2}
                                </span>
                              )}
                            </div>
                          </td>
                          <td className="px-4 py-3 text-xs text-surface-400">
                            {formatRelative(file.created_at)}
                          </td>
                          <td className="px-4 py-3">
                            <div
                              className="flex items-center justify-end gap-1"
                              onClick={(e) => e.stopPropagation()}
                            >
                              <button
                                type="button"
                                onClick={() => handleDownload(file)}
                                className="rounded p-1.5 text-surface-400 transition-colors hover:bg-surface-700 hover:text-zinc-100"
                                title="Download"
                              >
                                <Download className="h-3.5 w-3.5" />
                              </button>
                              <button
                                type="button"
                                onClick={() => void handleReprocess(file)}
                                className="rounded p-1.5 text-surface-400 transition-colors hover:bg-surface-700 hover:text-zinc-100"
                                title="Reprocess"
                              >
                                <RotateCcw className="h-3.5 w-3.5" />
                              </button>
                              <button
                                type="button"
                                onClick={() => handleDelete(file)}
                                className="rounded p-1.5 text-surface-400 transition-colors hover:bg-danger-900/50 hover:text-danger-400"
                                title="Delete"
                              >
                                <Trash2 className="h-3.5 w-3.5" />
                              </button>
                            </div>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}

        {/* Pagination */}
        {!currentFolderId && nextCursor && (
          <div className="flex justify-center">
            <Button variant="secondary" onClick={() => setCursor(nextCursor)}>
              Load More
            </Button>
          </div>
        )}
      </div>

      {/* ── Context Menu ───────────────────────────────────────────────── */}
      {contextMenu && contextMenu.type === 'folder' && (
        <ContextMenu
          x={contextMenu.x}
          y={contextMenu.y}
          onClose={() => setContextMenu(null)}
          items={[
            {
              label: 'Rename',
              icon: Pencil,
              onClick: () => {
                const folder = contextMenu.item as FolderResponse;
                setRenamingFolder(folder);
                setRenameValue(folder.name);
              },
            },
            {
              label: 'Delete',
              icon: Trash2,
              danger: true,
              onClick: () => {
                setDeleteFolderConfirm(contextMenu.item as FolderResponse);
              },
            },
          ]}
        />
      )}

      {/* ── Create Folder Modal ────────────────────────────────────────── */}
      <Modal
        open={showCreateFolder}
        onClose={() => {
          setShowCreateFolder(false);
          setNewFolderName('');
          setNewFolderDesc('');
        }}
        title="New Folder"
        size="sm"
      >
        <div className="space-y-4">
          <div>
            <label className="mb-1 block text-sm font-medium text-zinc-300">Name</label>
            <input
              type="text"
              value={newFolderName}
              onChange={(e) => setNewFolderName(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') void handleCreateFolder();
              }}
              placeholder="Folder name"
              className="w-full rounded-lg border border-zinc-700 bg-zinc-800 px-3 py-2 text-sm text-zinc-100 placeholder-zinc-500 outline-none focus:border-teal-500"
              autoFocus
            />
          </div>
          <div>
            <label className="mb-1 block text-sm font-medium text-zinc-300">
              Description <span className="text-zinc-500">(optional)</span>
            </label>
            <textarea
              value={newFolderDesc}
              onChange={(e) => setNewFolderDesc(e.target.value)}
              placeholder="What will this folder contain?"
              rows={2}
              className="w-full resize-none rounded-lg border border-zinc-700 bg-zinc-800 px-3 py-2 text-sm text-zinc-100 placeholder-zinc-500 outline-none focus:border-teal-500"
            />
          </div>
          {currentFolderId && currentFolder && (
            <p className="text-xs text-zinc-500">
              Creating inside <span className="text-zinc-400">{currentFolder.path}</span>
            </p>
          )}
          <div className="flex justify-end gap-2">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => {
                setShowCreateFolder(false);
                setNewFolderName('');
                setNewFolderDesc('');
              }}
            >
              Cancel
            </Button>
            <Button
              size="sm"
              onClick={() => void handleCreateFolder()}
              disabled={!newFolderName.trim() || createFolderMutation.isPending}
              loading={createFolderMutation.isPending}
            >
              Create Folder
            </Button>
          </div>
        </div>
      </Modal>

      {/* ── Rename Folder Modal ────────────────────────────────────────── */}
      <Modal
        open={renamingFolder !== null}
        onClose={() => {
          setRenamingFolder(null);
          setRenameValue('');
        }}
        title="Rename Folder"
        size="sm"
      >
        <div className="space-y-4">
          <input
            type="text"
            value={renameValue}
            onChange={(e) => setRenameValue(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') void handleRenameFolder();
            }}
            className="w-full rounded-lg border border-zinc-700 bg-zinc-800 px-3 py-2 text-sm text-zinc-100 outline-none focus:border-teal-500"
            autoFocus
          />
          <div className="flex justify-end gap-2">
            <Button variant="ghost" size="sm" onClick={() => setRenamingFolder(null)}>
              Cancel
            </Button>
            <Button
              size="sm"
              onClick={() => void handleRenameFolder()}
              disabled={!renameValue.trim() || updateFolderMutation.isPending}
              loading={updateFolderMutation.isPending}
            >
              Rename
            </Button>
          </div>
        </div>
      </Modal>

      {/* ── Delete Folder Confirmation ─────────────────────────────────── */}
      <Modal
        open={deleteFolderConfirm !== null}
        onClose={() => setDeleteFolderConfirm(null)}
        title="Delete Folder"
        size="sm"
      >
        <div className="space-y-4">
          <p className="text-sm text-surface-300">
            Are you sure you want to delete{' '}
            <strong className="text-zinc-100">{deleteFolderConfirm?.name}</strong>? All subfolders
            will be deleted. Files inside will be moved to the root.
          </p>
          <div className="flex justify-end gap-2">
            <Button variant="ghost" size="sm" onClick={() => setDeleteFolderConfirm(null)}>
              Cancel
            </Button>
            <Button
              variant="danger"
              size="sm"
              onClick={() => void handleDeleteFolder()}
              loading={deleteFolderMutation.isPending}
            >
              Delete
            </Button>
          </div>
        </div>
      </Modal>

      {/* ── File Detail Modal ──────────────────────────────────────────── */}
      <Modal
        open={selectedFile !== null}
        onClose={() => setSelectedFile(null)}
        title={selectedFile?.filename ?? ''}
        size="lg"
      >
        {selectedFile && (
          <FileDetailView
            file={selectedFile}
            onDownload={handleDownload}
            onReprocess={handleReprocess}
            onDelete={handleDelete}
            reprocessing={reprocessMutation.isPending}
          />
        )}
      </Modal>

      {/* ── Delete File Confirmation ───────────────────────────────────── */}
      <Modal
        open={deleteConfirm !== null}
        onClose={() => setDeleteConfirm(null)}
        title="Delete File"
        size="sm"
      >
        <div className="space-y-4">
          <p className="text-sm text-surface-300">
            Are you sure you want to delete{' '}
            <strong className="text-zinc-100">{deleteConfirm?.filename}</strong>? This action
            cannot be undone.
          </p>
          <div className="flex justify-end gap-2">
            <Button variant="ghost" size="sm" onClick={() => setDeleteConfirm(null)}>
              Cancel
            </Button>
            <Button
              variant="danger"
              size="sm"
              onClick={() => void confirmDelete()}
              loading={deleteMutation.isPending}
            >
              Delete
            </Button>
          </div>
        </div>
      </Modal>
    </div>
  );
}

// ── File Detail View ─────────────────────────────────────────────────────

const CATEGORY_COLORS: Record<string, string> = {
  technical: 'bg-sky-900/50 text-sky-400',
  business: 'bg-amber-900/50 text-amber-400',
  operational: 'bg-emerald-900/50 text-emerald-400',
  research: 'bg-violet-900/50 text-violet-400',
  communication: 'bg-pink-900/50 text-pink-400',
  reference: 'bg-zinc-700 text-zinc-300',
};

function FileDetailView({
  file,
  onDownload,
  onReprocess,
  onDelete,
  reprocessing,
}: {
  file: FileResponse;
  onDownload: (f: FileResponse) => void;
  onReprocess: (f: FileResponse) => void;
  onDelete: (f: FileResponse) => void;
  reprocessing: boolean;
}) {
  const { data: docsData, isLoading: docsLoading } = useDocumentsByFile(file.id);
  const docs = docsData?.data ?? [];
  const [expandedDocId, setExpandedDocId] = useState<string | null>(null);

  return (
    <div className="max-h-[75vh] space-y-5 overflow-y-auto pr-1">
      {/* Raw File Info */}
      <div className="rounded-xl border border-zinc-800 bg-zinc-900/50 p-4">
        <h3 className="mb-3 flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-zinc-500">
          <File className="h-3.5 w-3.5" />
          Raw File
        </h3>
        <div className="grid grid-cols-3 gap-3 text-sm">
          <div>
            <p className="text-[10px] text-zinc-500">Type</p>
            <p className="mt-0.5 text-zinc-300">{file.content_type}</p>
          </div>
          <div>
            <p className="text-[10px] text-zinc-500">Size</p>
            <p className="mt-0.5 text-zinc-300">{formatBytes(file.size_bytes)}</p>
          </div>
          <div>
            <p className="text-[10px] text-zinc-500">Status</p>
            <Badge
              variant={
                file.status === 'processed'
                  ? 'success'
                  : file.status === 'failed'
                    ? 'danger'
                    : 'info'
              }
            >
              {file.status}
            </Badge>
          </div>
          <div>
            <p className="text-[10px] text-zinc-500">Uploaded</p>
            <p className="mt-0.5 text-zinc-300">{formatRelative(file.created_at)}</p>
          </div>
          <div>
            <p className="text-[10px] text-zinc-500">By</p>
            <p className="mt-0.5 text-zinc-300">{file.uploaded_by ?? 'Unknown'}</p>
          </div>
          <div>
            <p className="text-[10px] text-zinc-500">SHA-256</p>
            <p className="mt-0.5 font-mono text-[10px] text-zinc-400">
              {file.sha256_hash?.slice(0, 16)}...
            </p>
          </div>
        </div>

        {(file.tags ?? []).length > 0 && (
          <div className="mt-3 flex flex-wrap gap-1.5">
            {(file.tags ?? []).map((tag) => (
              <Badge key={tag.id} variant="default" className="text-[10px]">
                {tag.name}
              </Badge>
            ))}
          </div>
        )}

        <div className="mt-3 flex gap-2">
          <Button size="sm" variant="secondary" onClick={() => onDownload(file)}>
            <Download className="h-3.5 w-3.5" />
            Download
          </Button>
          <Button
            size="sm"
            variant="secondary"
            onClick={() => onReprocess(file)}
            loading={reprocessing}
          >
            <RotateCcw className="h-3.5 w-3.5" />
            Reprocess
          </Button>
          <Button size="sm" variant="danger" onClick={() => onDelete(file)}>
            <Trash2 className="h-3.5 w-3.5" />
            Delete
          </Button>
        </div>
      </div>

      {/* Processed Documents */}
      <div>
        <h3 className="mb-3 flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-zinc-500">
          <FileText className="h-3.5 w-3.5" />
          Processed Data ({docs.length})
        </h3>

        {docsLoading && (
          <div className="flex items-center justify-center gap-2 py-6">
            <Spinner size="sm" />
            <span className="text-xs text-zinc-500">Loading processed documents...</span>
          </div>
        )}

        {!docsLoading && docs.length === 0 && (
          <div className="rounded-lg border border-zinc-800 bg-zinc-900/30 p-6 text-center">
            <p className="text-sm text-zinc-500">
              {file.status === 'pending' || file.status === 'processing'
                ? 'Document is still being processed...'
                : file.status === 'failed'
                  ? 'Processing failed. Try reprocessing.'
                  : 'No processed documents found.'}
            </p>
          </div>
        )}

        <div className="space-y-3">
          {docs.map((doc) => (
            <ProcessedDocCard
              key={doc.id}
              doc={doc}
              expanded={expandedDocId === doc.id}
              onToggle={() => setExpandedDocId(expandedDocId === doc.id ? null : doc.id)}
            />
          ))}
        </div>
      </div>
    </div>
  );
}

function ProcessedDocCard({
  doc,
  expanded,
  onToggle,
}: {
  doc: {
    id: string;
    title: string;
    summary: string;
    category: string;
    entities: Array<{ name: string; type: string }>;
    version: number;
    is_current: boolean;
    created_at: string;
    source_file_id: string;
  };
  expanded: boolean;
  onToggle: () => void;
}) {
  const { data: fullDocData, isLoading: fullLoading } = useDocument(expanded ? doc.id : '');
  const fullDoc = fullDocData?.data;
  const entities = doc.entities ?? [];

  return (
    <div className="overflow-hidden rounded-xl border border-zinc-800 bg-zinc-900/50">
      {/* Header */}
      <button
        type="button"
        onClick={onToggle}
        className="w-full px-4 py-3 text-left transition-colors hover:bg-zinc-800/30"
      >
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <span
                className={cn(
                  'inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-medium',
                  CATEGORY_COLORS[doc.category] ?? CATEGORY_COLORS.reference,
                )}
              >
                {doc.category}
              </span>
              {doc.is_current && (
                <Badge variant="success" className="text-[10px]">
                  current
                </Badge>
              )}
              <span className="text-[10px] text-zinc-500">v{doc.version}</span>
            </div>
            <h4 className="mt-1 truncate text-sm font-medium text-zinc-200">{doc.title}</h4>
            <p className="mt-0.5 line-clamp-2 text-xs text-zinc-400">
              {doc.summary?.slice(0, 200)}
            </p>
          </div>
          <svg
            className={cn(
              'h-4 w-4 shrink-0 text-zinc-500 transition-transform',
              expanded && 'rotate-180',
            )}
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
          >
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
          </svg>
        </div>

        {entities.length > 0 && (
          <div className="mt-2 flex flex-wrap gap-1">
            {entities.slice(0, 6).map((ent, i) => (
              <span
                key={`${ent.name}-${i}`}
                className="rounded bg-zinc-800 px-1.5 py-0.5 text-[10px] text-zinc-400"
              >
                {ent.name}
              </span>
            ))}
            {entities.length > 6 && (
              <span className="text-[10px] text-zinc-500">+{entities.length - 6} more</span>
            )}
          </div>
        )}
      </button>

      {/* Expanded content */}
      {expanded && (
        <div className="space-y-4 border-t border-zinc-800 px-4 py-4">
          {fullLoading && (
            <div className="flex items-center justify-center gap-2 py-4">
              <Spinner size="sm" />
              <span className="text-xs text-zinc-500">Loading document...</span>
            </div>
          )}

          {fullDoc && (
            <>
              {/* Frontmatter */}
              {fullDoc.frontmatter && Object.keys(fullDoc.frontmatter).length > 0 && (
                <div className="rounded-lg bg-zinc-800/40 p-3">
                  <p className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-zinc-500">
                    Frontmatter
                  </p>
                  <div className="grid grid-cols-2 gap-2 text-[11px]">
                    {Object.entries(fullDoc.frontmatter)
                      .filter(([k]) => !['entities', 'people', 'summary'].includes(k))
                      .slice(0, 8)
                      .map(([key, value]) => (
                        <div key={key}>
                          <span className="text-zinc-500">{key}: </span>
                          <span className="text-zinc-300">
                            {typeof value === 'string'
                              ? value.slice(0, 60)
                              : JSON.stringify(value).slice(0, 60)}
                          </span>
                        </div>
                      ))}
                  </div>
                </div>
              )}

              {/* People */}
              {fullDoc.frontmatter?.people &&
                Array.isArray(fullDoc.frontmatter.people) &&
                fullDoc.frontmatter.people.length > 0 && (
                  <div>
                    <p className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-zinc-500">
                      People Detected
                    </p>
                    <div className="space-y-1.5">
                      {(fullDoc.frontmatter.people as Array<Record<string, string>>).map(
                        (person, i) => (
                          <div
                            key={i}
                            className="flex items-center gap-3 rounded-lg bg-zinc-800/30 px-3 py-2 text-xs"
                          >
                            <span className="font-medium text-zinc-200">{person.name}</span>
                            {person.role && <span className="text-zinc-400">{person.role}</span>}
                            {person.organization && (
                              <span className="text-zinc-500">@{person.organization}</span>
                            )}
                            {person.email && (
                              <span className="font-mono text-teal-400/70">{person.email}</span>
                            )}
                          </div>
                        ),
                      )}
                    </div>
                  </div>
                )}

              {/* Tags */}
              {fullDoc.frontmatter?.tags &&
                Array.isArray(fullDoc.frontmatter.tags) &&
                fullDoc.frontmatter.tags.length > 0 && (
                  <div>
                    <p className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-zinc-500">
                      Auto-Generated Tags
                    </p>
                    <div className="flex flex-wrap gap-1.5">
                      {(fullDoc.frontmatter.tags as string[]).map((tag) => (
                        <span
                          key={tag}
                          className="rounded-full bg-teal-500/10 px-2 py-0.5 text-[10px] text-teal-400"
                        >
                          #{tag}
                        </span>
                      ))}
                    </div>
                  </div>
                )}

              {/* Chunks */}
              {fullDoc.chunks && fullDoc.chunks.length > 0 && (
                <div>
                  <p className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-zinc-500">
                    Chunks ({fullDoc.chunks.length})
                  </p>
                  <div className="max-h-60 space-y-2 overflow-y-auto">
                    {fullDoc.chunks.map((chunk) => (
                      <div
                        key={chunk.id}
                        className="rounded-lg border border-zinc-800/50 bg-zinc-900/30 p-3"
                      >
                        <div className="mb-1 flex items-center gap-2 text-[10px] text-zinc-500">
                          <span>Chunk {chunk.chunk_index}</span>
                          <span>&middot;</span>
                          <span>{chunk.source_locator}</span>
                          <span>&middot;</span>
                          <span>{chunk.token_count} tokens</span>
                        </div>
                        <p className="line-clamp-3 text-xs text-zinc-300">
                          {chunk.content?.slice(0, 300)}
                        </p>
                        {chunk.summary && (
                          <p className="mt-1.5 line-clamp-2 text-[11px] italic text-zinc-400">
                            Summary: {chunk.summary.slice(0, 200)}
                          </p>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Citations */}
              {fullDoc.citations && fullDoc.citations.length > 0 && (
                <div>
                  <p className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-zinc-500">
                    Citations ({fullDoc.citations.length})
                  </p>
                  <div className="space-y-1">
                    {fullDoc.citations.map((cit) => (
                      <div key={cit.id} className="flex items-center gap-2 text-xs">
                        <span className="flex h-5 w-5 items-center justify-center rounded bg-teal-500/15 text-[10px] font-bold text-teal-400">
                          {cit.citation_index}
                        </span>
                        <span className="text-zinc-400">{cit.source_locator}</span>
                        <span className="flex-1 truncate text-zinc-500">
                          {cit.quote_snippet?.slice(0, 80)}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Body markdown */}
              <details className="group">
                <summary className="cursor-pointer text-[10px] font-semibold uppercase tracking-wider text-zinc-500 hover:text-zinc-300">
                  Full Processed Content
                </summary>
                <div className="mt-3 max-h-96 overflow-y-auto rounded-lg border border-zinc-800 bg-zinc-950 p-4">
                  <MarkdownRenderer content={fullDoc.body_markdown ?? ''} />
                </div>
              </details>
            </>
          )}
        </div>
      )}
    </div>
  );
}
