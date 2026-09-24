import { useEffect, useRef } from "react";
import { accessToken, apiBase } from "../lib/deploy";

type MessageHandler = (payload: unknown) => void;

/**
 * Reconnecting WebSocket. Pass `enabled=false` to suspend; pass a factory for
 * the URL so callers can rebuild it when the run id changes.
 */
export function useWebSocket(
  urlFactory: () => string | null,
  onMessage: MessageHandler,
  onStatus?: (connected: boolean) => void,
): { reconnect: () => void } {
  const socketRef = useRef<WebSocket | null>(null);
  const retryRef = useRef<number | null>(null);
  const handlerRef = useRef(onMessage);
  const statusRef = useRef(onStatus);
  const generationRef = useRef(0);
  handlerRef.current = onMessage;
  statusRef.current = onStatus;

  const connect = () => {
    const generation = ++generationRef.current;
    if (retryRef.current) {
      window.clearTimeout(retryRef.current);
      retryRef.current = null;
    }
    socketRef.current?.close();
    const url = urlFactory();
    if (!url) return;
    try {
      const socket = new WebSocket(url);
      socketRef.current = socket;
      socket.onopen = () => statusRef.current?.(true);
      socket.onmessage = (message) => {
        let payload: unknown;
        try {
          payload = JSON.parse(message.data as string);
        } catch {
          return;
        }
        handlerRef.current(payload);
      };
      socket.onerror = () => socket.close();
      socket.onclose = () => {
        if (generationRef.current !== generation) return;
        statusRef.current?.(false);
        retryRef.current = window.setTimeout(connect, 1500);
      };
    } catch {
      retryRef.current = window.setTimeout(connect, 2000);
    }
  };

  useEffect(() => {
    connect();
    return () => {
      generationRef.current++;
      if (retryRef.current) window.clearTimeout(retryRef.current);
      retryRef.current = null;
      const socket = socketRef.current;
      if (socket) {
        socket.onclose = null;
        socket.close();
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return { reconnect: connect };
}

export function wsUrl(path: string): string {
  const append = (base: string) => {
    const [pathname, search] = base.split("?", 2);
    const params = new URLSearchParams(search || "");
    return { pathname, params };
  };
  if (apiBase) {
    const remote = new URL(apiBase);
    const protocol = remote.protocol === "https:" ? "wss:" : "ws:";
    const token = accessToken();
    const { pathname, params } = append(path);
    if (token) params.set("token", token);
    const query = params.toString();
    return `${protocol}//${remote.host}${pathname}${query ? `?${query}` : ""}`;
  }
  const protocol = location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${location.host}${path}`;
}
