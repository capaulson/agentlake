import { useState, useRef, useCallback } from 'react';
import { CloudUpload, Upload, X, FileText, Tag } from 'lucide-react';
import { cn } from '@/utils/cn';
import { useUploadFile } from '@/api/vault';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { formatBytes } from '@/utils/formatBytes';

interface QueuedFile {
  file: File;
  id: string;
  progress: number;
  status: 'queued' | 'uploading' | 'done' | 'error';
  error?: string;
}

interface FileUploadProps {
  onUploadComplete?: (fileId: string) => void;
  className?: string;
}

const SUPPORTED_FORMATS = [
  'PDF', 'DOCX', 'TXT', 'MD', 'HTML', 'CSV', 'JSON', 'XLSX',
];

export function FileUpload({ onUploadComplete, className }: FileUploadProps) {
  const [queuedFiles, setQueuedFiles] = useState<QueuedFile[]>([]);
  const [isDragOver, setIsDragOver] = useState(false);
  const [tags, setTags] = useState<string[]>([]);
  const [tagInput, setTagInput] = useState('');
  const fileInputRef = useRef<HTMLInputElement>(null);
  const uploadMutation = useUploadFile();

  const addFiles = useCallback((files: FileList | File[]) => {
    const newFiles: QueuedFile[] = Array.from(files).map((file) => ({
      file,
      id: `${file.name}-${Date.now()}-${Math.random().toString(36).slice(2)}`,
      progress: 0,
      status: 'queued' as const,
    }));
    setQueuedFiles((prev) => [...prev, ...newFiles]);
  }, []);

  function handleDragOver(e: React.DragEvent) {
    e.preventDefault();
    setIsDragOver(true);
  }

  function handleDragLeave(e: React.DragEvent) {
    e.preventDefault();
    setIsDragOver(false);
  }

  function handleDrop(e: React.DragEvent) {
    e.preventDefault();
    setIsDragOver(false);
    if (e.dataTransfer.files.length > 0) {
      addFiles(e.dataTransfer.files);
    }
  }

  function handleFileSelect(e: React.ChangeEvent<HTMLInputElement>) {
    if (e.target.files && e.target.files.length > 0) {
      addFiles(e.target.files);
      e.target.value = '';
    }
  }

  function removeFile(id: string) {
    setQueuedFiles((prev) => prev.filter((f) => f.id !== id));
  }

  function addTag() {
    const trimmed = tagInput.trim();
    if (trimmed && !tags.includes(trimmed)) {
      setTags((prev) => [...prev, trimmed]);
      setTagInput('');
    }
  }

  function removeTag(tag: string) {
    setTags((prev) => prev.filter((t) => t !== tag));
  }

  function handleTagKeyDown(e: React.KeyboardEvent) {
    if (e.key === 'Enter') {
      e.preventDefault();
      addTag();
    }
  }

  async function uploadAll() {
    const pending = queuedFiles.filter((f) => f.status === 'queued');
    for (const qf of pending) {
      setQueuedFiles((prev) =>
        prev.map((f) => (f.id === qf.id ? { ...f, status: 'uploading' as const, progress: 50 } : f)),
      );

      const formData = new FormData();
      formData.append('file', qf.file);
      if (tags.length > 0) {
        formData.append('tags', tags.join(','));
      }

      try {
        const result = await uploadMutation.mutateAsync(formData);
        setQueuedFiles((prev) =>
          prev.map((f) =>
            f.id === qf.id ? { ...f, status: 'done' as const, progress: 100 } : f,
          ),
        );
        onUploadComplete?.(result.data.file.id);
      } catch (err) {
        const message = err instanceof Error ? err.message : 'Upload failed';
        setQueuedFiles((prev) =>
          prev.map((f) =>
            f.id === qf.id ? { ...f, status: 'error' as const, error: message } : f,
          ),
        );
      }
    }
  }

  const hasQueued = queuedFiles.some((f) => f.status === 'queued');
  const isUploading = queuedFiles.some((f) => f.status === 'uploading');

  return (
    <div className={cn('space-y-4', className)}>
      {/* Drop zone */}
      <div
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        onClick={() => fileInputRef.current?.click()}
        className={cn(
          'cursor-pointer rounded-xl border-2 border-dashed p-12 text-center transition-all',
          isDragOver
            ? 'border-primary-500 bg-primary-500/5'
            : 'border-surface-600 bg-surface-800/30 hover:border-primary-500/50',
        )}
      >
        <CloudUpload
          className={cn(
            'mx-auto h-14 w-14 transition-colors',
            isDragOver ? 'text-primary-500' : 'text-surface-500',
          )}
        />
        <p className="mt-4 text-lg font-medium text-zinc-200">
          {isDragOver ? 'Drop files here' : 'Drag and drop files here'}
        </p>
        <p className="mt-2 text-sm text-surface-400">or click to browse</p>
        <div className="mt-4 flex flex-wrap justify-center gap-1.5">
          {SUPPORTED_FORMATS.map((fmt) => (
            <Badge key={fmt} variant="default" className="text-[10px]">
              {fmt}
            </Badge>
          ))}
        </div>
        <input
          ref={fileInputRef}
          type="file"
          multiple
          onChange={handleFileSelect}
          className="hidden"
        />
      </div>

      {/* Tag input */}
      <div className="space-y-2">
        <label className="flex items-center gap-2 text-sm font-medium text-zinc-300">
          <Tag className="h-4 w-4" />
          Batch Tags
        </label>
        <div className="flex flex-wrap items-center gap-2 rounded-lg border border-surface-700 bg-surface-800 p-2">
          {tags.map((tag) => (
            <span
              key={tag}
              className="inline-flex items-center gap-1 rounded-full bg-primary-500/15 px-2.5 py-0.5 text-xs font-medium text-primary-400"
            >
              {tag}
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  removeTag(tag);
                }}
                className="ml-0.5 text-primary-400/60 hover:text-primary-300"
              >
                <X className="h-3 w-3" />
              </button>
            </span>
          ))}
          <input
            type="text"
            value={tagInput}
            onChange={(e) => setTagInput(e.target.value)}
            onKeyDown={handleTagKeyDown}
            onBlur={addTag}
            placeholder={tags.length === 0 ? 'Add tags...' : ''}
            className="min-w-[100px] flex-1 bg-transparent text-sm text-zinc-100 placeholder-surface-500 outline-none"
          />
        </div>
      </div>

      {/* Queued files */}
      {queuedFiles.length > 0 && (
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-medium text-zinc-300">
              Files ({queuedFiles.length})
            </h3>
            {hasQueued && (
              <Button
                size="sm"
                onClick={uploadAll}
                loading={isUploading}
                disabled={isUploading}
              >
                <Upload className="h-4 w-4" />
                Upload All
              </Button>
            )}
          </div>
          <div className="max-h-80 space-y-1 overflow-y-auto">
            {queuedFiles.map((qf) => (
              <div
                key={qf.id}
                className="flex items-center gap-3 rounded-lg border border-surface-700 bg-surface-800/50 px-3 py-2"
              >
                <FileText className="h-4 w-4 shrink-0 text-surface-400" />
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm text-zinc-200">{qf.file.name}</p>
                  <p className="text-xs text-surface-500">
                    {formatBytes(qf.file.size)} &middot; {qf.file.type || 'unknown'}
                  </p>
                </div>
                {qf.status === 'uploading' && (
                  <div className="h-1.5 w-20 overflow-hidden rounded-full bg-surface-700">
                    <div
                      className="h-full rounded-full bg-primary-500 transition-all"
                      style={{ width: `${qf.progress}%` }}
                    />
                  </div>
                )}
                {qf.status === 'done' && (
                  <Badge variant="success">Done</Badge>
                )}
                {qf.status === 'error' && (
                  <Badge variant="danger" className="max-w-[120px] truncate">
                    {qf.error ?? 'Error'}
                  </Badge>
                )}
                {qf.status === 'queued' && (
                  <button
                    type="button"
                    onClick={() => removeFile(qf.id)}
                    className="rounded p-1 text-surface-400 transition-colors hover:text-zinc-100"
                  >
                    <X className="h-4 w-4" />
                  </button>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
