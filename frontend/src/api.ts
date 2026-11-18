export type ReceiptSummary = {
  id: string;
  retailer_code: string;
  retailer_name: string;
  original_filename: string;
  receipt_number: string | null;
  purchased_at: string | null;
  currency: string;
  total_paid: string | null;
  discount_total: string;
  status: "uploaded" | "queued" | "processing" | "needs_review" | "complete" | "failed";
  created_at: string | null;
  stage: string | null;
  error: string | null;
};

export type ReceiptLineItem = {
  line_number: number;
  product_code: string;
  canonical_product_code: string | null;
  needs_product_review: boolean;
  quantity: string;
  unit: string | null;
  unit_price: string | null;
  line_total: string | null;
  discount_amount: string;
};

export type ReceiptDetail = ReceiptSummary & {
  subtotal: string | null;
  items: ReceiptLineItem[];
};

export type AnalyticsCurrencyTotal = {
  currency: string;
  receipt_count: number;
  total_paid: string;
  discount_total: string;
};

export type AnalyticsMonthTotal = AnalyticsCurrencyTotal & {
  month: string;
};

export type AnalyticsTopProduct = {
  product_code: string;
  unit: string | null;
  currency: string;
  purchase_lines: number;
  receipt_count: number;
  quantity: string;
  discount_total: string;
};

export type AnalyticsSummary = {
  currency_totals: AnalyticsCurrencyTotal[];
  monthly_totals: AnalyticsMonthTotal[];
  top_products: AnalyticsTopProduct[];
};

export type ProductCodeCandidate = {
  id: string;
  observed_code: string;
  occurrence_count: number;
  created_at: string;
};

export type CanonicalProduct = {
  id: string;
  code: string;
};

export type CandidateResolution =
  | { resolution_type: "accepted_as_is" }
  | { resolution_type: "edited_code"; product_code: string }
  | { resolution_type: "mapped_existing"; product_id: string };

export type CandidateResolutionResult = {
  id: string;
  status: "resolved";
  product_id: string;
  product_code: string;
};

export async function apiRequest<T>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  const response = await fetch(`/api${path}`, {
    credentials: "same-origin",
    ...init,
  });
  if (!response.ok) {
    let detail = `Request failed (${response.status})`;
    try {
      const body = (await response.json()) as { detail?: string };
      if (body.detail) {
        detail = body.detail;
      }
    } catch {
      // Keep the HTTP status as the visible error when there is no JSON response.
    }
    throw new Error(detail);
  }
  return (await response.json()) as T;
}
