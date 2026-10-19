export function money(v: number | null | undefined, currency = "SGD"): string {
  if (v === null || v === undefined) return "—";
  const digits = Number.isInteger(v) ? 0 : 2;
  return `${currency} ${v.toLocaleString("en-SG", { minimumFractionDigits: digits, maximumFractionDigits: digits })}`;
}

export function parseDate(iso: string | null | undefined): Date | null {
  if (!iso) return null;
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? null : d;
}

export function dateTime(iso: string | null | undefined): string {
  const d = parseDate(iso);
  if (!d) return "—";
  return d.toLocaleString("en-SG", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}

export function ago(iso: string | null | undefined): string {
  const d = parseDate(iso);
  if (!d) return "—";
  const s = Math.round((Date.now() - d.getTime()) / 1000);
  if (s < 45) return "just now";
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  if (s < 86400 * 7) return `${Math.round(s / 86400)} d ago`;
  return d.toLocaleDateString("en-SG", { day: "numeric", month: "short", year: "numeric" });
}

export function bytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

export function actorName(actor: string): string {
  if (actor.startsWith("user:")) return actor.slice(5);
  if (actor.startsWith("agent:")) return actor.slice(6).replace(" for telegram:", " via Telegram ");
  if (actor === "system") return "Studio";
  return actor;
}

export const BOX_PAPERS: Record<string, string> = {
  full_set: "Full set (box and papers)",
  box_and_papers: "Box and papers",
  set_minus_box: "Papers and accessories, no box",
  papers_only: "Papers only",
  box_only: "Box only",
  watch_only: "Watch only",
  unknown: "Not recorded",
};

export const CUSTODY: Record<string, string> = {
  in_hand: "In hand",
  consigned_offsite: "Consigned, held off-site",
  unknown: "Not recorded",
};

export const CONDITION: Record<string, string> = {
  unworn: "Unworn",
  excellent: "Excellent",
  very_good: "Very good",
  good: "Good",
  fair: "Fair",
};

export const PHOTO_TYPES: Record<string, string> = {
  dial_front: "Dial / front",
  side_profile: "Side / profile",
  crown_side: "Crown side",
  clasp: "Clasp",
  strap: "Strap / bracelet",
  caseback: "Caseback",
  movement: "Movement",
  box_papers: "Box / papers",
  document: "Document",
  detail: "Detail",
  wrist: "On the wrist",
  unclassified: "Not classified",
};

export const BACKGROUNDS: Record<string, string> = {
  auto: "House default",
  green_velvet: "Green velvet",
  studio_white: "Studio white",
  studio_grey: "Studio grey",
  studio_black: "Studio black",
  cleanup: "Cleaned-up original",
  keep_original: "Original background (crop only)",
  ai_velvet: "Green velvet · AI",
  ai_studio: "Studio sweep · AI",
};

export const SCOPE_LABELS: Record<string, string> = {
  read: "See everything",
  intake: "Create watches and upload photos",
  process: "Run processing and AI analysis",
  copy: "Write listing copy",
  request_approval: "Ask for approval",
  approve: "Approve",
  publish: "Publish",
  lifecycle: "Mark reserved / sold",
  settings: "Change settings",
};

export function plural(n: number, one: string, many?: string) {
  return `${n} ${n === 1 ? one : many ?? one + "s"}`;
}
