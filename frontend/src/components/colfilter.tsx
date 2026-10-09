import { useEffect, useId, useLayoutEffect, useRef, useState, type RefObject } from 'react';
import { createPortal } from 'react-dom';
import { ListFilter } from 'lucide-react';
import { Button, cn } from '@/components/ui';
import { Field, Input } from '@/components/form';

export type FilterSpec =
  | { kind: 'values'; options: { value: string; label: string }[]; multi: boolean }
  | { kind: 'text'; placeholder: string; hint?: string; suggestions?: string[] }
  | { kind: 'range'; fromLabel: string; toLabel: string };

export function localDayISO(value: string, end = false) {
  if (!value) return '';
  const date = new Date(`${value}T${end ? '23:59:59.999' : '00:00:00'}`);
  return Number.isNaN(date.getTime()) ? '' : date.toISOString();
}

/** Shared editor; callers own the draft and decide when it is committed. */
export function FilterFields({
  label,
  spec,
  value,
  onChange,
}: {
  label: string;
  spec: FilterSpec;
  value: string[];
  onChange: (v: string[]) => void;
}) {
  const [search, setSearch] = useState('');
  const id = useId();
  if (spec.kind === 'range')
    return (
      <div className="grid grid-cols-2 gap-2">
        <Field label={spec.fromLabel}>
          <Input
            type="date"
            aria-label={`${label} from`}
            value={value[0] || ''}
            max={value[1] || undefined}
            onChange={(e) => onChange([e.target.value, value[1] || ''])}
          />
        </Field>
        <Field label={spec.toLabel}>
          <Input
            type="date"
            aria-label={`${label} to`}
            value={value[1] || ''}
            min={value[0] || undefined}
            onChange={(e) => onChange([value[0] || '', e.target.value])}
          />
        </Field>
      </div>
    );
  if (spec.kind === 'text')
    return (
      <Field label={label} hint={spec.hint}>
        <Input
          aria-label={`${label} contains`}
          placeholder={spec.placeholder}
          value={value[0] || ''}
          list={spec.suggestions?.length ? id : undefined}
          onChange={(e) => onChange([e.target.value])}
        />
        {!!spec.suggestions?.length && (
          <datalist id={id}>
            {spec.suggestions.map((v) => (
              <option key={v} value={v} />
            ))}
          </datalist>
        )}
      </Field>
    );
  const visible = spec.options.filter((o) => o.label.toLowerCase().includes(search.toLowerCase()));
  return (
    <div className="flex flex-col gap-2">
      <Input
        type="search"
        aria-label={`Search ${label} options`}
        placeholder="Search options…"
        value={search}
        onChange={(e) => setSearch(e.target.value)}
      />
      <div className="flex gap-3 text-xs text-primary">
        {spec.multi && (
          <button type="button" onClick={() => onChange(spec.options.map((o) => o.value))}>
            Select all
          </button>
        )}
        {!spec.multi && (
          <button type="button" onClick={() => onChange([])}>
            All values
          </button>
        )}
        <button type="button" onClick={() => onChange([])}>
          Clear
        </button>
      </div>
      <div className="max-h-[200px] overflow-y-auto">
        {visible.map((o) => (
          <label
            key={o.value}
            className="flex cursor-pointer items-center gap-2 rounded-md px-1 py-1.5 text-[13px] hover:bg-inset"
          >
            <input
              type="checkbox"
              checked={value.includes(o.value)}
              onChange={(e) =>
                onChange(
                  e.target.checked
                    ? spec.multi
                      ? [...value, o.value]
                      : [o.value]
                    : value.filter((v) => v !== o.value),
                )
              }
            />
            {o.label}
          </label>
        ))}
        {!visible.length && <p className="py-2 text-xs text-muted">No matching options</p>}
      </div>
    </div>
  );
}

interface ExtraFilter {
  label: string;
  spec: FilterSpec;
  value: string[];
  onApply: (v: string[]) => void;
}
interface Props {
  label: string;
  spec: FilterSpec;
  value: string[];
  open: boolean;
  onOpen: (open: boolean) => void;
  onApply: (v: string[]) => void;
  extra?: ExtraFilter;
}
export function ColumnFilter(props: Props) {
  const trigger = useRef<HTMLButtonElement>(null);
  const active = props.value.some(Boolean) || props.extra?.value.some(Boolean);
  return (
    <>
      <button
        ref={trigger}
        type="button"
        className={cn('column-filter', active && 'is-active')}
        aria-label={`Filter by ${props.label}`}
        title={`Filter by ${props.label}`}
        aria-haspopup="dialog"
        aria-expanded={props.open}
        onClick={() => props.onOpen(!props.open)}
      >
        <ListFilter size={12} aria-hidden />
        {active && <span className="filter-dot" />}
      </button>
      {props.open && <FilterPopover {...props} trigger={trigger} />}
    </>
  );
}

// Portalling prevents the table's horizontal scroll container from clipping
// the panel. Position follows its header and clamps to the viewport.
function FilterPopover({ trigger, ...props }: Props & { trigger: RefObject<HTMLButtonElement> }) {
  const panel = useRef<HTMLDivElement>(null);
  const [draft, setDraft] = useState(props.value);
  const [extra, setExtra] = useState(props.extra?.value ?? []);
  const [position, setPosition] = useState({ left: 0, top: 0 });
  const close = useRef(() => props.onOpen(false));
  close.current = () => props.onOpen(false);
  useLayoutEffect(() => {
    const place = () => {
      const rect = trigger.current?.getBoundingClientRect();
      if (!rect) return;
      const height = panel.current?.offsetHeight ?? 300;
      setPosition({
        left: Math.max(8, Math.min(rect.left, window.innerWidth - 336)),
        top: Math.max(8, Math.min(rect.bottom + 6, window.innerHeight - height - 8)),
      });
    };
    place();
    window.addEventListener('resize', place);
    window.addEventListener('scroll', place, true);
    return () => {
      window.removeEventListener('resize', place);
      window.removeEventListener('scroll', place, true);
    };
  }, [trigger]);
  useEffect(() => {
    panel.current?.querySelector<HTMLElement>('input,button')?.focus();
    const outside = (e: MouseEvent) => {
      if (!panel.current?.contains(e.target as Node) && !trigger.current?.contains(e.target as Node))
        close.current();
    };
    document.addEventListener('mousedown', outside);
    return () => {
      document.removeEventListener('mousedown', outside);
      trigger.current?.focus();
    };
  }, [trigger]);
  const invalidRange = props.spec.kind === 'range' && !!draft[0] && !!draft[1] && draft[0] > draft[1];
  return createPortal(
    <div
      ref={panel}
      role="dialog"
      aria-label={`Filter ${props.label}`}
      style={position}
      className="filter-popover surface fixed z-30 w-[320px] max-w-[calc(100vw-16px)] rounded-panel border border-line p-3 shadow-pop"
      onKeyDown={(e) => {
        if (e.key === 'Escape') {
          e.preventDefault();
          e.stopPropagation();
          close.current();
        }
        if (e.key === 'Tab') {
          const nodes = [
            ...(panel.current?.querySelectorAll<HTMLElement>(
              'input:not(:disabled),button:not(:disabled),select',
            ) ?? []),
          ];
          const first = nodes[0],
            last = nodes[nodes.length - 1];
          if (e.shiftKey && document.activeElement === first) {
            e.preventDefault();
            last?.focus();
          }
          if (!e.shiftKey && document.activeElement === last) {
            e.preventDefault();
            first?.focus();
          }
        }
      }}
    >
      <h3 className="mb-3 text-sm">Filter {props.label}</h3>
      <FilterFields label={props.label} spec={props.spec} value={draft} onChange={setDraft} />
      {props.extra && (
        <div className="mt-3 border-t border-line pt-3">
          <h4 className="mb-2 text-xs">{props.extra.label}</h4>
          <FilterFields label={props.extra.label} spec={props.extra.spec} value={extra} onChange={setExtra} />
        </div>
      )}
      {invalidRange && (
        <p role="alert" className="mt-2 text-xs text-crit">
          The end date must follow the start date.
        </p>
      )}
      <div className="mt-3 flex justify-end gap-2 border-t border-line pt-3">
        <Button size="sm" onClick={() => close.current()} isStatic>
          Cancel
        </Button>
        <Button
          size="sm"
          variant="primary"
          disabled={invalidRange}
          onClick={() => {
            props.onApply(draft);
            props.extra?.onApply(extra);
            close.current();
          }}
          isStatic
        >
          Apply
        </Button>
      </div>
    </div>,
    document.body,
  );
}
