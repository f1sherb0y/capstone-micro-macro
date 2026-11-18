import type { ApiResponse } from "../types/api";

type RequestOptions = RequestInit & {
  query?: Record<string, string | number | undefined | null>;
};

export class ApiRequestError extends Error {
  status: number;
  statusText: string;
  detail: unknown;

  constructor(message: string, status: number, statusText: string, detail: unknown = null) {
    super(message);
    this.name = "ApiRequestError";
    this.status = status;
    this.statusText = statusText;
    this.detail = detail;
  }
}

export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const url = withQuery(path, options.query);
  const response = await fetch(url, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {})
    }
  });
  if (!response.ok) {
    const errorPayload = await parseErrorPayload(response);
    const detail = errorPayload?.detail ?? errorPayload;
    throw new ApiRequestError(errorMessage(detail, response), response.status, response.statusText, detail);
  }
  const payload = (await response.json()) as ApiResponse<T> | T;
  if (isWrapped<T>(payload)) {
    if (!payload.success) {
      throw new Error(payload.error?.details?.join(", ") || payload.message || "API request failed");
    }
    return payload.data;
  }
  return payload;
}

async function parseErrorPayload(response: Response): Promise<Record<string, unknown> | null> {
  try {
    return (await response.json()) as Record<string, unknown>;
  } catch {
    return null;
  }
}

function errorMessage(detail: unknown, response: Response) {
  if (detail && typeof detail === "object" && "message" in detail) {
    return String((detail as { message?: unknown }).message || `Request failed: ${response.status} ${response.statusText}`);
  }
  if (typeof detail === "string") return detail;
  return `Request failed: ${response.status} ${response.statusText}`;
}

export function post<T>(path: string, body?: unknown): Promise<T> {
  return request<T>(path, {
    method: "POST",
    body: body === undefined ? undefined : JSON.stringify(body)
  });
}

export function put<T>(path: string, body?: unknown): Promise<T> {
  return request<T>(path, {
    method: "PUT",
    body: body === undefined ? undefined : JSON.stringify(body)
  });
}

function withQuery(path: string, query?: RequestOptions["query"]) {
  if (!query) return path;
  const params = new URLSearchParams();
  Object.entries(query).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") {
      params.set(key, String(value));
    }
  });
  const queryString = params.toString();
  return queryString ? `${path}?${queryString}` : path;
}

function isWrapped<T>(payload: ApiResponse<T> | T): payload is ApiResponse<T> {
  return Boolean(payload && typeof payload === "object" && "success" in payload && "message" in payload);
}
