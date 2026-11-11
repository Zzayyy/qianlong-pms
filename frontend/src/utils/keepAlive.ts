import { onActivated } from 'vue'

/**
 * keep-alive 页面重新激活时的数据刷新策略。
 *
 * 距上次加载超过 `staleMs` 才重新拉取：保留筛选、分页与未提交表单，
 * 同时避免长时间停留后回到页面仍看到过期数据。
 */
export function useKeepAliveRefresh(load: () => void | Promise<void>, staleMs = 60_000) {
  let loadedAt = 0

  /** 数据加载完成后调用，用于重置过期计时。 */
  const markLoaded = () => {
    loadedAt = Date.now()
  }

  onActivated(() => {
    if (!loadedAt || Date.now() - loadedAt < staleMs) return
    void load()
  })

  return { markLoaded }
}
