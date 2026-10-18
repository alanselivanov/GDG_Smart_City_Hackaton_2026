import type { HealthResponse, RecommendRequest, RecommendResponse } from './types'

const baseUrl = (import.meta.env.VITE_API_BASE_URL || '/api').replace(/\/$/, '')

export class ApiError extends Error {
  status: number

  constructor(
    message: string,
    status: number,
  ) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

function errorMessage(detail: unknown): string {
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    return detail.map((item) => {
      if (item && typeof item === 'object' && 'msg' in item) return String(item.msg)
      return 'Проверьте введённые данные.'
    }).join(' ')
  }
  return 'Не удалось получить ответ сервера.'
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(baseUrl + path, init)
  } catch {
    throw new ApiError('Нет связи с сервером. Запустите backend и попробуйте снова.', 0)
  }

  if (!response.ok) {
    const body: unknown = await response.json().catch(() => null)
    const detail = body && typeof body === 'object' && 'detail' in body ? body.detail : null
    const message = detail == null && response.status >= 500
      ? 'Backend недоступен или вернул ошибку. Проверьте, что сервер запущен.'
      : errorMessage(detail)
    throw new ApiError(message, response.status)
  }
  return response.json() as Promise<T>
}

export function getHealth(signal?: AbortSignal) {
  return request<HealthResponse>('/health', { signal })
}

export function getRecommendations(payload: RecommendRequest, signal?: AbortSignal) {
  return request<RecommendResponse>('/v1/recommendations', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
    signal,
  })
}
