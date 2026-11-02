import { useEffect, useRef, useState } from "react";
import {
  ArrowDownToLine,
  ArrowRight,
  Check,
  ChevronDown,
  CircleHelp,
  Clock3,
  FileImage,
  FileText,
  LayoutDashboard,
  PackageCheck,
  Plus,
  ReceiptText,
  Search,
  Settings2,
  ShieldCheck,
  Sparkles,
  Upload,
} from "lucide-react";

type View = "receipts" | "products";
type ApiStatus = "checking" | "available" | "unavailable";

function App() {
  const [view, setView] = useState<View>("receipts");
  const [apiStatus, setApiStatus] = useState<ApiStatus>("checking");
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const fileInput = useRef<HTMLInputElement>(null);

  useEffect(() => {
    let active = true;
    const controller = new AbortController();
    const timeoutId = window.setTimeout(() => controller.abort(), 2000);

    fetch("/api/health/ready", { signal: controller.signal })
      .then((response) => {
        if (active) {
          setApiStatus(response.ok ? "available" : "unavailable");
        }
      })
      .catch(() => {
        if (active) {
          setApiStatus("unavailable");
        }
      })
      .finally(() => window.clearTimeout(timeoutId));

    return () => {
      active = false;
      window.clearTimeout(timeoutId);
      controller.abort();
    };
  }, []);

  function chooseFile(file?: File) {
    if (!file) {
      return;
    }

    const supported = ["application/pdf", "image/png"].includes(file.type);
    if (!supported) {
      setSelectedFile(null);
      setFileError("Choose a PDF or PNG receipt.");
      return;
    }
    if (file.size > 10 * 1024 * 1024) {
      setSelectedFile(null);
      setFileError("The selected file is larger than 10 MB.");
      return;
    }

    setSelectedFile(file);
    setFileError(null);
  }

  const isProducts = view === "products";

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <a className="brand" href="#" aria-label="Receipt Tracker home">
          <span className="brand-mark"><ReceiptText size={20} /></span>
          <span>receipt<span className="brand-light">track</span></span>
        </a>

        <div className="workspace-label">WORKSPACE</div>
        <button className="workspace-switch" type="button">
          <span className="workspace-avatar">R</span>
          <span className="workspace-name">My receipts<small>Personal space</small></span>
          <ChevronDown size={16} className="muted-icon" />
        </button>

        <div className="nav-label">COLLECT</div>
        <nav className="nav-list" aria-label="Main navigation">
          <button
            type="button"
            className={`nav-item ${!isProducts ? "active" : ""}`}
            onClick={() => setView("receipts")}
          >
            <ReceiptText size={18} />
            <span>Receipts</span>
            <span className="nav-count">0</span>
          </button>
          <button
            type="button"
            className={`nav-item ${isProducts ? "active" : ""}`}
            onClick={() => setView("products")}
          >
            <PackageCheck size={18} />
            <span>Product review</span>
            <span className="nav-count">0</span>
          </button>
          <button type="button" className="nav-item muted-item" disabled>
            <LayoutDashboard size={18} />
            <span>Insights</span>
            <span className="soon-tag">SOON</span>
          </button>
        </nav>

        <div className="sidebar-bottom">
          <div className="sidebar-tip">
            <span className="tip-icon"><Sparkles size={16} /></span>
            <strong>Good to know</strong>
            <p>Product codes are reviewed once, then matched automatically next time.</p>
            <button type="button" onClick={() => setView("products")}>
              How review works <ArrowRight size={14} />
            </button>
          </div>
          <button className="nav-item footer-link" type="button" disabled>
            <Settings2 size={17} /><span>Settings</span>
          </button>
          <div className="user-row">
            <span className="user-avatar">U</span>
            <span className="user-label">Your account<small>Sign-in coming soon</small></span>
            <CircleHelp size={17} className="muted-icon" />
          </div>
        </div>
      </aside>

      <main className="main-area">
        <header className="topbar">
          <div className="breadcrumbs">
            <span>Workspace</span><span className="crumb-slash">/</span>
            <strong>{isProducts ? "Product review" : "Receipts"}</strong>
          </div>
          <div className="topbar-right">
            <div className={`connection-status ${apiStatus}`}>
              <span className="status-dot" />
              {apiStatus === "checking" ? "Checking API" : apiStatus === "available" ? "API connected" : "API not connected"}
            </div>
            <button className="help-button" type="button" aria-label="Help"><CircleHelp size={18} /></button>
            <span className="top-avatar">U</span>
          </div>
        </header>

        <div className="page-content">
          {isProducts ? (
            <ProductReview search={search} setSearch={setSearch} onAddReceipt={() => setView("receipts")} />
          ) : (
            <Receipts
              file={selectedFile}
              fileError={fileError}
              fileInput={fileInput}
              onChooseFile={chooseFile}
              onClearFile={() => {
                setSelectedFile(null);
                setFileError(null);
              }}
              apiStatus={apiStatus}
            />
          )}
        </div>
      </main>
    </div>
  );
}

type ReceiptsProps = {
  file: File | null;
  fileError: string | null;
  fileInput: React.RefObject<HTMLInputElement>;
  onChooseFile: (file?: File) => void;
  onClearFile: () => void;
  apiStatus: ApiStatus;
};

function Receipts({ file, fileError, fileInput, onChooseFile, onClearFile, apiStatus }: ReceiptsProps) {
  return (
    <>
      <div className="page-heading">
        <div>
          <div className="eyebrow"><span className="eyebrow-mark" /> YOUR PURCHASES</div>
          <h1>Receipts, <span>all in one place.</span></h1>
          <p>Upload a receipt and we’ll turn it into useful, searchable data.</p>
        </div>
        <div className="heading-date"><Clock3 size={15} /> Your receipt history</div>
      </div>

      <div className="stats-row">
        <StatCard label="RECEIPTS ADDED" value="—" detail="No receipts yet" icon={<ReceiptText size={17} />} />
        <StatCard label="TOTAL SPENT" value="—" detail="Appears after your first upload" icon={<ArrowDownToLine size={17} />} />
        <StatCard label="PRODUCTS TRACKED" value="—" detail="Codes from your receipts" icon={<PackageCheck size={17} />} />
      </div>

      <div className="section-title-row">
        <div><h2>Get started</h2><p>Your first receipt is one upload away.</p></div>
        <span className="period-pill"><Clock3 size={14} /> All time <ChevronDown size={14} /></span>
      </div>

      <section
        className="upload-card"
        onDragOver={(event) => event.preventDefault()}
        onDrop={(event) => {
          event.preventDefault();
          onChooseFile(event.dataTransfer.files[0]);
        }}
      >
        <div className="upload-art">
          <div className="art-glow" />
          <div className="receipt-paper">
            <span className="paper-line wide" /><span className="paper-line" /><span className="paper-line short" />
            <span className="paper-divider" /><span className="paper-line wide" /><span className="paper-line short" />
            <span className="paper-total" />
          </div>
          <span className="art-sparkle spark-one">✳</span><span className="art-sparkle spark-two">✦</span>
          <span className="art-tag">PDF · PNG</span>
        </div>
        <div className="upload-copy">
          <span className="step-label">01 <span>·</span> ADD A RECEIPT</span>
          <h3>Drop your receipt here</h3>
          <p>Start with a Biedronka PDF or a Lidl PNG. Account sign-in will be added before uploads are enabled.</p>
          <input
            ref={fileInput}
            className="visually-hidden"
            type="file"
            accept=".pdf,.png,application/pdf,image/png"
            onChange={(event) => onChooseFile(event.target.files?.[0])}
          />
          <button className="primary-button" type="button" onClick={() => fileInput.current?.click()}>
            <Upload size={16} /> Choose a file
          </button>
          <span className="file-hint"><ShieldCheck size={14} /> PDF or PNG · up to 10 MB</span>
          {fileError && <span className="file-error" role="alert">{fileError}</span>}
        </div>
        <div className="upload-side-note">
          <span className="note-icon"><Sparkles size={16} /></span>
          <strong>Less typing, more insight</strong>
          <p>Receipt details are read and organized automatically. You can review product codes that need attention.</p>
        </div>
        {file && (
          <div className="selected-file" role="status">
            <span className="file-type-icon">{file.type === "application/pdf" ? <FileText size={18} /> : <FileImage size={18} />}</span>
            <span className="selected-file-info"><strong>{file.name}</strong><small>{(file.size / 1024 / 1024).toFixed(2)} MB · selected, not uploaded</small></span>
            <button className="remove-file" onClick={onClearFile} type="button" aria-label="Remove selected file">×</button>
          </div>
        )}
      </section>

      <div className="notice-row">
        <span className="notice-icon"><CircleHelp size={16} /></span>
        <p>
          {apiStatus === "available"
            ? "The API is reachable. Receipt upload is being connected next."
            : "This is the first deployable UI slice. Upload is not enabled until the API upload endpoint and sign-in are implemented."}
        </p>
        <button type="button" onClick={() => fileInput.current?.click()}>Select a file <ArrowRight size={14} /></button>
      </div>

      <div className="section-title-row history-title">
        <div><h2>Recent receipts</h2><p>Your uploaded receipts and processing status will show here.</p></div>
        <button className="text-button" type="button" disabled>View all <ArrowRight size={15} /></button>
      </div>
      <div className="empty-table">
        <div className="empty-icon"><ReceiptText size={21} /></div>
        <strong>No receipts yet</strong>
        <span>Select a PDF or PNG above to get started.</span>
      </div>
      <div className="page-footnote">Receipt Tracker <span>·</span> built for clear, simple spending records</div>
    </>
  );
}

function ProductReview({
  search,
  setSearch,
  onAddReceipt,
}: {
  search: string;
  setSearch: (value: string) => void;
  onAddReceipt: () => void;
}) {
  return (
    <>
      <div className="page-heading">
        <div>
          <div className="eyebrow"><span className="eyebrow-mark review-mark" /> CATALOG CARE</div>
          <h1>Product <span>review.</span></h1>
          <p>Resolve unfamiliar receipt codes once. We’ll remember your choice for next time.</p>
        </div>
        <span className="queue-badge"><span /> 0 awaiting review</span>
      </div>

      <div className="review-summary">
        <div className="review-summary-icon"><PackageCheck size={20} /></div>
        <div><strong>Your product catalog stays tidy.</strong><p>Accept a code as-is, correct a typo, or match it to an existing product code.</p></div>
        <div className="review-summary-steps"><span>01 <small>SPOT</small></span><ArrowRight size={14} /><span>02 <small>RESOLVE</small></span><ArrowRight size={14} /><span>03 <small>REMEMBER</small></span></div>
      </div>

      <div className="section-title-row review-list-heading">
        <div><h2>Needs your attention <span className="small-count">0</span></h2><p>New codes will appear here after a receipt is processed.</p></div>
        <label className="search-box">
          <Search size={16} />
          <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search product codes" />
          <kbd>⌘ K</kbd>
        </label>
      </div>

      <div className="review-empty">
        <div className="review-empty-illustration">
          <div className="review-check"><Check size={23} /></div>
          <div className="review-code">LechHydrFree</div>
          <div className="review-code faded">LechHvdrFree</div>
        </div>
        <strong>All clear for now</strong>
        <p>When a receipt contains a new or misspelled code, it’ll land here for a quick decision.</p>
        <button className="secondary-button" type="button" onClick={onAddReceipt}>
          <Plus size={15} /> Add a receipt <ArrowRight size={14} />
        </button>
        <span className="review-empty-foot"><ShieldCheck size={13} /> Only authorized reviewers can change the product catalog.</span>
      </div>
      <div className="page-footnote">Product codes are matched exactly after your review <span>·</span> no display names required</div>
    </>
  );
}

function StatCard({ label, value, detail, icon }: { label: string; value: string; detail: string; icon: React.ReactNode }) {
  return (
    <div className="stat-card">
      <div className="stat-top"><span>{label}</span><span className="stat-icon">{icon}</span></div>
      <strong>{value}</strong>
      <small>{detail}</small>
    </div>
  );
}

export default App;
