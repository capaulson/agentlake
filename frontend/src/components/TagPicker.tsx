import { useState, useRef, useEffect } from 'react';
import { X, Plus } from 'lucide-react';
import { cn } from '@/utils/cn';
import { useTags, useCreateTag, type TagResponse } from '@/api/vault';

interface TagPickerProps {
  selectedIds: string[];
  onChange: (ids: string[]) => void;
  className?: string;
}

export function TagPicker({ selectedIds, onChange, className }: TagPickerProps) {
  const { data: tagsData } = useTags();
  const createTag = useCreateTag();
  const [inputValue, setInputValue] = useState('');
  const [isOpen, setIsOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const allTags: TagResponse[] = tagsData?.data ?? [];
  const selectedTags = allTags.filter((t) => selectedIds.includes(t.id));

  const filteredTags = allTags.filter(
    (t) =>
      !selectedIds.includes(t.id) &&
      t.name.toLowerCase().includes(inputValue.toLowerCase()),
  );

  const canCreateNew =
    inputValue.trim().length > 0 &&
    !allTags.some((t) => t.name.toLowerCase() === inputValue.trim().toLowerCase());

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setIsOpen(false);
      }
    }
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  function addTag(id: string) {
    onChange([...selectedIds, id]);
    setInputValue('');
  }

  function removeTag(id: string) {
    onChange(selectedIds.filter((sid) => sid !== id));
  }

  async function handleCreateTag() {
    const trimmed = inputValue.trim();
    if (!trimmed) return;

    try {
      const result = await createTag.mutateAsync({ name: trimmed });
      onChange([...selectedIds, result.data.id]);
      setInputValue('');
    } catch {
      // Error handled by mutation
    }
  }

  return (
    <div ref={containerRef} className={cn('relative', className)}>
      <div
        className="flex min-h-[38px] flex-wrap items-center gap-1.5 rounded-lg border border-surface-700 bg-surface-800 px-2 py-1.5 transition-colors focus-within:border-primary-500 focus-within:ring-2 focus-within:ring-primary-500/20"
        onClick={() => {
          setIsOpen(true);
          inputRef.current?.focus();
        }}
      >
        {selectedTags.map((tag) => (
          <span
            key={tag.id}
            className="inline-flex items-center gap-1 rounded-full bg-primary-500/15 px-2 py-0.5 text-xs font-medium text-primary-400"
          >
            {tag.name}
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                removeTag(tag.id);
              }}
              className="text-primary-400/60 hover:text-primary-300"
            >
              <X className="h-3 w-3" />
            </button>
          </span>
        ))}
        <input
          ref={inputRef}
          type="text"
          value={inputValue}
          onChange={(e) => {
            setInputValue(e.target.value);
            setIsOpen(true);
          }}
          onFocus={() => setIsOpen(true)}
          placeholder={selectedTags.length === 0 ? 'Select tags...' : ''}
          className="min-w-[80px] flex-1 bg-transparent text-sm text-zinc-100 placeholder-surface-500 outline-none"
        />
      </div>

      {isOpen && (filteredTags.length > 0 || canCreateNew) && (
        <div className="absolute z-20 mt-1 w-full rounded-lg border border-surface-700 bg-surface-800 py-1 shadow-xl">
          <div className="max-h-48 overflow-y-auto">
            {filteredTags.map((tag) => (
              <button
                key={tag.id}
                type="button"
                onClick={() => addTag(tag.id)}
                className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm text-zinc-200 transition-colors hover:bg-surface-700"
              >
                {tag.name && (
                  <span
                    className="h-2.5 w-2.5 rounded-full bg-teal-500"
                  />
                )}
                {tag.name}
              </button>
            ))}
          </div>
          {canCreateNew && (
            <button
              type="button"
              onClick={handleCreateTag}
              disabled={createTag.isPending}
              className="flex w-full items-center gap-2 border-t border-surface-700 px-3 py-2 text-left text-sm text-primary-400 transition-colors hover:bg-surface-700"
            >
              <Plus className="h-3.5 w-3.5" />
              Create &ldquo;{inputValue.trim()}&rdquo;
            </button>
          )}
        </div>
      )}
    </div>
  );
}
