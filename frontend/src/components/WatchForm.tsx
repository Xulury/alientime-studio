import { useEffect, useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { Calculator, Plus, Trash2 } from "lucide-react";
import { get } from "../lib/api";
import { keys } from "../lib/hooks";
import { BOX_PAPERS, CONDITION, CUSTODY } from "../lib/format";
import type { WatchRecord } from "../lib/types";
import { Button, Select, TextArea, TextInput, Toggle, cx } from "./ui";

export type FormValues = Record<string, any>;

const EXTRA_FACT_OPTIONS: Array<[string, string]> = [
  ["warranty", "Warranty"], ["service_history", "Service history"], ["accessories", "Accessories"],
  ["papers_date", "Papers dated"], ["auction_start_price", "Auction starting bid (SGD)"],
  ["case_size_mm", "Case size"], ["case_material", "Case material"], ["calibre", "Calibre"], ["dial", "Dial"],
  ["bracelet_strap", "Bracelet / strap"], ["water_resistance", "Water resistance"], ["power_reserve", "Power reserve"],
  ["functions", "Functions"],
];
const EXTRA_LABEL = Object.fromEntries(EXTRA_FACT_OPTIONS);

export function toForm(w?: Partial<WatchRecord>): FormValues {
  const extra = Object.entries(w?.extra_facts ?? {}).map(([k, v]) => ({ key: k, value: (v as any)?.value ?? "" }));
  return {
    sku: w?.sku ?? "", brand: w?.brand ?? "", model: w?.model ?? "", reference: w?.reference ?? "", year: w?.year ?? "",
    condition: w?.condition ?? "", condition_notes: w?.condition_notes ?? "",
    price_sgd: w?.price_sgd ?? "", price_usd: w?.price_usd ?? "", fx_rate_sgd_usd: w?.fx_rate_sgd_usd ?? null,
    box_papers: w?.box_papers ?? "unknown", box_papers_notes: w?.box_papers_notes ?? "", custody: w?.custody ?? "unknown",
    is_consignment: w?.is_consignment ?? false, consignor_name: w?.consignor_name ?? "", consignor_contact: w?.consignor_contact ?? "",
    consignment_ref: w?.consignment_ref ?? "", consignment_terms: w?.consignment_terms ?? "",
    consignment_payout_sgd: w?.consignment_payout_sgd ?? "", consignment_start: w?.consignment_start ?? "",
    consignment_end: w?.consignment_end ?? "", consignor_signoff: w?.consignor_signoff ?? "not_required",
    description: w?.description ?? "", internal_notes: w?.internal_notes ?? "", extra,
  };
}

const NUM = new Set(["price_sgd", "price_usd", "consignment_payout_sgd"]);

/** Convert form values to an API body; only fields that changed when `original` is given. */
export function toBody(v: FormValues, original?: FormValues): Record<string, any> {
  const out: Record<string, any> = {};
  for (const [k, raw] of Object.entries(v)) {
    if (k === "extra") continue;
    let val: any = raw;
    if (typeof val === "string") val = val.trim();
    if (NUM.has(k)) val = val === "" || val === null ? null : Number(String(val).replace(/,/g, ""));
    else if (val === "") val = null;
    if (k === "condition" && val === null) val = null;
    if (original) {
      let o: any = original[k];
      if (typeof o === "string") o = o.trim();
      if (NUM.has(k)) o = o === "" || o === null ? null : Number(String(o).replace(/,/g, ""));
      else if (o === "") o = null;
      if (o === val) continue;
    }
    out[k] = val;
  }
  const extra = Object.fromEntries((v.extra as Array<{ key: string; value: string }>).filter((e) => e.key && e.value.trim()).map((e) => [e.key, e.value.trim()]));
  const origExtra = original ? Object.fromEntries((original.extra as Array<{ key: string; value: string }>).filter((e) => e.key && e.value.trim()).map((e) => [e.key, e.value.trim()])) : null;
  if (!original || JSON.stringify(extra) !== JSON.stringify(origExtra)) out.extra_facts = extra;
  if (out.sku === null) delete out.sku;
  return out;
}

function Group({ title, sub, children }: { title: string; sub?: string; children: ReactNode }) {
  return (
    <fieldset className="grid md:grid-cols-[200px_1fr] gap-x-8 gap-y-3 py-6 border-t border-line first:border-t-0 first:pt-0">
      <legend className="sr-only">{title}</legend>
      <div>
        <div className="text-[14px] font-semibold">{title}</div>
        {sub && <div className="text-[12.5px] text-steel mt-0.5 max-w-[30ch]">{sub}</div>}
      </div>
      <div className="grid sm:grid-cols-2 gap-4 content-start">{children}</div>
    </fieldset>
  );
}

export function WatchForm({ value, onChange, mode, issues = {} }: {
  value: FormValues; onChange: (v: FormValues) => void; mode: "create" | "edit"; issues?: Record<string, string>;
}) {
  const set = (k: string, v: any) => onChange({ ...value, [k]: v });
  const settings = useQuery({ queryKey: keys.settings, queryFn: () => get<any>("/api/settings"), staleTime: 60000 });
  const fx: number | null = settings.data?.settings?.pricing?.fx_sgd_usd ?? null;
  const skuSuggestion = useQuery({
    queryKey: ["next-sku", value.brand],
    queryFn: () => get<{ sku: string }>("/api/watches/next-sku", { brand: value.brand }),
    enabled: mode === "create" && value.brand.trim().length > 1,
  });
  const [skuTouched, setSkuTouched] = useState(false);
  useEffect(() => {
    if (mode === "create" && !skuTouched && skuSuggestion.data) onChange({ ...value, sku: skuSuggestion.data.sku });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [skuSuggestion.data?.sku]);
  const hint = (k: string) => issues[k];

  return (
    <div>
      <Group title="Identity" sub="What the watch is. Brand and model are required.">
        <TextInput label="Brand" required value={value.brand} onChange={(e) => set("brand", e.target.value)} placeholder="Richard Mille" />
        <TextInput label="Model" required value={value.model} onChange={(e) => set("model", e.target.value)} placeholder="RM 67-01" />
        <TextInput label="Reference" value={value.reference} onChange={(e) => set("reference", e.target.value)} error={hint("reference")} placeholder="As printed on the papers" />
        <TextInput label="Year" value={value.year} onChange={(e) => set("year", e.target.value)} error={hint("year")} placeholder="2021, c. 2019 or Unknown" />
        <TextInput label="SKU" value={value.sku} onChange={(e) => { setSkuTouched(true); set("sku", e.target.value.toUpperCase()); }}
          hint={mode === "create" ? "Assigned automatically from the brand; you can change it." : "Changing the SKU renames it everywhere in the studio."} />
      </Group>

      <Group title="Condition" sub="The grade and a plain description of wear.">
        <Select label="Grade" value={value.condition ?? ""} onChange={(e) => set("condition", e.target.value)}
          options={[{ value: "", label: "Choose…" }, ...Object.entries(CONDITION).map(([k, l]) => ({ value: k, label: l }))]} />
        <div />
        <TextArea className="sm:col-span-2" label="Condition notes" rows={2} value={value.condition_notes} onChange={(e) => set("condition_notes", e.target.value)}
          error={hint("condition_notes")} placeholder="Light hairlines on the bezel; never polished." />
      </Group>

      <Group title="Box & papers" sub="What comes with the watch.">
        <Select label="Set" value={value.box_papers} onChange={(e) => set("box_papers", e.target.value)}
          options={Object.entries(BOX_PAPERS).map(([k, l]) => ({ value: k, label: k === "unknown" ? "Not recorded yet" : l }))} />
        <TextInput label="Set details" value={value.box_papers_notes} onChange={(e) => set("box_papers_notes", e.target.value)} placeholder="Warranty card dated 2021, spare strap" />
      </Group>

      <Group title="Price" sub="Both prices are typed by you. The studio flags them if they drift from your exchange rate.">
        <TextInput label="Price (SGD)" inputMode="decimal" value={value.price_sgd} onChange={(e) => set("price_sgd", e.target.value)} error={hint("price_sgd")} />
        <div>
          <TextInput label="Price (USD)" inputMode="decimal" value={value.price_usd} onChange={(e) => set("price_usd", e.target.value)} error={hint("price_usd")} />
          {fx && value.price_sgd !== "" && (
            <button type="button" className="mt-1.5 inline-flex items-center gap-1.5 text-[12.5px] text-velvet hover:underline cursor-pointer"
              onClick={() => onChange({ ...value, price_usd: String(Math.round(Number(String(value.price_sgd).replace(/,/g, "")) * fx)), fx_rate_sgd_usd: fx, fx_source: "settings" })}>
              <Calculator className="size-3.5" /> Calculate from SGD at {fx}
            </button>
          )}
        </div>
      </Group>

      <Group title="Custody & consignment" sub="Custody controls whether listings may say the watch is in hand.">
        <Select label="Custody" value={value.custody} onChange={(e) => set("custody", e.target.value)}
          options={Object.entries(CUSTODY).map(([k, l]) => ({ value: k, label: k === "unknown" ? "Not recorded yet" : l }))} />
        <div className="flex items-end pb-1.5">
          <Toggle checked={!!value.is_consignment} onChange={(v) => set("is_consignment", v)} label="Consigned watch" hint="Owned by a client, sold on their behalf." />
        </div>
        {value.is_consignment && (
          <>
            <TextInput label="Consignor" value={value.consignor_name} onChange={(e) => set("consignor_name", e.target.value)} />
            <TextInput label="Consignor contact" value={value.consignor_contact} onChange={(e) => set("consignor_contact", e.target.value)} hint="Private; never used in listings." />
            <TextInput label="Agreement reference" value={value.consignment_ref} onChange={(e) => set("consignment_ref", e.target.value)} />
            <TextInput label="Payout to consignor (SGD)" inputMode="decimal" value={value.consignment_payout_sgd} onChange={(e) => set("consignment_payout_sgd", e.target.value)} />
            <TextInput label="Consignment start" type="date" value={value.consignment_start ?? ""} onChange={(e) => set("consignment_start", e.target.value)} />
            <TextInput label="Consignment end" type="date" value={value.consignment_end ?? ""} onChange={(e) => set("consignment_end", e.target.value)} />
            <Select label="Consignor sign-off on price & photos" value={value.consignor_signoff} onChange={(e) => set("consignor_signoff", e.target.value)}
              options={[{ value: "pending", label: "Waiting for sign-off" }, { value: "approved", label: "Signed off" }, { value: "not_required", label: "Not required" }]} />
            <TextArea className="sm:col-span-2" label="Consignment terms" rows={2} value={value.consignment_terms} onChange={(e) => set("consignment_terms", e.target.value)} />
          </>
        )}
      </Group>

      <Group title="Description" sub="Selling points in your words. Used as-is in listing copy, so keep it factual.">
        <TextArea className="sm:col-span-2" rows={3} value={value.description} onChange={(e) => set("description", e.target.value)}
          placeholder="What makes this piece worth a look, in a sentence or two. Facts only." />
      </Group>

      <Group title="Additional facts" sub="Anything else buyers should know. Only facts entered here can appear in listings.">
        <div className="sm:col-span-2 space-y-2">
          {(value.extra as Array<{ key: string; value: string }>).map((e, i) => (
            <div key={i} className="grid grid-cols-[minmax(150px,220px)_1fr_auto] gap-2 items-center">
              <select className="field" value={e.key} aria-label="Fact" onChange={(ev) => {
                const extra = [...value.extra];
                extra[i] = { ...extra[i], key: ev.target.value };
                set("extra", extra);
              }}>
                <option value="">Choose a fact…</option>
                {EXTRA_FACT_OPTIONS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
                {e.key && !EXTRA_LABEL[e.key] && <option value={e.key}>{e.key}</option>}
              </select>
              <input className="field" value={e.value} aria-label="Value" onChange={(ev) => {
                const extra = [...value.extra];
                extra[i] = { ...extra[i], value: ev.target.value };
                set("extra", extra);
              }} />
              <Button size="sm" variant="ghost" aria-label="Remove fact" onClick={() => set("extra", value.extra.filter((_: unknown, j: number) => j !== i))}><Trash2 className="size-4" /></Button>
            </div>
          ))}
          <Button size="sm" variant="ghost" icon={<Plus className="size-4" />} onClick={() => set("extra", [...value.extra, { key: "", value: "" }])}>Add a fact</Button>
        </div>
      </Group>

      <Group title="Internal notes" sub="Private to the studio. Never used in listings.">
        <TextArea className={cx("sm:col-span-2")} rows={2} value={value.internal_notes} onChange={(e) => set("internal_notes", e.target.value)} />
      </Group>
    </div>
  );
}
