import { type ReactNode } from 'react';
import { cn } from '../../utils/cn';

export interface CardProps {
  title?: string | null;
  className?: string;
  children: ReactNode;
  actions?: ReactNode;
}

export function Card({ title, className, children, actions }: CardProps) {
  return (
    <div
      className={cn(
        'rounded-xl border border-zinc-800 bg-zinc-900',
        className,
      )}
    >
      {(title || actions) && (
        <div className="flex items-center justify-between border-b border-zinc-800 px-6 py-4">
          {title && (
            <h3 className="text-lg font-semibold text-zinc-100">{title}</h3>
          )}
          {actions && <div className="flex items-center gap-2">{actions}</div>}
        </div>
      )}
      <div className="px-6 py-4">{children}</div>
    </div>
  );
}
