/**
 * API请求优化器 - 缓存、防抖、重试
 */

// LRU 缓存实现
class LRUCache {
  constructor(maxSize = 50) {
    this.maxSize = maxSize;
    this.cache = new Map();
  }

  get(key) {
    if (!this.cache.has(key)) return undefined;
    const value = this.cache.get(key);
    // 刷新访问顺序
    this.cache.delete(key);
    this.cache.set(key, value);
    return value;
  }

  set(key, value) {
    if (this.cache.has(key)) {
      this.cache.delete(key);
    } else if (this.cache.size >= this.maxSize) {
      // 删除最旧的项（Map的第一个键）
      const firstKey = this.cache.keys().next().value;
      this.cache.delete(firstKey);
    }
    this.cache.set(key, value);
  }

  clear() {
    this.cache.clear();
  }
}

// 请求缓存
const requestCache = new LRUCache(100);
const pendingRequests = new Map();

/**
 * 带缓存的 fetch 包装器
 */
export async function cachedFetch(url, options = {}) {
  const cacheKey = `${url}:${JSON.stringify(options)}`;

  // 检查缓存
  if (options.method === 'GET' || !options.method) {
    const cached = requestCache.get(cacheKey);
    if (cached && Date.now() - cached.timestamp < (options.cacheTTL || 30000)) {
      return cached.data;
    }
  }

  // 防止重复请求
  if (pendingRequests.has(cacheKey)) {
    return pendingRequests.get(cacheKey);
  }

  const requestPromise = fetch(url, options)
    .then(res => {
      if (!res.ok) throw new Error(`HTTP ${res.status}: ${res.statusText}`);
      return res.json();
    })
    .then(data => {
      if (options.method === 'GET' || !options.method) {
        requestCache.set(cacheKey, { data, timestamp: Date.now() });
      }
      pendingRequests.delete(cacheKey);
      return data;
    })
    .catch(err => {
      pendingRequests.delete(cacheKey);
      throw err;
    });

  pendingRequests.set(cacheKey, requestPromise);
  return requestPromise;
}

/**
 * 防抖函数
 */
export function debounce(fn, delay = 300) {
  let timer = null;
  return function(...args) {
    clearTimeout(timer);
    timer = setTimeout(() => fn.apply(this, args), delay);
  };
}

/**
 * 节流函数
 */
export function throttle(fn, limit = 300) {
  let inThrottle = false;
  return function(...args) {
    if (!inThrottle) {
      fn.apply(this, args);
      inThrottle = true;
      setTimeout(() => inThrottle = false, limit);
    }
  };
}

/**
 * 带重试的请求
 */
export async function fetchWithRetry(url, options = {}, maxRetries = 3) {
  let lastError;

  for (let i = 0; i <= maxRetries; i++) {
    try {
      return await fetch(url, options);
    } catch (error) {
      lastError = error;
      if (i < maxRetries) {
        // 指数退避
        await new Promise(resolve => setTimeout(resolve, Math.pow(2, i) * 1000));
      }
    }
  }

  throw lastError;
}

/**
 * 批量请求优化器
 */
export class BatchRequestQueue {
  constructor(batchSize = 5, delay = 100) {
    this.queue = [];
    this.batchSize = batchSize;
    this.delay = delay;
    this.timer = null;
  }

  add(requestFn) {
    return new Promise((resolve, reject) => {
      this.queue.push({ requestFn, resolve, reject });
      this.scheduleFlush();
    });
  }

  scheduleFlush() {
    if (this.timer) return;

    this.timer = setTimeout(() => {
      this.flush();
    }, this.delay);
  }

  async flush() {
    clearTimeout(this.timer);
    this.timer = null;

    const batch = this.queue.splice(0, this.batchSize);
    if (batch.length === 0) return;

    // 并行执行批次
    await Promise.allSettled(
      batch.map(async ({ requestFn, resolve, reject }) => {
        try {
          const result = await requestFn();
          resolve(result);
        } catch (error) {
          reject(error);
        }
      })
    );

    // 如果还有请求，继续处理
    if (this.queue.length > 0) {
      this.scheduleFlush();
    }
  }
}

// 清除缓存
export function clearRequestCache() {
  requestCache.clear();
}
