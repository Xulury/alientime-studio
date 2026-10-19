import { lazy, Suspense } from "react";
import { BrowserRouter, Link, Route, Routes } from "react-router-dom";
import { AuthProvider, useAuth } from "./lib/auth";
import { ConfirmProvider, Empty, Loading, ToastProvider } from "./components/ui";
import Layout from "./components/Layout";
import { LoginPage, SetupPage } from "./pages/Auth";
import Dashboard from "./pages/Dashboard";
import Inventory from "./pages/Inventory";
import NewWatch from "./pages/NewWatch";
import WatchPage from "./pages/WatchPage";

const StudioEditor = lazy(() => import("./pages/StudioEditor"));
const ReviewQueue = lazy(() => import("./pages/ReviewQueue"));
const Publishing = lazy(() => import("./pages/Publishing"));
const Specs = lazy(() => import("./pages/Specs"));
const Jobs = lazy(() => import("./pages/Jobs"));
const ActivityLog = lazy(() => import("./pages/ActivityLog"));
const Settings = lazy(() => import("./pages/Settings"));

function Gate() {
  const { state } = useAuth();
  if (!state) return <div className="min-h-screen grid place-items-center"><Loading label="Opening the studio…" /></div>;
  if (state.setup_required) return <SetupPage allowed={!!state.setup_allowed_here} />;
  if (!state.authenticated) return <LoginPage />;
  return (
    <Suspense fallback={<Loading />}>
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<Dashboard />} />
          <Route path="inventory" element={<Inventory />} />
          <Route path="watches/new" element={<NewWatch />} />
          <Route path="watches/:id" element={<WatchPage />} />
          <Route path="watches/:id/studio/:assetId" element={<StudioEditor />} />
          <Route path="watches/:id/:tab" element={<WatchPage />} />
          <Route path="review" element={<ReviewQueue />} />
          <Route path="publishing" element={<Publishing />} />
          <Route path="specs" element={<Specs />} />
          <Route path="jobs" element={<Jobs />} />
          <Route path="activity" element={<ActivityLog />} />
          <Route path="settings" element={<Settings />} />
          <Route path="settings/:tab" element={<Settings />} />
          <Route path="*" element={<Empty title="Page not found" action={<Link className="text-velvet underline" to="/">Back to the dashboard</Link>}>That address does not exist in the studio.</Empty>} />
        </Route>
      </Routes>
    </Suspense>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <ToastProvider>
        <ConfirmProvider>
          <AuthProvider>
            <Gate />
          </AuthProvider>
        </ConfirmProvider>
      </ToastProvider>
    </BrowserRouter>
  );
}
