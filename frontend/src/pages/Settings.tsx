import { useEffect, useState, type ReactNode } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Copy, KeyRound, PlugZap, Plus, Trash2 } from "lucide-react";
import { del, get, post, put } from "../lib/api";
import { keys, useAction } from "../lib/hooks";
import { BACKGROUNDS, SCOPE_LABELS, actorName, ago, dateTime } from "../lib/format";
import type { ChannelInfo, IntegrationInfo } from "../lib/types";
import {
  Button, KeyValues, Loading, Modal, Notice, PageHeader, Panel, PanelHeader, Pill, Select, TextArea, TextInput, Toggle, cx, useConfirm, useToast,
} from "../components/ui";

type Tab = "terms" | "style" | "claims" | "pricing" | "studio" | "channels" | "ai" | "integrations" | "agents" | "account" | "system";
const TABS: Array<[Tab, string]> = [
  ["terms", "House terms"], ["style", "Writing style"], ["claims", "Claim rules"], ["pricing", "Pricing"], ["studio", "Studio defaults"],
  ["channels", "Channels"], ["ai", "AI"], ["integrations", "Integrations"], ["agents", "Agent access"], ["account", "Account"], ["system", "System"],
];

interface SettingsResp { settings: Record<string, any>; system: Record<string, any>; channels: ChannelInfo[] }

function useSection(section: string, data?: SettingsResp) {
  const [value, setValue] = useState<any>(null);
  useEffect(() => { if (data) setValue(structuredClone(data.settings[section])); }, [data, section]);
  const save = useAction(() => put(`/api/settings/${section}`, value), { success: "Settings saved", invalidate: [keys.settings] });
  const dirty = !!data && JSON.stringify(value) !== JSON.stringify(data.settings[section]);
  return { value, setValue, save, dirty };
}

function SaveBar({ dirty, onSave, saving, note }: { dirty: boolean; onSave: () => void; saving: boolean; note?: ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-3 pt-5 mt-5 border-t border-line">
      <span className="text-[12.5px] text-steel">{note}</span>
      <Button variant="primary" disabled={!dirty} loading={saving} onClick={onSave}>Save</Button>
    </div>
  );
}

function Terms({ data }: { data: SettingsResp }) {
  const s = useSection("fixed_blocks", data);
  if (!s.value) return null;
  const v = s.value;
  const set = (k: string, x: string) => s.setValue({ ...v, [k]: x });
  return (
    <Panel>
      <PanelHeader title="House terms" sub="Inserted by the studio word for word into every channel that uses them. The AI never writes or edits these." />
      <div className="grid gap-4">
        <TextArea label="Terms of sale" rows={4} value={v.terms} onChange={(e) => set("terms", e.target.value)} hint="Used on Shopify, Chrono24, eBay, Carousell, Reddit and MODA." />
        <TextArea label="Disclaimer" rows={3} value={v.disclaimer} onChange={(e) => set("disclaimer", e.target.value)} hint="e.g. brand names are used for identification only; not affiliated with the manufacturer." />
        <TextInput label="Licence line" value={v.licence} onChange={(e) => set("licence", e.target.value)} hint="e.g. your Second-Hand Goods Dealer licence number. Used on Shopify." />
        <TextInput label="Call to action" value={v.cta} onChange={(e) => set("cta", e.target.value)} />
        <TextInput label="Contact line" value={v.contact} onChange={(e) => set("contact", e.target.value)} />
        <div>
          <div className="field-label">Channel-specific call to action</div>
          <div className="grid sm:grid-cols-2 gap-3">
            {data.channels.filter((c) => c.fixed_blocks.includes("cta")).map((c) => (
              <TextInput key={c.key} label={c.name} placeholder="Same as above" value={v.channel_overrides?.[c.key]?.cta ?? ""}
                onChange={(e) => {
                  const o = { ...(v.channel_overrides ?? {}) };
                  if (e.target.value) o[c.key] = { ...(o[c.key] ?? {}), cta: e.target.value };
                  else if (o[c.key]) { const { cta: _c, ...rest } = o[c.key]; o[c.key] = rest; if (!Object.keys(rest).length) delete o[c.key]; }
                  s.setValue({ ...v, channel_overrides: o });
                }} />
            ))}
          </div>
        </div>
      </div>
      <SaveBar dirty={s.dirty} saving={s.save.isPending} onSave={() => s.save.mutate()} note="Existing copy is flagged “out of date” until it is refreshed, so approvals always match the current wording." />
    </Panel>
  );
}

function Style({ data }: { data: SettingsResp }) {
  const s = useSection("house_style", data);
  if (!s.value) return null;
  const v = s.value;
  const styleNames = Object.keys(v.styles ?? {});
  return (
    <Panel>
      <PanelHeader title="Writing style" sub="Guides the AI writer and chooses which style each channel uses. Templates follow the same structure." />
      <div className="grid gap-4">
        <TextArea label="House voice" rows={3} value={v.voice} onChange={(e) => s.setValue({ ...v, voice: e.target.value })} />
        {styleNames.map((n) => (
          <TextArea key={n} label={`Style: ${n}`} rows={2} value={v.styles[n]} onChange={(e) => s.setValue({ ...v, styles: { ...v.styles, [n]: e.target.value } })} />
        ))}
        <div>
          <div className="field-label">Style per channel</div>
          <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-3">
            {data.channels.map((c) => (
              <Select key={c.key} label={c.name} value={v.channel_styles?.[c.key] ?? "house"} onChange={(e) => s.setValue({ ...v, channel_styles: { ...v.channel_styles, [c.key]: e.target.value } })}
                options={styleNames.map((n) => ({ value: n, label: n }))} />
            ))}
          </div>
        </div>
        <TextInput label="Default hashtags" value={(v.default_hashtags ?? []).join(" ")} onChange={(e) => s.setValue({ ...v, default_hashtags: e.target.value.split(/\s+/).filter(Boolean) })} />
        <Toggle checked={!!v.brand_hashtags} onChange={(x) => s.setValue({ ...v, brand_hashtags: x })} label="Add brand and model hashtags" />
      </div>
      <SaveBar dirty={s.dirty} saving={s.save.isPending} onSave={() => s.save.mutate()} />
    </Panel>
  );
}

function Claims({ data }: { data: SettingsResp }) {
  const s = useSection("claims", data);
  if (!s.value) return null;
  const v = s.value;
  return (
    <Panel>
      <PanelHeader title="Claim rules" sub="Phrases that may only appear in copy when a fact supports them, and phrases never allowed. Checked by code after every generation or edit." />
      <div className="space-y-2">
        <div className="grid grid-cols-[1fr_1fr_auto] gap-2 text-[12.5px] text-steel"><span>Phrase</span><span>Allowed only when</span><span /></div>
        {v.rules.map((r: any, i: number) => (
          <div key={i} className="grid grid-cols-[1fr_1fr_auto] gap-2">
            <input className="field" value={r.phrase} aria-label="Phrase" onChange={(e) => { const rules = [...v.rules]; rules[i] = { ...r, phrase: e.target.value }; s.setValue({ ...v, rules }); }} />
            <input className="field" value={r.requires} aria-label="Requirement" onChange={(e) => { const rules = [...v.rules]; rules[i] = { ...r, requires: e.target.value }; s.setValue({ ...v, rules }); }} />
            <Button size="sm" variant="ghost" aria-label="Remove rule" onClick={() => s.setValue({ ...v, rules: v.rules.filter((_: any, j: number) => j !== i) })}><Trash2 className="size-4" /></Button>
          </div>
        ))}
        <Button size="sm" variant="ghost" icon={<Plus className="size-4" />} onClick={() => s.setValue({ ...v, rules: [...v.rules, { phrase: "", requires: "fact:" }] })}>Add rule</Button>
        <p className="text-[12.5px] text-steel">Requirements: <code>custody=in_hand</code>, <code>condition=unworn</code>, <code>box_papers in full_set,box_and_papers</code>, or <code>fact:warranty</code> (any recorded value).</p>
      </div>
      <TextArea className="mt-5" label="Never allowed (one per line)" rows={4} value={(v.banned ?? []).join("\n")} onChange={(e) => s.setValue({ ...v, banned: e.target.value.split("\n").map((x) => x.trim()).filter(Boolean) })} />
      <SaveBar dirty={s.dirty} saving={s.save.isPending} onSave={() => s.save.mutate()} />
    </Panel>
  );
}

function Pricing({ data }: { data: SettingsResp }) {
  const s = useSection("pricing", data);
  if (!s.value) return null;
  const v = s.value;
  return (
    <Panel>
      <PanelHeader title="Pricing" sub="Your SGD→USD rate is used only to check that the two prices you type agree, and to offer a calculation. It is never fetched automatically." />
      <div className="grid sm:grid-cols-2 gap-4 max-w-xl">
        <TextInput label="SGD → USD rate" inputMode="decimal" value={v.fx_sgd_usd ?? ""} placeholder="e.g. 0.77" onChange={(e) => s.setValue({ ...v, fx_sgd_usd: e.target.value === "" ? null : Number(e.target.value) })}
          hint={v.fx_updated_at ? `Last set ${ago(v.fx_updated_at)}` : "Not set"} />
        <TextInput label="Allowed difference (%)" inputMode="decimal" value={v.drift_tolerance_pct} onChange={(e) => s.setValue({ ...v, drift_tolerance_pct: Number(e.target.value) })} />
      </div>
      <SaveBar dirty={s.dirty} saving={s.save.isPending} onSave={() => s.save.mutate()} />
    </Panel>
  );
}

function Studio({ data }: { data: SettingsResp }) {
  const s = useSection("studio", data);
  if (!s.value) return null;
  const v = s.value;
  const set = (k: string, x: any) => s.setValue({ ...v, [k]: x });
  const bgOpts = Object.entries(BACKGROUNDS).filter(([k]) => k !== "auto").map(([k, l]) => ({ value: k, label: l }));
  return (
    <Panel>
      <PanelHeader title="Studio defaults" sub="Applied to every new render unless changed on the photo itself." />
      <div className="grid sm:grid-cols-2 gap-4">
        <Select label="Background for raw and phone photos" value={v.default_background} onChange={(e) => set("default_background", e.target.value)} options={bgOpts} />
        <Select label="Background for edited sets" value={v.edited_background} onChange={(e) => set("edited_background", e.target.value)} options={bgOpts.filter((o) => !o.value.startsWith("ai_"))} />
        <TextInput label="White balance strength (0–1)" type="number" step="0.05" min={0} max={1} value={v.white_balance_strength} onChange={(e) => set("white_balance_strength", Number(e.target.value))} />
        <TextInput label="Watch size in frame (0.4–0.95)" type="number" step="0.01" min={0.4} max={0.95} value={v.fill_ratio} onChange={(e) => set("fill_ratio", Number(e.target.value))} />
        <TextInput label="Lead image rotation (degrees)" type="number" step="1" min={-60} max={60} value={v.hero_rotation_deg} onChange={(e) => set("hero_rotation_deg", Number(e.target.value))} hint="Code rotates the real photo; 0 keeps it upright." />
        <TextInput label="Exposure adjustment (EV)" type="number" step="0.05" min={-1.5} max={1.5} value={v.exposure_ev} onChange={(e) => set("exposure_ev", Number(e.target.value))} />
        <TextInput label="Minimum sharpness score to keep a photo" type="number" min={0} max={100} value={v.min_sharpness} onChange={(e) => set("min_sharpness", Number(e.target.value))} />
        <TextInput label="Minimum short side (pixels)" type="number" min={200} max={4000} value={v.min_resolution} onChange={(e) => set("min_resolution", Number(e.target.value))} />
        <Toggle checked={!!v.auto_exposure} onChange={(x) => set("auto_exposure", x)} label="Automatic brightness" />
        <Toggle checked={!!v.shadow} onChange={(x) => set("shadow", x)} label="Soft contact shadow" />
      </div>
      <SaveBar dirty={s.dirty} saving={s.save.isPending} onSave={() => s.save.mutate()} />
    </Panel>
  );
}

function Channels({ data }: { data: SettingsResp }) {
  const s = useSection("channels", data);
  if (!s.value) return null;
  const enabled: string[] = s.value.enabled ?? [];
  return (
    <Panel>
      <PanelHeader title="Channels" sub="Channels switched off here are hidden everywhere. Individual watches can also leave out channels." />
      <ul className="grid md:grid-cols-2 gap-3">
        {data.channels.map((c) => (
          <li key={c.key} className="rounded-lg border border-line p-3.5">
            <Toggle checked={enabled.includes(c.key)} onChange={(x) => s.setValue({ ...s.value, enabled: x ? [...enabled, c.key] : enabled.filter((k) => k !== c.key) })}
              label={c.name} hint={c.route === "manual" ? "Draft pack — you post it" : c.route === "feed" ? "Dealer product feed" : "Official API"} />
            <div className="text-[12px] text-steel mt-2 pl-12">
              {Object.entries(c.limits).map(([k, l]) => <div key={k}>{k === "text" ? "Text" : "Title"} ≤ {l.max_chars.toLocaleString()} characters — {l.verified ? l.source : "no published limit; internal"}</div>)}
              {c.hashtags_max > 0 && <div>Hashtags ≤ {c.hashtags_max}</div>}
            </div>
          </li>
        ))}
      </ul>
      <SaveBar dirty={s.dirty} saving={s.save.isPending} onSave={() => s.save.mutate()} />
    </Panel>
  );
}

function AiTab() {
  const q = useQuery({ queryKey: keys.ai, queryFn: () => get<any>("/api/settings/ai") });
  const test = useAction(() => post<any>("/api/settings/ai/test"), { success: (r) => r.message, invalidate: [keys.ai] });
  if (q.isLoading || !q.data) return <Loading />;
  const d = q.data;
  const u = d.usage;
  return (
    <div className="space-y-5">
      <Panel>
        <PanelHeader title="OpenAI" sub="Used for photo tagging, listing checks, copy writing and AI backgrounds. The key is read from the server's .env file and never shown here."
          actions={<Button icon={<PlugZap className="size-4" />} loading={test.isPending} onClick={() => test.mutate()}>Test connection</Button>} />
        {!d.key_configured && d.provider !== "mock" && (
          <Notice tone="info" className="mb-4" title="Not configured yet">Add <code>OPENAI_API_KEY=…</code> to the <code>.env</code> file next to the app and restart the studio. Everything else keeps working without it.</Notice>
        )}
        {d.provider === "mock" && <Notice tone="warning" className="mb-4">Test mode: AI_PROVIDER=mock. Results are simulated and nothing is sent to OpenAI.</Notice>}
        {test.data && <Notice tone={test.data.ok ? "success" : "danger"} className="mb-4" title={test.data.message}>
          {Object.entries(test.data.models ?? {}).map(([role, m]: any) => <div key={role}>{role}: {m.model} — {m.ok ? "available" : m.error}</div>)}
        </Notice>}
        <KeyValues rows={[
          ["Status", d.available ? <Pill tone="velvet" dot>{d.provider === "mock" ? "Test mode" : "Configured"}</Pill> : <Pill tone="muted">Not configured</Pill>],
          ["Vision model", d.models.vision], ["Listing intelligence", d.models.intel], ["Copy writer", d.models.text], ["Image model", `${d.models.image} (quality: ${d.image_quality})`],
          ["Photos sent to AI", d.image_policy === "reviewed_only" ? "Only photos you have checked; never casebacks, movements or papers" : d.image_policy === "safe_auto" ? "Photos with no serial-like text found, plus checked ones; never casebacks or papers" : "None"],
          ["AI backgrounds", d.background_mode === "plate" ? "Empty backdrop from a text prompt — no photo is sent" : "Redacted, eligible frame sent for lighting; the model's watch pixels are discarded"],
          ["Timeout / retries", `${d.timeout_seconds}s / ${d.max_retries}`],
        ]} />
        <p className="text-[12.5px] text-steel mt-4">Models, budgets and the photo policy are changed in .env (OPENAI_MODEL_*, AI_*_BUDGET_USD, CLOUD_AI_IMAGE_POLICY).</p>
      </Panel>
      <Panel>
        <PanelHeader title="Usage and spending" sub={u.note} />
        <div className="grid sm:grid-cols-2 gap-5 mb-5">
          {[["Today", u.today_usd, u.daily_budget_usd], ["This month", u.month_usd, u.monthly_budget_usd]].map(([label, spent, budget]: any) => (
            <div key={label}>
              <div className="flex justify-between text-[13px] mb-1.5"><span>{label}</span><span className="tabular-nums">USD {spent.toFixed(2)} of {budget.toFixed(2)}</span></div>
              <div className="h-2 rounded-full bg-wash overflow-hidden"><div className={cx("h-full rounded-full", spent / budget > 0.9 ? "bg-danger" : spent / budget > 0.7 ? "bg-brass" : "bg-velvet")} style={{ width: `${Math.min(100, (spent / budget) * 100)}%` }} /></div>
            </div>
          ))}
        </div>
        {u.by_operation.length ? (
          <table className="w-full text-[13px]">
            <thead><tr className="text-left text-steel text-[12.5px] border-b border-line"><th className="font-medium py-1.5">Operation (30 days)</th><th className="font-medium">Model</th><th className="font-medium text-right">Calls</th><th className="font-medium text-right">Tokens in / out</th><th className="font-medium text-right">Est. cost</th></tr></thead>
            <tbody className="divide-y divide-line">{u.by_operation.map((r: any, i: number) => (
              <tr key={i}><td className="py-1.5">{r.operation}</td><td>{r.model}</td><td className="text-right tabular-nums">{r.calls}</td><td className="text-right tabular-nums">{r.input_tokens.toLocaleString()} / {r.output_tokens.toLocaleString()}</td><td className="text-right tabular-nums">USD {r.cost_usd.toFixed(4)}</td></tr>
            ))}</tbody>
          </table>
        ) : <p className="text-[13px] text-steel">No AI calls yet.</p>}
      </Panel>
    </div>
  );
}

function Integrations() {
  const q = useQuery({ queryKey: keys.integrations, queryFn: () => get<{ items: IntegrationInfo[] }>("/api/integrations") });
  const test = useAction((n: string) => post<IntegrationInfo>(`/api/integrations/${n}/test`), { success: (r) => `${r.label}: ${r.state_label}`, invalidate: [keys.integrations, keys.publishing] });
  if (q.isLoading) return <Loading />;
  return (
    <Panel>
      <PanelHeader title="Integrations" sub="Each connection is tested with a real call before it counts as connected. Credentials live in .env, never in the browser." />
      <ul className="grid md:grid-cols-2 gap-4">
        {q.data?.items.map((i) => (
          <li key={i.name} className="rounded-lg border border-line p-4">
            <div className="flex items-start justify-between gap-2">
              <div><div className="font-semibold text-[14px]">{i.label}</div><div className="text-[12px] text-steel capitalize">{i.kind}</div></div>
              <Pill tone={i.state === "connected" ? "velvetSolid" : i.state === "error" ? "danger" : i.state === "configured" ? "info" : "muted"}>{i.state_label}</Pill>
            </div>
            {i.message && <p className="text-[12.5px] text-ink-2 mt-2 break-words">{i.message}</p>}
            {i.capabilities.length > 0 && <p className="text-[12px] text-steel mt-1.5">{i.capabilities.join(" · ")}</p>}
            {i.notes.map((n, k) => <p key={k} className="text-[12px] text-steel mt-1">{n}</p>)}
            <div className="flex items-center justify-between mt-3">
              <span className="text-[12px] text-steel">{i.checked_at ? `Tested ${ago(i.checked_at)}` : "Never tested"}</span>
              <Button size="sm" disabled={i.state === "not_configured"} loading={test.isPending && test.variables === i.name} onClick={() => test.mutate(i.name)}>Test</Button>
            </div>
          </li>
        ))}
      </ul>
      <p className="text-[12.5px] text-steel mt-4">Setup steps for each platform are in docs/INTEGRATIONS.md.</p>
    </Panel>
  );
}

function Agents() {
  const q = useQuery({ queryKey: keys.tokens, queryFn: () => get<any>("/api/tokens") });
  const [name, setName] = useState("hermes");
  const [scopes, setScopes] = useState<string[] | null>(null);
  const [created, setCreated] = useState<string | null>(null);
  const toast = useToast();
  const confirm = useConfirm();
  useEffect(() => { if (q.data && scopes === null) setScopes(q.data.default_scopes); }, [q.data, scopes]);
  const create = useAction(() => post<any>("/api/tokens", { name, scopes }), { invalidate: [keys.tokens], onSuccess: (r) => setCreated(r.token) });
  const revoke = useAction((id: number) => del(`/api/tokens/${id}`), { success: "Token revoked", invalidate: [keys.tokens] });
  if (q.isLoading || !q.data) return <Loading />;
  return (
    <div className="space-y-5">
      <Panel>
        <PanelHeader title="Agent access (Hermes)" sub="Agents use a scoped token, never your password. They act through the same checks as you: no unapproved content can be published." />
        {!q.data.admin_users_configured && <Notice tone="info" className="mb-4">Approve, publish and sold/reserved actions by an agent also need the requesting Telegram user to be listed in TELEGRAM_ADMIN_USERS in .env. Until then those actions are refused.</Notice>}
        <div className="grid md:grid-cols-[240px_1fr] gap-5">
          <TextInput label="Token name" value={name} onChange={(e) => setName(e.target.value)} />
          <div>
            <div className="field-label">Permissions</div>
            <div className="grid sm:grid-cols-2 gap-2">
              {Object.entries(q.data.scopes).map(([k, desc]: any) => (
                <label key={k} className="flex gap-2 text-[13px] items-start cursor-pointer">
                  <input type="checkbox" className="mt-1" checked={!!scopes?.includes(k)} onChange={(e) => setScopes(e.target.checked ? [...(scopes ?? []), k] : (scopes ?? []).filter((s) => s !== k))} />
                  <span><b className="font-medium">{SCOPE_LABELS[k] ?? k}</b><span className="block text-steel text-[12px]">{desc}</span></span>
                </label>
              ))}
            </div>
          </div>
        </div>
        <div className="mt-4"><Button variant="primary" icon={<KeyRound className="size-4" />} disabled={!name || !scopes?.length} loading={create.isPending} onClick={() => create.mutate()}>Create token</Button></div>
      </Panel>
      <Panel>
        <PanelHeader title="Tokens" />
        {!q.data.items.length ? <p className="text-[13px] text-steel">No tokens yet.</p> : (
          <ul className="divide-y divide-line">
            {q.data.items.map((t: any) => (
              <li key={t.id} className="py-3 flex flex-wrap items-center gap-3">
                <div className="flex-1 min-w-[220px]">
                  <div className="text-[13.5px] font-medium">{t.name} <span className="text-steel font-normal tabular-nums">{t.prefix}…</span> {t.revoked && <Pill tone="danger">Revoked</Pill>}</div>
                  <div className="text-[12px] text-steel">{t.scopes.map((s: string) => SCOPE_LABELS[s] ?? s).join(" · ")}</div>
                  <div className="text-[12px] text-steel">Created {dateTime(t.created_at)} by {actorName(t.created_by ?? "")} · last used {t.last_used_at ? ago(t.last_used_at) : "never"}</div>
                </div>
                {!t.revoked && <Button size="sm" variant="ghost" onClick={async () => { if (await confirm({ title: `Revoke ${t.name}?`, body: "Anything using this token stops working immediately.", confirm: "Revoke", danger: true })) revoke.mutate(t.id); }}>Revoke</Button>}
              </li>
            ))}
          </ul>
        )}
      </Panel>
      <Modal open={!!created} onClose={() => setCreated(null)} title="Copy this token now" footer={<Button variant="primary" onClick={() => setCreated(null)}>Done</Button>}>
        <p className="text-[13.5px] text-ink-2 mb-3">It will not be shown again. Store it in your password manager and give it to Hermes as <code>STUDIO_AGENT_TOKEN</code>.</p>
        <div className="flex gap-2"><input className="field font-mono text-[12.5px]" readOnly value={created ?? ""} onFocus={(e) => e.target.select()} />
          <Button icon={<Copy className="size-4" />} onClick={() => { navigator.clipboard?.writeText(created ?? ""); toast("success", "Copied"); }}>Copy</Button></div>
      </Modal>
    </div>
  );
}

function Account() {
  const [cur, setCur] = useState("");
  const [next, setNext] = useState("");
  const [rep, setRep] = useState("");
  const change = useAction(() => post("/api/auth/password", { current_password: cur, new_password: next }), {
    success: "Password changed. Other sessions were signed out.", onSuccess: () => { setCur(""); setNext(""); setRep(""); },
  });
  return (
    <Panel className="max-w-xl">
      <PanelHeader title="Change password" sub="This version has one owner account. More users can be added in a later version." />
      <div className="grid gap-4">
        <TextInput label="Current password" type="password" autoComplete="current-password" value={cur} onChange={(e) => setCur(e.target.value)} />
        <TextInput label="New password" type="password" autoComplete="new-password" value={next} onChange={(e) => setNext(e.target.value)} hint="At least 10 characters." />
        <TextInput label="Repeat new password" type="password" autoComplete="new-password" value={rep} onChange={(e) => setRep(e.target.value)} error={rep && rep !== next ? "Does not match." : undefined} />
        <div><Button variant="primary" disabled={!cur || next.length < 10 || next !== rep} loading={change.isPending} onClick={() => change.mutate()}>Change password</Button></div>
      </div>
    </Panel>
  );
}

function System({ data }: { data: SettingsResp }) {
  const s = data.system;
  return (
    <Panel>
      <PanelHeader title="System" sub="How this installation is running." />
      <KeyValues rows={[
        ["Data folder", <code className="text-[12.5px] break-all">{s.data_dir}</code>],
        ["Address", s.base_url], ["Mode", s.environment], ["Background worker", s.worker_mode],
        ["Local OCR (serials)", s.ocr.available ? <Pill tone="velvet" dot>{s.ocr.engine}</Pill> : <Pill tone="danger">Not available — photos need a manual check</Pill>],
        ["Cutout model", <span>{s.segmentation.backend}{s.segmentation.note ? <span className="block text-[12px] text-steel">{s.segmentation.note}</span> : null}</span>],
        ["Photos to cloud AI", s.cloud_ai_image_policy], ["Simulated publishing", s.simulated_publishing ? "On (for channels not yet connected)" : "Off"],
        ["Upload limit", `${s.max_upload_mb} MB per photo`], ["Secure cookies (HTTPS)", s.cookie_secure ? "On" : "Off — fine on this computer only"],
      ]} />
    </Panel>
  );
}

export default function Settings() {
  const { tab = "terms" } = useParams();
  const navigate = useNavigate();
  const q = useQuery({ queryKey: keys.settings, queryFn: () => get<SettingsResp>("/api/settings") });
  const current = (TABS.find(([k]) => k === tab)?.[0] ?? "terms") as Tab;
  return (
    <>
      <PageHeader title="Settings" sub="House wording, studio defaults, connections and access." />
      <div className="grid lg:grid-cols-[210px_1fr] gap-6 items-start">
        <nav className="panel p-2 lg:sticky lg:top-8 flex lg:flex-col gap-0.5 overflow-x-auto" aria-label="Settings sections">
          {TABS.map(([k, l]) => (
            <button key={k} onClick={() => navigate(`/settings/${k}`)}
              className={cx("text-left whitespace-nowrap rounded-md px-3 h-9 text-[13.5px] cursor-pointer", current === k ? "bg-velvet-50 text-velvet font-semibold" : "text-ink-2 hover:bg-wash")}>{l}</button>
          ))}
        </nav>
        <div className="min-w-0">
          {q.isLoading || !q.data ? <Loading /> : (
            <>
              {current === "terms" && <Terms data={q.data} />}
              {current === "style" && <Style data={q.data} />}
              {current === "claims" && <Claims data={q.data} />}
              {current === "pricing" && <Pricing data={q.data} />}
              {current === "studio" && <Studio data={q.data} />}
              {current === "channels" && <Channels data={q.data} />}
              {current === "ai" && <AiTab />}
              {current === "integrations" && <Integrations />}
              {current === "agents" && <Agents />}
              {current === "account" && <Account />}
              {current === "system" && <System data={q.data} />}
            </>
          )}
        </div>
      </div>
    </>
  );
}
