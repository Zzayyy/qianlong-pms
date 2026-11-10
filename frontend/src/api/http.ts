import axios, { type AxiosError, type InternalAxiosRequestConfig } from 'axios'
import { ElMessage } from 'element-plus'

/** 统一响应体（设计稿 09 §1.1）。 */
export interface ApiEnvelope<T> {
  code: number
  message: string
  data: T
  traceId: string
  timestamp: string
}

/** 分页包装。 */
export interface Page<T> {
  list: T[]
  total: number
  pageNum: number
  pageSize: number
  pages: number
}

const http = axios.create({ baseURL: '/api/v1', timeout: 20000 })

http.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  const token = localStorage.getItem('pms_token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

http.interceptors.response.use(
  (response) => {
    const body = response.data as ApiEnvelope<unknown>
    if (body && body.code !== 0) {
      // 登录接口的错误由页面内联展示，避免 toast 与表单提示重复
      if (!response.config.url?.includes('/auth/login')) {
        ElMessage.error(`${body.code} ${body.message}`)
      }
      return Promise.reject(new Error(body.message))
    }
    return response
  },
  (error: AxiosError<ApiEnvelope<unknown>>) => {
    const status = error.response?.status ?? 0
    const body = error.response?.data
    const isLogin = error.config?.url?.includes('/auth/login') ?? false
    // 初始密码未修改：保留登录态，引导到改密页
    if (body?.code === 40303) {
      if (!location.hash.startsWith('#/change-password')) {
        ElMessage.warning(body.message || '请先修改初始密码')
        location.href = '#/change-password'
      }
      return Promise.reject(error)
    }
    // 只有「未认证 / 登录失效」才清理登录态。
    // 40301（缺少功能权限）与 40302（数据越权）属于业务权限不足：
    // 提示后必须保留会话，否则用户点一个无权按钮就会被强制登出。
    if (status === 401 || body?.code === 40101) {
      localStorage.removeItem('pms_token')
      if (!location.hash.startsWith('#/login')) {
        const current = location.hash.replace(/^#/, '') || '/dashboard'
        ElMessage.warning(body?.message || '登录已失效，请重新登录')
        location.href = `#/login?redirect=${encodeURIComponent(current)}`
        return Promise.reject(error)
      }
    }
    if (!isLogin) {
      ElMessage.error(body?.message || error.message)
    }
    return Promise.reject(error)
  }
)

/** GET 并返回 `data`。 */
export async function get<T>(url: string, params?: Record<string, unknown>): Promise<T> {
  const response = await http.get<ApiEnvelope<T>>(url, { params })
  return response.data.data
}

/** POST 并返回 `data`。 */
export async function post<T>(url: string, data?: unknown): Promise<T> {
  const response = await http.post<ApiEnvelope<T>>(url, data)
  return response.data.data
}

/** PUT 并返回 `data`。 */
export async function put<T>(url: string, data?: unknown): Promise<T> {
  const response = await http.put<ApiEnvelope<T>>(url, data)
  return response.data.data
}

/** DELETE 并返回 `data`。 */
export async function del<T>(url: string): Promise<T> {
  const response = await http.delete<ApiEnvelope<T>>(url)
  return response.data.data
}

/** 上传（multipart）并返回 `data`。 */
export async function upload<T>(url: string, form: FormData): Promise<T> {
  const response = await http.post<ApiEnvelope<T>>(url, form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
  return response.data.data
}

/** 带鉴权下载二进制文件并触发浏览器保存。 */
export async function download(url: string, fileName: string): Promise<void> {
  const token = localStorage.getItem('pms_token')
  const response = await fetch(`/api/v1${url}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  })
  if (!response.ok) {
    ElMessage.error(`下载失败（${response.status}）`)
    return
  }
  const blob = await response.blob()
  const href = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = href
  anchor.download = fileName
  document.body.appendChild(anchor)
  anchor.click()
  document.body.removeChild(anchor)
  URL.revokeObjectURL(href)
}

export default http
