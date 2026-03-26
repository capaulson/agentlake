import { useState, useCallback, type ReactNode } from 'react';
import ReactMarkdown from 'react-markdown';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { oneDark } from 'react-syntax-highlighter/dist/esm/styles/prism';
import { Copy, Check, Link as LinkIcon } from 'lucide-react';
import { cn } from '@/utils/cn';

interface MarkdownRendererProps {
  content: string;
  className?: string;
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = useCallback(async () => {
    await navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }, [text]);

  return (
    <button
      type="button"
      onClick={handleCopy}
      className="absolute right-2 top-2 rounded-md bg-surface-700/80 p-1.5 text-surface-400 opacity-0 transition-all group-hover:opacity-100 hover:bg-surface-600 hover:text-zinc-100"
      aria-label="Copy code"
    >
      {copied ? <Check className="h-3.5 w-3.5 text-emerald-400" /> : <Copy className="h-3.5 w-3.5" />}
    </button>
  );
}

function HeadingAnchor({ id, children }: { id: string; children: ReactNode }) {
  return (
    <a
      href={`#${id}`}
      className="group/anchor inline-flex items-center gap-1.5 no-underline hover:text-primary-400"
    >
      {children}
      <LinkIcon className="h-3.5 w-3.5 text-surface-600 opacity-0 transition-opacity group-hover/anchor:opacity-100" />
    </a>
  );
}

function slugify(text: string): string {
  return text
    .toLowerCase()
    .replace(/[^\w\s-]/g, '')
    .replace(/\s+/g, '-')
    .replace(/-+/g, '-')
    .trim();
}

const CITATION_REGEX = /\[(\d+)\]\(\/api\/v1\/vault\/files\/([^/]+)\/download#chunk=(\d+)\)/g;

function renderCitationBadges(text: string): ReactNode {
  const parts: ReactNode[] = [];
  let lastIndex = 0;
  let match: RegExpExecArray | null;

  const regex = new RegExp(CITATION_REGEX.source, 'g');
  match = regex.exec(text);

  while (match !== null) {
    if (match.index > lastIndex) {
      parts.push(text.slice(lastIndex, match.index));
    }
    const citNum = match[1];
    const fileId = match[2];
    const chunk = match[3];
    parts.push(
      <a
        key={`${fileId}-${chunk}-${match.index}`}
        href={`/api/v1/vault/files/${fileId}/download#chunk=${chunk}`}
        className="mx-0.5 inline-flex h-5 min-w-[20px] items-center justify-center rounded bg-primary-500/15 px-1 text-[10px] font-bold text-primary-400 no-underline transition-colors hover:bg-primary-500/25"
        title={`Citation ${citNum}`}
      >
        {citNum}
      </a>,
    );
    lastIndex = match.index + match[0].length;
    match = regex.exec(text);
  }

  if (lastIndex < text.length) {
    parts.push(text.slice(lastIndex));
  }

  return parts.length > 0 ? <>{parts}</> : text;
}

export function MarkdownRenderer({ content, className }: MarkdownRendererProps) {
  return (
    <div className={cn('prose-dark max-w-none', className)}>
      <ReactMarkdown
        components={{
          h1: ({ children, ...props }) => {
            const text = typeof children === 'string' ? children : String(children);
            const id = slugify(text);
            return (
              <h1 id={id} className="mb-4 mt-8 text-2xl font-bold text-zinc-100" {...props}>
                <HeadingAnchor id={id}>{children}</HeadingAnchor>
              </h1>
            );
          },
          h2: ({ children, ...props }) => {
            const text = typeof children === 'string' ? children : String(children);
            const id = slugify(text);
            return (
              <h2 id={id} className="mb-3 mt-6 text-xl font-semibold text-zinc-100" {...props}>
                <HeadingAnchor id={id}>{children}</HeadingAnchor>
              </h2>
            );
          },
          h3: ({ children, ...props }) => {
            const text = typeof children === 'string' ? children : String(children);
            const id = slugify(text);
            return (
              <h3 id={id} className="mb-2 mt-5 text-lg font-semibold text-zinc-200" {...props}>
                <HeadingAnchor id={id}>{children}</HeadingAnchor>
              </h3>
            );
          },
          h4: ({ children, ...props }) => (
            <h4 className="mb-2 mt-4 text-base font-semibold text-zinc-200" {...props}>{children}</h4>
          ),
          p: ({ children, ...props }) => {
            if (typeof children === 'string') {
              return <p className="mb-4 leading-relaxed text-surface-300" {...props}>{renderCitationBadges(children)}</p>;
            }
            return <p className="mb-4 leading-relaxed text-surface-300" {...props}>{children}</p>;
          },
          a: ({ href, children, ...props }) => (
            <a
              href={href}
              className="text-primary-400 underline decoration-primary-400/30 underline-offset-2 transition-colors hover:text-primary-300 hover:decoration-primary-400/60"
              target={href?.startsWith('http') ? '_blank' : undefined}
              rel={href?.startsWith('http') ? 'noopener noreferrer' : undefined}
              {...props}
            >
              {children}
            </a>
          ),
          ul: ({ children, ...props }) => (
            <ul className="mb-4 list-disc space-y-1 pl-6 text-surface-300" {...props}>{children}</ul>
          ),
          ol: ({ children, ...props }) => (
            <ol className="mb-4 list-decimal space-y-1 pl-6 text-surface-300" {...props}>{children}</ol>
          ),
          li: ({ children, ...props }) => (
            <li className="text-surface-300" {...props}>{children}</li>
          ),
          blockquote: ({ children, ...props }) => (
            <blockquote className="my-4 border-l-4 border-primary-500/40 bg-surface-800/50 py-2 pl-4 pr-3 text-surface-300 italic" {...props}>
              {children}
            </blockquote>
          ),
          code: ({ className: codeClassName, children, ...props }) => {
            const match = /language-(\w+)/.exec(codeClassName ?? '');
            const codeString = String(children).replace(/\n$/, '');

            if (match) {
              return (
                <div className="group relative my-4 overflow-hidden rounded-lg border border-surface-700">
                  <div className="flex items-center justify-between border-b border-surface-700 bg-surface-800/80 px-4 py-2">
                    <span className="text-xs font-medium text-surface-400">{match[1]}</span>
                  </div>
                  <CopyButton text={codeString} />
                  <SyntaxHighlighter
                    style={oneDark}
                    language={match[1]}
                    PreTag="div"
                    customStyle={{
                      margin: 0,
                      borderRadius: 0,
                      background: 'transparent',
                      padding: '1rem',
                    }}
                  >
                    {codeString}
                  </SyntaxHighlighter>
                </div>
              );
            }

            return (
              <code
                className="rounded bg-surface-700/60 px-1.5 py-0.5 font-mono text-[0.85em] text-primary-400"
                {...props}
              >
                {children}
              </code>
            );
          },
          table: ({ children, ...props }) => (
            <div className="my-4 overflow-x-auto rounded-lg border border-surface-700">
              <table className="min-w-full divide-y divide-surface-700" {...props}>
                {children}
              </table>
            </div>
          ),
          thead: ({ children, ...props }) => (
            <thead className="bg-surface-800/50" {...props}>{children}</thead>
          ),
          th: ({ children, ...props }) => (
            <th className="px-4 py-2.5 text-left text-xs font-semibold uppercase tracking-wider text-surface-300" {...props}>
              {children}
            </th>
          ),
          td: ({ children, ...props }) => (
            <td className="px-4 py-2.5 text-sm text-surface-300" {...props}>{children}</td>
          ),
          tr: ({ children, ...props }) => (
            <tr className="border-b border-surface-700/50 last:border-0" {...props}>{children}</tr>
          ),
          hr: (props) => <hr className="my-6 border-surface-700" {...props} />,
          strong: ({ children, ...props }) => (
            <strong className="font-semibold text-zinc-100" {...props}>{children}</strong>
          ),
          em: ({ children, ...props }) => (
            <em className="text-surface-200" {...props}>{children}</em>
          ),
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}
