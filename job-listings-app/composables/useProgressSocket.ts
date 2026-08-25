// Streams progress from job-search-automation's WebSocket endpoints
// (WS /ws/run/status, WS /ws/jobs/{id}/cv-status). Each message is JSON:
// {"status": "running" | "done" | "error", "detail": "<step or reason>"}.
//
// Unlike the old HTTP polling (GET /run/status, GET /jobs/{id}/cv-status),
// the browser connects to the backend directly rather than through a Nitro
// proxy route - Nitro doesn't have a WebSocket proxy set up in this app,
// and the backend's CORS is already opened up for direct browser calls
// (see api.py). backendWsUrl() below picks a URL the *browser* can reach,
// which is not necessarily the same as runtimeConfig.backendUrl used
// server-side (that one may point at a docker-network-internal hostname
// like http://backend:8000 that the browser can't resolve at all).

export interface ProgressMessage {
  status: "running" | "done" | "error";
  detail: string;
}

export function backendWsUrl(path: string): string {
  const { public: publicConfig } = useRuntimeConfig();
  const base = publicConfig.backendWsBase as string;
  if (base) {
    return `${base.replace(/\/$/, "")}${path}`;
  }
  if (import.meta.client) {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    return `${protocol}//${window.location.hostname}:${publicConfig.backendWsPort}${path}`;
  }
  // SSR fallback - never actually opens a socket server-side, this just
  // keeps the function total.
  return `ws://localhost:${publicConfig.backendWsPort}${path}`;
}

/**
 * Opens a WebSocket at `path`, calls `onMessage` for every frame received,
 * and resolves with the final {"status": "done" | "error", ...} message.
 * Rejects if the socket errors or closes before a terminal message arrives
 * (e.g. the backend restarted mid-job).
 */
export function streamProgress(
  path: string,
  onMessage?: (message: ProgressMessage) => void,
): Promise<ProgressMessage> {
  return new Promise((resolve, reject) => {
    const url = backendWsUrl(path);
    let settled = false;
    let socket: WebSocket;
    try {
      socket = new WebSocket(url);
    } catch (err) {
      reject(err);
      return;
    }

    socket.onmessage = (event) => {
      let message: ProgressMessage;
      try {
        message = JSON.parse(event.data);
      } catch {
        return; // ignore malformed frame rather than aborting the stream
      }
      onMessage?.(message);
      if (message.status === "done" || message.status === "error") {
        settled = true;
        resolve(message);
        socket.close();
      }
    };

    socket.onerror = () => {
      if (!settled) {
        settled = true;
        reject(new Error("Lost connection to the backend"));
      }
    };

    socket.onclose = () => {
      if (!settled) {
        settled = true;
        reject(new Error("Connection closed before the job finished"));
      }
    };
  });
}
