import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { BookOpen, Check, Pencil, Plus, Search, Trash2 } from "lucide-react";
import { del, get, post, put } from "../lib/api";
import { keys, useAction } from "../lib/hooks";
import { actorName, ago } from "../lib/format";
import { Button, Empty, Loading, Modal, PageHeader, Panel, Pill, TextArea, TextInput, useConfirm } from "../components/ui";

const FIELDS: Array<[string, string, string?]> = [
  ["brand", "Brand"], ["model", "Model"], ["reference", "Reference"], ["calibre", "Calibre"], ["movement_type", "Movement", "Automatic, manual, quartz…"],
  ["case_size_mm", "Case size", "38.7 × 47.5 mm"], ["case_thickness_mm", "Case thickness"], ["case_material", "Case material"], ["dial", "Dial"],
  ["bezel", "Bezel"], ["crystal", "Crystal"], ["water_resistance", "Water resistance"], ["power_reserve", "Power reserve"],
  ["bracelet_strap", "Bracelet / strap"], ["functions", "Functions"],
];

type Spec = Record<string, any>;

export default function Specs() {
  const [q, setQ] = useState("");
  const [edit, setEdit] = useState<Spec | null>(null);
  const confirm = useConfirm();
  const list = useQuery({ queryKey: keys.specs(q), queryFn: () => get<{ items: Spec[] }>("/api/specs", { q }) });
  const inv = [["specs"]];
  const save = useAction((s: Spec) => {
    const body = Object.fromEntries([...FIELDS.map(([k]) => [k, s[k] || null]), ["source_note", s.source_note || null]]);
    return s.id ? put(`/api/specs/${s.id}`, body) : post("/api/specs", body);
  }, { success: "Saved as a draft. Approve it to use it in listings.", invalidate: inv, onSuccess: () => setEdit(null) });
  const approve = useAction((id: string) => post(`/api/specs/${id}/approve`), { success: "Specification approved", invalidate: inv });
  const remove = useAction((id: string) => del(`/api/specs/${id}`), { success: "Deleted", invalidate: inv });

  return (
    <>
      <PageHeader title="Specifications" sub="Your trusted reference data. Listing copy only uses calibre, case and dial details from approved records here — never from the web."
        actions={<Button variant="primary" icon={<Plus className="size-4" />} onClick={() => setEdit({ brand: "", model: "" })}>New record</Button>} />
      <Panel className="mb-5">
        <label className="relative block max-w-md">
          <Search className="size-4 text-steel absolute left-3 top-1/2 -translate-y-1/2" />
          <input className="field pl-9" placeholder="Search brand, model or reference" value={q} onChange={(e) => setQ(e.target.value)} />
        </label>
      </Panel>
      {list.isLoading ? <Loading /> : !list.data?.items.length ? (
        <Panel><Empty icon={<BookOpen className="size-8" />} title="No specification records" action={<Button variant="primary" onClick={() => setEdit({ brand: "", model: "" })}>Add the first record</Button>}>
          Add the references you sell so the studio can describe calibre, case and dial accurately.
        </Empty></Panel>
      ) : (
        <Panel pad={false}>
          <ul className="divide-y divide-line">
            {list.data.items.map((s) => (
              <li key={s.id} className="p-4 sm:px-5 flex flex-wrap gap-4 items-start">
                <div className="flex-1 min-w-[240px]">
                  <div className="flex items-center gap-2"><span className="font-display text-[19px]">{s.brand} {s.model}</span>{s.status === "approved" ? <Pill tone="velvet" dot>Approved</Pill> : <Pill tone="brass" dot>Draft</Pill>}</div>
                  <div className="text-[13px] text-steel mt-0.5">{s.reference ? `Ref. ${s.reference}` : "No reference"} · updated {ago(s.updated_at)}{s.approved_by ? ` · approved by ${actorName(s.approved_by)}` : ""}</div>
                  <div className="text-[13px] text-ink-2 mt-1.5">{FIELDS.slice(3).filter(([k]) => s[k]).map(([k, l]) => `${l}: ${s[k]}`).join(" · ") || "No details yet."}</div>
                </div>
                <div className="flex gap-2">
                  {s.status !== "approved" && <Button size="sm" variant="primary" icon={<Check className="size-3.5" />} onClick={() => approve.mutate(s.id)}>Approve</Button>}
                  <Button size="sm" icon={<Pencil className="size-3.5" />} onClick={() => setEdit(s)}>Edit</Button>
                  <Button size="sm" variant="ghost" aria-label="Delete" onClick={async () => {
                    if (await confirm({ title: "Delete this record?", body: "Watches using it lose these details in their listings.", confirm: "Delete", danger: true })) remove.mutate(s.id);
                  }}><Trash2 className="size-4" /></Button>
                </div>
              </li>
            ))}
          </ul>
        </Panel>
      )}
      <Modal open={!!edit} onClose={() => setEdit(null)} title={edit?.id ? "Edit specification" : "New specification"} wide
        footer={<><Button onClick={() => setEdit(null)}>Cancel</Button><Button variant="primary" loading={save.isPending} disabled={!edit?.brand || !edit?.model} onClick={() => edit && save.mutate(edit)}>Save draft</Button></>}>
        {edit && (
          <div className="grid sm:grid-cols-2 gap-4">
            {FIELDS.map(([k, l, ph]) => <TextInput key={k} label={l} placeholder={ph} value={edit[k] ?? ""} onChange={(e) => setEdit({ ...edit, [k]: e.target.value })} required={k === "brand" || k === "model"} />)}
            <TextArea className="sm:col-span-2" label="Source" rows={2} hint="Where this came from, e.g. the brand's official spec sheet." value={edit.source_note ?? ""} onChange={(e) => setEdit({ ...edit, source_note: e.target.value })} />
            {edit.id && edit.status === "approved" && <p className="sm:col-span-2 text-[12.5px] text-brass">Saving changes returns this record to draft until you approve it again.</p>}
          </div>
        )}
      </Modal>
    </>
  );
}
