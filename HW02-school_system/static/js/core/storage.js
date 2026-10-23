import { config } from "../config.js";

const PREFIX = config.storagePrefix;

export const storage = {
  get(key, fallback = null) {
    try {
      const raw = localStorage.getItem(PREFIX + key);
      return raw == null ? fallback : JSON.parse(raw);
    } catch {
      return fallback;
    }
  },
  set(key, value) {
    try {
      localStorage.setItem(PREFIX + key, JSON.stringify(value));
    } catch {
      /* quota exceeded — silently ignore in demo */
    }
  },
  remove(key) {
    try { localStorage.removeItem(PREFIX + key); } catch { /* noop */ }
  },
};