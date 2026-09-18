const API_KEY = 'credit-review-api-base';

export function getApiBase() {
  return (localStorage.getItem(API_KEY) || '').trim().replace(/\/$/, '');
}

export function setApiBase(value) {
  const normalized = value.trim().replace(/\/$/, '');
  if (normalized) localStorage.setItem(API_KEY, normalized);
  else localStorage.removeItem(API_KEY);
}

async function request(path, options = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), options.timeout || 120000);
  const base = getApiBase();
  try {
    const response = await fetch(base + path, {
      ...options,
      timeout: undefined,
      signal: controller.signal,
      headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    });
    const raw = await response.text();
    let body = null;
    try { body = raw ? JSON.parse(raw) : null; } catch { body = { detail: raw }; }
    if (!response.ok) {
      const detail = body && (body.detail || body.message);
      throw new Error(detail || ('请求失败（HTTP ' + response.status + '）'));
    }
    return body;
  } catch (error) {
    if (error.name === 'AbortError') throw new Error('请求超时。当前复核 API 是同步执行的，请检查后端状态后重试。');
    if (error instanceof TypeError) throw new Error('无法连接复核 API。请检查服务是否运行，以及 API 地址设置是否正确。');
    throw error;
  } finally {
    clearTimeout(timer);
  }
}

export const api = {
  health: () => request('/health/live', { timeout: 8000 }),
  createReview: (payload) => request('/v1/reviews', { method: 'POST', body: JSON.stringify(payload) }),
  getReview: (reviewId) => request('/v1/reviews/' + encodeURIComponent(reviewId)),
  humanTasks: () => request('/v1/human-tasks'),
  submitDecision: (reviewId, payload) => request('/v1/human-tasks/' + encodeURIComponent(reviewId) + '/decision', {
    method: 'POST', body: JSON.stringify(payload),
  }),
};
