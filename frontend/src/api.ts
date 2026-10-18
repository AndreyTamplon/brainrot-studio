export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

export const isTransientError = (error: unknown) =>
  error instanceof TypeError || (error instanceof ApiError && error.status >= 500);

export async function api<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch("/api" + path, options);
  const data = await response.json().catch(() => null);
  if (!response.ok || data === null) {
    throw new ApiError(
      typeof data?.detail === "string" ? data.detail : response.status >= 500
        ? "Студия временно недоступна" : "Проверьте параметры запроса",
      response.status,
    );
  }
  return data;
}

export async function post<T>(path: string, body: unknown = {}): Promise<T> {
  const creating = path === "/jobs" || path.endsWith("/revisions");
  const options: RequestInit = {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(creating ? { "Idempotency-Key": crypto.randomUUID() } : {}),
    },
    body: JSON.stringify(body),
  };
  try {
    return await api<T>(path, options);
  } catch (error) {
    // A lost response may hide a successful submission; preserve the logical request ID.
    if (creating && isTransientError(error)) return api<T>(path, options);
    throw error;
  }
}
