export type Account = {
  id: string;
  email: string | null;
  display_name: string | null;
  is_admin: boolean;
};

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
