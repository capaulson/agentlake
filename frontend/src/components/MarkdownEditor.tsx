import MDEditor from '@uiw/react-md-editor';

interface MarkdownEditorProps {
  value: string;
  onChange: (value: string) => void;
  height?: number;
}

/**
 * Reusable markdown editor with dark mode and split view (edit + live preview).
 * Wraps @uiw/react-md-editor with AgentLake's dark theme.
 */
export function MarkdownEditor({ value, onChange, height = 500 }: MarkdownEditorProps) {
  return (
    <div data-color-mode="dark">
      <MDEditor
        value={value}
        onChange={(val) => onChange(val ?? '')}
        height={height}
        preview="live"
        visibleDragbar={false}
        style={{
          backgroundColor: 'rgb(24 24 27)', // zinc-900
          borderRadius: '0.75rem',
          border: '1px solid rgb(63 63 70)', // zinc-700
        }}
      />
    </div>
  );
}
