/**
 * 增强型状态管理 - 支持订阅、持久化、时间旅行调试
 */

// 原有的历史记录功能保留
const HISTORY_KEY = 'credit-review-history';

export function readHistory() {
  try {
    return JSON.parse(localStorage.getItem(HISTORY_KEY) || '[]');
  } catch {
    return [];
  }
}

export function saveHistoryEntry(entry) {
  const hist = readHistory();
  hist.unshift({...entry, createdAt: Date.now()});
  if (hist.length > 100) hist.length = 100;
  localStorage.setItem(HISTORY_KEY, JSON.stringify(hist));
}

export function updateHistoryEntry(reviewId, updates) {
  const hist = readHistory();
  const index = hist.findIndex(e => e.reviewId === reviewId);
  if (index >= 0) {
    hist[index] = {...hist[index], ...updates, updatedAt: Date.now()};
    localStorage.setItem(HISTORY_KEY, JSON.stringify(hist));
  }
}

export function getHistoryEntry(reviewId) {
  return readHistory().find(e => e.reviewId === reviewId);
}

export function deleteHistoryEntry(reviewId) {
  const hist = readHistory().filter(e => e.reviewId !== reviewId);
  localStorage.setItem(HISTORY_KEY, JSON.stringify(hist));
}

export function clearHistory() {
  localStorage.removeItem(HISTORY_KEY);
}

// ========== 新增：增强型状态管理器 ==========

class StateStore {
  constructor(initialState = {}) {
    this.state = { ...initialState };
    this.listeners = new Map();
    this.history = []; // 时间旅行调试
    this.maxHistory = 50;
    this.middleware = [];
  }

  /**
   * 获取状态
   */
  getState(path) {
    if (!path) return this.state;
    return path.split('.').reduce((obj, key) => obj?.[key], this.state);
  }

  /**
   * 设置状态
   */
  setState(path, value) {
    const oldState = { ...this.state };

    if (typeof path === 'object' && value === undefined) {
      // 批量更新: setState({ key1: val1, key2: val2 })
      this.state = { ...this.state, ...path };
    } else {
      // 路径更新: setState('user.name', 'John')
      const keys = path.split('.');
      const lastKey = keys.pop();
      const target = keys.reduce((obj, key) => {
        if (!obj[key]) obj[key] = {};
        return obj[key];
      }, this.state);
      target[lastKey] = value;
    }

    // 执行中间件
    this.middleware.forEach(fn => fn(oldState, this.state));

    // 保存历史
    if (this.history.length >= this.maxHistory) {
      this.history.shift();
    }
    this.history.push({ state: oldState, timestamp: Date.now() });

    // 通知订阅者
    this.notifyListeners(path);
  }

  /**
   * 订阅状态变化
   */
  subscribe(path, callback) {
    if (!this.listeners.has(path)) {
      this.listeners.set(path, new Set());
    }
    this.listeners.get(path).add(callback);

    // 返回取消订阅函数
    return () => {
      const callbacks = this.listeners.get(path);
      if (callbacks) {
        callbacks.delete(callback);
        if (callbacks.size === 0) {
          this.listeners.delete(path);
        }
      }
    };
  }

  /**
   * 通知订阅者
   */
  notifyListeners(changedPath) {
    this.listeners.forEach((callbacks, listenerPath) => {
      // 如果监听的路径匹配或是父路径
      if (!listenerPath || changedPath.startsWith(listenerPath)) {
        callbacks.forEach(callback => {
          try {
            callback(this.getState(listenerPath));
          } catch (error) {
            console.error('State listener error:', error);
          }
        });
      }
    });
  }

  /**
   * 添加中间件
   */
  use(middleware) {
    this.middleware.push(middleware);
  }

  /**
   * 时间旅行 - 撤销
   */
  undo() {
    if (this.history.length > 0) {
      const previous = this.history.pop();
      this.state = previous.state;
      this.notifyListeners('');
      return true;
    }
    return false;
  }

  /**
   * 清空历史
   */
  clearHistory() {
    this.history = [];
  }

  /**
   * 重置状态
   */
  reset(initialState = {}) {
    this.state = { ...initialState };
    this.history = [];
    this.notifyListeners('');
  }
}

// 创建全局状态实例
export const globalState = new StateStore({
  user: {
    name: '',
    role: '',
  },
  ui: {
    sidebarCollapsed: false,
    theme: 'light',
    loading: false,
  },
  review: {
    current: null,
    filters: {
      type: '',
      risk: '',
    },
  },
  cache: {
    lastRefresh: null,
  },
});

// 持久化中间件
export function persistMiddleware(keys = []) {
  return (oldState, newState) => {
    keys.forEach(key => {
      if (newState[key] !== oldState[key]) {
        try {
          localStorage.setItem(`state:${key}`, JSON.stringify(newState[key]));
        } catch (error) {
          console.warn(`Failed to persist state key: ${key}`, error);
        }
      }
    });
  };
}

// 恢复持久化状态
export function restorePersistedState(store, keys = []) {
  keys.forEach(key => {
    try {
      const saved = localStorage.getItem(`state:${key}`);
      if (saved) {
        store.setState(key, JSON.parse(saved));
      }
    } catch (error) {
      console.warn(`Failed to restore state key: ${key}`, error);
    }
  });
}

// 日志中间件（开发模式）
export function loggerMiddleware(oldState, newState) {
  if (process.env.NODE_ENV === 'development') {
    console.group('State Change');
    console.log('Old State:', oldState);
    console.log('New State:', newState);
    console.groupEnd();
  }
}

// 性能监控中间件
export function performanceMiddleware(oldState, newState) {
  const start = performance.now();
  // 深度比较状态变化
  const changes = findChanges(oldState, newState);
  const duration = performance.now() - start;

  if (duration > 16) { // 超过一帧时间
    console.warn(`State update took ${duration.toFixed(2)}ms`, changes);
  }
}

function findChanges(obj1, obj2, path = '') {
  const changes = [];
  for (const key in obj2) {
    const fullPath = path ? `${path}.${key}` : key;
    if (obj1[key] !== obj2[key]) {
      changes.push(fullPath);
    }
  }
  return changes;
}

// 初始化持久化
restorePersistedState(globalState, ['ui', 'user']);
globalState.use(persistMiddleware(['ui', 'user']));
