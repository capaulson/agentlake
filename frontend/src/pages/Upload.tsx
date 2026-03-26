import { useState } from 'react';
import { Upload as UploadIcon, FileText, CheckCircle } from 'lucide-react';
import { useFiles } from '@/api/vault';
import { FileUpload } from '@/components/FileUpload';
import { ProcessingProgress } from '@/components/ProcessingProgress';
import { Badge } from '@/components/ui/Badge';
import { formatBytes } from '@/utils/formatBytes';
import { formatRelative } from '@/utils/formatDate';

export default function Upload() {
  const [uploadedFileIds, setUploadedFileIds] = useState<string[]>([]);
  const [activeFileId, setActiveFileId] = useState<string | null>(null);

  const { data: recentData } = useFiles({
    limit: 10,
    sort_by: 'created_at',
    sort_order: 'desc',
  });

  const recentFiles = recentData?.data ?? [];

  function handleUploadComplete(fileId: string) {
    setUploadedFileIds((prev) => [fileId, ...prev]);
    setActiveFileId(fileId);
  }

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-bold text-zinc-100">Upload</h1>
        <p className="mt-1 text-surface-400">
          Upload files to the data lake for processing
        </p>
      </div>

      {/* File upload */}
      <FileUpload onUploadComplete={handleUploadComplete} />

      {/* Processing progress for uploaded files */}
      {uploadedFileIds.length > 0 && (
        <div className="space-y-4">
          <h2 className="text-lg font-semibold text-zinc-100">Processing Status</h2>
          <div className="space-y-3">
            {uploadedFileIds.map((fid) => (
              <div key={fid}>
                <div className="mb-1 flex items-center gap-2">
                  <FileText className="h-4 w-4 text-surface-400" />
                  <span className="font-mono text-xs text-surface-400">
                    {fid?.slice(0, 12) ?? fid}...
                  </span>
                  {fid === activeFileId && (
                    <Badge variant="info">Active</Badge>
                  )}
                </div>
                <ProcessingProgress fileId={fid} />
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Recent uploads */}
      <div>
        <h2 className="mb-4 text-lg font-semibold text-zinc-100">Recently Uploaded</h2>
        {recentFiles.length === 0 ? (
          <div className="rounded-xl border border-surface-700 bg-surface-800/50 p-8 text-center">
            <UploadIcon className="mx-auto h-10 w-10 text-surface-600" />
            <p className="mt-3 text-sm text-surface-400">
              No files uploaded yet
            </p>
          </div>
        ) : (
          <div className="rounded-xl border border-surface-700 bg-surface-800/50">
            <div className="divide-y divide-surface-700/50">
              {recentFiles.map((file) => (
                <div
                  key={file.id}
                  className="flex items-center gap-4 px-5 py-3 transition-colors hover:bg-surface-800/30"
                >
                  <FileText className="h-4 w-4 shrink-0 text-surface-400" />
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm text-zinc-200">{file.filename}</p>
                    <p className="text-xs text-surface-500">
                      {formatBytes(file.size_bytes)} &middot; {file.content_type} &middot; {formatRelative(file.created_at)}
                    </p>
                  </div>
                  <div className="flex items-center gap-2">
                    {(file.tags ?? []).length > 0 && (
                      <div className="flex gap-1">
                        {(file.tags ?? []).slice(0, 2).map((tag) => (
                          <Badge key={tag.id} variant="default" className="text-[10px]">
                            {tag.name}
                          </Badge>
                        ))}
                      </div>
                    )}
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
                      {file.status === 'processed' && (
                        <CheckCircle className="mr-1 inline h-3 w-3" />
                      )}
                      {file.status}
                    </Badge>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
