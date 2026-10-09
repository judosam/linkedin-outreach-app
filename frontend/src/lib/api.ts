/* Thin fetch client for the FastAPI backend. Cookie session auth, so every
   request sends credentials; a 401 signals the caller to show the login view. */

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

async function detail(res: Response): Promise<string> {
  try {
    const j = await res.json();
    if (Array.isArray(j?.detail)) {
      return j.detail
        .map((e: { loc?: string[]; msg?: string }) => `${(e.loc || []).slice(1).join('.')}: ${e.msg}`)
        .join('; ');
    }
    if (j?.detail) return String(j.detail);
    return JSON.stringify(j);
  } catch {
    return res.statusText || 'Request failed';
  }
}

async function request<T>(method: string, url: string, body?: unknown): Promise<T> {
  const isForm = typeof FormData !== 'undefined' && body instanceof FormData;
  const res = await fetch(url, {
    method,
    credentials: 'include',
    cache: 'no-store',
    signal: AbortSignal.timeout(30000),
    headers: body !== undefined && !isForm ? { 'Content-Type': 'application/json' } : undefined,
    body: isForm ? body : body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) throw new ApiError(await detail(res), res.status);
  return res.json() as Promise<T>;
}

export const apiGet = <T>(url: string) => request<T>('GET', url);
export const apiPost = <T>(url: string, body?: unknown) => request<T>('POST', url, body);
export const apiPut = <T>(url: string, body?: unknown) => request<T>('PUT', url, body);
export const apiDelete = <T>(url: string) => request<T>('DELETE', url);
