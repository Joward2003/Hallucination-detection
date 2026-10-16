const HISTORY_KEY = 'credit-review-local-index-v1';

export function readHistory() {
  try {
    const value = JSON.parse(localStorage.getItem(HISTORY_KEY) || '[]');
    return Array.isArray(value) ? value : [];
  } catch {
    return [];
  }
}

export function saveHistoryEntry(entry) {
  const items = readHistory().filter((item) => item.reviewId !== entry.reviewId);
  items.unshift({ ...entry, savedAt: entry.savedAt || new Date().toISOString() });
  localStorage.setItem(HISTORY_KEY, JSON.stringify(items.slice(0, 100)));
}

export function updateHistoryEntry(reviewId, updates) {
  const items = readHistory().map((item) => item.reviewId === reviewId ? { ...item, ...updates } : item);
  localStorage.setItem(HISTORY_KEY, JSON.stringify(items));
}

export function getHistoryEntry(reviewId) {
  return readHistory().find((item) => item.reviewId === reviewId) || null;
}
