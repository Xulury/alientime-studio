import { useState, type FormEvent, type ReactNode } from "react";
import { useAuth } from "../lib/auth";
import { errorMessage, ApiError } from "../lib/api";
import { Button, Notice, TextInput } from "../components/ui";

function Shell({ children, title, sub }: { children: ReactNode; title: string; sub: string }) {
  return (
    <div className="min-h-screen grid lg:grid-cols-[1.1fr_1fr]">
      <div className="hidden lg:flex flex-col justify-between bg-stage text-white p-12 relative overflow-hidden">
        <div className="absolute inset-0 opacity-90" style={{
          background: "radial-gradient(120% 90% at 30% 25%, #2a6a50 0%, #1e4d3a 38%, #10251c 75%, #0b1712 100%)",
        }} />
        <div className="relative">
          <div className="font-display text-[34px] leading-none">Alien Time</div>
          <div className="text-white/60 mt-2 text-[13px]">Listing Studio</div>
        </div>
        <div className="relative max-w-md">
          <p className="font-display text-[40px] leading-[1.1] text-white/95">
            Every watch pixel comes from your photograph.
          </p>
          <p className="text-white/60 mt-4 text-[14px] leading-relaxed">
            Serials are masked on this machine before anything else happens. Nothing is published until you approve it.
          </p>
        </div>
        <div className="relative text-white/40 text-[12px]">Private workspace · Singapore</div>
      </div>
      <div className="flex items-center justify-center p-6 sm:p-10 bg-paper">
        <div className="w-full max-w-sm">
          <div className="lg:hidden font-display text-[30px] mb-8">Alien Time</div>
          <h1 className="font-display text-[32px] leading-tight">{title}</h1>
          <p className="text-steel mt-1.5 mb-7">{sub}</p>
          {children}
        </div>
      </div>
    </div>
  );
}

export function LoginPage() {
  const { login, register } = useAuth();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [repeat, setRepeat] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [errorDetails, setErrorDetails] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const isRegister = mode === "register";

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (isRegister && password !== repeat) {
      setErrorDetails(null);
      return setError("The two passwords do not match.");
    }
    setBusy(true);
    setError(null);
    setErrorDetails(null);
    try {
      if (isRegister) {
        await register(username, password, name);
      } else {
        await login(username, password);
      }
    } catch (err: any) {
      setError(errorMessage(err));
      if (err instanceof ApiError && err.details) {
        const d = err.details;
        const extra = d.traceback || d.raw || (Object.keys(d).length > 0 ? JSON.stringify(d, null, 2) : null);
        setErrorDetails(typeof extra === "string" ? extra : null);
      } else {
        setErrorDetails(null);
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <Shell
      title={isRegister ? "Create account" : "Sign in"}
      sub={
        isRegister
          ? "Set up an account to access the studio and inventory."
          : "Use the studio account set up on this computer."
      }
    >
      <form onSubmit={submit} className="space-y-4">
        {isRegister && (
          <TextInput
            label="Your name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Matthew"
          />
        )}
        <TextInput
          label="Username"
          autoComplete="username"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          required
          autoFocus
          pattern={isRegister ? "[A-Za-z0-9_.@\\-]+" : undefined}
          hint={isRegister ? "Letters, numbers, dots, dashes." : undefined}
        />
        <TextInput
          label="Password"
          type="password"
          autoComplete={isRegister ? "new-password" : "current-password"}
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
          hint={isRegister ? "At least 10 characters. A short sentence works well." : undefined}
        />
        {isRegister && (
          <TextInput
            label="Repeat password"
            type="password"
            autoComplete="new-password"
            value={repeat}
            onChange={(e) => setRepeat(e.target.value)}
            required
          />
        )}
        {error && (
          <Notice tone="danger">
            <div className="break-words">{error}</div>
            {errorDetails && (
              <details className="mt-2 text-[11px] font-mono whitespace-pre-wrap max-h-48 overflow-auto bg-black/5 dark:bg-black/30 p-2 rounded border border-danger/20">
                <summary className="cursor-pointer font-sans font-medium text-[12px] opacity-80 hover:opacity-100 select-none">
                  Show technical details
                </summary>
                <div className="mt-1 select-text">{errorDetails}</div>
              </details>
            )}
          </Notice>
        )}
        <Button variant="primary" size="lg" className="w-full" loading={busy} type="submit">
          {isRegister ? "Create account" : "Sign in"}
        </Button>
        <div className="pt-2 text-center text-[13.5px] text-steel">
          {isRegister ? (
            <>
              Already have an account?{" "}
              <button
                type="button"
                onClick={() => {
                  setMode("login");
                  setError(null);
                }}
                className="text-velvet hover:underline font-medium cursor-pointer"
              >
                Sign in
              </button>
            </>
          ) : (
            <>
              Need another login?{" "}
              <button
                type="button"
                onClick={() => {
                  setMode("register");
                  setError(null);
                }}
                className="text-velvet hover:underline font-medium cursor-pointer"
              >
                Create new account
              </button>
            </>
          )}
        </div>
      </form>
    </Shell>
  );
}

export function SetupPage({ allowed }: { allowed: boolean }) {
  const { setup } = useAuth();
  const [username, setUsername] = useState("");
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [repeat, setRepeat] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (password !== repeat) return setError("The two passwords do not match.");
    setBusy(true);
    setError(null);
    try {
      await setup(username, password, name);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Shell title="Set up the studio" sub="Create the owner account. This is done once, on the computer that runs the studio.">
      {!allowed ? (
        <Notice tone="warning" title="Open the studio on its own computer">
          For safety, the first account can only be created from the machine running the studio (http://127.0.0.1:8000).
          You can also run <code>python -m app.cli create-user</code> there.
        </Notice>
      ) : (
        <form onSubmit={submit} className="space-y-4">
          <TextInput label="Your name" value={name} onChange={(e) => setName(e.target.value)} placeholder="Matthew" />
          <TextInput label="Username" autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} required
            pattern="[A-Za-z0-9_.@\-]+" hint="Letters, numbers, dots, dashes." />
          <TextInput label="Password" type="password" autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} required
            hint="At least 10 characters. A short sentence works well." />
          <TextInput label="Repeat password" type="password" autoComplete="new-password" value={repeat} onChange={(e) => setRepeat(e.target.value)} required />
          {error && <Notice tone="danger">{error}</Notice>}
          <Button variant="primary" size="lg" className="w-full" loading={busy} type="submit">Create account</Button>
        </form>
      )}
    </Shell>
  );
}
