import { useState } from 'react';
import { Tags, Plus, Trash2, Hash } from 'lucide-react';
import { cn } from '@/utils/cn';
import { useTags, useCreateTag, type TagResponse } from '@/api/vault';
import { Button } from '@/components/ui/Button';
import { Modal } from '@/components/ui/Modal';
import { Spinner } from '@/components/ui/Spinner';

export default function TagsManager() {
  const { data: tagsData, isLoading } = useTags();
  const createTag = useCreateTag();

  const [showCreate, setShowCreate] = useState(false);
  const [newName, setNewName] = useState('');
  const [newColor, setNewColor] = useState('#14b8a6');
  const [deleteConfirm, setDeleteConfirm] = useState<TagResponse | null>(null);

  const allTags: TagResponse[] = tagsData?.data ?? [];

  function getCount(tag: TagResponse): number {
    return tag.file_count ?? 0;
  }

  async function handleCreate() {
    if (!newName.trim()) return;
    await createTag.mutateAsync({ name: newName.trim(), color: newColor });
    setNewName('');
    setShowCreate(false);
  }

  const PRESET_COLORS = [
    '#14b8a6', '#3b82f6', '#f59e0b', '#ef4444', '#a855f7',
    '#22c55e', '#ec4899', '#f97316', '#06b6d4', '#71717a',
  ];

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-24">
        <Spinner size="lg" />
      </div>
    );
  }

  return (
    <div className="space-y-8">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-zinc-100">Tags</h1>
          <p className="mt-1 text-surface-400">
            Manage tags for organizing your documents ({allTags.length} tags)
          </p>
        </div>
        <Button size="sm" onClick={() => setShowCreate(true)}>
          <Plus className="h-4 w-4" />
          New Tag
        </Button>
      </div>

      {/* Tags list */}
      {allTags.length === 0 ? (
        <div className="rounded-xl border border-surface-700 bg-surface-800/50 p-12 text-center">
          <Tags className="mx-auto h-12 w-12 text-surface-600" />
          <p className="mt-4 text-lg font-medium text-zinc-200">No tags yet</p>
          <p className="mt-2 text-sm text-surface-400">
            Create tags to organize your documents
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {allTags.map((tag) => {
            const count = getCount(tag);
            return (
              <div
                key={tag.id}
                className="group flex items-center gap-3 rounded-xl border border-surface-700 bg-surface-800/50 p-4 transition-all hover:border-surface-600"
              >
                <span
                  className="h-4 w-4 shrink-0 rounded-full"
                  style={{ backgroundColor: "#14b8a6" }}
                />
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <Hash className="h-3.5 w-3.5 text-surface-500" />
                    <span className="text-sm font-medium text-zinc-200">{tag.name}</span>
                  </div>
                  <p className="mt-0.5 text-xs text-surface-500">
                    {count} file{count !== 1 ? 's' : ''}
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => setDeleteConfirm(tag)}
                  className="rounded p-1.5 text-surface-500 opacity-0 transition-all group-hover:opacity-100 hover:bg-danger-900/50 hover:text-danger-400"
                  title="Delete tag"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </div>
            );
          })}
        </div>
      )}

      {/* Create modal */}
      <Modal open={showCreate} onClose={() => setShowCreate(false)} title="Create Tag" size="sm">
        <div className="space-y-4">
          <div>
            <label className="mb-1.5 block text-sm font-medium text-zinc-300">Name</label>
            <input
              type="text"
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') void handleCreate();
              }}
              placeholder="Tag name..."
              className="w-full rounded-lg border border-surface-700 bg-surface-800 px-3 py-2 text-sm text-zinc-100 placeholder-surface-500 outline-none focus:border-primary-500"
              autoFocus
            />
          </div>
          <div>
            <label className="mb-1.5 block text-sm font-medium text-zinc-300">Color</label>
            <div className="flex flex-wrap gap-2">
              {PRESET_COLORS.map((color) => (
                <button
                  key={color}
                  type="button"
                  onClick={() => setNewColor(color)}
                  className={cn(
                    'h-7 w-7 rounded-full transition-all',
                    newColor === color && 'ring-2 ring-white ring-offset-2 ring-offset-surface-900',
                  )}
                  style={{ backgroundColor: color }}
                />
              ))}
            </div>
          </div>
          <div className="flex justify-end gap-2 pt-2">
            <Button variant="ghost" size="sm" onClick={() => setShowCreate(false)}>
              Cancel
            </Button>
            <Button
              size="sm"
              onClick={() => void handleCreate()}
              disabled={!newName.trim() || createTag.isPending}
              loading={createTag.isPending}
            >
              Create
            </Button>
          </div>
        </div>
      </Modal>

      {/* Delete confirmation */}
      <Modal
        open={deleteConfirm !== null}
        onClose={() => setDeleteConfirm(null)}
        title="Delete Tag"
        size="sm"
      >
        <div className="space-y-4">
          <p className="text-sm text-surface-300">
            Are you sure you want to delete the tag{' '}
            <strong className="text-zinc-100">{deleteConfirm?.name}</strong>?
            It will be removed from all associated files.
          </p>
          <div className="flex justify-end gap-2">
            <Button variant="ghost" size="sm" onClick={() => setDeleteConfirm(null)}>
              Cancel
            </Button>
            <Button variant="danger" size="sm" onClick={() => setDeleteConfirm(null)}>
              Delete
            </Button>
          </div>
        </div>
      </Modal>
    </div>
  );
}
