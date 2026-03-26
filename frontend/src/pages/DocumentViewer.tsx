import { useState } from 'react';
import { useParams, Link } from '@tanstack/react-router';
import {
  ArrowLeft,
  Edit3,
  Save,
  X,
  FileText,
  ExternalLink,
  ChevronRight,
  History,
} from 'lucide-react';
import {
  useDocument,
  useDocumentHistory,
  useEditDocument,
  useCitations,
} from '@/api/query';
import { MarkdownEditor } from '@/components/MarkdownEditor';
import { MarkdownRenderer } from '@/components/MarkdownRenderer';
import { DiffViewer } from '@/components/DiffViewer';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Modal } from '@/components/ui/Modal';
import { Spinner } from '@/components/ui/Spinner';
import { formatRelative, formatAbsolute } from '@/utils/formatDate';

export default function DocumentViewer() {
  const { id } = useParams({ from: '/documents/$id' });
  const { data: docData, isLoading } = useDocument(id);
  const { data: historyData } = useDocumentHistory(id);
  const { data: citationsData } = useCitations(id);
  const editMutation = useEditDocument();

  const [isEditing, setIsEditing] = useState(false);
  const [editContent, setEditContent] = useState('');
  const [showJustification, setShowJustification] = useState(false);
  const [justification, setJustification] = useState('');
  const [showMeta, setShowMeta] = useState(true);
  const [showHistory, setShowHistory] = useState(false);

  const doc = docData?.data;
  const history = historyData?.data ?? [];
  const citations = citationsData?.data ?? [];

  function startEdit() {
    if (!doc) return;
    setEditContent(doc.body_markdown ?? '');
    setIsEditing(true);
  }

  function cancelEdit() {
    setIsEditing(false);
    setEditContent('');
  }

  async function handleSave() {
    if (!doc || !justification.trim()) return;

    await editMutation.mutateAsync({
      documentId: doc.id,
      body_markdown: editContent,
      justification: justification.trim(),
    });

    setIsEditing(false);
    setEditContent('');
    setShowJustification(false);
    setJustification('');
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-24">
        <Spinner size="lg" />
      </div>
    );
  }

  if (!doc) {
    return (
      <div className="py-24 text-center">
        <FileText className="mx-auto h-12 w-12 text-surface-600" />
        <p className="mt-4 text-lg text-zinc-200">Document not found</p>
        <Link to="/search" className="mt-2 inline-block text-sm text-primary-400 hover:text-primary-300">
          Back to search
        </Link>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Top bar */}
      <div className="flex items-center justify-between">
        <Link
          to="/search"
          className="flex items-center gap-1.5 text-sm text-surface-400 transition-colors hover:text-zinc-200"
        >
          <ArrowLeft className="h-4 w-4" />
          Back to search
        </Link>
        <div className="flex items-center gap-2">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setShowHistory(!showHistory)}
          >
            <History className="h-4 w-4" />
            History ({history.length})
          </Button>
          {!isEditing ? (
            <Button variant="secondary" size="sm" onClick={startEdit}>
              <Edit3 className="h-4 w-4" />
              Edit
            </Button>
          ) : (
            <>
              <Button variant="ghost" size="sm" onClick={cancelEdit}>
                <X className="h-4 w-4" />
                Cancel
              </Button>
              <Button
                size="sm"
                onClick={() => setShowJustification(true)}
                disabled={editContent === (doc.body_markdown ?? '')}
              >
                <Save className="h-4 w-4" />
                Save
              </Button>
            </>
          )}
        </div>
      </div>

      {/* Main layout */}
      <div className="flex gap-6">
        {/* Content area */}
        <div className="min-w-0 flex-1">
          {/* Title */}
          <div className="mb-6">
            <div className="flex items-center gap-3">
              <h1 className="text-2xl font-bold text-zinc-100">{doc.title}</h1>
              <Badge
                variant={
                  doc.category === 'technical'
                    ? 'info'
                    : doc.category === 'business'
                      ? 'warning'
                      : 'default'
                }
              >
                {doc.category}
              </Badge>
            </div>
            <p className="mt-2 text-sm text-surface-400">{doc.summary}</p>
          </div>

          {/* Edit mode / View mode */}
          {isEditing ? (
            <MarkdownEditor
              value={editContent}
              onChange={setEditContent}
              height={600}
            />
          ) : (
            <div className="rounded-xl border border-surface-700 bg-surface-800/50 p-6">
              <MarkdownRenderer content={doc.body_markdown ?? ''} />
            </div>
          )}

          {/* Citations */}
          {citations.length > 0 && (
            <div className="mt-6 rounded-xl border border-surface-700 bg-surface-800/50 p-5">
              <h3 className="mb-3 text-base font-semibold text-zinc-100">
                Citations ({citations.length})
              </h3>
              <div className="space-y-2">
                {citations.map((cit) => (
                  <a
                    key={`${cit.source_file_id}-${cit.chunk_index}`}
                    href={cit.download_url ?? '#'}
                    className="flex items-start gap-3 rounded-lg p-2 transition-colors hover:bg-surface-800"
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded bg-primary-500/15 text-xs font-bold text-primary-400">
                      {cit.citation_index}
                    </span>
                    <div className="min-w-0 flex-1">
                      <p className="line-clamp-2 text-sm text-zinc-300">{cit.quote_snippet}</p>
                      <p className="mt-1 text-xs text-zinc-500">
                        Chunk {cit.chunk_index} &middot; {cit.source_locator} &middot; File {cit.source_file_id?.slice(0, 8)}...
                      </p>
                    </div>
                    <ExternalLink className="h-3.5 w-3.5 shrink-0 text-surface-500" />
                  </a>
                ))}
              </div>
            </div>
          )}

          {/* Version history */}
          {showHistory && history.length > 0 && (
            <div className="mt-6 space-y-3">
              <h3 className="text-base font-semibold text-zinc-100">Version History</h3>
              {history.map((entry) => (
                <DiffViewer key={entry.id} entry={entry} />
              ))}
            </div>
          )}
          {showHistory && history.length === 0 && (
            <div className="mt-6 rounded-lg border border-surface-700 bg-surface-800/50 p-6 text-center text-sm text-surface-400">
              No edit history
            </div>
          )}
        </div>

        {/* Metadata sidebar */}
        {showMeta && (
          <div className="w-72 shrink-0">
            <div className="sticky top-0 space-y-4">
              <div className="rounded-xl border border-surface-700 bg-surface-800/50 p-4">
                <div className="flex items-center justify-between mb-3">
                  <h3 className="text-sm font-semibold text-zinc-100">Metadata</h3>
                  <button
                    type="button"
                    onClick={() => setShowMeta(false)}
                    className="text-surface-400 hover:text-zinc-200"
                  >
                    <X className="h-4 w-4" />
                  </button>
                </div>

                <div className="space-y-3 text-sm">
                  <div>
                    <p className="text-xs text-surface-500">Category</p>
                    <p className="mt-0.5 capitalize text-zinc-200">{doc.category}</p>
                  </div>
                  <div>
                    <p className="text-xs text-surface-500">Version</p>
                    <p className="mt-0.5 text-zinc-200">v{doc.version}</p>
                  </div>
                  <div>
                    <p className="text-xs text-surface-500">Created</p>
                    <p className="mt-0.5 text-zinc-200">{formatAbsolute(doc.created_at)}</p>
                  </div>
                  <div>
                    <p className="text-xs text-surface-500">Updated</p>
                    <p className="mt-0.5 text-zinc-200">{formatRelative(doc.updated_at)}</p>
                  </div>
                  <div>
                    <p className="text-xs text-surface-500">Source File</p>
                    <Link
                      to="/vault"
                      className="mt-0.5 flex items-center gap-1 text-primary-400 hover:text-primary-300"
                    >
                      <FileText className="h-3.5 w-3.5" />
                      {doc.source_file_id?.slice(0, 8)}...
                    </Link>
                  </div>
                </div>
              </div>

              {/* Category */}
              <div className="rounded-xl border border-zinc-800 bg-zinc-900/50 p-4">
                <h3 className="mb-2 text-sm font-semibold text-zinc-100">Category</h3>
                <Badge variant="info">{doc.category}</Badge>
              </div>

              {/* Entities */}
              {(doc.entities ?? []).length > 0 && (
                <div className="rounded-xl border border-surface-700 bg-surface-800/50 p-4">
                  <h3 className="mb-2 text-sm font-semibold text-zinc-100">
                    Entities ({(doc.entities ?? []).length})
                  </h3>
                  <div className="space-y-1.5">
                    {(doc.entities ?? []).map((entity, idx) => (
                      <Link
                        key={`${entity.name}-${idx}`}
                        to="/graph"
                        className="flex items-center gap-2 rounded-md px-2 py-1 text-sm transition-colors hover:bg-surface-800"
                      >
                        <span className="text-xs capitalize text-surface-500">{entity.type}</span>
                        <span className="text-zinc-200">{entity.name}</span>
                      </Link>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>
        )}

        {/* Show sidebar toggle when hidden */}
        {!showMeta && (
          <button
            type="button"
            onClick={() => setShowMeta(true)}
            className="fixed right-4 top-24 rounded-lg border border-surface-700 bg-surface-800 p-2 text-surface-400 shadow-lg transition-colors hover:text-zinc-100"
            title="Show metadata"
          >
            <ChevronRight className="h-4 w-4 rotate-180" />
          </button>
        )}
      </div>

      {/* Justification modal */}
      <Modal
        open={showJustification}
        onClose={() => setShowJustification(false)}
        title="Save Edit"
      >
        <div className="space-y-4">
          <p className="text-sm text-surface-300">
            Provide a justification for this edit. This will be recorded in the diff log.
          </p>
          <textarea
            value={justification}
            onChange={(e) => setJustification(e.target.value)}
            placeholder="Why are you making this change?"
            className="w-full resize-none rounded-lg border border-surface-700 bg-surface-800 p-3 text-sm text-zinc-100 placeholder-surface-500 outline-none focus:border-primary-500"
            rows={3}
          />
          <div className="flex justify-end gap-2">
            <Button variant="ghost" size="sm" onClick={() => setShowJustification(false)}>
              Cancel
            </Button>
            <Button
              size="sm"
              onClick={() => void handleSave()}
              disabled={!justification.trim() || editMutation.isPending}
              loading={editMutation.isPending}
            >
              Save Changes
            </Button>
          </div>
        </div>
      </Modal>
    </div>
  );
}
