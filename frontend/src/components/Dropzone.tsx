import { useCallback, useRef, useState } from "react";
import { ImagePlus, X } from "lucide-react";
import { uploadFiles } from "../lib/api";
import { bytes } from "../lib/format";
import { Button, Progress, cx } from "./ui";

export const ACCEPT = "image/jpeg,image/png,image/webp,.heic";
const MAX_MB = 30;

export interface PendingFile {
  id: string;
  file: File;
  preview: string;
  progress: number;
  status: "ready" | "uploading" | "added" | "duplicate" | "rejected" | "error";
  message?: string;
}

export function useUploader() {
  const [files, setFiles] = useState<PendingFile[]>([]);
  const add = useCallback((list: FileList | File[]) => {
    const next: PendingFile[] = [];
    for (const f of Array.from(list)) {
      const okType = /image\/(jpeg|png|webp|heic)/.test(f.type) || /\.(jpe?g|png|webp|heic)$/i.test(f.name);
      const tooBig = f.size > MAX_MB * 1024 * 1024;
      next.push({
        id: `${f.name}-${f.size}-${Math.random()}`, file: f, preview: okType ? URL.createObjectURL(f) : "", progress: 0,
        status: okType && !tooBig ? "ready" : "rejected",
        message: !okType ? "Not a JPEG, PNG or WebP image." : tooBig ? `Larger than ${MAX_MB} MB.` : undefined,
      });
    }
    setFiles((cur) => [...cur, ...next]);
  }, []);
  const remove = (id: string) => setFiles((cur) => cur.filter((f) => f.id !== id));
  const clear = () => setFiles([]);

  /** Upload ready files one at a time so each has its own progress and errors do not block the rest. */
  const uploadAll = async (watchId: string) => {
    const results: { added: number; failed: number } = { added: 0, failed: 0 };
    for (const pf of files.filter((f) => f.status === "ready" || f.status === "error")) {
      setFiles((cur) => cur.map((f) => (f.id === pf.id ? { ...f, status: "uploading", progress: 0 } : f)));
      try {
        const res: any = await uploadFiles(`/api/watches/${watchId}/assets`, [pf.file], (p) =>
          setFiles((cur) => cur.map((f) => (f.id === pf.id ? { ...f, progress: p } : f))),
        );
        const r = res.results?.[0];
        const status = (r?.status ?? "added") as PendingFile["status"];
        if (status === "added") results.added++;
        else results.failed++;
        setFiles((cur) => cur.map((f) => (f.id === pf.id ? { ...f, status, progress: 100, message: r?.warnings?.join(" ") || (status !== "added" ? r?.message : undefined) } : f)));
      } catch (e: any) {
        results.failed++;
        setFiles((cur) => cur.map((f) => (f.id === pf.id ? { ...f, status: "error", message: e?.message ?? "Upload failed." } : f)));
      }
    }
    return results;
  };
  return { files, add, remove, clear, uploadAll, readyCount: files.filter((f) => f.status === "ready").length };
}

export function Dropzone({ onFiles, compact, dark }: { onFiles: (f: FileList | File[]) => void; compact?: boolean; dark?: boolean }) {
  const input = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);
  return (
    <div
      onDragOver={(e) => { e.preventDefault(); setOver(true); }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => { e.preventDefault(); setOver(false); if (e.dataTransfer.files.length) onFiles(e.dataTransfer.files); }}
      onClick={() => input.current?.click()}
      role="button" tabIndex={0} onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && input.current?.click()}
      className={cx(
        "rounded-lg border border-dashed cursor-pointer transition-colors flex items-center justify-center text-center",
        compact ? "px-4 py-5" : "px-6 py-12",
        dark ? "border-stage-line text-white/70 hover:bg-stage-2" : "border-line-strong bg-paper/50 hover:bg-velvet-50/60",
        over && (dark ? "bg-stage-2 border-velvet" : "bg-velvet-50 border-velvet"),
      )}>
      <input ref={input} type="file" accept={ACCEPT} multiple className="hidden"
        onChange={(e) => { if (e.target.files?.length) onFiles(e.target.files); e.target.value = ""; }} />
      <div>
        <ImagePlus className={cx("mx-auto mb-2", compact ? "size-5" : "size-7", dark ? "text-white/50" : "text-steel-2")} />
        <div className={cx("font-medium", compact ? "text-[13.5px]" : "text-[15px]")}>Drop photographs here, or click to choose</div>
        <div className={cx("text-[12.5px] mt-1", dark ? "text-white/50" : "text-steel")}>
          JPEG, PNG or WebP · up to {MAX_MB} MB each · edited, camera or WhatsApp photos
        </div>
      </div>
    </div>
  );
}

export function PendingList({ files, onRemove }: { files: PendingFile[]; onRemove: (id: string) => void }) {
  if (!files.length) return null;
  return (
    <ul className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3 mt-4">
      {files.map((f) => (
        <li key={f.id} className="rounded-lg border border-line bg-surface overflow-hidden">
          <div className="relative aspect-[4/3] bg-stage">
            {f.preview && <img src={f.preview} alt="" className="size-full object-cover" />}
            {(f.status === "ready" || f.status === "rejected" || f.status === "error") && (
              <Button size="sm" variant="secondary" className="absolute top-1.5 right-1.5 h-7 px-1.5" onClick={() => onRemove(f.id)} aria-label={`Remove ${f.file.name}`}>
                <X className="size-3.5" />
              </Button>
            )}
          </div>
          <div className="p-2.5">
            <div className="text-[12.5px] truncate" title={f.file.name}>{f.file.name}</div>
            <div className="text-[12px] text-steel">{bytes(f.file.size)}</div>
            {f.status === "uploading" && <Progress value={f.progress} className="mt-1.5" />}
            {f.status === "added" && <div className="text-[12px] text-velvet mt-1">Uploaded</div>}
            {(f.status === "duplicate" || f.status === "rejected" || f.status === "error") && (
              <div className={cx("text-[12px] mt-1", f.status === "duplicate" ? "text-brass" : "text-danger")}>{f.message ?? f.status}</div>
            )}
            {f.status === "added" && f.message && <div className="text-[12px] text-brass mt-0.5">{f.message}</div>}
          </div>
        </li>
      ))}
    </ul>
  );
}
