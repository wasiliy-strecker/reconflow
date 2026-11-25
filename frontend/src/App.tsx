import {
  type ReactNode,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import {
  ArrowDownToLine,
  ArrowRight,
  ArrowUpRight,
  Check,
  CheckCheck,
  ChevronRight,
  CircleAlert,
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

const demoStartup = "Beispieldaten werden geladen …";

function WorkspaceStat({
  label,
  icon,
  value,
  detail,
  loading,
}: {
  label: string;
  icon: ReactNode;
  value: ReactNode;
  detail: string;
  loading: boolean;
}) {
  return (
    <div className="stat">
      <div className="stat-top">
        {label}
        {icon}
      </div>
      {loading ? (
        <div aria-hidden="true" className="stat-placeholder">
          <span className="skeleton" />
          <span className="skeleton" />
        </div>
      ) : (
        <>
          <strong>{value}</strong>
          <span>{detail}</span>
        </>
      )}
    </div>
  );
}

const reconcileProgress = "Zahlungen werden abgeglichen …";
const restoreProgress = "Dein Arbeitsplatz wird wieder geladen …";
const sections = [
  {
    key: "invoices",
    label: "Rechnungen",
    step: 1,
    hint: "Lade deine Rechnungen oder starte mit den Beispieldaten. Prüfe die Angaben am Original.",
  },
  {
    key: "payments",
    label: "Zahlungen",
    step: 2,
    hint: "Prüfe, wer wie viel überwiesen hat und welche Rechnungsnummer im Verwendungszweck steht.",
  },
  {
    key: "matches",
    label: "Zahlungsabgleich",
    step: 3,
    hint: "Gleiche die Zahlungseingänge mit den bestätigten Rechnungen ab und prüfe offene Fälle.",
  },
  {
    key: "activity",
    label: "Aktivitäten",
    step: null,
    hint: "Hier siehst du den Status deiner Verarbeitungsaufträge.",
  },
] as const;
type Section = (typeof sections)[number]["key"];

function ActionProgress({ message }: { message: string }) {
  return (
    <div className="action-progress" role="status" aria-atomic="true">
      <LoaderCircle size={18} className="spin" aria-hidden="true" />
      {message}
    </div>
  );
}

function TableSkeleton() {
  return (
    <div className="loading-table" aria-hidden="true">
      {Array.from({ length: 6 }, (_, index) => (
        <div className="loading-row" key={index}>
          <span className="loading-invoice">
            <span className="skeleton document-shape" />
            <span className="loading-lines">
              <span className="skeleton" />
              <span className="skeleton" />
            </span>
          </span>
          <span className="skeleton customer-shape" />
          <span className="skeleton amount-shape" />
          <span className="skeleton status-shape" />
        </div>
      ))}
    </div>
  );
}

function PaymentReview({
  match,
  payment,
  invoices,
  busy,
  aiAvailable,
  suggestion,
  onAssign,
  onSuggest,
  onClose,
}: {
  match: Match;
  payment?: Payment;
  invoices: Invoice[];
  busy: boolean;
  aiAvailable: boolean;
  suggestion: Job["payload"] | null;
  onAssign: (id: string) => void;
  onSuggest: () => void;
  onClose: () => void;
}) {
  const candidates = invoices.filter((i) => match.candidates.includes(i.id));
  const canAssign = (i: Invoice) =>
    i.confirmed && i.payload.currency === match.currency;
  const hasChoice = candidates.some(canAssign);
  const reason =
    {
      NO_REFERENCE:
        "Im Verwendungszweck lässt sich keine eindeutige Rechnungsnummer erkennen.",
      AMBIGUOUS_REFERENCE: "Der Verwendungszweck passt zu mehreren Rechnungen.",
      CURRENCY_MISMATCH:
        "Die Zahlung und die genannte Rechnung haben unterschiedliche Währungen.",
    }[match.reason_code] ?? match.reason;

  return (
    <>
      <h2 id="match-title" className="payment-question">
        Zu welcher Rechnung gehört diese Zahlung?
      </h2>
      <dl className="payment-receipt">
        <div>
          <dt>Zahlung von</dt>
          <dd>{payment?.payer || match.customer || "Unbekannt"}</dd>
        </div>
        <div>
          <dt>Eingegangener Betrag</dt>
          <dd className="receipt-amount">
            {money(match.received, match.currency)}
          </dd>
        </div>
        <div className="receipt-purpose">
          <dt>Verwendungszweck</dt>
          <dd>{payment?.reference || "Nicht angegeben"}</dd>
        </div>
      </dl>
      <p className="payment-reason">{reason}</p>
      {candidates.length > 0 ? (
        <>
          <h3 className="choices-heading">
            {candidates.length === 1
              ? "Mögliche Rechnung"
              : "Mögliche Rechnungen"}
          </h3>
          {hasChoice && (
            <p className="choice-help">
              {match.reason_code === "NO_REFERENCE"
                ? "Betrag und Währung passen. Prüfe den Kundennamen, bevor du die Zahlung zuordnest."
                : "Vergleiche den Kunden und den Betrag, bevor du die Zahlung zuordnest."}
            </p>
          )}
          {candidates.map((i) => (
            <article
              className="invoice-choice"
              key={i.id}
              aria-labelledby={"choice-" + i.id}
            >
              <div className="choice-summary">
                <div>
                  <h4 id={"choice-" + i.id}>
                    {i.payload.invoice_number || "Rechnung ohne Nummer"}
                  </h4>
                  <span>{i.payload.customer || "Kunde unbekannt"}</span>
                </div>
                <div className="choice-amount">
                  <span>Rechnungsbetrag</span>
                  <strong>
                    {i.payload.gross_amount && i.payload.currency
                      ? money(i.payload.gross_amount, i.payload.currency)
                      : "—"}
                  </strong>
                </div>
              </div>
              {i.document_id ? (
                <a
                  className="original-link"
                  href={originalFileUrl(i.document_id)}
                  target="_blank"
                  rel="noopener noreferrer"
                  aria-describedby={"choice-" + i.id}
                >
                  Originalrechnung ansehen (neuer Tab)
                  <ArrowUpRight size={15} aria-hidden="true" />
                </a>
              ) : (
                <p className="choice-help">
                  Für diese Rechnung ist kein Original hinterlegt.
                </p>
              )}
              {canAssign(i) ? (
                <button
                  className="button primary"
                  disabled={busy}
                  aria-describedby={"choice-" + i.id}
                  onClick={() => onAssign(i.id)}
                >
                  <Check size={16} aria-hidden="true" /> Zahlung dieser Rechnung
                  zuordnen
                </button>
              ) : (
                <p className="choice-help">
                  {i.confirmed
                    ? "Eine Zuordnung ist nur bei gleicher Währung möglich."
                    : "Bestätige zuerst die Rechnungsangaben."}
                </p>
              )}
            </article>
          ))}
        </>
      ) : (
        <p className="no-candidate">
          Keine passende Rechnung gefunden. Die Zahlung bleibt offen.
        </p>
      )}
      {suggestion && (
        <div className="ai-explanation">
          <strong>
            <Sparkles size={16} />
            KI-Vorschlag
          </strong>
          <p>{suggestion.reason}</p>
          <small>Du entscheidest, ob du die Zahlung zuordnest.</small>
        </div>
      )}
      <div className="payment-options">
        <button className="button secondary" disabled={busy} onClick={onClose}>
          Offen lassen
        </button>
        {hasChoice && aiAvailable && (
          <button
            className="button ai-button"
            disabled={busy}
            onClick={onSuggest}
          >
            <Sparkles size={15} />
            KI-Vorschlag einholen
          </button>
        )}
      </div>
    </>
  );
}

function originalFileUrl(documentId: string) {
  return "/api/documents/" + encodeURIComponent(documentId) + "/file";
}

function OriginalPreview({ id, mime }: { id: string; mime: string | null }) {
  const [state, setState] = useState<"loading" | "ready" | "failed">("loading");
  const props = {
    src: originalFileUrl(id),
    onLoad: () => setState("ready"),
    onError: () => setState("failed"),
  };
  return (
    <>
      {state === "loading" && (
        <div className="preview-progress" role="status">
          <LoaderCircle className="spin" size={18} aria-hidden="true" />
          Originalrechnung wird geöffnet …
        </div>
      )}
      {state === "failed" ? (
        <p role="alert">
          Die Vorschau konnte nicht geladen werden. Das Original kannst du in
          der Rechnungsliste herunterladen.
        </p>
      ) : mime === "application/pdf" ? (
        <iframe title="Originalrechnung" {...props} />
      ) : (
        <img alt="Originalrechnung" {...props} />
      )}
    </>
  );
}

async function saveFile(path: string, filename: string) {
  const response = await fetch(path);
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(
      body?.detail || "Die Datei konnte nicht heruntergeladen werden.",
    );
  }
  const url = URL.createObjectURL(await response.blob());
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export default function App() {
  const [config, setConfig] = useState<Config>({
    mode: "local",
    ai_available: false,
    model: "",
    monthly_budget_eur: "10",
  });
  const [workspace, setWorkspace] = useState<Workspace>(empty);
  const [active, setActive] = useState(false);
  const [tab, setTab] = useState<Section>("invoices");
  const section = sections.find((item) => item.key === tab)!;
  const [busy, setBusy] = useState(() =>
    sessionStorage.getItem("rf_csrf") ? restoreProgress : "",
  );
  const resultsHeading = useRef<HTMLHeadingElement>(null);
  const pageHeading = useRef<HTMLHeadingElement>(null);
  const previousTab = useRef(tab);
  const reconciling = busy === reconcileProgress;
  const showingMatchProgress = reconciling && tab === "matches";

  useLayoutEffect(() => {
    if (previousTab.current !== tab && !showingMatchProgress) {
      pageHeading.current?.focus({ preventScroll: true });
      pageHeading.current?.scrollIntoView({ block: "nearest" });
    }
    previousTab.current = tab;
    if (showingMatchProgress) {
      resultsHeading.current?.focus({ preventScroll: true });
      resultsHeading.current?.scrollIntoView({ block: "start" });
    }
  }, [tab, showingMatchProgress]);
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
    if (!csrf.current) return;
    let current = true;
    async function restoreWorkspace() {
      try {
        const session = await api<{ csrf_token: string }>(
          "/demo-sessions/current",
        );
        if (!current) return;
        csrf.current = session.csrf_token;
        const data = await api<Workspace>("/workspace");
        if (current) {
          setActive(true);
          setWorkspace(data);
        }
      } catch (e) {
        if (current) {
          csrf.current = "";
          sessionStorage.removeItem("rf_csrf");
          setError(
            e instanceof Error
              ? e.message
              : "Die Sitzung konnte nicht geladen werden.",
          );
        }
      } finally {
        if (current) setBusy("");
      }
    }
    void restoreWorkspace();
    return () => {
      current = false;
    };
  }, []);

  function navigate(next: Section) {
    setTab(next);
    setQuery("");
    setFilter("ALL");
    setNotice("");
  }

  async function startDemo() {
    navigate("invoices");
    await perform(demoStartup, async () => {
      await ensureSession();
      const data = await api<Workspace>("/demo-sessions/seed", {
        method: "POST",
      });
      setWorkspace(data);
      setNotice(
        "Die Beispieldaten sind geladen. Sechs Rechnungen und sechs Zahlungseingänge sind bereit.",
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
    await perform(reconcileProgress, async () => {
      await waitForJob(
        await api<Job>("/reconciliation-runs", { method: "POST" }),
      );
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
      navigate(importKind === "payments" ? "payments" : "invoices");
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
        `Die Zahlung über ${money(selectedMatch.received, selectedMatch.currency)} wurde der Rechnung ${invoice.payload.invoice_number || "ohne Nummer"} zugeordnet.`,
      );
    });
  }
  async function download() {
    if (!workspace.run) return;
    await perform("Bericht wird erstellt …", async () => {
      await saveFile(
        "/api/reports/" + workspace.run!.id + ".xlsx",
        "ReconFlow-Abgleich.xlsx",
      );
    });
  }

  function originalDownload(documentId: string, filename: string) {
    return (
      <button
        className="original-link"
        disabled={!!busy}
        aria-label={"Original herunterladen: " + filename}
        onClick={(event) => {
          event.stopPropagation();
          void perform("Original wird heruntergeladen …", () =>
            saveFile(originalFileUrl(documentId), filename),
          );
        }}
      >
        <ArrowDownToLine size={14} aria-hidden="true" />
        Original herunterladen
      </button>
    );
  }

  const rows = workspace.run?.stale ? [] : workspace.run?.payload.results || [];
  const canReconcile =
    workspace.payments.length > 0 ||
    workspace.invoices.some((invoice) => invoice.confirmed);
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
  const emptyMatch = !canReconcile
    ? [
        "Noch keine Daten für den Abgleich",
        "Lade und bestätige eine Rechnung in Schritt 1 oder importiere Zahlungseingänge in Schritt 2.",
      ]
    : workspace.run?.stale
      ? [
          "Abgleich aktualisieren",
          "Die bisherigen Ergebnisse sind veraltet. Gleiche die geänderten Daten erneut ab.",
        ]
      : [
          "Bereit für deinen ersten Abgleich",
          "Starte den Abgleich, um zu sehen, welche Zahlungen zu deinen Rechnungen passen.",
        ];
  const [emptyTitle, emptyHint] = {
    invoices: [
      "Hier ist Platz für deine Daten",
      "Starte mit den Beispieldaten oder füge eine Rechnung hinzu.",
    ],
    payments: [
      "Noch keine Zahlungseingänge",
      "Importiere die Zahlungseingänge als CSV oder lade die Beispieldaten in Schritt 1.",
    ],
    matches: emptyMatch,
    activity: [
      "Noch keine Aufträge",
      "Hier erscheinen deine KI-Auswertungen und Zahlungsabgleiche.",
    ],
  }[tab];
  const startingDemo = busy === demoStartup;
  const restoring = busy === restoreProgress;
  const loadingWorkspace = startingDemo || restoring;
  const loadingTable = loadingWorkspace || showingMatchProgress;
  const floatingProgress =
    busy && !loadingWorkspace && !showingMatchProgress ? (
      <ActionProgress message={busy} />
    ) : null;
  const currency = workspace.invoices[0]?.payload.currency || "EUR";

  const pageError = error && !modalOpen && (
    <div role="alert" className="message error">
      <CircleAlert size={19} />
      <span>{error}</span>
      <button aria-label="Meldung schließen" onClick={() => setError("")}>
        <X size={17} />
      </button>
    </div>
  );

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
        <div className="nav-caption">DEIN ABLAUF</div>
        <nav aria-label="Hauptnavigation">
          {sections.map(({ key, label, step }) => (
            <button
              key={key}
              className={"nav-item " + (tab === key ? "active" : "")}
              aria-current={tab === key ? "page" : undefined}
              aria-label={step ? `Schritt ${step}: ${label}` : label}
              onClick={() => navigate(key)}
            >
              {step ? (
                <span className="nav-step" aria-hidden="true">
                  {step}
                </span>
              ) : (
                <LayoutDashboard size={20} aria-hidden="true" />
              )}
              {label}
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="demo-note">
            <Sparkles size={19} />
            <strong>Ausprobieren. Verstehen.</strong>
            <p>Echte Abläufe mit fiktiven Rechnungen und Zahlungen.</p>
            <button onClick={startDemo} disabled={!!busy}>
              {startingDemo ? "Daten werden geladen …" : "Beispieldaten laden"}{" "}
              <ArrowRight size={15} />
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
            <strong>{section.label}</strong>
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
          <div className="page-heading">
            <div>
              {section.step && (
                <div className="eyebrow">Schritt {section.step} von 3</div>
              )}
              <h1 ref={pageHeading} tabIndex={-1}>
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
                {tab === "invoices" && workspace.invoices.length
                  ? "Öffne eine Rechnung und prüfe die Angaben am Original. Gehe anschließend weiter zu den Zahlungen."
                  : tab === "matches" && workspace.run && !workspace.run.stale
                    ? "Öffne einen Fall, um die Zuordnung zu prüfen, oder lade den Abgleich als Excel-Datei herunter."
                    : section.hint}
              </p>
            </div>
            {(tab === "invoices" || tab === "payments") && (
              <div className="heading-actions">
                {tab === "payments" ? (
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
                ) : (
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
                )}
              </div>
            )}
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
          {tab !== "matches" && pageError}
          {notice && !error && !busy && (
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
          {!modalOpen && floatingProgress}
          {workspace.run?.stale && !busy && (
            <div role="status" className="message">
              Die Daten haben sich geändert. Aktualisiere den Zahlungsabgleich
              in Schritt 3.
            </div>
          )}
          <section
            className="stats"
            aria-label="Übersicht"
            aria-busy={loadingWorkspace}
          >
            <WorkspaceStat
              label="Rechnungsvolumen"
              loading={loadingWorkspace}
              icon={<FileText size={18} />}
              value={
                workspace.invoices.length
                  ? mixedCurrencies
                    ? "Mehrere Währungen"
                    : money(total, currency)
                  : "—"
              }
              detail={workspace.invoices.length + " Rechnungen im Arbeitsplatz"}
            />
            <WorkspaceStat
              label="Zugeordnet"
              loading={loadingWorkspace || reconciling}
              icon={
                <span className="stat-icon green">
                  <CheckCheck size={17} />
                </span>
              }
              value={
                <>
                  {workspace.run ? matched : "—"}
                  <small>Rechnungen</small>
                </>
              }
              detail="Referenz, Betrag und Währung stimmen"
            />
            <WorkspaceStat
              label="Noch zu prüfen"
              loading={loadingWorkspace || reconciling}
              icon={
                <span className="stat-icon amber">
                  <CircleAlert size={17} />
                </span>
              }
              value={
                <>
                  {workspace.run ? review : "—"}
                  <small>Fälle</small>
                </>
              }
              detail="Abweichungen nachvollziehbar klären"
            />
            <WorkspaceStat
              label="Zahlungseingänge"
              loading={loadingWorkspace}
              icon={<Wallet size={18} />}
              value={
                <>
                  {workspace.payments.length}
                  <small>Einträge</small>
                </>
              }
              detail="Über CSV importiert und geprüft"
            />
          </section>
          {loadingWorkspace && (
            <div className="demo-loading-note" role="status" aria-atomic="true">
              <LoaderCircle className="spin" size={22} aria-hidden="true" />
              <div>
                <strong>
                  {restoring
                    ? restoreProgress
                    : "Dein Demo-Arbeitsplatz wird geladen"}
                </strong>
                <p>
                  {restoring
                    ? "Bitte warte kurz. Deine gespeicherten Daten werden geladen."
                    : "Bitte warte kurz. Wir laden sechs Beispielrechnungen und die zugehörigen Zahlungen. Nach einer Pause kann der Start etwas länger dauern."}
                </p>
              </div>
            </div>
          )}
          {tab === "invoices" &&
            !loadingWorkspace &&
            !workspace.invoices.length &&
            !missingDocs.length && (
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
                <h2 ref={resultsHeading} tabIndex={-1}>
                  {
                    {
                      invoices: "Deine Rechnungen",
                      matches: "Ergebnisse des Abgleichs",
                      payments: "Deine Zahlungen",
                      activity: "Verarbeitungsprotokoll",
                    }[tab]
                  }{" "}
                  <span className="count" hidden={loadingTable}>
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
                {tab === "invoices" && workspace.invoices.length > 0 && (
                  <button
                    className="button secondary small-button"
                    onClick={() => navigate("payments")}
                  >
                    Weiter zu den Zahlungen <ArrowRight size={16} />
                  </button>
                )}
                {tab === "payments" && canReconcile && (
                  <button
                    className="button secondary small-button"
                    onClick={() => navigate("matches")}
                  >
                    Weiter zum Zahlungsabgleich <ArrowRight size={16} />
                  </button>
                )}
                {tab === "matches" && canReconcile && (
                  <button
                    className={
                      workspace.run && !workspace.run.stale
                        ? "button secondary small-button"
                        : "button primary small-button"
                    }
                    onClick={match}
                    disabled={!!busy}
                  >
                    <CheckCheck size={17} />
                    {reconciling
                      ? "Abgleich läuft …"
                      : workspace.run
                        ? "Erneut abgleichen"
                        : "Abgleich starten"}
                  </button>
                )}
                {tab === "matches" && workspace.run && (
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
            {!loadingTable && tab !== "activity" && (
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
            {tab === "matches" && pageError}
            {showingMatchProgress && (
              <div className="match-progress" role="status" aria-atomic="true">
                <LoaderCircle size={20} className="spin" aria-hidden="true" />
                <div>
                  <strong>{reconcileProgress}</strong>
                  <p>
                    Wir vergleichen die Rechnungen mit den Zahlungseingängen.
                    Die Ergebnisse erscheinen hier automatisch.
                  </p>
                </div>
              </div>
            )}
            {loadingTable && <TableSkeleton />}
            <div
              className="table-scroll"
              aria-busy={loadingTable}
              hidden={loadingTable}
            >
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
                              {i.document_id && i.filename ? (
                                originalDownload(i.document_id, i.filename)
                              ) : (
                                <small>CSV-Import</small>
                              )}
                            </span>
                          </div>
                        </td>
                        <td>{i.payload.customer || "Noch nicht erkannt"}</td>
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
                              {originalDownload(d.id, d.filename)}
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
                          {r.invoice_id ? money(r.expected, r.currency) : "—"}
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
                            {new Date(p.paid_at).toLocaleDateString("de-DE")}
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
                                  perform("Status wird geprüft …", async () => {
                                    await waitForJob(j);
                                  })
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
            {!loadingTable &&
              ((tab === "invoices" &&
                !workspace.invoices.length &&
                !missingDocs.length) ||
                (tab === "matches" && !rows.length) ||
                (tab === "payments" && !workspace.payments.length) ||
                (tab === "activity" && !workspace.jobs.length)) && (
                <div className="empty-state">
                  <FolderOpen size={30} />
                  <strong>{emptyTitle}</strong>
                  <p>{emptyHint}</p>
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
                      navigate("invoices");
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
                  disabled={!!busy}
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
            {floatingProgress}
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
                  <OriginalPreview
                    key={selectedInvoice.document_id}
                    id={selectedInvoice.document_id}
                    mime={selectedInvoice.mime}
                  />
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
                {floatingProgress}
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
            {selectedMatch.invoice_id ? (
              <>
                <span className={"pill status-" + selectedMatch.status}>
                  {labels[selectedMatch.status]}
                </span>
                <h2 id="match-title">
                  {selectedMatch.invoice_number || "Rechnung prüfen"}
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
              </>
            ) : (
              <PaymentReview
                match={selectedMatch}
                payment={workspace.payments.find(
                  (p) => p.id === selectedMatch.payment_ids[0],
                )}
                invoices={workspace.invoices}
                busy={!!busy}
                aiAvailable={config.ai_available}
                suggestion={
                  suggestion?.payment_id === selectedMatch.payment_ids[0]
                    ? suggestion
                    : null
                }
                onAssign={applyDecision}
                onSuggest={() => requestSuggestion(selectedMatch)}
                onClose={() => setSelectedMatch(null)}
              />
            )}
            {floatingProgress}
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
