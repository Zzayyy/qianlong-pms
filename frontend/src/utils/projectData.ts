import { ref } from 'vue'

/**
 * 项目数据版本号：列表页与详情页是两个路由实例（/projects 与 /projects/:id），
 * 详情页改了状态、进度、基础信息后自增，缓存中的列表页据此重新取数，避免返回列表看到旧数据。
 */
export const projectDataVersion = ref(0)

/** 标记项目数据已变更。 */
export const bumpProjectData = () => {
  projectDataVersion.value += 1
}
