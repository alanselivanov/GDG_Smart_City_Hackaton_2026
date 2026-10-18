export type Language = 'ru' | 'kk' | 'en'

export type Category =
  | 'cafe'
  | 'food'
  | 'nightlife'
  | 'culture'
  | 'museum'
  | 'landmark'
  | 'viewpoint'
  | 'park'
  | 'family'
  | 'activity'
  | 'shopping'

export interface RecommendRequest {
  query: string
  language: Language
  time_budget_minutes?: number
  limit: number
  max_travel_minutes?: number
  starts_at?: string
  categories?: Category[]
  lat?: number
  lon?: number
  reference_place?: string
}

export interface Poi {
  id: string
  name: string
  category: Category
  lat: number
  lon: number
  description: string | null
  opening_hours: string | null
  website: string | null
  phone: string | null
  source_url: string
  fetched_at: string
  name_is_generic: boolean
  rating?: number | null
  review_count?: number | null
}

export interface Recommendation {
  poi: Poi
  distance_m: number
  walking_minutes: number
  visit_minutes: number
  open_status: 'open' | 'closed' | 'unknown'
  open_status_reason: string
  why: string
  what_to_do: string
  missing_information: string[]
}

export interface RecommendResponse {
  recommendations: Recommendation[]
  language: Language
  context_used: {
    origin?: { name: string | null; lat: number; lon: number; source?: string } | null
    time_budget_minutes?: number
    starts_at?: string
    max_travel_minutes?: number
    source_license_urls?: Record<string, string>
    fallback_used?: boolean
    fallback_reason?: string | null
  }
  source: string
  source_license_url: string
  generated_with: 'grounded_templates' | 'llm_verified'
  notices: string[]
}

export interface HealthResponse {
  status: 'ready' | 'awaiting_poi'
  poi_count: number
  last_refresh_error: string | null
}
