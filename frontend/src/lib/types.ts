// Shapes returned by the studio API (see app/api/views.py and friends).

export type WatchStatus =
  | "draft" | "processing" | "awaiting_review" | "approved" | "published" | "reserved" | "sold" | "withdrawn";

export interface WatchSummary {
  id: string;
  sku: string;
  brand: string;
  model: string;
  reference: string | null;
  year: string | null;
  condition: string | null;
  price_sgd: number | null;
  price_usd: number | null;
  custody: string;
  box_papers: string;
  is_consignment: boolean;
  status: WatchStatus;
  status_label: string;
  availability: string;
  photo_count: number;
  open_manual_tasks: number;
  thumb: string | null;
  created_at: string;
  updated_at: string;
  archived: boolean;
}

export interface WatchRecord {
  id: string;
  sku: string;
  brand: string;
  model: string;
  reference: string | null;
  year: string | null;
  condition: string | null;
  condition_notes: string | null;
  price_sgd: number | null;
  price_usd: number | null;
  fx_rate_sgd_usd: number | null;
  fx_source: string | null;
  fx_updated_at: string | null;
  box_papers: string;
  box_papers_notes: string | null;
  custody: string;
  is_consignment: boolean;
  consignor_name: string | null;
  consignor_contact: string | null;
  consignment_ref: string | null;
  consignment_terms: string | null;
  consignment_payout_sgd: number | null;
  consignment_start: string | null;
  consignment_end: string | null;
  consignor_signoff: string;
  description: string | null;
  internal_notes: string | null;
  extra_facts: Record<string, { value: string; source: string }>;
  spec_id: string | null;
  status: WatchStatus;
  status_label: string;
  status_changed_at: string;
  availability: string;
  allowed_actions: string[];
  gallery: string[];
  channels: string[] | null;
  hero_asset_id: string | null;
  content_version: number;
  created_at: string;
  updated_at: string;
  archived: boolean;
}

export interface AssetUrls {
  thumb: string;
  working: string;
  redacted: string | null;
  mask: string | null;
  cutout: string | null;
  final: string | null;
  original: string;
}

export interface Asset {
  id: string;
  watch_id: string;
  filename: string;
  source: string;
  width: number;
  height: number;
  bytes: number;
  format: string;
  sha256: string;
  uploaded_at: string;
  sort_order: number;
  duplicate_of: string | null;
  pipeline_status: string;
  pipeline_label: string;
  pipeline_error: string | null;
  source_profile: string | null;
  quality_score: number | null;
  selected: boolean | null;
  selection_auto: boolean | null;
  selection_override: boolean | null;
  selection_reasons: string[];
  photo_type: string | null;
  photo_type_label: string;
  photo_type_source: string | null;
  safety_status: string;
  safety_label: string;
  review_status: string;
  review_note: string | null;
  render_stale: boolean;
  warnings: string[];
  has_mask: boolean;
  has_render: boolean;
  fidelity_passed: boolean | null;
  urls: AssetUrls;
}

export interface Region {
  id?: string;
  x: number;
  y: number;
  w: number;
  h: number;
  source?: string;
  category?: string | null;
  confidence?: number | null;
  enabled: boolean;
}

export interface FidelityResult {
  passed: boolean;
  psnr_db?: number;
  mean_abs_error?: number;
  p99_abs_error?: number;
  pixels_compared?: number;
  message?: string;
  redactions?: { passed: boolean; checked: number; intact?: number };
}

export interface Render {
  id: string;
  version: number;
  created_at: string;
  status: string;
  background_source: string | null;
  fidelity_passed: boolean;
  url: string;
  settings?: Record<string, any>;
  fidelity?: Record<string, FidelityResult>;
  warnings?: string[];
  variants?: Record<string, { width: number; height: number; label: string; url: string }>;
}

export interface AssetDetail extends Asset {
  inspection: { metrics?: Record<string, any>; rejects?: string[]; warnings?: string[]; score?: number };
  source_profile_reasons: string[];
  photo_type_confidence: number | null;
  ai_tags: Record<string, any>;
  exif: Record<string, string>;
  safety_engine: string | null;
  safety_findings: Array<Record<string, any>>;
  safety_recheck: { passed?: boolean; message?: string; checked?: number; failures?: number[] };
  safety_reviewed_at: string | null;
  safety_reviewed_by: string | null;
  regions: Region[];
  segmentation: { backend?: string; notes?: string[]; stats?: Record<string, any> };
  mask_source: string | null;
  studio_settings: Record<string, any>;
  studio_resolved: Record<string, any>;
  working_size: [number, number];
  render: Render | null;
  renders: Render[];
  cloud_ai: { eligible: boolean; reason: string; policy: string };
}

export interface Job {
  id: string;
  type: string;
  label: string;
  status: "pending" | "running" | "completed" | "failed" | "cancelled";
  watch_id: string | null;
  asset_id: string | null;
  channel: string | null;
  progress: number;
  message: string | null;
  error: string | null;
  attempts: number;
  max_attempts: number;
  result: Record<string, any>;
  run_after: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  created_by: string | null;
  sku?: string | null;
}

export interface FactIssue {
  code: string;
  field: string;
  severity: "blocker" | "warning" | "info";
  message: string;
  suggestion: string | null;
  suggestion_id: string | null;
}

export interface ApprovalView {
  id: string;
  status: string;
  approved_by: string;
  approved_at: string;
  invalidated_at: string | null;
  invalidated_reason: string | null;
  content_hash: string;
  snapshot: Record<string, any>;
}

export interface ChannelMode {
  channel: string;
  route: "api" | "feed" | "manual";
  mode: "live" | "simulation" | "manual" | "unavailable";
  state: string;
  message: string;
  live_enabled: boolean;
}

export interface Limit {
  max_chars: number;
  source: string;
  verified: boolean;
}

export interface ChannelInfo {
  key: string;
  name: string;
  route: "api" | "feed" | "manual";
  audience: string;
  has_title: boolean;
  sections: string[];
  fixed_blocks: string[];
  max_images: number;
  currency: string;
  hashtags_max: number;
  manual_steps: string[];
  notes: string[];
  limits: Record<string, Limit>;
}

export interface ListingState {
  status: string;
  label: string;
  mode: string;
  external_url: string | null;
  external_id: string | null;
  published_at: string | null;
  last_error: string | null;
  up_to_date: boolean;
}

export interface ReadinessChannel extends ChannelInfo {
  copy: null | {
    version: number;
    title: string | null;
    generator: string;
    updated_at: string;
    chars: number;
    errors: Array<{ section: string; message: string }>;
    warnings: Array<{ section: string; message: string }>;
    stale: string[];
  };
  approved: boolean;
  approval: ApprovalView | null;
  approval_blockers: string[];
  mode: ChannelMode;
  listing: ListingState | null;
  publish_ready: boolean;
  publish_blockers: string[];
}

export interface Readiness {
  facts: Record<string, { value: any; label: string; source: string }>;
  issues: FactIssue[];
  suggestions: Array<{ id: string; field: string; value: string; source: string; evidence: string | null; confidence: number | null }>;
  images: Array<{ asset_id: string; filename: string; photo_type: string | null; review_status: string; approved: boolean; blockers: string[]; approval: ApprovalView | null; thumb: string }>;
  image_problems: string[];
  channels: ReadinessChannel[];
  package: { approved: boolean; approval: ApprovalView | null; blockers: string[] };
  open_manual_tasks: number;
  summary: {
    images_total: number;
    images_approved: number;
    channels_with_copy: number;
    channels_approved: number;
    channels_live: number;
    fact_blockers: number;
    ready_to_publish: number;
  };
}

export interface WatchDetail {
  watch: WatchRecord;
  summary: WatchSummary;
  assets: Asset[];
  jobs: Job[];
  readiness: Readiness;
}

export interface CopySections {
  title?: string;
  body?: string;
  hashtags?: string[];
  [k: string]: any;
}

export interface ChannelCopyView extends ChannelInfo {
  included: boolean;
  copy: null | {
    id: string;
    version: number;
    sections: CopySections;
    sources: Record<string, string>;
    text: string;
    generator: string;
    style: string;
    validation: {
      errors: Array<{ section: string; message: string }>;
      warnings: Array<{ section: string; message: string }>;
      counts: { text: number; title: number; hashtags: number };
      ok: boolean;
      limits: Record<string, { max: number; verified: boolean; source: string }>;
    };
    updated_at: string;
    updated_by: string | null;
    stale: string[];
    hash: string;
  };
  approved: boolean;
  approval: null | { status: string; approved_by: string; approved_at: string; invalidated_reason: string | null };
}

export interface ManualTask {
  id: string;
  watch_id: string;
  sku: string | null;
  watch: string | null;
  channel: string;
  channel_name: string;
  kind: string;
  title: string;
  instructions: string;
  status: string;
  live_url: string | null;
  created_at: string;
  completed_at: string | null;
  completed_by: string | null;
}

export interface ActivityItem {
  id: number;
  at: string;
  actor: string;
  action: string;
  summary: string;
  watch_id: string | null;
  sku?: string | null;
  detail?: Record<string, any>;
}

export interface IntegrationInfo {
  name: string;
  label: string;
  kind: string;
  state: "not_configured" | "configured" | "connected" | "error" | "unsupported";
  state_label: string;
  message: string | null;
  checked_at: string | null;
  live_enabled: boolean;
  required_env: string[];
  missing_env: string[];
  capabilities: string[];
  notes: string[];
}

export interface AuthState {
  authenticated: boolean;
  setup_required: boolean;
  setup_allowed_here?: boolean;
  user: { username: string; display_name: string; last_login_at: string | null } | null;
  csrf_token: string | null;
}
