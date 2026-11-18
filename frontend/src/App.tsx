import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { apiRequest } from "./api";
import {
  type AnalyticsSummary,
  type CandidateResolution,
  type CandidateResolutionResult,
  type CanonicalProduct,
  type ProductCodeCandidate,
  type ReceiptDetail,
  type ReceiptReprocessResult,
  type ReceiptSummary,
} from "./api";
import {
  ArrowLeft,
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
  RotateCcw,
  Search,
  Settings2,
  ShieldCheck,
  Sparkles,
  Upload,
} from "lucide-react";

type View = "receipts" | "receipt-detail" | "products" | "insights";
type ApiStatus = "checking" | "available" | "unavailable";

function App() {
  const [view, setView] = useState<View>("receipts");
  const [apiStatus, setApiStatus] = useState<ApiStatus>("checking");
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);
  const [receipts, setReceipts] = useState<ReceiptSummary[]>([]);
  const [selectedReceiptId, setSelectedReceiptId] = useState<string | null>(null);
  const [receiptError, setReceiptError] = useState<string | null>(null);
  const [candidates, setCandidates] = useState<ProductCodeCandidate[]>([]);
  const [products, setProducts] = useState<CanonicalProduct[]>([]);
  const [productError, setProductError] = useState<string | null>(null);
  const [analytics, setAnalytics] = useState<AnalyticsSummary | null>(null);
  const [analyticsError, setAnalyticsError] = useState<string | null>(null);
  const [isLoadingCandidates, setIsLoadingCandidates] = useState(false);
  const [resolvingCandidateId, setResolvingCandidateId] = useState<string | null>(null);
  const [isLoadingReceipts, setIsLoadingReceipts] = useState(false);
  const [isLoadingAnalytics, setIsLoadingAnalytics] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [retailerCode, setRetailerCode] = useState("biedronka");
  const [search, setSearch] = useState("");
  const fileInput = useRef<HTMLInputElement>(null);
  const hasLoadedReceipts = useRef(false);

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

  const hasActiveReceipts = receipts.some(
    (receipt) => receipt.status === "queued" || receipt.status === "processing",
  );

  useEffect(() => {
    let active = true;
    const refresh = () => {
      if (!hasLoadedReceipts.current) {
        setIsLoadingReceipts(true);
      }
      apiRequest<ReceiptSummary[]>("/receipts")
        .then((value) => {
          if (active) {
            setReceipts(value);
            setReceiptError(null);
            hasLoadedReceipts.current = true;
          }
        })
        .catch((error: unknown) => {
          if (active) {
            setReceiptError(error instanceof Error ? error.message : "Could not load receipts.");
          }
        })
        .finally(() => {
          if (active) {
            setIsLoadingReceipts(false);
          }
        });
    };
    refresh();
    const intervalId = hasActiveReceipts ? window.setInterval(refresh, 5000) : undefined;

    return () => {
      active = false;
      if (intervalId !== undefined) {
        window.clearInterval(intervalId);
      }
    };
  }, [hasActiveReceipts]);

  useEffect(() => {
    if (view !== "products") {
      return;
    }

    let active = true;
    setIsLoadingCandidates(true);
    setProductError(null);
    Promise.all([
      apiRequest<ProductCodeCandidate[]>("/admin/product-candidates"),
      apiRequest<CanonicalProduct[]>("/admin/products"),
    ])
      .then(([candidateRows, productRows]) => {
        if (active) {
          setCandidates(candidateRows);
          setProducts(productRows);
        }
      })
      .catch((error: unknown) => {
        if (active) {
          setProductError(error instanceof Error ? error.message : "Could not load product review data.");
        }
      })
      .finally(() => {
        if (active) {
          setIsLoadingCandidates(false);
        }
      });

    return () => {
      active = false;
    };
  }, [view]);

  useEffect(() => {
    if (view !== "insights") {
      return;
    }

    let active = true;
    setIsLoadingAnalytics(true);
    setAnalyticsError(null);
    apiRequest<AnalyticsSummary>("/analytics")
      .then((value) => {
        if (active) {
          setAnalytics(value);
        }
      })
      .catch((error: unknown) => {
        if (active) {
          setAnalyticsError(error instanceof Error ? error.message : "Could not load insights.");
        }
      })
      .finally(() => {
        if (active) {
          setIsLoadingAnalytics(false);
        }
      });

    return () => {
      active = false;
    };
  }, [view]);

  function chooseFile(file?: File) {
    if (!file) {
      return;
    }

    const supportedExtension = retailerCode === "biedronka" ? ".pdf" : ".png";
    const supported = file.name.toLowerCase().endsWith(supportedExtension);
    if (!supported) {
      setSelectedFile(null);
      setFileError(retailerCode === "biedronka"
        ? "Choose a Biedronka PDF receipt."
        : "Choose a Lidl PNG receipt.");
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

  async function uploadReceipt() {
    if (!selectedFile) {
      return;
    }
    setIsUploading(true);
    setFileError(null);
    const formData = new FormData();
    formData.set("file", selectedFile);
    formData.set("retailer_code", retailerCode);
    try {
      await apiRequest<{ id: string; status: string }>("/receipts", {
        method: "POST",
        body: formData,
      });
      setSelectedFile(null);
      setIsLoadingReceipts(true);
      const updatedReceipts = await apiRequest<ReceiptSummary[]>("/receipts");
      setReceipts(updatedReceipts);
    } catch (error) {
      setFileError(error instanceof Error ? error.message : "Receipt upload failed.");
    } finally {
      setIsUploading(false);
      setIsLoadingReceipts(false);
    }
  }

  async function resolveCandidate(candidateId: string, resolution: CandidateResolution) {
    setResolvingCandidateId(candidateId);
    setProductError(null);
    try {
      const result = await apiRequest<CandidateResolutionResult>(
        `/admin/product-candidates/${candidateId}/resolve`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(resolution),
        },
      );
      setCandidates((current) => current.filter((candidate) => candidate.id !== candidateId));
      setProducts((current) => (
        current.some((product) => product.id === result.product_id)
          ? current
          : [...current, { id: result.product_id, code: result.product_code }].sort(
              (a, b) => a.code.localeCompare(b.code),
            )
      ));
      try {
        setReceipts(await apiRequest<ReceiptSummary[]>("/receipts"));
        setReceiptError(null);
      } catch (error) {
        setReceiptError(error instanceof Error ? error.message : "Could not refresh receipt statuses.");
      }
    } catch (error) {
      setProductError(error instanceof Error ? error.message : "Could not resolve product code.");
    } finally {
      setResolvingCandidateId(null);
    }
  }

  const isProducts = view === "products";
  const isInsights = view === "insights";
  const isReceiptDetails = view === "receipt-detail";

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
            className={`nav-item ${view === "receipts" || isReceiptDetails ? "active" : ""}`}
            onClick={() => {
              setSelectedReceiptId(null);
              setView("receipts");
            }}
          >
            <ReceiptText size={18} />
            <span>Receipts</span>
            <span className="nav-count">{receipts.length}</span>
          </button>
          <button
            type="button"
            className={`nav-item ${isProducts ? "active" : ""}`}
            onClick={() => setView("products")}
          >
            <PackageCheck size={18} />
            <span>Product review</span>
            <span className="nav-count">{candidates.length}</span>
          </button>
          <button
            type="button"
            className={`nav-item ${isInsights ? "active" : ""}`}
            onClick={() => setView("insights")}
          >
            <LayoutDashboard size={18} />
            <span>Insights</span>
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
            <span className="user-avatar">L</span>
            <span className="user-label">
              Local app
              <small>Network access only</small>
            </span>
            <CircleHelp size={17} className="muted-icon" />
          </div>
        </div>
      </aside>

      <main className="main-area">
        <header className="topbar">
          <div className="breadcrumbs">
            <span>Workspace</span><span className="crumb-slash">/</span>
            <strong>
              {isProducts ? "Product review" : isInsights ? "Insights" : isReceiptDetails ? "Receipt details" : "Receipts"}
            </strong>
          </div>
          <div className="topbar-right">
            <div className={`connection-status ${apiStatus}`}>
              <span className="status-dot" />
              {apiStatus === "checking" ? "Checking API" : apiStatus === "available" ? "API connected" : "API not connected"}
            </div>
            <button className="help-button" type="button" aria-label="Help"><CircleHelp size={18} /></button>
            <span className="top-avatar">L</span>
          </div>
        </header>

        <div className="page-content">
          {isReceiptDetails && selectedReceiptId ? (
            <ReceiptDetails
              receiptId={selectedReceiptId}
              onBack={() => {
                setSelectedReceiptId(null);
                setView("receipts");
              }}
            />
          ) : isProducts ? (
            <ProductReview
              search={search}
              setSearch={setSearch}
              candidates={candidates}
              products={products}
              error={productError}
              isLoading={isLoadingCandidates}
              resolvingCandidateId={resolvingCandidateId}
              onResolve={resolveCandidate}
              onAddReceipt={() => setView("receipts")}
            />
          ) : isInsights ? (
            <Insights
              analytics={analytics}
              error={analyticsError}
              isLoading={isLoadingAnalytics}
              onAddReceipt={() => setView("receipts")}
            />
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
              retailerCode={retailerCode}
              onRetailerChange={(value) => {
                setRetailerCode(value);
                setSelectedFile(null);
                setFileError(null);
              }}
              onUpload={uploadReceipt}
              isUploading={isUploading}
              receipts={receipts}
              isLoadingReceipts={isLoadingReceipts}
              receiptError={receiptError}
              apiStatus={apiStatus}
              onSelectReceipt={(receiptId) => {
                setSelectedReceiptId(receiptId);
                setView("receipt-detail");
              }}
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
  retailerCode: string;
  onRetailerChange: (value: string) => void;
  onUpload: () => void;
  isUploading: boolean;
  receipts: ReceiptSummary[];
  isLoadingReceipts: boolean;
  receiptError: string | null;
  apiStatus: ApiStatus;
  onSelectReceipt: (receiptId: string) => void;
};

function Receipts({
  file,
  fileError,
  fileInput,
  onChooseFile,
  onClearFile,
  retailerCode,
  onRetailerChange,
  onUpload,
  isUploading,
  receipts,
  isLoadingReceipts,
  receiptError,
  apiStatus,
  onSelectReceipt,
}: ReceiptsProps) {
  const totalSpent = receipts.reduce(
    (total, receipt) => total + (receipt.total_paid ? Number(receipt.total_paid) : 0),
    0,
  );
  const totalDiscounts = receipts.reduce(
    (total, receipt) => total + Number(receipt.discount_total || 0),
    0,
  );

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
        <StatCard label="RECEIPTS ADDED" value={String(receipts.length)} detail="In this app" icon={<ReceiptText size={17} />} />
        <StatCard label="TOTAL SPENT" value={`${totalSpent.toFixed(2)} PLN`} detail="From processed receipts" icon={<ArrowDownToLine size={17} />} />
        <StatCard label="DISCOUNTS FOUND" value={`${totalDiscounts.toFixed(2)} PLN`} detail="From processed receipts" icon={<PackageCheck size={17} />} />
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
          <p>Upload a Biedronka PDF or a Lidl PNG. Processing runs securely in the background.</p>
          <label className="retailer-select">
            Store
            <select
              value={retailerCode}
              onChange={(event) => onRetailerChange(event.target.value)}
              disabled={isUploading}
            >
              <option value="biedronka">Biedronka · PDF</option>
              <option value="lidl">Lidl · PNG</option>
            </select>
          </label>
          <input
            ref={fileInput}
            className="visually-hidden"
            type="file"
            accept={retailerCode === "biedronka" ? ".pdf,application/pdf" : ".png,image/png"}
            onChange={(event) => onChooseFile(event.target.files?.[0])}
          />
          <div className="upload-actions">
            <button className="primary-button" type="button" onClick={() => fileInput.current?.click()} disabled={isUploading}>
              <Upload size={16} /> Choose a file
            </button>
            {file && (
              <button className="primary-button" type="button" onClick={onUpload} disabled={isUploading || apiStatus !== "available"}>
                <ArrowRight size={16} /> {isUploading ? "Uploading…" : "Upload receipt"}
              </button>
            )}
          </div>
          <span className="file-hint"><ShieldCheck size={14} /> {retailerCode === "biedronka" ? "PDF" : "PNG"} · up to 10 MB</span>
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
            <span className="selected-file-info"><strong>{file.name}</strong><small>{(file.size / 1024 / 1024).toFixed(2)} MB · {isUploading ? "uploading" : "selected"}</small></span>
            <button className="remove-file" onClick={onClearFile} type="button" aria-label="Remove selected file">×</button>
          </div>
        )}
      </section>

      <div className="notice-row">
        <span className="notice-icon"><CircleHelp size={16} /></span>
        <p>
          {apiStatus === "available"
            ? "No login is required. Anyone who can reach this app can view and change its receipt data."
            : "The API is unavailable. Try again when the service is ready."}
        </p>
        <button type="button" onClick={() => fileInput.current?.click()}>Select a file <ArrowRight size={14} /></button>
      </div>

      <div className="section-title-row history-title">
        <div><h2>Recent receipts</h2><p>Your uploaded receipts and processing status.</p></div>
        <span className="text-button">{receipts.length} receipts</span>
      </div>
      {receiptError && <div className="file-error" role="alert">{receiptError}</div>}
      {isLoadingReceipts ? (
        <div className="empty-table"><strong>Loading receipts…</strong></div>
      ) : receipts.length === 0 ? (
        <div className="empty-table">
          <div className="empty-icon"><ReceiptText size={21} /></div>
          <strong>No receipts yet</strong>
          <span>Choose a PDF or PNG above to get started.</span>
        </div>
      ) : (
        <div className="receipt-list">
          {receipts.map((receipt) => (
            <article className="receipt-row" key={receipt.id}>
              <span className="receipt-row-icon"><ReceiptText size={17} /></span>
              <div className="receipt-row-main">
                <strong>{receipt.retailer_name}</strong>
                <span>{receipt.original_filename}</span>
              </div>
              <span className={`receipt-status ${receipt.status}`}>
                {receipt.status.replace("_", " ")}
                {(receipt.status === "queued" || receipt.status === "processing") && receipt.stage
                  ? ` · ${receipt.stage}`
                  : ""}
              </span>
              <strong className="receipt-row-total">
                {receipt.total_paid ? `${receipt.total_paid} ${receipt.currency}` : "—"}
              </strong>
              <button
                className="receipt-details-button"
                type="button"
                onClick={() => onSelectReceipt(receipt.id)}
              >
                Details <ArrowRight size={14} />
              </button>
              {receipt.status === "failed" && receipt.error && (
                <span className="receipt-error" role="status">
                  {receipt.stage ? `${receipt.stage}: ` : ""}{receipt.error}
                </span>
              )}
            </article>
          ))}
        </div>
      )}
      <div className="page-footnote">Receipt Tracker <span>·</span> built for clear, simple spending records</div>
    </>
  );
}

type ReceiptDetailsProps = {
  receiptId: string;
  onBack: () => void;
};

function ReceiptDetails({ receiptId, onBack }: ReceiptDetailsProps) {
  const [receipt, setReceipt] = useState<ReceiptDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isReprocessing, setIsReprocessing] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let active = true;
    let timeoutId: number | undefined;

    const loadReceipt = async () => {
      try {
        const value = await apiRequest<ReceiptDetail>(`/receipts/${receiptId}`);
        if (!active) {
          return;
        }
        setReceipt(value);
        setError(null);
        if (value.status === "queued" || value.status === "processing") {
          timeoutId = window.setTimeout(loadReceipt, 5000);
        }
      } catch (loadError) {
        if (active) {
          setError(loadError instanceof Error ? loadError.message : "Could not load receipt details.");
        }
      } finally {
        if (active) {
          setIsLoading(false);
        }
      }
    };

    setReceipt(null);
    setError(null);
    setIsLoading(true);
    void loadReceipt();

    return () => {
      active = false;
      if (timeoutId !== undefined) {
        window.clearTimeout(timeoutId);
      }
    };
  }, [receiptId, reloadKey]);

  const formatMoney = (value: string | null) => (
    value === null || !receipt ? "—" : `${value} ${receipt.currency}`
  );

  async function reprocessReceipt() {
    setIsReprocessing(true);
    setError(null);
    try {
      await apiRequest<ReceiptReprocessResult>(`/receipts/${receiptId}/reprocess`, {
        method: "POST",
      });
      setReloadKey((current) => current + 1);
    } catch (reprocessError) {
      setError(
        reprocessError instanceof Error
          ? reprocessError.message
          : "Could not reprocess this receipt.",
      );
    } finally {
      setIsReprocessing(false);
    }
  }

  return (
    <>
      <button className="receipt-back-button" type="button" onClick={onBack}>
        <ArrowLeft size={15} /> All receipts
      </button>
      {error && <div className="file-error" role="alert">{error}</div>}
      {!receipt ? (
        <div className="empty-table">
          <strong>{isLoading ? "Loading receipt details…" : "Receipt details unavailable"}</strong>
        </div>
      ) : (
        <>
          <div className="page-heading receipt-detail-heading">
            <div>
              <div className="eyebrow"><span className="eyebrow-mark" /> RECEIPT DETAILS</div>
              <h1>{receipt.retailer_name}<span> · {receipt.original_filename}</span></h1>
              <p>
                {receipt.receipt_number ? `Receipt ${receipt.receipt_number}` : "Receipt number unavailable"}
                {receipt.purchased_at
                  ? ` · ${new Date(receipt.purchased_at).toLocaleString()}`
                  : ""}
              </p>
            </div>
            <div className="receipt-detail-heading-actions">
              <span className={`receipt-status ${receipt.status}`}>
                {receipt.status.replace("_", " ")}
              </span>
              {receipt.status === "failed" && (
                <button
                  className="receipt-reprocess-button"
                  type="button"
                  onClick={reprocessReceipt}
                  disabled={isReprocessing}
                >
                  <RotateCcw size={14} />
                  {isReprocessing ? "Queueing…" : "Reprocess"}
                </button>
              )}
            </div>
          </div>

          {receipt.error && (
            <div className="receipt-detail-error" role="status">
              {receipt.stage ? `${receipt.stage}: ` : ""}{receipt.error}
            </div>
          )}
          {(receipt.status === "queued" || receipt.status === "processing") && (
            <div className="receipt-detail-notice">
              Processing is still in progress. This page will refresh automatically.
            </div>
          )}

          <div className="receipt-detail-totals">
            <div><span>Subtotal</span><strong>{formatMoney(receipt.subtotal)}</strong></div>
            <div><span>Discounts</span><strong>{formatMoney(receipt.discount_total)}</strong></div>
            <div><span>Total paid</span><strong>{formatMoney(receipt.total_paid)}</strong></div>
          </div>

          <div className="section-title-row receipt-items-heading">
            <div>
              <h2>Products from this receipt</h2>
              <p>{receipt.items.length} purchase lines · Values are extracted from the receipt</p>
            </div>
          </div>
          {receipt.items.length === 0 ? (
            <div className="empty-table">
              <strong>{receipt.status === "queued" || receipt.status === "processing"
                ? "Product lines will appear when processing finishes."
                : "No product lines are available for this receipt."}</strong>
            </div>
          ) : (
            <div className="receipt-items-table-wrap">
              <table className="receipt-items-table">
                <thead>
                  <tr>
                    <th>Line</th>
                    <th>Product code</th>
                    <th>Quantity</th>
                    <th>Unit price</th>
                    <th>Discount</th>
                    <th>Line total</th>
                  </tr>
                </thead>
                <tbody>
                  {receipt.items.map((item) => (
                    <tr key={item.line_number}>
                      <td>{item.line_number}</td>
                      <td>
                        <strong>{item.product_code}</strong>
                        {item.canonical_product_code && item.canonical_product_code !== item.product_code && (
                          <small>Matched to {item.canonical_product_code}</small>
                        )}
                        {item.needs_product_review && (
                          <small className="receipt-item-review">Needs product-code review</small>
                        )}
                      </td>
                      <td>{item.quantity}{item.unit ? ` ${item.unit}` : ""}</td>
                      <td>{formatMoney(item.unit_price)}</td>
                      <td>{formatMoney(item.discount_amount)}</td>
                      <td>{formatMoney(item.line_total)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <div className="page-footnote">Receipt Tracker <span>·</span> extracted purchase details</div>
        </>
      )}
    </>
  );
}

function Insights({
  analytics,
  error,
  isLoading,
  onAddReceipt,
}: {
  analytics: AnalyticsSummary | null;
  error: string | null;
  isLoading: boolean;
  onAddReceipt: () => void;
}) {
  return (
    <>
      <div className="page-heading">
        <div>
          <div className="eyebrow"><span className="eyebrow-mark" /> YOUR SPENDING</div>
          <h1>Insights, <span>made from your receipts.</span></h1>
          <p>Completed receipts only. Each currency is reported separately.</p>
        </div>
      </div>

      {error && <div className="file-error" role="alert">{error}</div>}
      {isLoading && !analytics ? (
        <div className="insights-empty" role="status"><strong>Loading your insights…</strong></div>
      ) : !analytics ? (
        <div className="insights-empty">
          <div className="empty-icon"><LayoutDashboard size={21} /></div>
          <strong>Insights are unavailable</strong>
          <span>Try opening this page again in a moment.</span>
        </div>
      ) : analytics.currency_totals.length === 0 ? (
        <div className="insights-empty">
          <div className="empty-icon"><LayoutDashboard size={21} /></div>
          <strong>No completed receipts yet</strong>
          <span>Spending trends will appear after a receipt has been processed and reviewed.</span>
          <button className="secondary-button" type="button" onClick={onAddReceipt}>
            <Plus size={15} /> Add a receipt <ArrowRight size={14} />
          </button>
        </div>
      ) : (
        <>
          <section className="insights-currency-grid" aria-label="All-time totals">
            {analytics.currency_totals.map((total) => (
              <article className="insights-currency-card" key={total.currency}>
                <div className="insights-card-heading">
                  <span>{total.currency} · ALL TIME</span>
                  <ReceiptText size={17} />
                </div>
                <strong>{formatAmount(total.total_paid, total.currency)}</strong>
                <div className="insights-card-details">
                  <span><PackageCheck size={14} /> Discounts {formatAmount(total.discount_total, total.currency)}</span>
                  <span><ReceiptText size={14} /> {total.receipt_count} completed {total.receipt_count === 1 ? "receipt" : "receipts"}</span>
                </div>
              </article>
            ))}
          </section>

          <section className="insights-panel">
            <div className="section-title-row">
              <div><h2>Monthly spending</h2><p>Receipt totals for the last 12 months</p></div>
              <span className="period-pill"><Clock3 size={14} /> 12 months</span>
            </div>
            <div className="insights-charts">
              {analytics.currency_totals.map((total) => (
                <MonthlySpendChart
                  key={total.currency}
                  currency={total.currency}
                  months={analytics.monthly_totals.filter((month) => month.currency === total.currency)}
                />
              ))}
            </div>
          </section>

          <section className="insights-panel">
            <div className="section-title-row">
              <div><h2>Frequently purchased products</h2><p>Ranked by receipt-line appearances across completed receipts</p></div>
            </div>
            {analytics.top_products.length === 0 ? (
              <div className="insights-table-empty">No product lines are available yet.</div>
            ) : (
              <div className="insights-table-wrap">
                <table className="insights-table">
                  <thead>
                    <tr>
                      <th scope="col">Product code</th>
                      <th scope="col">Unit</th>
                      <th scope="col">Receipt lines</th>
                      <th scope="col">Quantity</th>
                      <th scope="col">Discounts</th>
                    </tr>
                  </thead>
                  <tbody>
                    {analytics.top_products.map((product) => (
                      <tr key={`${product.product_code}-${product.unit ?? ""}-${product.currency}`}>
                        <td><strong>{product.product_code}</strong></td>
                        <td>{product.unit ?? "—"}</td>
                        <td>{product.purchase_lines} · {product.receipt_count} {product.receipt_count === 1 ? "receipt" : "receipts"}</td>
                        <td>{Number(product.quantity).toLocaleString(undefined, { maximumFractionDigits: 3 })} {product.unit ?? ""}</td>
                        <td>{formatAmount(product.discount_total, product.currency)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </>
      )}
      <div className="page-footnote">Only your own completed receipts are included <span>·</span> currencies are never combined</div>
    </>
  );
}

function MonthlySpendChart({
  currency,
  months,
}: {
  currency: string;
  months: AnalyticsSummary["monthly_totals"];
}) {
  const maximum = Math.max(...months.map((month) => Number(month.total_paid)), 0);
  const chartDescription = months
    .map((month) => `${month.month}: ${formatAmount(month.total_paid, currency)}`)
    .join("; ");

  return (
    <div className="insights-chart">
      <h3>{currency}</h3>
      <div
        className="insights-month-bars"
        role="img"
        aria-label={`Monthly spending in ${currency}. ${chartDescription}`}
      >
        {months.map((month) => {
          const amount = Number(month.total_paid);
          const height = maximum > 0 && amount > 0 ? Math.max((amount / maximum) * 100, 3) : 0;
          const [year, monthNumber] = month.month.split("-").map(Number);
          const monthLabel = new Date(year, monthNumber - 1, 15).toLocaleDateString(undefined, {
            month: "short",
          });
          return (
            <div
              className="insights-month"
              key={month.month}
              title={`${month.month}: ${formatAmount(month.total_paid, currency)}`}
            >
              <div className="insights-bar-area">
                <span className="insights-bar" style={{ height: `${height}%` }} />
              </div>
              <span className="insights-month-label">{monthLabel}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function formatAmount(value: string, currency: string): string {
  const formatted = Number(value).toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
  return `${formatted} ${currency}`;
}

function ProductReview({
  search,
  setSearch,
  candidates,
  products,
  error,
  isLoading,
  resolvingCandidateId,
  onResolve,
  onAddReceipt,
}: {
  search: string;
  setSearch: (value: string) => void;
  candidates: ProductCodeCandidate[];
  products: CanonicalProduct[];
  error: string | null;
  isLoading: boolean;
  resolvingCandidateId: string | null;
  onResolve: (candidateId: string, resolution: CandidateResolution) => void;
  onAddReceipt: () => void;
}) {
  const filteredCandidates = candidates.filter((candidate) =>
    candidate.observed_code.toLocaleLowerCase().includes(search.toLocaleLowerCase()),
  );

  return (
    <>
      <div className="page-heading">
        <div>
          <div className="eyebrow"><span className="eyebrow-mark review-mark" /> CATALOG CARE</div>
          <h1>Product <span>review.</span></h1>
          <p>Resolve unfamiliar receipt codes once. We’ll remember your choice for next time.</p>
        </div>
        <span className="queue-badge"><span /> {candidates.length} awaiting review</span>
      </div>

      <div className="review-summary">
        <div className="review-summary-icon"><PackageCheck size={20} /></div>
        <div><strong>Your product catalog stays tidy.</strong><p>Accept a code as-is, correct a typo, or match it to an existing product code.</p></div>
        <div className="review-summary-steps"><span>01 <small>SPOT</small></span><ArrowRight size={14} /><span>02 <small>RESOLVE</small></span><ArrowRight size={14} /><span>03 <small>REMEMBER</small></span></div>
      </div>

      <div className="section-title-row review-list-heading">
        <div><h2>Needs your attention <span className="small-count">{candidates.length}</span></h2><p>New codes will appear here after a receipt is processed.</p></div>
        <label className="search-box">
          <Search size={16} />
          <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search product codes" />
        </label>
      </div>

      {error && <div className="file-error" role="alert">{error}</div>}
      {isLoading ? (
        <div className="review-empty"><strong>Loading product codes…</strong></div>
      ) : filteredCandidates.length === 0 ? (
        <div className="review-empty">
          <div className="review-empty-illustration">
            <div className="review-check"><Check size={23} /></div>
            <div className="review-code">Product code</div>
            <div className="review-code faded">Needs review</div>
          </div>
          <strong>{candidates.length === 0 ? "All clear for now" : "No matching product codes"}</strong>
          <p>
            {candidates.length === 0
              ? "New or unfamiliar codes will appear here after a receipt is processed."
              : "Try another search, or clear the search field to see all pending codes."}
          </p>
          {candidates.length === 0 && (
            <button className="secondary-button" type="button" onClick={onAddReceipt}>
              <Plus size={15} /> Add a receipt <ArrowRight size={14} />
            </button>
          )}
          <span className="review-empty-foot"><ShieldCheck size={13} /> Anyone who can reach the app can change the product catalog.</span>
        </div>
      ) : (
        <div className="candidate-list">
          {filteredCandidates.map((candidate) => (
            <CandidateReviewCard
              key={candidate.id}
              candidate={candidate}
              products={products}
              isResolving={resolvingCandidateId === candidate.id}
              onResolve={onResolve}
            />
          ))}
        </div>
      )}
      <div className="page-footnote">Product codes are matched exactly after your review <span>·</span> no display names required</div>
    </>
  );
}

function CandidateReviewCard({
  candidate,
  products,
  isResolving,
  onResolve,
}: {
  candidate: ProductCodeCandidate;
  products: CanonicalProduct[];
  isResolving: boolean;
  onResolve: (candidateId: string, resolution: CandidateResolution) => void;
}) {
  const [resolutionType, setResolutionType] = useState<CandidateResolution["resolution_type"]>("accepted_as_is");
  const [productCode, setProductCode] = useState(candidate.observed_code);
  const [productId, setProductId] = useState(products[0]?.id ?? "");

  function submitResolution(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (resolutionType === "accepted_as_is") {
      onResolve(candidate.id, { resolution_type: resolutionType });
    } else if (resolutionType === "edited_code") {
      onResolve(candidate.id, { resolution_type: resolutionType, product_code: productCode });
    } else if (productId) {
      onResolve(candidate.id, { resolution_type: resolutionType, product_id: productId });
    }
  }

  return (
    <article className="candidate-card">
      <div className="candidate-heading">
        <div>
          <span className="candidate-label">OBSERVED CODE</span>
          <strong>{candidate.observed_code}</strong>
        </div>
        <span className="candidate-occurrences">
          {candidate.occurrence_count} {candidate.occurrence_count === 1 ? "receipt line" : "receipt lines"}
        </span>
      </div>
      <form className="candidate-form" onSubmit={submitResolution}>
        <label>
          Resolve as
          <select
            value={resolutionType}
            onChange={(event) => {
              const value = event.target.value;
              if (value === "accepted_as_is" || value === "edited_code" || value === "mapped_existing") {
                setResolutionType(value);
              }
            }}
            disabled={isResolving}
          >
            <option value="accepted_as_is">Accept observed code</option>
            <option value="edited_code">Edit and create canonical code</option>
            <option value="mapped_existing">Map to an existing product</option>
          </select>
        </label>
        {resolutionType === "edited_code" && (
          <label>
            Canonical code
            <input
              value={productCode}
              onChange={(event) => setProductCode(event.target.value)}
              maxLength={300}
              required
              disabled={isResolving}
            />
          </label>
        )}
        {resolutionType === "mapped_existing" && (
          <label>
            Existing product
            <select
              value={productId}
              onChange={(event) => setProductId(event.target.value)}
              required
              disabled={isResolving || products.length === 0}
            >
              <option value="" disabled>Select a product</option>
              {products.map((product) => (
                <option key={product.id} value={product.id}>{product.code}</option>
              ))}
            </select>
          </label>
        )}
        <button
          className="secondary-button"
          type="submit"
          disabled={isResolving || (resolutionType === "mapped_existing" && products.length === 0)}
        >
          {isResolving ? "Saving…" : "Resolve code"}
        </button>
      </form>
    </article>
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
