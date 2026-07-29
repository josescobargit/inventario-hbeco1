import { apiRequest, apiUpload } from "./client";

export type DocumentJobStatus = "pending" | "processing" | "review" | "error" | "cancelled";
export type DocumentJobKind = "purchase_order" | "supplier_invoice" | "customer_invoice";

export interface DocumentJob<T = unknown> {
  id: string;
  filename: string;
  status: DocumentJobStatus;
  progress: number;
  requires_ocr: boolean;
  result: T | null;
  error: string | null;
}

interface JobResponse<T> {
  jobs: DocumentJob<T>[];
  queue: {
    pending_ocr_jobs: number;
    pending_digital_jobs: number;
    active_ocr_jobs: number;
    active_digital_jobs: number;
  };
}

const wait = (milliseconds: number) => new Promise((resolve) => window.setTimeout(resolve, milliseconds));

async function pollDocumentJobs<T>(
  kind: DocumentJobKind,
  ids: string[],
  initial: JobResponse<T>,
  onUpdate?: (response: JobResponse<T>) => void,
): Promise<DocumentJob<T>[]> {
  let response = initial;
  const deadline = Date.now() + 3 * 60_000;
  while (response.jobs.some((job) => job.status === "pending" || job.status === "processing")) {
    if (Date.now() > deadline) throw new Error("El procesamiento continúa en segundo plano. Puedes volver a esta pantalla para consultar el avance.");
    await wait(700);
    response = await apiRequest<JobResponse<T>>(`/document-jobs?ids=${ids.join(",")}`);
    onUpdate?.(response);
  }
  const failed = response.jobs.find((job) => job.status === "error" || job.status === "cancelled");
  if (failed) throw new Error(`${failed.filename}: ${failed.error ?? "el procesamiento fue cancelado."}`);
  try { sessionStorage.removeItem(`document-jobs:${kind}`); } catch { /* Persistence is optional in restricted browsers. */ }
  return response.jobs;
}

export async function submitDocumentJobs<T>({
  kind, files, pastedText, onUpdate,
}: {
  kind: DocumentJobKind;
  files: File[];
  pastedText?: string;
  onUpdate?: (response: JobResponse<T>) => void;
}): Promise<DocumentJob<T>[]> {
  const body = new FormData();
  body.append("kind", kind);
  files.forEach((file) => body.append("files", file));
  if (pastedText?.trim()) body.append("pasted_text", pastedText.trim());
  const response = await apiUpload<JobResponse<T>>("/document-jobs", body);
  onUpdate?.(response);
  const ids = response.jobs.map((job) => job.id);
  try { sessionStorage.setItem(`document-jobs:${kind}`, ids.join(",")); } catch { /* Polling still works in this screen. */ }
  return pollDocumentJobs(kind, ids, response, onUpdate);
}

export async function resumeDocumentJobs<T>(
  kind: DocumentJobKind,
  onUpdate?: (response: JobResponse<T>) => void,
): Promise<DocumentJob<T>[]> {
  let stored: string | null = null;
  try { stored = sessionStorage.getItem(`document-jobs:${kind}`); } catch { return []; }
  const ids = stored?.split(",").filter(Boolean) ?? [];
  if (!ids.length) return [];
  const response = await apiRequest<JobResponse<T>>(`/document-jobs?ids=${ids.join(",")}`);
  onUpdate?.(response);
  return pollDocumentJobs(kind, ids, response, onUpdate);
}

export async function cancelDocumentJob(jobId: string): Promise<void> {
  await apiRequest(`/document-jobs/${jobId}`, { method: "DELETE" });
}
