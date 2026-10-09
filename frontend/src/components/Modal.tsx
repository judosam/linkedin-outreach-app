import { useEffect, useRef, type ReactNode } from 'react';
import { X } from 'lucide-react';
import { cn, IconButton } from '@/components/ui';

/* Native <dialog> gives focus trapping, Escape handling, background inertness
   and the top-layer stacking for free — no hand-rolled focus management. */
export function Modal({
  open,
  onClose,
  title,
  children,
  footer,
  size = 'md',
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
  footer?: ReactNode;
  size?: 'sm' | 'md' | 'lg' | 'xl';
}) {
  const ref = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (open && !d.open) d.showModal();
    else if (!open && d.open) d.close();
  }, [open]);

  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    const onCancel = (e: Event) => {
      e.preventDefault();
      onClose();
    };
    d.addEventListener('cancel', onCancel);
    return () => d.removeEventListener('cancel', onCancel);
  }, [onClose]);

  if (!open) return null;

  const width =
    size === 'xl' ? 'max-w-5xl' : size === 'sm' ? 'max-w-md' : size === 'lg' ? 'max-w-3xl' : 'max-w-xl';

  return (
    <dialog
      ref={ref}
      aria-label={title}
      onClose={onClose}
      onClick={(e) => {
        if (e.target === ref.current) onClose();
      }}
      className={cn('cm-dialog flex flex-col overflow-hidden max-h-[90vh] w-[calc(100vw-2rem)]', width)}
    >
      <div className="flex shrink-0 items-start justify-between gap-4 px-5 pt-4 pb-1">
        <h2 className="text-[17px] font-semibold">{title}</h2>
        <IconButton label="Close dialog" onClick={onClose} className="-mr-1 -mt-1">
          <X size={18} aria-hidden />
        </IconButton>
      </div>
      <div
        className={cn(
          'scroll-y flex-1 min-h-0 px-5 py-3.5',
          size === 'sm' && 'max-h-[65vh]',
          size === 'md' && 'max-h-[72vh]',
          size === 'lg' && 'max-h-[76vh]',
          size === 'xl' && 'max-h-[82vh]',
        )}
      >
        {children}
      </div>
      {footer && (
        <div className="flex shrink-0 justify-end gap-2 border-t border-line bg-inset/60 px-5 py-3">{footer}</div>
      )}
    </dialog>
  );
}
