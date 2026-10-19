import { useState, type ReactNode } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  Activity, BadgeCheck, BookOpen, Cog, Gauge, History, LogOut, Menu, Plus, Send, Watch, X,
} from "lucide-react";
import { get } from "../lib/api";
import { useAuth } from "../lib/auth";
import { keys } from "../lib/hooks";
import { Button, cx } from "./ui";

interface Dash {
  counts: Record<string, number>;
}
interface AiState {
  provider: string;
  available: boolean;
  mode: string;
}

function NavItem({ to, icon, label, badge, onClick }: { to: string; icon: ReactNode; label: string; badge?: number; onClick?: () => void }) {
  return (
    <NavLink to={to} end={to === "/"} onClick={onClick}
      className={({ isActive }) => cx(
        "group flex items-center gap-3 rounded-md px-3 h-9 text-[13.5px] font-medium transition-colors",
        isActive ? "bg-velvet-50 text-velvet" : "text-ink-2 hover:bg-wash hover:text-ink",
      )}>
      <span className="opacity-80">{icon}</span>
      <span className="flex-1">{label}</span>
      {!!badge && <span className="min-w-5 h-5 px-1.5 rounded-full bg-brass text-white text-[11px] font-semibold flex items-center justify-center tabular-nums">{badge}</span>}
    </NavLink>
  );
}

function Sidebar({ onNavigate }: { onNavigate?: () => void }) {
  const { state, logout } = useAuth();
  const navigate = useNavigate();
  const dash = useQuery({ queryKey: keys.dashboard, queryFn: () => get<Dash>("/api/dashboard"), refetchInterval: 20000 });
  const ai = useQuery({ queryKey: keys.ai, queryFn: () => get<AiState>("/api/settings/ai"), staleTime: 60000 });
  const c = dash.data?.counts ?? {};
  const reviewBadge = (c.images_awaiting_review ?? 0) + (c.listings_awaiting_approval ?? 0) + (c.privacy_checks ?? 0);
  const pubBadge = (c.open_manual_tasks ?? 0) + (c.failed ?? 0);
  const aiLabel = ai.data ? (ai.data.provider === "openai" ? "OpenAI connected" : ai.data.provider === "mock" ? "AI in test mode" : "AI not configured") : "…";
  return (
    <div className="flex h-full flex-col">
      <div className="px-5 pt-6 pb-5">
        <div className="font-display text-[26px] leading-none text-ink">Alien Time</div>
        <div className="text-[12.5px] text-steel mt-1.5 tracking-[0.01em]">Listing Studio</div>
      </div>
      <div className="px-3 mb-4">
        <Button variant="primary" className="w-full" icon={<Plus className="size-4" />} onClick={() => { navigate("/watches/new"); onNavigate?.(); }}>
          New watch
        </Button>
      </div>
      <nav className="px-3 space-y-0.5" aria-label="Main">
        <NavItem to="/" icon={<Gauge className="size-4" />} label="Dashboard" onClick={onNavigate} />
        <NavItem to="/inventory" icon={<Watch className="size-4" />} label="Inventory" onClick={onNavigate} />
        <NavItem to="/review" icon={<BadgeCheck className="size-4" />} label="Review" badge={reviewBadge} onClick={onNavigate} />
        <NavItem to="/publishing" icon={<Send className="size-4" />} label="Publishing" badge={pubBadge} onClick={onNavigate} />
      </nav>
      <div className="px-6 mt-6 mb-2 text-[12px] text-steel-2">Library &amp; system</div>
      <nav className="px-3 space-y-0.5" aria-label="System">
        <NavItem to="/specs" icon={<BookOpen className="size-4" />} label="Specifications" onClick={onNavigate} />
        <NavItem to="/jobs" icon={<Activity className="size-4" />} label="Background jobs" onClick={onNavigate} />
        <NavItem to="/activity" icon={<History className="size-4" />} label="Activity log" onClick={onNavigate} />
        <NavItem to="/settings" icon={<Cog className="size-4" />} label="Settings" onClick={onNavigate} />
      </nav>
      <div className="mt-auto px-5 py-4 border-t border-line text-[12.5px] space-y-2">
        <div className="flex items-center gap-2 text-steel">
          <span className={cx("size-2 rounded-full", ai.data?.provider === "openai" ? "bg-velvet" : ai.data?.provider === "mock" ? "bg-info" : "bg-steel-2")} />
          {aiLabel}
        </div>
        <div className="flex items-center justify-between gap-2">
          <span className="truncate text-ink-2">{state?.user?.display_name}</span>
          <button className="inline-flex items-center gap-1.5 text-steel hover:text-ink cursor-pointer" onClick={() => logout()}>
            <LogOut className="size-3.5" /> Sign out
          </button>
        </div>
      </div>
    </div>
  );
}

export default function Layout() {
  const [open, setOpen] = useState(false);
  const loc = useLocation();
  const fullBleed = /^\/watches\/[^/]+\/studio/.test(loc.pathname);
  if (fullBleed) return <Outlet />;
  return (
    <div className="min-h-screen lg:grid lg:grid-cols-[248px_1fr]">
      <aside className="hidden lg:block sticky top-0 h-screen border-r border-line bg-surface/70 backdrop-blur">
        <Sidebar />
      </aside>
      <div className="lg:hidden sticky top-0 z-30 flex items-center justify-between px-4 h-14 border-b border-line bg-surface/90 backdrop-blur">
        <div className="font-display text-[21px]">Alien Time</div>
        <button className="p-2 -mr-2 rounded hover:bg-wash cursor-pointer" aria-label="Open menu" onClick={() => setOpen(true)}><Menu className="size-5" /></button>
      </div>
      {open && (
        <div className="lg:hidden fixed inset-0 z-40 bg-ink/40" onClick={() => setOpen(false)}>
          <aside className="absolute inset-y-0 left-0 w-[280px] bg-surface shadow-xl" onClick={(e) => e.stopPropagation()}>
            <button className="absolute right-3 top-4 p-1.5 rounded hover:bg-wash cursor-pointer" aria-label="Close menu" onClick={() => setOpen(false)}><X className="size-4" /></button>
            <Sidebar onNavigate={() => setOpen(false)} />
          </aside>
        </div>
      )}
      <main className="min-w-0 px-4 sm:px-8 xl:px-12 py-7 lg:py-10 max-w-[1440px]">
        <Outlet />
      </main>
    </div>
  );
}
