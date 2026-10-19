import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { BookOpen, Check, Sparkles, X } from "lucide-react";
import { get, patch, post } from "../../lib/api";
import { keys, useAction } from "../../lib/hooks";
import type { WatchDetail } from "../../lib/types";
import { toBody, toForm, WatchForm } from "../../components/WatchForm";
import { Button, Notice, Panel, PanelHeader, Pill, cx } from "../../components/ui";

interface FactsResp {
  facts: Record<string, { value: any; label: string; source: string }>;
  suggestions: Array<{ id: string; field: string; label: string; value: string; source: string; evidence: string | null; confidence: number | null }>;
  spec: { id: string; brand: string; model: string; reference: string } | null;
  ai: { available: boolean; provider: string; eligible_frames: number; kept_local: Array<{ filename: string; reason: string }> };
}

const SOURCE_LABEL = (s: string) =>
  s === "inventory" ? "You" : s.startsWith("spec_table") ? "Specs library" : s.endsWith("_confirmed") ? "Confirmed suggestion" : s.replace(/_/g, " ");

export default function OverviewTab({ detail, onSaved }: { detail: WatchDetail; onSaved: () => void }) {
  const w = detail.watch;
  const original = useMemo(() => toForm(w), [w]);
  const [form, setForm] = useState(original);
  useEffect(() => setForm(original), [original]);
  const changes = toBody(form, original);
  const dirty = Object.keys(changes).length > 0;
  const facts = useQuery({ queryKey: keys.facts(w.id), queryFn: () => get<FactsResp>(`/api/watches/${w.id}/facts`) });
  const inv = [keys.watch(w.id), keys.facts(w.id), keys.review(w.id), keys.copy(w.id)];
  const save = useAction(() => patch(`/api/watches/${w.id}`, changes), { success: "Saved", invalidate: inv, onSuccess: onSaved });
  const decide = useAction((a: { id: string; accept: boolean }) => post(`/api/watches/${w.id}/suggestions/${a.id}`, { accept: a.accept }), {
    success: (r: any) => (r.status === "accepted" ? "Fact confirmed" : "Suggestion dismissed"), invalidate: inv,
  });
  const intel = useAction(() => post(`/api/watches/${w.id}/ai/intel`), { success: "Comparing photos with the record…", invalidate: [keys.watch(w.id)] });
  const specs = useQuery({
    queryKey: keys.specs(w.reference ?? w.model), queryFn: () => get<{ items: any[] }>("/api/specs", { q: w.reference || w.model }),
    enabled: !facts.data?.spec,
  });
  const link = useAction((specId: string) => post(`/api/watches/${w.id}/spec/${specId}`), { success: "Specification linked", invalidate: inv });

  const issues = detail.readiness.issues;
  const fieldIssues = Object.fromEntries(issues.filter((i) => i.severity !== "info").map((i) => [i.field, i.message]));
  const approvedSpecs = (specs.data?.items ?? []).filter((s) => s.status === "approved");

  return (
    <div className="grid xl:grid-cols-[1fr_380px] gap-6 items-start">
      <Panel className="min-w-0">
        <WatchForm value={form} onChange={setForm} mode="edit" issues={fieldIssues} />
        <div className={cx("mt-6 flex items-center justify-between gap-3 rounded-lg border px-4 py-3 transition-all",
          dirty ? "sticky bottom-4 z-10 bg-ink text-white border-ink shadow-[var(--shadow-pop)]" : "bg-paper border-line text-steel")}>
          <span className="text-[13px]">{dirty ? `Unsaved changes: ${Object.keys(changes).map((k) => k.replace(/_/g, " ")).join(", ")}` : "All changes saved"}</span>
          <div className="flex gap-2">
            {dirty && <Button size="sm" variant="ghost" className="text-white hover:bg-white/10" onClick={() => setForm(original)}>Discard</Button>}
            <Button size="sm" variant={dirty ? "secondary" : "ghost"} disabled={!dirty} loading={save.isPending} onClick={() => save.mutate()}>Save changes</Button>
          </div>
        </div>
      </Panel>

      <div className="space-y-5 xl:sticky xl:top-8">
        <Panel>
          <PanelHeader title="Facts check" sub="What is missing or does not agree. Blockers stop approval." />
          {issues.length === 0 ? <p className="text-[13.5px] text-velvet flex items-center gap-2"><Check className="size-4" /> Every required fact is in place.</p> : (
            <ul className="space-y-2.5">
              {issues.map((i, n) => (
                <li key={n} className="flex gap-2.5 text-[13px]">
                  <Pill tone={i.severity === "blocker" ? "brass" : i.severity === "warning" ? "neutral" : "muted"} className="shrink-0 mt-0.5">
                    {i.severity === "blocker" ? "Needed" : i.severity === "warning" ? "Check" : "Note"}
                  </Pill>
                  <span className="text-ink-2">{i.message}{i.suggestion && !i.suggestion_id && <span className="text-steel"> Suggested: <b className="font-medium text-ink">{i.suggestion}</b></span>}</span>
                </li>
              ))}
            </ul>
          )}
        </Panel>

        {!!facts.data?.suggestions.length && (
          <Panel>
            <PanelHeader title="Suggestions to confirm" sub="Proposed by AI or your Sheet. Nothing changes until you accept it." />
            <ul className="space-y-3">
              {facts.data.suggestions.map((s) => (
                <li key={s.id} className="rounded-lg border border-line p-3">
                  <div className="text-[12.5px] text-steel">{s.label} · from {s.source.replace(/_/g, " ")}{s.confidence ? ` · ${Math.round(s.confidence * 100)}% sure` : ""}</div>
                  <div className="text-[14px] font-medium mt-0.5">{s.value}</div>
                  {s.evidence && <div className="text-[12.5px] text-steel mt-0.5">{s.evidence}</div>}
                  <div className="flex gap-2 mt-2.5">
                    <Button size="sm" variant="primary" icon={<Check className="size-3.5" />} onClick={() => decide.mutate({ id: s.id, accept: true })}>Accept</Button>
                    <Button size="sm" icon={<X className="size-3.5" />} onClick={() => decide.mutate({ id: s.id, accept: false })}>Dismiss</Button>
                  </div>
                </li>
              ))}
            </ul>
          </Panel>
        )}

        <Panel>
          <PanelHeader title="Photo check with AI" sub="Compares checked photos with this record and reports differences as suggestions." />
          {!facts.data?.ai.available ? (
            <Notice tone="info">AI is not configured. Add your OpenAI key in the .env file to use this.</Notice>
          ) : (
            <>
              <p className="text-[13px] text-steel mb-3">
                {facts.data.ai.eligible_frames} photo{facts.data.ai.eligible_frames === 1 ? "" : "s"} can be sent.
                {facts.data.ai.kept_local.length > 0 && ` ${facts.data.ai.kept_local.length} stay on this machine (casebacks, papers, or not yet checked).`}
              </p>
              <Button icon={<Sparkles className="size-4" />} disabled={!facts.data.ai.eligible_frames} loading={intel.isPending} onClick={() => intel.mutate()}>
                Compare photos with record
              </Button>
            </>
          )}
        </Panel>

        <Panel>
          <PanelHeader title="Specifications" sub="Calibre, case and dial details come only from your approved specs library." />
          {facts.data?.spec ? (
            <p className="text-[13.5px]"><BookOpen className="inline size-4 mr-1.5 text-velvet" />Using <b className="font-medium">{facts.data.spec.brand} {facts.data.spec.model} {facts.data.spec.reference}</b></p>
          ) : approvedSpecs.length ? (
            <ul className="space-y-2">
              {approvedSpecs.slice(0, 4).map((s) => (
                <li key={s.id} className="flex items-center justify-between gap-2 text-[13px]">
                  <span>{s.brand} {s.model} {s.reference}</span>
                  <Button size="sm" onClick={() => link.mutate(s.id)}>Use</Button>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-[13px] text-steel">No approved record matches. <Link to="/specs" className="text-velvet hover:underline">Add one in the specs library</Link>.</p>
          )}
        </Panel>

        {facts.data && (
          <Panel>
            <PanelHeader title="Facts used in listings" sub="Every claim in the copy must come from this list." />
            <dl className="text-[13px] divide-y divide-line">
              {Object.entries(facts.data.facts).map(([k, f]) => (
                <div key={k} className="flex justify-between gap-3 py-1.5">
                  <dt className="text-steel">{f.label}</dt>
                  <dd className="m-0 text-right"><span className="text-ink">{String(f.value)}</span> <span className="block text-[11.5px] text-steel-2">{SOURCE_LABEL(f.source)}</span></dd>
                </div>
              ))}
            </dl>
          </Panel>
        )}
      </div>
    </div>
  );
}
