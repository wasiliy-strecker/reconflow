import { useEffect, useRef, useState } from "react";
import {
  ArrowDownToLine,
  ArrowRight,
  ArrowUpRight,
  Check,
  CheckCheck,
  ChevronRight,
  CircleAlert,
  Cpu,
  FileCheck2,
  FileSpreadsheet,
  FileText,
  FolderOpen,
  LayoutDashboard,
  LoaderCircle,
  Plus,
  RefreshCw,
  Search,
  ShieldCheck,
  Sparkles,
  Upload,
  Wallet,
  X,
  Zap,
} from "lucide-react";

import Benchmarks from "./Benchmarks";

type InvoiceData = {
  invoice_number: string | null;
  issuer: string | null;
  customer: string | null;
  invoice_date: string | null;
  due_date: string | null;
  currency: string | null;
  net_amount: string | null;
  tax_amount: string | null;
  gross_amount: string | null;
  line_items: {
    description: string;
    quantity: string | null;
    amount: string | null;
  }[];
  warnings: string[];
  evidence: { field: string; page: number | null; text: string }[];
};
type Invoice = {
  id: string;
  document_id: string | null;
  payload: InvoiceData;
  confirmed: boolean;
  source: string;
  version: number;
  filename: string | null;
  mime: string | null;
  issues: string[];
};
type Payment = {
  id: string;
  external_id: string;
  reference: string;
  amount: string;
  currency: string;
  paid_at: string;
  payer: string;
};
type Match = {
  invoice_id: string | null;
  invoice_number: string | null;
  customer: string;
  status: string;
  reason_code: string;
  reason: string;
  payment_ids: string[];
  expected: string;
  received: string;
  difference: string;
  currency: string;
  candidates: string[];
};
type Job = {
  id: string;
  kind: string;
  target: string;
  status: string;
  error: string | null;
  payload: {
    invoice_id?: string;
    reason?: string;
    versions?: Record<string, number>;
    payment_id?: string;
  };
};
type Run = {
  id: string;
  stale?: boolean;
  payload: {
    results: Match[];
    invoice_versions: Record<string, number>;
    payment_ids: string[];
  };
};
type Workspace = {
  totals?: Record<string, string>;
  invoices: Invoice[];
  documents: { id: string; filename: string; mime: string }[];
  payments: Payment[];
  jobs: Job[];
  run: Run | null;
};
type Config = {
  mode: string;
  ai_available: boolean;
  model: string;
  monthly_budget_eur: string;
};

const empty: Workspace = {
  invoices: [],
  documents: [],
  payments: [],
  jobs: [],
  run: null,
};
const labels: Record<string, string> = {
  MATCHED: "Zugeordnet",
  PARTIAL: "Teilzahlung",
  REVIEW: "Prüfen",
  UNMATCHED: "Offen",
  DUPLICATE: "Duplikatverdacht",
};
const money = (value: string | number | null, currency = "EUR") =>
  new Intl.NumberFormat("de-DE", { style: "currency", currency }).format(
    Number(value || 0),
  );
const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

export default function App() {
  const [config, setConfig] = useState<Config>({
    mode: "local",
    ai_available: false,
    model: "",
    monthly_budget_eur: "10",
  });
  const [workspace, setWorkspace] = useState<Workspace>(empty);
  const [active, setActive] = useState(false);
  const [tab, setTab] = useState("invoices");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState("ALL");
  const [selected, setSelected] = useState<string | null>(null);
  const [draft, setDraft] = useState<InvoiceData | null>(null);
  const [selectedMatch, setSelectedMatch] = useState<Match | null>(null);
  const [suggestion, setSuggestion] = useState<Job["payload"] | null>(null);
  const [showImport, setShowImport] = useState(false);
  const [importKind, setImportKind] = useState("document");
  const csrf = useRef(sessionStorage.getItem("rf_csrf") || "");
  const inputRef = useRef<HTMLInputElement>(null);

  const modalOpen = showImport || !!selected || !!selectedMatch;
  useEffect(() => {
    if (!modalOpen) return;
    const previous = document.activeElement as HTMLElement | null;
    const dialog = document.querySelector<HTMLElement>('[role="dialog"]');
    const focusable = () =>
      Array.from(
        dialog?.querySelectorAll<HTMLElement>(
          "button:not(:disabled),a[href],input:not(:disabled),select,textarea,summary",
        ) || [],
      ).filter((el) => el.getClientRects().length > 0);
    focusable()[0]?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setShowImport(false);
        setSelected(null);
        setSelectedMatch(null);
      }
      if (event.key === "Tab") {
        const items = focusable();
        const first = items[0];
        const last = items[items.length - 1];
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last?.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first?.focus();
        }
      }
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      previous?.focus();
    };
  }, [modalOpen]);

  async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
    const headers = new Headers(options.headers);
    if (csrf.current) headers.set("X-CSRF-Token", csrf.current);
    if (options.body && !(options.body instanceof FormData))
      headers.set("Content-Type", "application/json");
    for (let attempt = 0; attempt < 8; attempt++) {
      const response = await fetch("/api" + path, {
        ...options,
        headers,
        credentials: "same-origin",
      });
      if (response.status === 503 && attempt < 7) {
        setNotice(
          "Die Demo wird gestartet. Das kann nach einer Pause etwas dauern.",
        );
        await sleep(5000);
        continue;
      }
      const data = await response.json();
      if (!response.ok)
        throw new Error(
          typeof data.detail === "string"
            ? data.detail
            : "Bitte Eingaben prüfen und erneut versuchen.",
        );
      return data as T;
    }
    throw new Error("Die Demo konnte gerade nicht gestartet werden.");
  }

  async function load() {
    const data = await api<Workspace>("/workspace");
    setWorkspace(data);
    return data;
  }
  async function ensureSession() {
    if (active) return;
    const data = await api<{ csrf_token: string }>("/demo-sessions", {
      method: "POST",
    });
    csrf.current = data.csrf_token;
    sessionStorage.setItem("rf_csrf", data.csrf_token);
    setActive(true);
  }
  async function perform(message: string, action: () => Promise<void>) {
    setBusy(message);
    setError("");
    setNotice("");
    try {
      await action();
    } catch (e) {
      setError(
        e instanceof Error
          ? e.message
          : "Die Aktion konnte nicht abgeschlossen werden.",
      );
    } finally {
      setBusy("");
    }
  }
  useEffect(() => {
    fetch("/api/config")
      .then((r) => r.json())
      .then(setConfig)
      .catch(() => setError("Das Backend ist noch nicht erreichbar."));
    if (csrf.current) {
      api<{ csrf_token: string }>("/demo-sessions/current")
        .then((data) => {
          csrf.current = data.csrf_token;
          setActive(true);
          return load();
        })
        .catch(() => {
          csrf.current = "";
          sessionStorage.removeItem("rf_csrf");
        });
    }
  }, []);

  async function startDemo() {
    await perform("Beispieldaten werden geladen …", async () => {
      await ensureSession();
      const data = await api<Workspace>("/demo-sessions/seed", {
        method: "POST",
      });
      setWorkspace(data);
      setNotice(
        "Sechs synthetische Rechnungen und sechs Zahlungen sind bereit. Wähle eine Rechnung für die echte KI-Auswertung.",
      );
    });
  }

  async function waitForJob(job: Job) {
    for (let i = 0; i < 90; i++) {
      const current = await api<Job>("/jobs/" + job.id);
      if (current.status === "failed")
        throw new Error(current.error || "Verarbeitung fehlgeschlagen.");
      if (current.status === "succeeded") {
        await load();
        return current;
      }
      await sleep(2000);
    }
    throw new Error(
      "Die Verarbeitung dauert länger. Den Status findest du unter Aktivitäten.",
    );
  }
  function openInvoice(invoice: Invoice) {
    setSelected(invoice.id);
    setDraft(structuredClone(invoice.payload));
    setSelectedMatch(null);
  }
  async function extract(docId: string) {
    await perform("OpenAI liest die Rechnung …", async () => {
      const job = await api<Job>("/documents/" + docId + "/extract", {
        method: "POST",
      });
      const finished = await waitForJob(job);
      const data = await load();
      const invoice = data.invoices.find(
        (i) => i.id === finished.payload.invoice_id,
      );
      if (invoice) openInvoice(invoice);
      setNotice(
        "Die KI-Auswertung ist fertig. Bitte erkannte Angaben am Original prüfen und bestätigen.",
      );
    });
  }
  async function confirm() {
    if (!selected || !draft) return;
    const current = workspace.invoices.find((i) => i.id === selected);
    if (!current) return;
    await perform("Rechnung wird bestätigt …", async () => {
      await api("/invoices/" + selected, {
        method: "PUT",
        body: JSON.stringify({ data: draft, version: current.version }),
      });
      await load();
      setSelected(null);
      setDraft(null);
      setNotice(
        "Rechnung bestätigt. Die Daten können jetzt abgeglichen werden.",
      );
    });
  }
  async function match() {
    await perform("Zahlungen werden abgeglichen …", async () => {
      await waitForJob(
        await api<Job>("/reconciliation-runs", { method: "POST" }),
      );
      setTab("matches");
      setNotice(
        "Abgleich abgeschlossen. Jeder Fall zeigt die angewendete Regel.",
      );
    });
  }
  async function upload(file: File) {
    await perform("Datei wird geprüft …", async () => {
      await ensureSession();
      const body = new FormData();
      body.append("file", file);
      const endpoint =
        importKind === "document"
          ? "/documents"
          : importKind === "payments"
            ? "/imports/payments"
            : "/imports/invoices";
      const result = await api<{
        id?: string;
        inserted?: number;
        duplicates?: number;
        errors?: { line: number; message: string }[];
      }>(endpoint, { method: "POST", body });
      if (result.errors?.length)
        throw new Error(
          result.errors.map((e) => `Zeile ${e.line}: ${e.message}`).join(" · "),
        );
      await load();
      setShowImport(false);
      if (importKind === "document")
        setNotice("Dokument hochgeladen. Starte jetzt die KI-Auswertung.");
      else
        setNotice(
          `${result.inserted || 0} Einträge importiert. ${result.duplicates || 0} bereits vorhandene Einträge übersprungen.`,
        );
    });
  }
  async function requestSuggestion(row: Match) {
    await perform("KI prüft mögliche Zuordnungen …", async () => {
      const job = await api<Job>(
        "/payments/" + row.payment_ids[0] + "/suggest",
        { method: "POST" },
      );
      const result = await waitForJob(job);
      setSuggestion(result.payload);
    });
  }
  async function applyDecision(invoiceId: string) {
    if (!selectedMatch) return;
    const invoice = workspace.invoices.find((i) => i.id === invoiceId);
    if (!invoice) return;
    await perform("Zuordnung wird übernommen …", async () => {
      await api("/reconciliation-decisions", {
        method: "POST",
        body: JSON.stringify({
          payment_id: selectedMatch.payment_ids[0],
          invoice_id: invoiceId,
          invoice_version: suggestion?.versions?.[invoiceId] ?? invoice.version,
        }),
      });
      await load();
      setSelectedMatch(null);
      setSuggestion(null);
      setNotice(
        "Deine Zuordnung wurde protokolliert und der Abgleich aktualisiert.",
      );
    });
  }
  async function download() {
    if (!workspace.run) return;
    await perform("Bericht wird erstellt …", async () => {
      const response = await fetch(
        "/api/reports/" + workspace.run!.id + ".xlsx",
      );
      if (!response.ok) {
        const body = await response.json();
        throw new Error(body.detail);
      }
      const url = URL.createObjectURL(await response.blob());
      const a = document.createElement("a");
      a.href = url;
      a.download = "ReconFlow-Abgleich.xlsx";
      a.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    });
  }

  const rows = workspace.run?.stale ? [] : workspace.run?.payload.results || [];
  const selectedInvoice = workspace.invoices.find((i) => i.id === selected);
  const visibleInvoices = workspace.invoices.filter((i) =>
    [i.payload.invoice_number, i.payload.customer]
      .join(" ")
      .toLowerCase()
      .includes(query.toLowerCase()),
  );
  const visibleMatches = rows.filter(
    (r) =>
      (filter === "ALL" || r.status === filter) &&
      [r.invoice_number, r.customer, r.reason]
        .join(" ")
        .toLowerCase()
        .includes(query.toLowerCase()),
  );
  const total =
    workspace.totals?.[workspace.invoices[0]?.payload.currency || "EUR"] ||
    "0.00";
  const mixedCurrencies =
    new Set(workspace.invoices.map((i) => i.payload.currency)).size > 1;
  const matched = rows.filter(
    (r) => r.invoice_id && r.status === "MATCHED",
  ).length;
  const review = rows.filter((r) =>
    ["REVIEW", "DUPLICATE", "PARTIAL"].includes(r.status),
  ).length;
  const missingDocs = workspace.documents.filter(
    (d) => !workspace.invoices.some((i) => i.document_id === d.id),
  );
  const currency = workspace.invoices[0]?.payload.currency || "EUR";

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <a className="brand" href="/" aria-label="ReconFlow Start">
          <span className="brand-icon">
            <CheckCheck size={25} />
          </span>
          Recon<span>Flow</span>
          <span className="brand-dot">.</span>
        </a>
        <div className="workspace-label">
          <span className="avatar">RF</span>
          <div>
            Dein Demo-Arbeitsplatz<small>Alles im Blick</small>
          </div>
        </div>
        <div className="nav-caption">ARBEITSBEREICH</div>
        <nav aria-label="Hauptnavigation">
          {[
            ["invoices", "Rechnungen", FileText],
            ["matches", "Zahlungsabgleich", CheckCheck],
            ["payments", "Zahlungen", Wallet],
            ["activity", "Aktivitäten", LayoutDashboard],
            ["benchmarks", "GPU Benchmarks", Cpu],
          ].map(([key, label, Icon]) => {
            const I = Icon as typeof FileText;
            return (
              <button
                key={String(key)}
                className={"nav-item " + (tab === key ? "active" : "")}
                onClick={() => {
                  setTab(String(key));
                  setQuery("");
                }}
              >
                <I size={19} />
                {String(label)}
                {key === "invoices" && workspace.invoices.length > 0 && (
                  <span className="nav-count">{workspace.invoices.length}</span>
                )}
              </button>
            );
          })}
        </nav>
        <div className="sidebar-bottom">
          <div className="demo-note">
            <Sparkles size={19} />
            <strong>Ausprobieren. Verstehen.</strong>
            <p>Echte Abläufe mit fiktiven Rechnungen und Zahlungen.</p>
            <button onClick={startDemo} disabled={!!busy}>
              Beispieldaten laden <ArrowRight size={15} />
            </button>
          </div>
          <a
            href="/api/docs"
            target="_blank"
            rel="noreferrer"
            className="docs-link"
          >
            API-Dokumentation <ArrowUpRight size={15} />
          </a>
          <div className="sidebar-foot">
            <span className="avatar small">WS</span>
            <span>
              Portfolio von wasiliy-strecker<small>Python · Cloud · KI</small>
            </span>
          </div>
        </div>
      </aside>
      <div className="main-shell">
        <header className="topbar">
          <div className="breadcrumb">
            Arbeitsbereich <ChevronRight size={14} />
            <strong>
              {
                {
                  invoices: "Rechnungen",
                  matches: "Zahlungsabgleich",
                  payments: "Zahlungen",
                  activity: "Aktivitäten",
                  benchmarks: "GPU Benchmarks",
                }[tab]
              }
            </strong>
          </div>
          <div className="topbar-right">
            <span className="pill neutral">
              <span className="live-dot" />
              Live-Demo
            </span>
            <span className="top-avatar">WS</span>
          </div>
        </header>
        <main>
          {tab === "benchmarks" ? (
            <Benchmarks api={api} ensureSession={ensureSession} />
          ) : (
            <>
              <div className="page-heading">
                <div>
                  <div className="eyebrow">WENIGER SUCHEN. MEHR ÜBERBLICK.</div>
                  <h1>
                    {
                      {
                        invoices: "Rechnungen verstehen.",
                        matches: "Jede Zahlung an ihrem Platz.",
                        payments: "Zahlungseingänge im Blick.",
                        activity: "Jeder Schritt nachvollziehbar.",
                      }[tab]
                    }
                  </h1>
                  <p>
                    Von der Rechnung zur passenden Zahlung. Mit KI und klaren
                    Regeln.
                  </p>
                </div>
                <div className="heading-actions">
                  <button
                    className="button secondary"
                    onClick={() => {
                      setImportKind("payments");
                      setShowImport(true);
                    }}
                    disabled={!!busy}
                  >
                    <FileSpreadsheet size={17} />
                    CSV importieren
                  </button>
                  <button
                    className="button primary"
                    onClick={() => {
                      setImportKind("document");
                      setShowImport(true);
                    }}
                    disabled={!!busy}
                  >
                    <Plus size={18} />
                    Rechnung hinzufügen
                  </button>
                </div>
              </div>
              <div className="demo-banner">
                <div className="banner-icon">
                  <ShieldCheck size={20} />
                </div>
                <div>
                  <strong>Dein Platz zum Ausprobieren</strong>
                  <span>
                    Alle mitgelieferten Daten sind fiktiv. Deine Sitzung ist für
                    andere Besucher nicht sichtbar.
                  </span>
                </div>
                <span className="demo-tag">BEISPIELDATEN</span>
              </div>
              {error && (
                <div role="alert" className="message error">
                  <CircleAlert size={19} />
                  <span>{error}</span>
                  <button
                    aria-label="Meldung schließen"
                    onClick={() => setError("")}
                  >
                    <X size={17} />
                  </button>
                </div>
              )}
              {notice && !error && (
                <div role="status" className="message success">
                  <Check size={18} />
                  <span>{notice}</span>
                  <button
                    aria-label="Meldung schließen"
                    onClick={() => setNotice("")}
                  >
                    <X size={17} />
                  </button>
                </div>
              )}
              {busy && (
                <div className="working" role="status">
                  <LoaderCircle className="spin" size={18} />
                  {busy}
                </div>
              )}
              {workspace.run?.stale && (
                <div role="status" className="message">
                  Die Rechnungen wurden geändert. Bitte den Abgleich erneut
                  starten.
                </div>
              )}
              <section className="stats" aria-label="Übersicht">
                <div className="stat">
                  <div className="stat-top">
                    Rechnungsvolumen <FileText size={18} />
                  </div>
                  <strong>
                    {workspace.invoices.length
                      ? mixedCurrencies
                        ? "Mehrere Währungen"
                        : money(total, currency)
                      : "—"}
                  </strong>
                  <span>
                    {workspace.invoices.length} Rechnungen im Arbeitsplatz
                  </span>
                </div>
                <div className="stat">
                  <div className="stat-top">
                    Zugeordnet{" "}
                    <span className="stat-icon green">
                      <CheckCheck size={17} />
                    </span>
                  </div>
                  <strong>
                    {workspace.run ? matched : "—"}
                    <small>Rechnungen</small>
                  </strong>
                  <span>Referenz, Betrag und Währung stimmen</span>
                </div>
                <div className="stat">
                  <div className="stat-top">
                    Noch zu prüfen{" "}
                    <span className="stat-icon amber">
                      <CircleAlert size={17} />
                    </span>
                  </div>
                  <strong>
                    {workspace.run ? review : "—"}
                    <small>Fälle</small>
                  </strong>
                  <span>Abweichungen nachvollziehbar klären</span>
                </div>
                <div className="stat">
                  <div className="stat-top">
                    Zahlungseingänge <Wallet size={18} />
                  </div>
                  <strong>
                    {workspace.payments.length}
                    <small>Einträge</small>
                  </strong>
                  <span>Über CSV importiert und geprüft</span>
                </div>
              </section>
              {!workspace.invoices.length && !missingDocs.length && (
                <section className="welcome-card">
                  <div className="welcome-copy">
                    <span className="pill green">
                      <Sparkles size={14} />
                      DEIN ERSTER ABGLEICH
                    </span>
                    <h2>
                      Sechs Rechnungen.
                      <br />
                      Ein klarer Überblick.
                    </h2>
                    <p>
                      Entdecke passende Zahlungen, eine Teilzahlung und einen
                      möglichen Doppeleingang. Oder lass eine Beispielrechnung
                      direkt von der KI auslesen.
                    </p>
                    <button
                      className="button primary"
                      onClick={startDemo}
                      disabled={!!busy}
                    >
                      Demo starten <ArrowRight size={17} />
                    </button>
                    <small>
                      Ohne Anmeldung · Mit herunterladbaren Beispielen
                    </small>
                  </div>
                  <div className="welcome-visual" aria-hidden="true">
                    <div className="mini-doc">
                      <div className="mini-doc-head">
                        <FileText size={20} />
                        <span>
                          RE-2026-1001<small>Nordlicht Studio</small>
                        </span>
                        <span className="mini-amount">1.190,00 €</span>
                      </div>
                      <div className="doc-line" />
                      <div className="doc-line short" />
                      <div className="doc-line" />
                    </div>
                    <div className="connection">
                      <span />
                      <Sparkles size={20} />
                      <span />
                    </div>
                    <div className="mini-match">
                      <span className="check-circle">
                        <Check size={18} />
                      </span>
                      <span>
                        Zahlung zugeordnet
                        <small>Referenz und Betrag stimmen überein</small>
                      </span>
                    </div>
                    <div className="floating-label">
                      <ShieldCheck size={14} />
                      Nachvollziehbar bis ins Detail
                    </div>
                  </div>
                </section>
              )}
              <section className="table-card">
                <div className="table-header">
                  <div>
                    <h2>
                      {
                        {
                          invoices: "Deine Rechnungen",
                          matches: "Ergebnisse des Abgleichs",
                          payments: "Deine Zahlungen",
                          activity: "Verarbeitungsprotokoll",
                        }[tab]
                      }{" "}
                      <span className="count">
                        {tab === "invoices"
                          ? workspace.invoices.length
                          : tab === "payments"
                            ? workspace.payments.length
                            : tab === "matches"
                              ? rows.length
                              : workspace.jobs.length}
                      </span>
                    </h2>
                    <p>
                      {tab === "invoices"
                        ? "Original ansehen, Angaben prüfen und freigeben."
                        : tab === "matches"
                          ? "Jede Zuordnung hat einen nachvollziehbaren Grund."
                          : tab === "payments"
                            ? "Zahlungsdaten bleiben unverändert. Zuordnungen werden separat protokolliert."
                            : "Echte KI-Aufrufe und gespeicherte Beispiele sind klar gekennzeichnet."}
                    </p>
                  </div>
                  <div className="table-actions">
                    {workspace.invoices.length > 0 && (
                      <button
                        className="button primary small-button"
                        onClick={match}
                        disabled={!!busy}
                      >
                        <CheckCheck size={17} />
                        Abgleich starten
                      </button>
                    )}
                    {workspace.run && (
                      <button
                        className="button secondary small-button"
                        onClick={download}
                        disabled={!!busy || workspace.run.stale}
                      >
                        <ArrowDownToLine size={16} />
                        Excel
                      </button>
                    )}
                  </div>
                </div>
                {tab !== "activity" && (
                  <div className="table-toolbar">
                    <div className="filter-tabs">
                      {tab === "matches" ? (
                        [
                          "ALL",
                          "MATCHED",
                          "PARTIAL",
                          "REVIEW",
                          "UNMATCHED",
                          "DUPLICATE",
                        ].map((value) => (
                          <button
                            key={value}
                            className={filter === value ? "selected" : ""}
                            onClick={() => setFilter(value)}
                          >
                            {value === "ALL" ? "Alle Fälle" : labels[value]}
                          </button>
                        ))
                      ) : (
                        <span className="toolbar-label">
                          {tab === "invoices"
                            ? "Alle Rechnungen"
                            : "Alle Zahlungseingänge"}
                        </span>
                      )}
                    </div>
                    <label className="search">
                      <Search size={16} />
                      <input
                        aria-label="Suchen"
                        placeholder="Nummer oder Kunde suchen …"
                        value={query}
                        onChange={(e) => setQuery(e.target.value)}
                      />
                    </label>
                  </div>
                )}
                <div className="table-scroll">
                  {tab === "invoices" && (
                    <table>
                      <thead>
                        <tr>
                          <th>RECHNUNG</th>
                          <th>KUNDE</th>
                          <th>BETRAG</th>
                          <th>DATENQUELLE</th>
                          <th>STATUS</th>
                          <th />
                        </tr>
                      </thead>
                      <tbody>
                        {visibleInvoices.map((i) => (
                          <tr
                            key={i.id}
                            onClick={() => openInvoice(i)}
                            className="clickable"
                          >
                            <td>
                              <div className="invoice-cell">
                                <span className="file-icon">
                                  <FileText size={19} />
                                </span>
                                <span>
                                  <strong>
                                    {i.payload.invoice_number || "Nummer fehlt"}
                                  </strong>
                                  <small>{i.filename || "CSV-Import"}</small>
                                </span>
                              </div>
                            </td>
                            <td>
                              {i.payload.customer || "Noch nicht erkannt"}
                            </td>
                            <td className="amount">
                              {i.payload.gross_amount
                                ? money(
                                    i.payload.gross_amount,
                                    i.payload.currency || "EUR",
                                  )
                                : "—"}
                            </td>
                            <td>
                              <span
                                className={
                                  "source " +
                                  (i.source === "openai" ? "ai-source" : "")
                                }
                              >
                                {i.source === "openai" ? (
                                  <Sparkles size={13} />
                                ) : (
                                  <FileCheck2 size={13} />
                                )}{" "}
                                {i.source === "openai"
                                  ? "OpenAI-Auswertung"
                                  : i.source === "example"
                                    ? "Beispielwerte"
                                    : "CSV-Import"}
                              </span>
                            </td>
                            <td>
                              <span
                                className={
                                  "pill " + (i.confirmed ? "green" : "amber")
                                }
                              >
                                {i.confirmed ? (
                                  <Check size={13} />
                                ) : (
                                  <CircleAlert size={13} />
                                )}{" "}
                                {i.confirmed ? "Bestätigt" : "Angaben prüfen"}
                              </span>
                            </td>
                            <td>
                              <button
                                className="row-action"
                                aria-label={
                                  "Rechnung " +
                                  (i.payload.invoice_number || "öffnen")
                                }
                                onClick={(e) => {
                                  e.stopPropagation();
                                  openInvoice(i);
                                }}
                              >
                                <ArrowUpRight size={18} />
                              </button>
                            </td>
                          </tr>
                        ))}
                        {missingDocs.map((d) => (
                          <tr key={d.id}>
                            <td colSpan={3}>
                              <div className="invoice-cell">
                                <span className="file-icon">
                                  <FileText size={18} />
                                </span>
                                <span>
                                  <strong>{d.filename}</strong>
                                  <small>Bereit für die KI-Auswertung</small>
                                </span>
                              </div>
                            </td>
                            <td colSpan={3}>
                              <button
                                className="button secondary small-button"
                                disabled={!!busy || !config.ai_available}
                                onClick={() => extract(d.id)}
                              >
                                <Sparkles size={16} />
                                Mit KI auslesen
                              </button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                  {tab === "matches" && (
                    <table>
                      <thead>
                        <tr>
                          <th>RECHNUNG / ZAHLUNG</th>
                          <th>KUNDE</th>
                          <th>ERWARTET</th>
                          <th>ERHALTEN</th>
                          <th>STATUS</th>
                          <th />
                        </tr>
                      </thead>
                      <tbody>
                        {visibleMatches.map((r, n) => (
                          <tr
                            key={r.invoice_id || r.payment_ids.join(",") || n}
                            className="clickable"
                            onClick={() => {
                              setSelectedMatch(r);
                              setSuggestion(null);
                            }}
                          >
                            <td>
                              <strong>
                                {r.invoice_number || "Unzugeordnete Zahlung"}
                              </strong>
                              <small className="subline">{r.reason}</small>
                            </td>
                            <td>{r.customer}</td>
                            <td className="amount">
                              {r.invoice_id
                                ? money(r.expected, r.currency)
                                : "—"}
                            </td>
                            <td className="amount">
                              {money(r.received, r.currency)}
                            </td>
                            <td>
                              <span className={"pill status-" + r.status}>
                                {labels[r.status]}
                              </span>
                            </td>
                            <td>
                              <button
                                className="row-action"
                                aria-label="Abgleich ansehen"
                                onClick={(e) => {
                                  e.stopPropagation();
                                  setSelectedMatch(r);
                                  setSuggestion(null);
                                }}
                              >
                                <ChevronRight size={18} />
                              </button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                  {tab === "payments" && (
                    <table>
                      <thead>
                        <tr>
                          <th>ZAHLUNG</th>
                          <th>ZAHLER</th>
                          <th>VERWENDUNGSZWECK</th>
                          <th>BETRAG</th>
                          <th>DATUM</th>
                        </tr>
                      </thead>
                      <tbody>
                        {workspace.payments
                          .filter((p) =>
                            [p.reference, p.payer, p.external_id]
                              .join(" ")
                              .toLowerCase()
                              .includes(query.toLowerCase()),
                          )
                          .map((p) => (
                            <tr key={p.id}>
                              <td>
                                <strong>{p.external_id}</strong>
                              </td>
                              <td>{p.payer}</td>
                              <td>{p.reference}</td>
                              <td className="amount">
                                {money(p.amount, p.currency)}
                              </td>
                              <td>
                                {new Date(p.paid_at).toLocaleDateString(
                                  "de-DE",
                                )}
                              </td>
                            </tr>
                          ))}
                      </tbody>
                    </table>
                  )}
                  {tab === "activity" && (
                    <table>
                      <thead>
                        <tr>
                          <th>AUFTRAG</th>
                          <th>STATUS</th>
                          <th>ERGEBNIS</th>
                          <th />
                        </tr>
                      </thead>
                      <tbody>
                        {workspace.jobs.map((j) => (
                          <tr key={j.id}>
                            <td>
                              <strong>
                                {{
                                  extract: "KI-Rechnungsauswertung",
                                  reconcile: "Zahlungsabgleich",
                                  suggest: "KI-Zuordnungsvorschlag",
                                }[j.kind] || j.kind}
                              </strong>
                            </td>
                            <td>
                              <span
                                className={
                                  "pill " +
                                  (j.status === "succeeded" ? "green" : "amber")
                                }
                              >
                                {
                                  {
                                    succeeded: "Abgeschlossen",
                                    failed: "Fehlgeschlagen",
                                    running: "In Verarbeitung",
                                    pending: "In Warteschlange",
                                  }[j.status]
                                }
                              </span>
                            </td>
                            <td>
                              {j.error ||
                                (j.status === "succeeded"
                                  ? "Ergebnis gespeichert"
                                  : "Verarbeitung läuft")}
                            </td>
                            <td>
                              {j.status === "failed" ? (
                                <button
                                  className="button secondary small-button"
                                  disabled={!!busy}
                                  onClick={() =>
                                    perform(
                                      "Auftrag wird erneut gestartet …",
                                      async () => {
                                        await waitForJob(
                                          await api<Job>(
                                            "/jobs/" + j.id + "/retry",
                                            { method: "POST" },
                                          ),
                                        );
                                      },
                                    )
                                  }
                                >
                                  Erneut starten
                                </button>
                              ) : (
                                j.status !== "succeeded" && (
                                  <button
                                    className="button secondary small-button"
                                    disabled={!!busy}
                                    onClick={() =>
                                      perform(
                                        "Status wird geprüft …",
                                        async () => {
                                          await waitForJob(j);
                                        },
                                      )
                                    }
                                  >
                                    Status prüfen
                                  </button>
                                )
                              )}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                </div>
                {((tab === "invoices" &&
                  !workspace.invoices.length &&
                  !missingDocs.length) ||
                  (tab === "matches" && !rows.length) ||
                  (tab === "payments" && !workspace.payments.length) ||
                  (tab === "activity" && !workspace.jobs.length)) && (
                  <div className="empty-state">
                    <FolderOpen size={30} />
                    <strong>
                      {tab === "matches"
                        ? "Bereit für deinen ersten Abgleich"
                        : "Hier ist Platz für deine Daten"}
                    </strong>
                    <p>
                      {tab === "matches"
                        ? "Lade Rechnungen und Zahlungen und starte den Abgleich."
                        : "Starte mit den Beispieldaten oder importiere eine Datei."}
                    </p>
                  </div>
                )}
                <div className="table-footer">
                  <span>
                    <ShieldCheck size={14} />
                    Deine Entscheidungen bleiben nachvollziehbar.
                  </span>
                  {active && (
                    <button
                      disabled={!!busy}
                      onClick={() =>
                        perform("Sitzung wird zurückgesetzt …", async () => {
                          await api("/demo-sessions/current", {
                            method: "DELETE",
                          });
                          csrf.current = "";
                          sessionStorage.removeItem("rf_csrf");
                          setWorkspace(empty);
                          setActive(false);
                          setSelected(null);
                          setSelectedMatch(null);
                        })
                      }
                    >
                      <RefreshCw size={13} />
                      Sitzung zurücksetzen
                    </button>
                  )}
                </div>
              </section>
              <section className="how-it-works">
                <div>
                  <span>01</span>
                  <div>
                    <strong>Rechnung hinzufügen</strong>
                    <p>PDF oder Foto. Die KI erkennt die Angaben.</p>
                  </div>
                </div>
                <ArrowRight size={16} />
                <div>
                  <span>02</span>
                  <div>
                    <strong>Angaben bestätigen</strong>
                    <p>Du prüfst das Ergebnis am Original.</p>
                  </div>
                </div>
                <ArrowRight size={16} />
                <div>
                  <span>03</span>
                  <div>
                    <strong>Zahlungen abgleichen</strong>
                    <p>Klare Regeln. Verständliche Ergebnisse.</p>
                  </div>
                </div>
              </section>
              <footer className="page-footer">
                <span>
                  ReconFlow <span className="muted">/</span> Entwickelt von
                  wasiliy-strecker
                </span>
                <span>
                  <span className="live-dot" />
                  {config.mode === "demo"
                    ? "Öffentliche Demo"
                    : "Lokale Entwicklungsumgebung"}
                </span>
              </footer>
            </>
          )}
        </main>
      </div>
      {showImport && (
        <div className="overlay" onClick={() => !busy && setShowImport(false)}>
          <section
            role="dialog"
            aria-modal="true"
            aria-labelledby="import-title"
            className="modal import-modal"
            onClick={(e) => e.stopPropagation()}
          >
            <button
              className="close"
              aria-label="Schließen"
              onClick={() => setShowImport(false)}
            >
              <X />
            </button>
            <div className="modal-icon">
              <Upload size={24} />
            </div>
            <h2 id="import-title">Daten hinzufügen</h2>
            <p>Wähle den passenden Import für deinen nächsten Schritt.</p>
            <div className="import-tabs">
              {[
                ["document", "PDF / Foto"],
                ["payments", "Zahlungs-CSV"],
                ...(config.mode === "local"
                  ? [["invoices", "Rechnungs-CSV"]]
                  : []),
              ].map(([key, label]) => (
                <button
                  key={key}
                  className={importKind === key ? "selected" : ""}
                  onClick={() => setImportKind(key)}
                >
                  {label}
                </button>
              ))}
            </div>
            <input
              ref={inputRef}
              type="file"
              className="file-input"
              accept={
                importKind === "document" ? ".pdf,.png,.jpg,.jpeg" : ".csv"
              }
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) upload(file);
                e.target.value = "";
              }}
            />
            <button
              className="dropzone"
              disabled={!!busy}
              onClick={() => inputRef.current?.click()}
            >
              <Upload size={30} />
              <strong>Datei auswählen</strong>
              <span>
                {importKind === "document"
                  ? "PDF, JPG oder PNG · bis 4 MB · bis 5 PDF-Seiten"
                  : "UTF-8-CSV · bis 4 MB"}
              </span>
            </button>
            {importKind === "document" ? (
              <div className="download-example">
                <span>Keine Rechnung zur Hand?</span>
                <a href="/api/examples/0">
                  Beispiel-PDF herunterladen <ArrowDownToLine size={14} />
                </a>
              </div>
            ) : importKind === "payments" ? (
              <div className="download-example">
                <span>Passend zu den Beispielrechnungen</span>
                <a href="/api/examples-payments">
                  Zahlungs-CSV herunterladen <ArrowDownToLine size={14} />
                </a>
              </div>
            ) : (
              <p className="muted">
                Spalten: invoice_number, issuer, customer, invoice_date,
                currency, gross_amount. Datumsformat: YYYY-MM-DD.
              </p>
            )}
            <p className="fine-print">
              {importKind === "document"
                ? "Die Datei wird erst beim Start der KI-Auswertung an OpenAI übertragen."
                : ""}{" "}
              {config.mode === "demo"
                ? "Diese Demo akzeptiert ausschließlich unsere synthetischen Beispieldateien."
                : "Verwende zum Ausprobieren vorzugsweise die mitgelieferten Testdaten."}
            </p>
            {error && (
              <p role="alert" className="inline-error">
                {error}
              </p>
            )}
          </section>
        </div>
      )}
      {selectedInvoice && draft && (
        <div className="overlay" onClick={() => !busy && setSelected(null)}>
          <section
            role="dialog"
            aria-modal="true"
            aria-labelledby="invoice-title"
            className="modal invoice-modal"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="modal-heading">
              <div>
                <span className="eyebrow">RECHNUNG PRÜFEN</span>
                <h2 id="invoice-title">
                  {draft.invoice_number || "Neue Rechnung"}
                </h2>
              </div>
              <button
                className="close inline"
                aria-label="Schließen"
                onClick={() => setSelected(null)}
              >
                <X />
              </button>
            </div>
            <div className="invoice-review">
              <div className="original">
                {selectedInvoice.document_id ? (
                  selectedInvoice.mime === "application/pdf" ? (
                    <iframe
                      title="Originalrechnung"
                      src={
                        "/api/documents/" +
                        selectedInvoice.document_id +
                        "/file"
                      }
                    />
                  ) : (
                    <img
                      alt="Originalrechnung"
                      src={
                        "/api/documents/" +
                        selectedInvoice.document_id +
                        "/file"
                      }
                    />
                  )
                ) : (
                  <div className="empty-state">
                    <FileSpreadsheet size={30} />
                    <p>Diese Rechnung wurde aus einer CSV importiert.</p>
                  </div>
                )}
              </div>
              <div className="review-fields">
                <div className="review-source">
                  <span
                    className={
                      "pill " +
                      (selectedInvoice.source === "openai"
                        ? "green"
                        : "neutral")
                    }
                  >
                    {selectedInvoice.source === "openai" ? (
                      <Sparkles size={13} />
                    ) : (
                      <FileText size={13} />
                    )}{" "}
                    {selectedInvoice.source === "openai"
                      ? "Mit OpenAI ausgelesen"
                      : "Gespeicherte Beispiel- oder Importwerte"}
                  </span>
                  {selectedInvoice.document_id && (
                    <button
                      disabled={!!busy || !config.ai_available}
                      className="button ai-button"
                      onClick={() => extract(selectedInvoice.document_id!)}
                    >
                      <Sparkles size={16} />
                      Mit KI auslesen
                    </button>
                  )}
                </div>
                <div className="form-grid">
                  {[
                    ["invoice_number", "Rechnungsnummer"],
                    ["customer", "Kunde"],
                    ["issuer", "Aussteller"],
                    ["invoice_date", "Rechnungsdatum"],
                    ["due_date", "Fälligkeit"],
                    ["currency", "Währung"],
                    ["net_amount", "Netto"],
                    ["tax_amount", "Steuer"],
                    ["gross_amount", "Brutto"],
                  ].map(([key, label]) => (
                    <label
                      key={key}
                      className={key === "issuer" ? "full-width" : ""}
                    >
                      {label}
                      <input
                        type={key.includes("date") ? "date" : "text"}
                        value={String(draft[key as keyof InvoiceData] ?? "")}
                        onChange={(e) =>
                          setDraft({ ...draft, [key]: e.target.value || null })
                        }
                      />
                    </label>
                  ))}
                </div>
                {draft.line_items.length > 0 && (
                  <div className="line-items">
                    <strong>Rechnungspositionen</strong>
                    {draft.line_items.map((item, n) => (
                      <div key={n}>
                        <span>{item.description}</span>
                        <b>
                          {item.amount
                            ? money(item.amount, draft.currency || "EUR")
                            : "—"}
                        </b>
                      </div>
                    ))}
                  </div>
                )}
                {[...selectedInvoice.issues, ...draft.warnings].length > 0 && (
                  <div className="review-warning">
                    <CircleAlert size={17} />
                    <div>
                      {[...selectedInvoice.issues, ...draft.warnings].map(
                        (warning, n) => (
                          <p key={n}>{warning}</p>
                        ),
                      )}
                    </div>
                  </div>
                )}
                {draft.evidence.length > 0 && (
                  <details className="evidence">
                    <summary>Fundstellen im Dokument</summary>
                    {draft.evidence.map((item, n) => (
                      <p key={n}>
                        <strong>
                          {item.field}
                          {item.page ? ` · Seite ${item.page}` : ""}
                        </strong>
                        <br />
                        {item.text}
                      </p>
                    ))}
                  </details>
                )}
                <p className="fine-print">
                  Bitte mit dem Original vergleichen. KI-Ergebnisse können
                  Fehler enthalten.
                </p>
                {error && (
                  <p role="alert" className="inline-error">
                    {error}
                  </p>
                )}
                <button
                  className="button primary full"
                  onClick={confirm}
                  disabled={!!busy}
                >
                  <CheckCheck size={18} />
                  Angaben bestätigen
                </button>
              </div>
            </div>
          </section>
        </div>
      )}
      {selectedMatch && (
        <div
          className="overlay"
          onClick={() => !busy && setSelectedMatch(null)}
        >
          <section
            role="dialog"
            aria-modal="true"
            aria-labelledby="match-title"
            className="modal match-modal"
            onClick={(e) => e.stopPropagation()}
          >
            <button
              className="close"
              aria-label="Schließen"
              onClick={() => setSelectedMatch(null)}
            >
              <X />
            </button>
            <span className={"pill status-" + selectedMatch.status}>
              {labels[selectedMatch.status]}
            </span>
            <h2 id="match-title">
              {selectedMatch.invoice_number || "Zahlung prüfen"}
            </h2>
            <p>{selectedMatch.customer}</p>
            <div className="match-numbers">
              <div>
                Erwartet
                <strong>
                  {money(selectedMatch.expected, selectedMatch.currency)}
                </strong>
              </div>
              <div>
                Eingegangen
                <strong>
                  {money(selectedMatch.received, selectedMatch.currency)}
                </strong>
              </div>
            </div>
            <div className="reason-box">
              <ShieldCheck size={21} />
              <div>
                <strong>Warum dieser Status?</strong>
                <p>{selectedMatch.reason}</p>
                <code>{selectedMatch.reason_code}</code>
              </div>
            </div>
            {!selectedMatch.invoice_id &&
              selectedMatch.candidates.length > 0 && (
                <>
                  <button
                    className="button ai-button full"
                    onClick={() => requestSuggestion(selectedMatch)}
                    disabled={!!busy || !config.ai_available}
                  >
                    <Sparkles size={17} />
                    KI um einen Zuordnungsvorschlag bitten
                  </button>
                  {suggestion && (
                    <div className="ai-explanation">
                      <strong>
                        <Sparkles size={16} />
                        KI-Vorschlag
                      </strong>
                      <p>{suggestion.reason}</p>
                      <small>
                        Der Vorschlag wird erst nach deiner Bestätigung
                        übernommen.
                      </small>
                    </div>
                  )}
                  <h3>Mögliche Rechnungen</h3>
                  {selectedMatch.candidates.map((id) => {
                    const i = workspace.invoices.find((i) => i.id === id);
                    return (
                      i && (
                        <div className="candidate" key={id}>
                          <div>
                            <strong>{i.payload.invoice_number}</strong>
                            <small>
                              {i.payload.customer} ·{" "}
                              {money(
                                i.payload.gross_amount,
                                i.payload.currency || "EUR",
                              )}
                            </small>
                          </div>
                          <button
                            className="button secondary small-button"
                            disabled={!!busy}
                            onClick={() => applyDecision(id)}
                          >
                            Zuordnen
                          </button>
                        </div>
                      )
                    );
                  })}
                </>
              )}
            {error && (
              <p role="alert" className="inline-error">
                {error}
              </p>
            )}
          </section>
        </div>
      )}
    </div>
  );
}
