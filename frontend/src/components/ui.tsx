import { createContext, useCallback, useContext, useEffect, useId, useRef, useState, type ReactNode } from "react";
import { AlertTriangle, CheckCircle2, Info, Loader2, X, XCircle } from "lucide-react";

export function cx(...c: Array<string | false | null | undefined>) {
  return c.filter(Boolean).join(" ");
}

// ---- buttons ------------------------------------------------------------------------------------
type BtnVariant = "primary" | "secondary" | "ghost" | "danger" | "quiet";
const BTN: Record<BtnVariant, string> = {
  primary: "bg-velvet text-white hover:bg-velvet-700 border border-velvet-700/40 shadow-[0_1px_0_rgb(255_255_255/0.12)_inset]",
  secondary: "bg-surface text-ink border border-line-strong hover:border-steel-2 hover:bg-wash/60",
  ghost: "bg-transparent text-ink-2 hover:bg-wash border border-transparent",
  danger: "bg-danger text-white hover:brightness-95 border border-danger",
  quiet: "bg-transparent text-velvet hover:underline underline-offset-4 border border-transparent px-0!",
};

export function Button({
  variant = "secondary", size = "md", loading, icon, children, className, ...rest
}: React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: BtnVariant; size?: "sm" | "md" | "lg"; loading?: boolean; icon?: ReactNode;
}) {
  const sizes = { sm: "h-8 px-2.5 text-[13px] gap-1.5", md: "h-9 px-3.5 text-[13.5px] gap-2", lg: "h-11 px-5 text-[14.5px] gap-2" };
  return (
    <button
      {...rest}
      disabled={rest.disabled || loading}
      className={cx(
        "inline-flex items-center justify-center rounded-md font-medium whitespace-nowrap transition-colors",
        "disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer select-none",
        BTN[variant], sizes[size], className,
      )}
    >
      {loading ? <Loader2 className="size-4 animate-spin" aria-hidden /> : icon}
      {children}
    </button>
  );
}

// ---- pills --------------------------------------------------------------------------------------
export type Tone = "neutral" | "velvet" | "velvetSolid" | "brass" | "brassSolid" | "danger" | "info" | "ink" | "muted";
const TONES: Record<Tone, string> = {
  neutral: "bg-wash text-ink-2 border-line",
  velvet: "bg-velvet-50 text-velvet border-velvet-100",
  velvetSolid: "bg-velvet text-white border-velvet",
  brass: "bg-brass-50 text-brass border-brass-100",
  brassSolid: "bg-brass text-white border-brass",
  danger: "bg-danger-50 text-danger border-danger/20",
  info: "bg-info-50 text-info border-info/20",
  ink: "bg-ink text-white border-ink",
  muted: "bg-transparent text-steel border-line",
};

export function Pill({ tone = "neutral", children, dot, className, title }: {
  tone?: Tone; children: ReactNode; dot?: boolean; className?: string; title?: string;
}) {
  return (
    <span title={title} className={cx("inline-flex items-center gap-1.5 rounded-full border px-2 py-[1px] text-[12px] font-medium leading-5 whitespace-nowrap", TONES[tone], className)}>
      {dot && <span className="size-1.5 rounded-full bg-current opacity-80" aria-hidden />}
      {children}
    </span>
  );
}

export const STATUS_TONE: Record<string, Tone> = {
  draft: "neutral", processing: "info", awaiting_review: "brass", approved: "velvet", published: "velvetSolid",
  reserved: "brassSolid", sold: "ink", withdrawn: "muted",
};

export function StatusPill({ status, label }: { status: string; label?: string }) {
  return <Pill tone={STATUS_TONE[status] ?? "neutral"} dot>{label ?? status.replace("_", " ")}</Pill>;
}

export const SAFETY_TONE: Record<string, Tone> = {
  pending: "neutral", clear: "velvet", reviewed: "velvet", needs_review: "brass", ocr_unavailable: "brass", failed: "danger",
};

export const LISTING_TONE: Record<string, Tone> = {
  not_started: "muted", queued: "info", publishing: "info", update_pending: "info", live: "velvetSolid",
  simulated: "info", manual_pending: "brass", manual_posted: "velvet", reserved: "brass", sold: "ink",
  withdrawn: "muted", failed: "danger", sync_failed: "danger",
};

export const JOB_TONE: Record<string, Tone> = {
  pending: "neutral", running: "info", completed: "velvet", failed: "danger", cancelled: "muted",
};

// ---- layout bits --------------------------------------------------------------------------------
export function Panel({ children, className, pad = true }: { children: ReactNode; className?: string; pad?: boolean }) {
  return <section className={cx("panel", pad && "p-5", className)}>{children}</section>;
}

export function PanelHeader({ title, sub, actions, className }: { title: ReactNode; sub?: ReactNode; actions?: ReactNode; className?: string }) {
  return (
    <div className={cx("flex flex-wrap items-start justify-between gap-3 mb-4", className)}>
      <div className="min-w-0">
        <h2 className="text-[15.5px] font-semibold text-ink">{title}</h2>
        {sub && <p className="text-[13px] text-steel mt-0.5">{sub}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

export function PageHeader({ title, sub, actions, eyebrow }: { title: ReactNode; sub?: ReactNode; actions?: ReactNode; eyebrow?: ReactNode }) {
  return (
    <header className="flex flex-wrap items-end justify-between gap-4 mb-7">
      <div className="min-w-0">
        {eyebrow && <div className="text-[13px] text-steel mb-1">{eyebrow}</div>}
        <h1 className="font-display text-[34px] leading-[1.08] text-ink">{title}</h1>
        {sub && <p className="text-[14px] text-steel mt-1.5 max-w-[68ch]">{sub}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </header>
  );
}

export function Notice({ tone = "info", title, children, action, className }: {
  tone?: "info" | "warning" | "danger" | "success"; title?: ReactNode; children?: ReactNode; action?: ReactNode; className?: string;
}) {
  const map = {
    info: { cls: "bg-info-50 border-info/20 text-ink", icon: <Info className="size-4 text-info" /> },
    warning: { cls: "bg-brass-50 border-brass-100 text-ink", icon: <AlertTriangle className="size-4 text-brass" /> },
    danger: { cls: "bg-danger-50 border-danger/20 text-ink", icon: <XCircle className="size-4 text-danger" /> },
    success: { cls: "bg-velvet-50 border-velvet-100 text-ink", icon: <CheckCircle2 className="size-4 text-velvet" /> },
  }[tone];
  return (
    <div className={cx("flex gap-3 rounded-lg border px-3.5 py-3 text-[13.5px]", map.cls, className)} role={tone === "danger" ? "alert" : undefined}>
      <div className="pt-0.5 shrink-0">{map.icon}</div>
      <div className="min-w-0 flex-1">
        {title && <div className="font-semibold mb-0.5">{title}</div>}
        {children && <div className="text-ink-2">{children}</div>}
      </div>
      {action && <div className="shrink-0 self-center">{action}</div>}
    </div>
  );
}

export function Empty({ icon, title, children, action }: { icon?: ReactNode; title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center text-center py-12 px-6">
      {icon && <div className="mb-3 text-steel-2">{icon}</div>}
      <div className="font-display text-[22px] text-ink">{title}</div>
      {children && <p className="text-steel text-[13.5px] mt-1.5 max-w-[52ch]">{children}</p>}
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}

export function Spinner({ className }: { className?: string }) {
  return <Loader2 className={cx("size-4 animate-spin text-steel", className)} aria-label="Loading" />;
}

export function Loading({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 text-steel text-[13.5px] py-10 justify-center">
      <Spinner /> {label}
    </div>
  );
}

export function Progress({ value, indeterminate, tone = "velvet", className }: { value?: number; indeterminate?: boolean; tone?: "velvet" | "info" | "brass"; className?: string }) {
  const bar = { velvet: "bg-velvet", info: "bg-info", brass: "bg-brass" }[tone];
  return (
    <div className={cx("h-1.5 w-full rounded-full bg-wash overflow-hidden", className)} role="progressbar" aria-valuenow={value} aria-valuemin={0} aria-valuemax={100}>
      {indeterminate ? (
        <div className={cx("h-full w-1/3 rounded-full animate-indeterminate", bar)} />
      ) : (
        <div className={cx("h-full rounded-full transition-[width] duration-500", bar)} style={{ width: `${Math.max(2, Math.min(100, value ?? 0))}%` }} />
      )}
    </div>
  );
}

// ---- form fields --------------------------------------------------------------------------------
export function Field({ label, hint, error, children, className, htmlFor }: {
  label?: ReactNode; hint?: ReactNode; error?: ReactNode; children: ReactNode; className?: string; htmlFor?: string;
}) {
  return (
    <div className={className}>
      {label && <label className="field-label" htmlFor={htmlFor}>{label}</label>}
      {children}
      {error ? <p className="text-[12.5px] text-danger mt-1">{error}</p> : hint ? <p className="text-[12.5px] text-steel mt-1">{hint}</p> : null}
    </div>
  );
}

export function TextInput({ label, hint, error, className, ...rest }: React.InputHTMLAttributes<HTMLInputElement> & { label?: ReactNode; hint?: ReactNode; error?: ReactNode }) {
  const id = useId();
  return (
    <Field label={label} hint={hint} error={error} className={className} htmlFor={rest.id ?? id}>
      <input id={rest.id ?? id} {...rest} className={cx("field", !!error && "border-danger")} />
    </Field>
  );
}

export function TextArea({ label, hint, error, className, ...rest }: React.TextareaHTMLAttributes<HTMLTextAreaElement> & { label?: ReactNode; hint?: ReactNode; error?: ReactNode }) {
  const id = useId();
  return (
    <Field label={label} hint={hint} error={error} className={className} htmlFor={rest.id ?? id}>
      <textarea id={rest.id ?? id} {...rest} className={cx("field resize-y leading-relaxed", !!error && "border-danger")} />
    </Field>
  );
}

export function Select({ label, hint, options, className, ...rest }: React.SelectHTMLAttributes<HTMLSelectElement> & {
  label?: ReactNode; hint?: ReactNode; options: Array<{ value: string; label: string }>;
}) {
  const id = useId();
  return (
    <Field label={label} hint={hint} className={className} htmlFor={rest.id ?? id}>
      <select id={rest.id ?? id} {...rest} className="field pr-8">
        {options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
    </Field>
  );
}

export function Toggle({ checked, onChange, label, hint, disabled }: { checked: boolean; onChange: (v: boolean) => void; label: ReactNode; hint?: ReactNode; disabled?: boolean }) {
  return (
    <label className={cx("flex items-start gap-3 cursor-pointer", disabled && "opacity-50 cursor-not-allowed")}>
      <button type="button" role="switch" aria-checked={checked} disabled={disabled} onClick={() => onChange(!checked)}
        className={cx("relative mt-0.5 h-5 w-9 shrink-0 rounded-full border transition-colors", checked ? "bg-velvet border-velvet" : "bg-wash border-line-strong")}>
        <span className={cx("absolute left-0 top-0.5 size-3.5 rounded-full bg-white shadow transition-transform", checked ? "translate-x-[18px]" : "translate-x-0.5")} />
      </button>
      <span>
        <span className="block text-[13.5px] font-medium text-ink">{label}</span>
        {hint && <span className="block text-[12.5px] text-steel">{hint}</span>}
      </span>
    </label>
  );
}

// ---- tabs ---------------------------------------------------------------------------------------
export function Tabs<T extends string>({ tabs, value, onChange, className }: {
  tabs: Array<{ key: T; label: ReactNode; badge?: ReactNode }>; value: T; onChange: (k: T) => void; className?: string;
}) {
  return (
    <div role="tablist" className={cx("flex gap-1 border-b border-line overflow-x-auto scroll-thin", className)}>
      {tabs.map((t) => (
        <button key={t.key} role="tab" aria-selected={value === t.key} onClick={() => onChange(t.key)}
          className={cx("relative px-3 h-10 text-[13.5px] font-medium whitespace-nowrap flex items-center gap-2 transition-colors cursor-pointer",
            value === t.key ? "text-ink" : "text-steel hover:text-ink")}>
          {t.label}
          {t.badge}
          {value === t.key && <span className="absolute left-2 right-2 -bottom-px h-[2px] rounded-full bg-velvet" />}
        </button>
      ))}
    </div>
  );
}

// ---- modal & confirm ----------------------------------------------------------------------------
export function Modal({ open, onClose, title, children, footer, wide }: {
  open: boolean; onClose: () => void; title: ReactNode; children: ReactNode; footer?: ReactNode; wide?: boolean;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const prev = document.activeElement as HTMLElement | null;
    ref.current?.focus();
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      prev?.focus?.();
    };
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-start sm:items-center justify-center p-4 bg-ink/40 backdrop-blur-[2px]" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div ref={ref} tabIndex={-1} role="dialog" aria-modal="true"
        className={cx("panel w-full outline-none max-h-[90vh] flex flex-col shadow-[var(--shadow-pop)]", wide ? "max-w-3xl" : "max-w-lg")}>
        <div className="flex items-center justify-between px-5 pt-4 pb-3 border-b border-line">
          <h2 className="text-[15.5px] font-semibold">{title}</h2>
          <button onClick={onClose} className="p-1 rounded hover:bg-wash cursor-pointer" aria-label="Close"><X className="size-4" /></button>
        </div>
        <div className="px-5 py-4 overflow-y-auto scroll-thin">{children}</div>
        {footer && <div className="px-5 py-3 border-t border-line flex justify-end gap-2 bg-paper/60 rounded-b-[11px]">{footer}</div>}
      </div>
    </div>
  );
}

interface ConfirmOpts {
  title: string;
  body?: ReactNode;
  confirm?: string;
  danger?: boolean;
}
const ConfirmCtx = createContext<(o: ConfirmOpts) => Promise<boolean>>(async () => false);

export function ConfirmProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<(ConfirmOpts & { resolve: (v: boolean) => void }) | null>(null);
  const ask = useCallback((o: ConfirmOpts) => new Promise<boolean>((resolve) => setState({ ...o, resolve })), []);
  const close = (v: boolean) => {
    state?.resolve(v);
    setState(null);
  };
  return (
    <ConfirmCtx.Provider value={ask}>
      {children}
      <Modal open={!!state} onClose={() => close(false)} title={state?.title ?? ""}
        footer={<>
          <Button onClick={() => close(false)}>Cancel</Button>
          <Button variant={state?.danger ? "danger" : "primary"} onClick={() => close(true)} autoFocus>{state?.confirm ?? "Confirm"}</Button>
        </>}>
        <div className="text-[14px] text-ink-2">{state?.body}</div>
      </Modal>
    </ConfirmCtx.Provider>
  );
}
export const useConfirm = () => useContext(ConfirmCtx);

// ---- toasts -------------------------------------------------------------------------------------
interface Toast { id: number; tone: "success" | "error" | "info"; text: ReactNode }
const ToastCtx = createContext<(tone: Toast["tone"], text: ReactNode) => void>(() => {});

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<Toast[]>([]);
  const push = useCallback((tone: Toast["tone"], text: ReactNode) => {
    const id = Date.now() + Math.random();
    setItems((x) => [...x.slice(-3), { id, tone, text }]);
    setTimeout(() => setItems((x) => x.filter((t) => t.id !== id)), tone === "error" ? 9000 : 4500);
  }, []);
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="fixed z-[60] bottom-4 right-4 left-4 sm:left-auto flex flex-col gap-2 items-end pointer-events-none" aria-live="polite">
        {items.map((t) => (
          <div key={t.id} className={cx("pointer-events-auto max-w-sm w-full sm:w-auto rounded-lg px-4 py-3 text-[13.5px] shadow-[var(--shadow-pop)] border flex gap-2.5 items-start",
            t.tone === "error" ? "bg-surface border-danger/30" : "bg-ink text-white border-ink")}>
            {t.tone === "error" ? <XCircle className="size-4 text-danger mt-0.5 shrink-0" /> : t.tone === "success" ? <CheckCircle2 className="size-4 text-velvet-100 mt-0.5 shrink-0" /> : <Info className="size-4 mt-0.5 shrink-0" />}
            <div className={t.tone === "error" ? "text-ink" : ""}>{t.text}</div>
            <button className="ml-2 opacity-60 hover:opacity-100 cursor-pointer" aria-label="Dismiss" onClick={() => setItems((x) => x.filter((y) => y.id !== t.id))}><X className="size-3.5" /></button>
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
}
export const useToast = () => useContext(ToastCtx);

// ---- misc ---------------------------------------------------------------------------------------
export function KeyValues({ rows, className }: { rows: Array<[ReactNode, ReactNode]>; className?: string }) {
  return (
    <dl className={cx("grid grid-cols-[minmax(110px,auto)_1fr] gap-x-5 gap-y-2 text-[13.5px]", className)}>
      {rows.map(([k, v], i) => (
        <div key={i} className="contents">
          <dt className="text-steel">{k}</dt>
          <dd className="text-ink m-0 min-w-0 break-words">{v}</dd>
        </div>
      ))}
    </dl>
  );
}

export function Blockers({ items, title = "Before this can go ahead" }: { items: string[]; title?: string }) {
  if (!items.length) return null;
  return (
    <div className="rounded-lg border border-brass-100 bg-brass-50 px-3.5 py-3">
      <div className="text-[13px] font-semibold text-brass mb-1.5">{title}</div>
      <ul className="text-[13px] text-ink-2 space-y-1 list-none p-0 m-0">
        {items.map((b, i) => (
          <li key={i} className="flex gap-2"><span className="mt-[7px] size-1 rounded-full bg-brass shrink-0" />{b}</li>
        ))}
      </ul>
    </div>
  );
}
