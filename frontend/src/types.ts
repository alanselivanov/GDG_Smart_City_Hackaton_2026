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

export type Requirement = 'sockets' | 'quiet' | 'interactive'

export interface GroupParticipant {
  lat: number
  lon: number
  interests: Category[]
}

export interface RecommendRequest {
  query: string
  language: Language
  time_budget_minutes?: number
  limit: number
  max_travel_minutes?: number
  starts_at?: string
  flight_departure_at?: string
  airport_arrival_buffer_minutes?: number
  categories?: Category[]
  exclude_categories?: Category[]
  interests?: Category[]
  must_have?: Requirement[]
  airport_transfer_mode?: 'auto' | 'pedestrian'
  lat?: number
  lon?: number
  reference_place?: string
}

export type GroupRecommendRequest = Omit<RecommendRequest, 'lat' | 'lon' | 'reference_place' | 'interests'> & {
  participants: GroupParticipant[]
}

export interface PoiFact {
  key: string
  kind: string
  text: string
  source_url: string
  verified_at: string
}

export interface TwoGisAttributeGroup {
  name: string
  attributes: { name: string; tag?: string | null }[]
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
  distance_m?: number | null
  rating?: number | null
  review_count?: number | null
  attribute_groups?: TwoGisAttributeGroup[]
  facts?: PoiFact[]
}

export interface Recommendation {
  poi: Poi
  distance_m: number
  walking_minutes: number
  walking_seconds?: number
  visit_minutes: number
  open_status: 'open' | 'closed' | 'unknown'
  open_status_reason: string
  why: string
  what_to_do: string
  missing_information: string[]
  evidence?: PoiFact[]
  requirement_status?: Partial<Record<Requirement, 'confirmed' | 'unknown'>>
  airport_transfer_minutes?: number | null
  airport_transfer_distance_m?: number | null
  latest_leave_for_airport_at?: string | null
  group_meeting_at?: string | null
  group_ends_at?: string | null
  participant_walking_minutes?: number[] | null
  participant_interest_matches?: boolean[] | null
}

export interface RecommendResponse {
  recommendations: Recommendation[]
  language: Language
  context_used: {
    origin?: { name: string | null; lat: number; lon: number; source?: string } | null
    time_budget_minutes?: number
    starts_at?: string
    max_travel_minutes?: number
    flight_plan?: { departure_at: string; airport_arrival_buffer_minutes: number }
    source_license_urls?: Record<string, string>
    fallback_used?: boolean
    fallback_reason?: string | null
    search_tag_method?: 'ai_tags' | 'rules_fallback' | 'not_used'
    search_tags?: string[]
    provider_search_queries?: string[]
    selection_method?: 'ai_scored' | 'rules_fallback' | 'single_candidate' | 'no_candidates'
    selection_candidate_count?: number
    selection_priorities?: string[]
    selection_scores?: Record<string, number>
    providers?: string[]
    participant_count?: number
  }
  source: string
  source_license_url: string
  generated_with: 'grounded_templates' | 'llm_verified' | 'mixed'
  notices: string[]
}

export interface HealthResponse {
  status: 'ready' | 'awaiting_poi'
  poi_count: number
  last_refresh_error: string | null
}
