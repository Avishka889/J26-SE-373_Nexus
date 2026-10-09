/**
 * Safe localStorage wrapper. Do not store tokens, API keys, or other secrets.
 */

export const storage = {
  get(key: string): string | null {
    try {
      return localStorage.getItem(key);
    } catch {
      return null;
    }
  },

  set(key: string, value: string): void {
    try {
      localStorage.setItem(key, value);
    } catch {
      // Quota or privacy mode, so ignore it
    }
  },

  remove(key: string): void {
    try {
      localStorage.removeItem(key);
    } catch {
      // ignore
    }
  },
};
