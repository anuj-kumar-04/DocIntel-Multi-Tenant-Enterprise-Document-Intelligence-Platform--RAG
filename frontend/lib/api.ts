const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export function getStoredToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("docintel_access_token");
}

export function setStoredTokens(accessToken: string, refreshToken: string) {
  if (typeof window === "undefined") return;
  localStorage.setItem("docintel_access_token", accessToken);
  localStorage.setItem("docintel_refresh_token", refreshToken);
}

export function clearStoredTokens() {
  if (typeof window === "undefined") return;
  localStorage.removeItem("docintel_access_token");
  localStorage.removeItem("docintel_refresh_token");
}

export async function apiRequest<T = any>(
  endpoint: string,
  options: RequestInit = {}
): Promise<T> {
  const token = getStoredToken();
  const headers = new Headers(options.headers || {});

  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }
  if (!headers.has("Content-Type") && !(options.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }

  const url = endpoint.startsWith("http") ? endpoint : `${API_BASE_URL}${endpoint}`;
  const response = await fetch(url, { ...options, headers });

  if (response.status === 401) {
    clearStoredTokens();
    if (typeof window !== "undefined" && !window.location.pathname.includes("/login")) {
      window.location.href = "/login";
    }
    throw new Error("Unauthorized");
  }

  if (!response.ok) {
    let errMessage = "Request failed";
    try {
      const errData = await response.json();
      errMessage = errData.error?.message || errData.detail || errMessage;
    } catch {}
    throw new Error(errMessage);
  }

  if (response.status === 204) {
    return null as T;
  }

  return response.json();
}
