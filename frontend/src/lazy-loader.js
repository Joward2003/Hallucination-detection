/**
 * 懒加载模块管理器 - 减少初始加载时间
 */
const moduleCache = new Map();

export async function lazyLoad(moduleName) {
  if (moduleCache.has(moduleName)) {
    return moduleCache.get(moduleName);
  }

  let module;
  switch(moduleName) {
    case 'workbench':
      module = await import('./workbench.js');
      break;
    case 'adapter':
      module = await import('./adapter.js');
      break;
    default:
      throw new Error(`Unknown module: ${moduleName}`);
  }

  moduleCache.set(moduleName, module);
  return module;
}

// 预加载关键模块
export function preloadCriticalModules() {
  // 在空闲时预加载
  if ('requestIdleCallback' in window) {
    requestIdleCallback(() => {
      lazyLoad('workbench');
      lazyLoad('adapter');
    });
  }
}
