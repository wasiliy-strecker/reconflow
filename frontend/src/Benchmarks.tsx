import { useEffect, useRef, useState } from "react";
import {
  Activity,
  Cpu,
  LockKeyhole,
  Play,
  RefreshCw,
  Square,
  Timer,
  Wallet,
} from "lucide-react";
import "./benchmarks.css";

type API = <T>(path: string, options?: RequestInit) => Promise<T>;
type Config = {
  enabled: boolean;
  configured: boolean;
  monthly_budget_eur: string;
  session_budget_eur: string;
  max_minutes: number;
  idle_seconds: number;
  protocol: string;
  models: {
    id: string;
    min_vram_mib: number;
    quantization: string;
    digest: string;
  }[];
  prompts: { id: string; text: string }[];
};
type Offer = {
  id: number;
  gpu: string;
  vram_mib: number;
  hourly_usd: string;
  estimated_eur: string;
  within_budget: boolean;
  download_usd_gb: string;
  upload_usd_gb: string;
  storage_usd_gb_month: string;
};
type Lease = {
  id: string;
  model: string;
  mode: string;
  status: string;
  offer: Offer;
  reserved_eur: string;
  estimated_eur: string;
  debited_eur: string | null;
  deadline_at: string;
  error: string | null;
};
type Sample = {
  index: number;
  warmup: boolean;
  output: string;
  elapsed_ms: number;
  ttft_ms: number | null;
  tokens_per_second: number | null;
  vram_peak_mib: number | null;
  gpu_only: boolean;
  eval_count: number;
};
type Result = {
  protocol: string;
  model: string;
  options: { num_ctx: number; num_predict: number };
  metadata: {
    gpu: string;
    driver: string;
    runtime_version: string;
    model_digest: string;
    quantization: string;
    download_ms: number;
    load_ms: number;
  };
  samples: Sample[];
  summary: {
    count: number;
    median_ttft_ms: number | null;
    median_elapsed_ms: number | null;
    peak_vram_mib: number | null;
    median_tokens_per_second: number | null;
    min_tokens_per_second: number | null;
    max_tokens_per_second: number | null;
    gpu_only: boolean;
  };
};
type Run = {
  id: string;
  gpu: string;
  model: string;
  finished_at: string;
  result: Omit<Result, "samples">;
};
type Job = {
  id: string;
  lease_id: string;
  status: string;
  error: string | null;
  progress: { sample?: number; text?: string };
  result: Omit<Result, "samples"> | null;
};
type Workspace = {
  leases: Lease[];
  requests: Job[];
  operator: boolean;
  budget: { reserved_eur: string; debited_eur: string } | null;
};

const empty: Workspace = {
  leases: [],
  requests: [],
  operator: false,
  budget: null,
};
const states: Record<string, string> = {
  queued: "Start vorgemerkt",
  creating: "GPU wird gemietet",
  unknown: "Zustand wird abgeglichen",
  starting: "Modell wird geladen",
  ready: "Bereit für Prompts",
  busy: "Test läuft",
  stopping: "GPU wird freigegeben",
  destroyed: "Freigabe bestätigt",
  failed: "Fehlgeschlagen",
  pending: "Wartet",
  running: "Läuft",
  succeeded: "Abgeschlossen",
};
const number = (v: number | null | undefined, digits = 1) =>
  v == null
    ? "—"
    : v.toLocaleString("de-DE", { maximumFractionDigits: digits });
const money = (v: string | undefined) => (v ? `${v} €` : "—");
const date = (v: string) => new Date(v).toLocaleString("de-DE");

export default function Benchmarks({
  api,
  ensureSession,
}: {
  api: API;
  ensureSession: () => Promise<void>;
}) {
  const [config, setConfig] = useState<Config | null>(null);
  const [workspace, setWorkspace] = useState(empty);
  const [offers, setOffers] = useState<Offer[]>([]);
  const [runs, setRuns] = useState<Run[]>([]);
  const [model, setModel] = useState("");
  const [offerId, setOfferId] = useState<number | null>(null);
  const [mode, setMode] = useState("suite");
  const [promptId, setPromptId] = useState("explain");
  const [series, setSeries] = useState(false);
  const [custom, setCustom] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [selected, setSelected] = useState<string[]>([]);
  const [filterModel, setFilterModel] = useState("");
  const [filterGpu, setFilterGpu] = useState("");
  const [detail, setDetail] = useState<Result | null>(null);
  const apiRef = useRef(api);
  apiRef.current = api;
  const requestKeys = useRef(new Map<string, string>());
  const mounted = useRef(true);
  const active = workspace.leases.find(
    (l) => !["destroyed", "failed"].includes(l.status),
  );
  const chosen = offers.find((o) => o.id === offerId);
  const requiredMemory =
    config?.models.find((m) => m.id === model)?.min_vram_mib ?? 0;

  async function loadWorkspace() {
    const data = await apiRef.current<Workspace>("/benchmarks/workspace");
    if (mounted.current) setWorkspace(data);
    return data;
  }
  async function loadResults() {
    const data = await apiRef.current<{ results: Run[] }>(
      "/benchmarks/results",
    );
    if (mounted.current) setRuns(data.results);
  }
  async function perform(label: string, action: () => Promise<void>) {
    setBusy(label);
    setError("");
    try {
      await action();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Aktion fehlgeschlagen.");
    } finally {
      if (mounted.current) setBusy("");
    }
  }
  async function send<T>(path: string, body: unknown): Promise<T> {
    const identity = path + JSON.stringify(body);
    const key = requestKeys.current.get(identity) ?? crypto.randomUUID();
    requestKeys.current.set(identity, key);
    const result = await apiRef.current<T>(path, {
      method: "POST",
      headers: { "Idempotency-Key": key },
      body: JSON.stringify(body),
    });
    requestKeys.current.delete(identity);
    return result;
  }
  useEffect(() => {
    mounted.current = true;
    apiRef
      .current<Config>("/benchmarks/config")
      .then((c) => {
        if (mounted.current) {
          setConfig(c);
          setModel(c.models[0]?.id ?? "");
        }
      })
      .catch((e) => setError(e.message));
    loadResults().catch((e) => setError(e.message));
    if (sessionStorage.getItem("rf_csrf")) loadWorkspace().catch(() => {});
    return () => {
      mounted.current = false;
    };
  }, []);
  useEffect(() => {
    if (!active) return;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    const tick = async () => {
      try {
        const data = await loadWorkspace();
        if (
          !data.leases.some((l) => !["destroyed", "failed"].includes(l.status))
        )
          await loadResults();
      } catch (e) {
        if (!stopped)
          setError(e instanceof Error ? e.message : "Status nicht erreichbar.");
      }
      if (!stopped) timer = setTimeout(tick, 2000);
    };
    timer = setTimeout(tick, 2000);
    return () => {
      stopped = true;
      clearTimeout(timer);
    };
  }, [active?.id]);

  const filtered = runs.filter(
    (r) =>
      (!filterModel || r.model === filterModel) &&
      (!filterGpu || r.gpu === filterGpu),
  );
  const compared = runs.filter((r) => selected.includes(r.id));
  return (
    <div className="gpu-page">
      <div className="page-heading">
        <div>
          <div className="eyebrow">LOKALE MODELLE. ECHTE MESSWERTE.</div>
          <h1>GPU Benchmarks.</h1>
          <p>GPU auswählen, Gemma testen und nachvollziehbar vergleichen.</p>
        </div>
        <span className="pill neutral">
          <Cpu size={16} /> Vast.ai · Ollama · AWS
        </span>
      </div>
      <div className="gpu-stats">
        <div>
          <Wallet />
          <span>
            Monatsbudget<strong>{money(config?.monthly_budget_eur)}</strong>
          </span>
        </div>
        <div>
          <Timer />
          <span>
            Je GPU-Sitzung
            <strong>
              {money(config?.session_budget_eur)} · {config?.max_minutes ?? 30}{" "}
              Min.
            </strong>
          </span>
        </div>
        <div>
          <Activity />
          <span>
            Automatische Freigabe
            <strong>
              Nach {Math.floor((config?.idle_seconds ?? 300) / 60)} Min.
              Inaktivität
            </strong>
          </span>
        </div>
      </div>
      {error && (
        <div className="gpu-alert" role="alert">
          {error}
        </div>
      )}
      {config && (!config.enabled || !config.configured) && (
        <div className="gpu-info" role="status">
          <strong>GPU-Mieten sind noch nicht freigeschaltet.</strong>
          <p>
            Gespeicherte echte Benchmarks bleiben verfügbar. Neue Tests
            benötigen die eingerichtete GPU-Verbindung und eine aktive
            automatische Freigabe.
          </p>
        </div>
      )}
      <div className="gpu-layout">
        <section className="gpu-card">
          <div className="gpu-card-title">
            <h2>1. GPU und Modell wählen</h2>
            <button
              className="button secondary small-button"
              disabled={!!busy}
              onClick={() =>
                perform("Angebote werden geladen …", async () => {
                  await ensureSession();
                  const data = await apiRef.current<{
                    offers: Offer[];
                    available: boolean;
                  }>("/benchmarks/offers");
                  setOffers(data.offers);
                  await loadWorkspace();
                  if (!data.available)
                    setError("Vast.ai ist noch nicht verbunden.");
                })
              }
            >
              <RefreshCw size={15} /> Angebote laden
            </button>
          </div>
          <div className="gpu-fields">
            <label>
              Modell
              <select value={model} onChange={(e) => setModel(e.target.value)}>
                {config?.models.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.id}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Testmodus
              <select value={mode} onChange={(e) => setMode(e.target.value)}>
                <option value="suite">Standardbenchmark · 15 Messungen</option>
                <option value="live">Live-Sitzung · einzelne Prompts</option>
              </select>
            </label>
          </div>
          <p className="gpu-muted">
            Einzel-GPUs mit mindestens {number(requiredMemory / 1024, 0)} GiB
            VRAM. Preise stammen aus aktuellen Vast-Angeboten.
          </p>
          <div
            className="gpu-offers"
            role="radiogroup"
            aria-label="GPU-Angebote"
          >
            {offers.map((o) => (
              <label
                key={o.id}
                className={"gpu-offer " + (offerId === o.id ? "selected" : "")}
              >
                <input
                  type="radio"
                  name="gpu-offer"
                  value={o.id}
                  checked={offerId === o.id}
                  disabled={
                    !o.within_budget || o.vram_mib < requiredMemory || !!active
                  }
                  onChange={() => setOfferId(o.id)}
                />
                <span>
                  <strong>{o.gpu}</strong>
                  <small>
                    {number(o.vram_mib / 1024, 0)} GiB VRAM · Angebot {o.id}
                  </small>
                  <small>
                    {o.within_budget
                      ? "Im Sitzungsbudget"
                      : "Über dem Sitzungsbudget"}
                  </small>
                </span>
                <span>
                  <strong>{o.hourly_usd} $/h</strong>
                  <small>Planung: {o.estimated_eur} €</small>
                </span>
              </label>
            ))}
            {!offers.length && (
              <div className="gpu-empty">
                <Cpu size={30} />
                <p>Noch keine Angebote geladen.</p>
                <small>
                  Verfügbarkeit und Preise werden beim Start erneut geprüft.
                </small>
              </div>
            )}
          </div>
          {chosen && (
            <p className="gpu-muted">
              Speicher: {chosen.storage_usd_gb_month} $/GB/Monat · Download:{" "}
              {chosen.download_usd_gb} $/GB · Upload: {chosen.upload_usd_gb}{" "}
              $/GB. Die Planung enthält Laufzeit, Speicher, Transfer und
              Abschaltpuffer.
            </p>
          )}
          <button
            className="button primary gpu-wide"
            disabled={
              !!busy ||
              !!active ||
              !config?.enabled ||
              !config.configured ||
              !chosen?.within_budget ||
              chosen.vram_mib < requiredMemory
            }
            onClick={() =>
              perform("GPU wird angefordert …", async () => {
                await ensureSession();
                await send("/benchmarks/leases", {
                  offer_id: chosen!.id,
                  model,
                  mode,
                  hourly_usd: chosen!.hourly_usd,
                });
                await loadWorkspace();
              })
            }
          >
            <Play size={17} /> GPU mieten und{" "}
            {mode === "suite" ? "Benchmark starten" : "Live-Sitzung starten"}
          </button>
          <p className="gpu-muted">
            Bis zu {money(config?.session_budget_eur)} werden reserviert.
            Standardtests geben die GPU nach Abschluss automatisch frei.
          </p>
        </section>
        <section className="gpu-card">
          <div className="gpu-card-title">
            <h2>2. Live verfolgen</h2>
            <span className="pill neutral">
              {active ? states[active.status] : "Keine aktive GPU"}
            </span>
          </div>
          {active ? (
            <>
              <div className="gpu-active">
                <Cpu />
                <div>
                  <strong>{active.offer.gpu}</strong>
                  <small>{active.model}</small>
                  <small>
                    Spätestes Laufzeitende: {date(active.deadline_at)}
                  </small>
                </div>
              </div>
              {active.error && <p role="status">{active.error}</p>}
              <button
                className="button secondary gpu-wide"
                disabled={!!busy || active.status === "stopping"}
                onClick={() =>
                  perform("Freigabe wird angefordert …", async () => {
                    await apiRef.current(
                      `/benchmarks/leases/${active.id}/stop`,
                      { method: "POST" },
                    );
                    await loadWorkspace();
                  })
                }
              >
                <Square size={16} /> GPU freigeben
              </button>
            </>
          ) : (
            <div className="gpu-empty">
              <Activity size={30} />
              <p>Bereit für deinen nächsten Test.</p>
              <small>
                Hier erscheinen Fortschritt, Antworten und der bestätigte
                Freigabestatus.
              </small>
            </div>
          )}
          {active?.mode === "live" && (
            <div className="gpu-prompts">
              <label>
                Vorbereiteter Prompt
                <select
                  value={promptId}
                  onChange={(e) => setPromptId(e.target.value)}
                >
                  {config?.prompts.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.id}
                    </option>
                  ))}
                </select>
              </label>
              <p>{config?.prompts.find((p) => p.id === promptId)?.text}</p>
              <label className="gpu-check">
                <input
                  type="checkbox"
                  checked={series}
                  onChange={(e) => setSeries(e.target.checked)}
                />{" "}
                Alle fünf Prompts nacheinander
              </label>
              {workspace.operator && (
                <label>
                  Freier Prompt (privat)
                  <textarea
                    maxLength={4000}
                    value={custom}
                    onChange={(e) => setCustom(e.target.value)}
                    placeholder="Optional: eigener Prompt statt der Vorlagen"
                  />
                </label>
              )}
              <button
                className="button primary gpu-wide"
                disabled={!!busy || active.status !== "ready"}
                onClick={() =>
                  perform("Anfrage wird gestartet …", async () => {
                    const body =
                      custom.trim() && workspace.operator
                        ? { custom_prompts: [custom.trim()] }
                        : {
                            prompt_ids: series
                              ? config!.prompts.map((p) => p.id)
                              : [promptId],
                          };
                    await send(
                      `/benchmarks/leases/${active.id}/requests`,
                      body,
                    );
                    await loadWorkspace();
                  })
                }
              >
                <Play size={16} /> Anfrage senden
              </button>
            </div>
          )}
          {workspace.requests.slice(0, 3).map((job) => (
            <div className="gpu-job" key={job.id}>
              <strong>{states[job.status] ?? job.status}</strong>
              {job.error && <p>{job.error}</p>}
              {job.progress.text && (
                <>
                  <small>Messung {(job.progress.sample ?? 0) + 1}</small>
                  <pre aria-live="polite">{job.progress.text}</pre>
                </>
              )}
              {job.result && (
                <>
                  <p>
                    {number(job.result.summary.median_tokens_per_second)}{" "}
                    Tokens/s · {job.result.summary.count} Messungen
                  </p>
                  <button
                    className="button secondary small-button"
                    onClick={() =>
                      perform("Messbericht wird geladen …", async () => {
                        const data = await apiRef.current<{ result: Result }>(
                          `/benchmarks/requests/${job.id}`,
                        );
                        setDetail(data.result);
                      })
                    }
                  >
                    Messbericht öffnen
                  </button>
                </>
              )}
            </div>
          ))}
          {workspace.leases
            .filter((l) => ["destroyed", "failed"].includes(l.status))
            .slice(0, 2)
            .map((l) => (
              <p key={l.id} className="gpu-muted">
                {l.offer.gpu}: {states[l.status]}
                {l.error ? ` · ${l.error}` : ""}
              </p>
            ))}
          {workspace.budget && (
            <p className="gpu-muted">
              Reserviert: {workspace.budget.reserved_eur} € · Budgetbelastung:{" "}
              {workspace.budget.debited_eur} €. Die volle Reservierung wird
              vorsorglich als Budgetverbrauch gezählt; dies ist keine
              Anbieterrechnung.
            </p>
          )}
          <details className="gpu-operator">
            <summary>
              <LockKeyhole size={15} /> Betreiberzugang
            </summary>
            {workspace.operator ? (
              <>
                <p>Freie Prompts sind für diese Sitzung freigeschaltet.</p>
                <button
                  className="button secondary small-button"
                  onClick={() =>
                    perform("Abmeldung …", async () => {
                      await apiRef.current("/benchmarks/operator/logout", {
                        method: "POST",
                      });
                      setCustom("");
                      await loadWorkspace();
                    })
                  }
                >
                  Abmelden
                </button>
              </>
            ) : (
              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  perform("Anmeldung …", async () => {
                    await ensureSession();
                    try {
                      await apiRef.current("/benchmarks/operator/login", {
                        method: "POST",
                        body: JSON.stringify({ password }),
                      });
                      await loadWorkspace();
                    } finally {
                      setPassword("");
                    }
                  });
                }}
              >
                <label>
                  Betreiberpasswort
                  <input
                    type="password"
                    autoComplete="current-password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    required
                  />
                </label>
                <button
                  className="button secondary small-button"
                  disabled={!!busy}
                >
                  Anmelden
                </button>
              </form>
            )}
          </details>
        </section>
      </div>
      <section className="gpu-card gpu-comparison">
        <div className="gpu-card-title">
          <div>
            <h2>3. Ergebnisse vergleichen</h2>
            <p className="gpu-muted">
              Ausschließlich abgeschlossene Standardtests. Unterschiedliche
              Modelle und Quantisierungen werden sichtbar ausgewiesen.
            </p>
          </div>
          <button
            className="button secondary small-button"
            disabled={!!busy}
            onClick={() => perform("Ergebnisse laden …", loadResults)}
          >
            <RefreshCw size={15} /> Aktualisieren
          </button>
        </div>
        <div className="gpu-fields">
          <label>
            GPU filtern
            <select
              value={filterGpu}
              onChange={(e) => setFilterGpu(e.target.value)}
            >
              <option value="">Alle GPUs</option>
              {[...new Set(runs.map((r) => r.gpu))].map((g) => (
                <option key={g}>{g}</option>
              ))}
            </select>
          </label>
          <label>
            Modell filtern
            <select
              value={filterModel}
              onChange={(e) => setFilterModel(e.target.value)}
            >
              <option value="">Alle Modelle</option>
              {[...new Set(runs.map((r) => r.model))].map((m) => (
                <option key={m}>{m}</option>
              ))}
            </select>
          </label>
        </div>
        {!filtered.length ? (
          <div className="gpu-empty">
            <Cpu size={30} />
            <p>Noch keine echten Benchmark-Ergebnisse vorhanden.</p>
            <small>
              Nach dem ersten erfolgreichen Standardtest erscheinen hier die
              gemessenen Werte.
            </small>
          </div>
        ) : (
          <div className="gpu-table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Vergleich</th>
                  <th>GPU / Modell</th>
                  <th>Tokens/s (Median)</th>
                  <th>Spanne</th>
                  <th>Erstes Token (Median)</th>
                  <th>Antwortzeit (Median)</th>
                  <th>VRAM-Spitze</th>
                  <th>Messungen</th>
                  <th>Zeitpunkt</th>
                  <th>Bericht</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((r) => (
                  <tr key={r.id}>
                    <td>
                      <input
                        type="checkbox"
                        aria-label={`Vergleichen ${r.gpu} ${r.id}`}
                        checked={selected.includes(r.id)}
                        disabled={
                          !selected.includes(r.id) && selected.length >= 4
                        }
                        onChange={(e) =>
                          setSelected(
                            e.target.checked
                              ? [...selected, r.id]
                              : selected.filter((id) => id !== r.id),
                          )
                        }
                      />
                    </td>
                    <td>
                      <strong>{r.gpu}</strong>
                      <small>{r.model}</small>
                      {!r.result.summary.gpu_only && (
                        <small>CPU-Offloading · kein reiner GPU-Test</small>
                      )}
                    </td>
                    <td>{number(r.result.summary.median_tokens_per_second)}</td>
                    <td>
                      {number(r.result.summary.min_tokens_per_second)}–
                      {number(r.result.summary.max_tokens_per_second)}
                    </td>
                    <td>{number(r.result.summary.median_ttft_ms)} ms</td>
                    <td>{number(r.result.summary.median_elapsed_ms)} ms</td>
                    <td>{number(r.result.summary.peak_vram_mib, 0)} MiB</td>
                    <td>{r.result.summary.count}</td>
                    <td>{date(r.finished_at)}</td>
                    <td>
                      <button
                        className="button secondary small-button"
                        onClick={() =>
                          perform("Messbericht wird geladen …", async () => {
                            const data = await apiRef.current<{
                              result: Result;
                            }>(`/benchmarks/results/${r.id}`);
                            setDetail(data.result);
                          })
                        }
                      >
                        Öffnen
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {compared.length > 0 && (
          <div className="gpu-compare-cards">
            {compared.map((r) => (
              <article key={r.id}>
                <h3>{r.gpu}</h3>
                <p>{r.model}</p>
                <strong>
                  {number(r.result.summary.median_tokens_per_second)} Tokens/s
                </strong>
                <p>
                  {r.result.metadata.quantization} · Kontext{" "}
                  {r.result.options.num_ctx}
                </p>
                <small>
                  {r.result.protocol} · Ollama{" "}
                  {r.result.metadata.runtime_version}
                </small>
                <small>
                  Digest {r.result.metadata.model_digest.slice(0, 16)}…
                </small>
              </article>
            ))}
          </div>
        )}
      </section>
      {detail && (
        <section className="gpu-card" aria-label="Messbericht">
          <div className="gpu-card-title">
            <h2>Messbericht · {detail.metadata.gpu}</h2>
            <button
              className="button secondary small-button"
              onClick={() => setDetail(null)}
            >
              Schließen
            </button>
          </div>
          <p>
            {detail.model} · {detail.metadata.quantization} · Ollama{" "}
            {detail.metadata.runtime_version} · Treiber {detail.metadata.driver}
          </p>
          <p className="gpu-muted">
            Modelldownload: {number(detail.metadata.download_ms / 1000)} s ·
            Modellladen: {number(detail.metadata.load_ms / 1000)} s. TTFT und
            Antwortzeit werden am GPU-Runner gemessen. Cacheverhalten folgt dem
            dokumentierten Testprotokoll.
          </p>
          <div className="gpu-table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Lauf</th>
                  <th>Tokens/s</th>
                  <th>Erstes Token</th>
                  <th>Antwortzeit</th>
                  <th>VRAM-Spitze</th>
                  <th>Ausgabetokens</th>
                </tr>
              </thead>
              <tbody>
                {detail.samples.map((s) => (
                  <tr key={s.index}>
                    <td>{s.warmup ? "Aufwärmen" : s.index + 1}</td>
                    <td>{number(s.tokens_per_second)}</td>
                    <td>{number(s.ttft_ms)} ms</td>
                    <td>{number(s.elapsed_ms)} ms</td>
                    <td>{number(s.vram_peak_mib, 0)} MiB</td>
                    <td>{s.eval_count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {detail.samples.map((s) => (
            <details key={s.index}>
              <summary>
                Antwort {s.index + 1}
                {s.warmup ? " · Aufwärmlauf" : ""}
              </summary>
              <pre>{s.output}</pre>
            </details>
          ))}
        </section>
      )}
      {busy && (
        <div className="gpu-working" role="status">
          {busy}
        </div>
      )}
    </div>
  );
}
