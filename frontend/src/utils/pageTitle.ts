import { reactive } from 'vue'

/**
 * 页面自定义标题：路由 path → 标题。
 *
 * 页面数据加载后写入（如项目详情写入项目名），标签栏与面包屑统一读它。
 * 不用改写 `route.meta.title`：vue-router 的 `useRoute()` 是 shallowReactive 的
 * getter 集合，`route.meta` 拿到的是原始对象，改了不会触发任何响应式更新。
 */
const titles = reactive<Record<string, string>>({})

/** 设置某个路由的自定义标题；空标题忽略，避免把已有标题清成占位文案。 */
export const setPageTitle = (path: string, title: string) => {
  const text = String(title || '').trim()
  if (!path || !text) return
  titles[path] = text
}

/** 取某个路由的自定义标题，没有则返回空串（调用处回落默认标题）。 */
export const pageTitleOf = (path: string) => titles[path] || ''
