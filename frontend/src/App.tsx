import { useEffect, useRef, useState, type FormEvent } from 'react'
import { ApiError, getGroupRecommendations, getHealth, getRecommendations } from './api'
import MapPanel from './MapPanel'
import { formatBudget, formatDistance, formatStart, resultCopy } from './resultCopy'
import { uiCopy } from './uiCopy'
import type { Category, GroupParticipant, HealthResponse, Language, RecommendResponse, Recommendation, Requirement } from './types'
import './App.css'

type Coordinates = { lat: number; lon: number; accuracy?: number }
type StartMode = 'now' | 'later'
type GroupDraft = { lat: number | null; lon: number | null; interest: Category | '' }
const newGroupMember = (): GroupDraft => ({ lat: null, lon: null, interest: '' })
const emptyGroup: GroupDraft[] = []
const categoryOptions = Object.keys(resultCopy.ru.categories) as Category[]
function groupInterestFlags(interests: Category[] | Category[][] | undefined): boolean[] | undefined {
  return interests && Array.isArray(interests[0])
    ? (interests as Category[][]).map((categories) => categories.length > 0)
    : undefined
}
const requirementLabels: Record<Language, Record<Requirement, string>> = {
  ru: { quiet: 'Тихо', sockets: 'Розетки', interactive: 'Интерактивно' },
  kk: { quiet: 'Тыныш', sockets: 'Розеткалар', interactive: 'Интерактивті' },
  en: { quiet: 'Quiet', sockets: 'Sockets', interactive: 'Interactive' },
}
const serviceErrorCopy: Record<Language, { offline: string; embedding: string; busy: string; limit: string; dailyLimit: string }> = {
  ru: {
    offline: 'Нет связи с сервером. Попробуйте ещё раз чуть позже.',
    embedding: 'Текстовый поиск сейчас недоступен. Попробуйте позже.',
    busy: 'Сервис занят. Повторите поиск через несколько секунд.',
    limit: 'Слишком много запросов. Повторите поиск позже.',
    dailyLimit: 'Лимит запросов на сегодня исчерпан. Попробуйте завтра.',
  },
  kk: {
    offline: 'Сервермен байланыс жоқ. Сәл кейінірек қайталап көріңіз.',
    embedding: 'Мәтін бойынша іздеу қазір қолжетімсіз. Кейінірек көріңіз.',
    busy: 'Қызмет бос емес. Бірнеше секундтан кейін қайта іздеңіз.',
    limit: 'Сұраулар тым көп. Кейінірек қайталап көріңіз.',
    dailyLimit: 'Бүгінгі сұраулар лимиті бітті. Ертең қайталап көріңіз.',
  },
  en: {
    offline: 'Cannot connect to the server. Please try again shortly.',
    embedding: 'Text search is unavailable right now. Please try again later.',
    busy: 'The service is busy. Try again in a few seconds.',
    limit: 'Too many requests. Please try again later.',
    dailyLimit: 'Today’s request limit has been reached. Try again tomorrow.',
  },
}

function displayError(error: unknown, language: Language): string {
  const message = uiCopy[language].errors
  if (!(error instanceof ApiError)) return message.unknown
  if (error.status === 429) {
    if (error.message.includes('Daily external API budget')) return serviceErrorCopy[language].dailyLimit
    if (error.message.includes('service is busy')) return serviceErrorCopy[language].busy
    return serviceErrorCopy[language].limit
  }
  if (error.message.includes('Embedding API failed')) return serviceErrorCopy[language].embedding
  if (error.status === 0 || error.message.includes('Backend недоступен')) return serviceErrorCopy[language].offline
  if (error.message.includes('Provide device lat/lon or mention a starting place')) {
    return message.start
  }
  if (error.message.includes("'там' needs reference_place")) {
    return message.named
  }
  if (error.message.includes('LLM_API_KEY')) return message.llm
  if (error.message.includes('POI data unavailable')) return message.poi
  if (error.message.startsWith('Place search unavailable')) return message.search
  if (error.message.startsWith('Several places have this name') || error.message.startsWith('Place name is ambiguous')) return message.ambiguous
  if (error.message.includes('Requested time must be between')) return message.budget
  if (error.status === 503 && error.message.startsWith('Routing failed')) return message.routing
  return language === 'ru' ? error.message : message.unknown
}

function prepareQuery(text: string): string {
  // The local POI uses the Latin name; this common Russian spelling otherwise
  // sends the backend to an external geocoder that may be unavailable.
  return text
    .replace(/Мег[аи][\s-]+Силк[\s-]?(?:вей|вэй)/giu, 'Mega Silk Way')
    .replace(/((?:возле|около|у|рядом\s+с|неподал[её]ку\s+от)\s+)Мег[аи](?![\p{L}\p{N}])/giu, '$1Mega Silk Way')
    .replace(/(?:Мен\s+)?(Mega Silk Way)\s+жанында(?:мын)?/giu, 'near $1,')
    .replace(/(^|[\s,.;])около\s+((?:\d+\s*)?)(час(?:а|ов)?|минут(?:а|ы|у)?)/giu, '$1примерно $2$3')
}

function hasNamedStartingPlace(text: string): boolean {
  return /(?:^|[\s,.;])(?:я\s+)?(?:сейчас\s+)?(?:нахожусь\s+)?(?:возле|около|у(?!\s+меня(?![\p{L}\p{N}]))|рядом\s+с|неподал[её]ку\s+от|near|by|at(?!\s+\d{1,2}(?::\d{2})?\s*(?:am|pm)\b))\s+(?:(?:здания|здании|трц|тц|музея|парка|мечети)\s+)?[^\s,;.!?—–]+/iu.test(text)
    || /(?:^|[\s,.;])(?:я\s+)?(?:сейчас\s+)?(?:нахожусь\s+)?(?:в|на|inside)\s+(?:здании|трц|тц|музее|парке)\s+[^\s,;.!?—–]+/iu.test(text)
}

function RecommendationCard({ recommendation, index, selected, language, routeEstimated, interestSpecified, onShowMap }: { recommendation: Recommendation; index: number; selected: boolean; language: Language; routeEstimated: boolean; interestSpecified?: boolean[]; onShowMap: () => void }) {
  const { poi } = recommendation
  const copy = resultCopy[language]
  const [showDetails, setShowDetails] = useState(false)
  const mapUrl = `https://www.openstreetmap.org/?mlat=${poi.lat}&mlon=${poi.lon}#map=16/${poi.lat}/${poi.lon}`
  const websiteUrl = poi.website && /^https?:\/\//i.test(poi.website) ? poi.website : null
  const provider = poi.id.startsWith('2gis/') ? '2GIS' : 'OpenStreetMap'
  const attributes = [...new Set((poi.attribute_groups || []).flatMap((group) => group.attributes.map((attribute) => attribute.name.trim())).filter(Boolean))]
  const cuisine = attributes.find((item) => /кухн|cuisine|асхан/iu.test(item))
  const price = attributes.find((item) => /^(?:чек|average check|орташа чек)/iu.test(item))
  const highlights = provider === '2GIS' ? [...new Set([cuisine, price, ...attributes.filter((item) => !/^(?:Премия|Завтрак)(?:\s|$)/iu.test(item))].filter((item): item is string => Boolean(item)))].slice(0, 2) : []
  const facts = [...new Map([...(poi.facts || []), ...(recommendation.evidence || [])].map((fact) => [fact.key, fact])).values()]
  const requirements = Object.entries(recommendation.requirement_status || {}) as [Requirement, 'confirmed' | 'unknown'][]

  return (
    <article className={selected ? 'recommendation-card selected' : 'recommendation-card'} id={`card-${index}`} tabIndex={-1}>
      <span className="card-number" aria-hidden="true">{String(index + 1).padStart(2, '0')}</span>
      <div className="card-body">
        <div className="card-main">
          <div className="card-copy">
            <div className="card-topline"><span className="category-badge">{copy.categories[poi.category]}</span><span className="card-provider">{provider === '2GIS' ? '2GIS' : 'OSM'}</span></div>
            <h3>{poi.name}</h3>
            <p className="card-reason"><strong>{copy.why}</strong> {recommendation.why}</p>
            {highlights.length > 0 && <div className="card-highlights">{highlights.map((item) => <span key={item}>{item}</span>)}</div>}
          </div>
          <div className="card-aside">
            <strong className="card-walk">{routeEstimated ? '≈ ' : ''}{recommendation.participant_walking_minutes ? copy.groupWalk(recommendation.walking_minutes) : copy.walk(recommendation.walking_minutes)}</strong>
            <span className="card-distance">{routeEstimated ? '≈ ' : ''}{recommendation.participant_walking_minutes ? copy.groupFromStart(formatDistance(recommendation.distance_m, language)) : copy.fromStart(formatDistance(recommendation.distance_m, language))}</span>
            <div className="card-status"><span className={recommendation.open_status === 'open' ? 'hours-known' : recommendation.open_status === 'closed' ? 'hours-closed' : 'hours-unknown'}>
              {recommendation.open_status === 'open' ? copy.open : recommendation.open_status === 'closed' ? copy.closed : copy.unknown}
            </span>{provider === '2GIS' && poi.rating != null && poi.rating > 0 && <span>★ {poi.rating.toFixed(1).replace('.', ',')}{poi.review_count ? ` · ${new Intl.NumberFormat({ ru: 'ru-RU', kk: 'kk-KZ', en: 'en-US' }[language]).format(poi.review_count)}` : ''}</span>}</div>
            <div className="card-actions"><button type="button" onClick={onShowMap}>{copy.showMap}</button><button type="button" className="details-toggle" aria-expanded={showDetails} aria-controls={`details-${index}`} onClick={() => setShowDetails((value) => !value)}>{showDetails ? copy.hideDetails : copy.showDetails} <span aria-hidden="true">{showDetails ? '−' : '+'}</span></button></div>
          </div>
        </div>
        <div className="card-details-body" id={`details-${index}`} hidden={!showDetails}>
          <section className="visit-estimate" aria-label={copy.visitTitle}>
            <div className="visit-estimate-heading"><span>{copy.visitTitle}</span><div className="visit-estimate-total"><span>{copy.visitTotal}</span><strong>≈ {formatBudget(recommendation.walking_minutes + recommendation.visit_minutes, language)}</strong></div></div>
            <div className="time-meter" aria-hidden="true"><span style={{ flex: recommendation.walking_minutes }} /><span style={{ flex: recommendation.visit_minutes }} /></div>
            <div className="visit-estimate-breakdown">
              <div className="visit-estimate-part"><span>{copy.visitWalk}</span><strong>{routeEstimated ? '≈ ' : ''}{formatBudget(recommendation.walking_minutes, language)}</strong></div>
              <span className="visit-estimate-plus" aria-hidden="true">+</span>
              <div className="visit-estimate-part"><span>{copy.visitPlace}</span><strong>≈ {formatBudget(recommendation.visit_minutes, language)}</strong></div>
            </div>
            <p className="visit-estimate-note">{copy.visitNote}</p>
          </section>
          {recommendation.what_to_do && <div className="place-plan"><strong>{copy.action}</strong><p>{recommendation.what_to_do}</p></div>}
          {recommendation.participant_walking_minutes && <div className="group-result"><strong>{copy.groupWalks}</strong><div>{recommendation.participant_walking_minutes.map((minutes, memberIndex) => <span key={memberIndex}>{memberIndex + 1} · {routeEstimated ? '≈ ' : ''}{formatBudget(minutes, language)}{interestSpecified?.[memberIndex] && recommendation.participant_interest_matches && ` · ${recommendation.participant_interest_matches[memberIndex] ? copy.interestMatched : copy.interestNotMatched}`}</span>)}</div>{recommendation.group_meeting_at && <p>{copy.groupMeet} {formatStart(recommendation.group_meeting_at, language)}</p>}</div>}
          {recommendation.airport_transfer_minutes != null && <div className="flight-result"><strong>{copy.airportTransfer}</strong><span>≈ {formatBudget(recommendation.airport_transfer_minutes, language)}</span>{recommendation.latest_leave_for_airport_at && <span>{copy.leaveAirportBy} {formatStart(recommendation.latest_leave_for_airport_at, language)}</span>}</div>}
          <details className="place-data"><summary>{copy.placeData}</summary><div className="place-data-content">
            <p>{copy.textSource[recommendation.text_source]}</p>
            {poi.name_is_generic && <p>{copy.genericName}</p>}
            {recommendation.missing_information.length > 0 && <section><strong>{copy.missing}</strong><ul>{recommendation.missing_information.map((item, itemIndex) => <li key={itemIndex}>{item}</li>)}</ul></section>}
            {requirements.length > 0 && <section><strong>{copy.requirements}</strong><div className="data-chips">{requirements.map(([requirement, status]) => <span key={requirement} className={status === 'confirmed' ? 'confirmed' : 'uncertain'}>{requirementLabels[language][requirement]} · {status === 'confirmed' ? copy.confirmed : copy.unconfirmed}</span>)}</div></section>}
            {poi.attribute_groups && poi.attribute_groups.length > 0 && <section><strong>2GIS</strong><div className="attribute-groups">{poi.attribute_groups.map((group, groupIndex) => <div key={`${group.name}-${groupIndex}`}><span>{group.name}</span><div className="data-chips">{group.attributes.map((attribute, attributeIndex) => <span key={`${attribute.name}-${attributeIndex}`}>{attribute.name}</span>)}</div></div>)}</div></section>}
            {facts.length > 0 && <section><strong>{copy.facts}</strong><ul>{facts.map((fact) => <li key={fact.key}>{fact.text} <a href={fact.source_url} target="_blank" rel="noopener noreferrer">↗</a></li>)}</ul></section>}
            <div className="card-source-links"><a href={mapUrl} target="_blank" rel="noopener noreferrer">{copy.openOsm}</a><a href={poi.source_url} target="_blank" rel="noopener noreferrer">{copy.dataLink(provider)}</a>{websiteUrl && <a href={websiteUrl} target="_blank" rel="noopener noreferrer">{copy.website}</a>}{poi.phone && <span>{copy.phone} {poi.phone}</span>}</div>
          </div></details>
        </div>
      </div>
    </article>
  )
}

function App() {
  const [query, setQuery] = useState('')
  const [coordinates, setCoordinates] = useState<Coordinates | null>(null)
  const [locationPending, setLocationPending] = useState(false)
  const [locationError, setLocationError] = useState<string | null>(null)
  const [maxTravel, setMaxTravel] = useState<number | ''>('')
  const [categoryFilter, setCategoryFilter] = useState<Category | ''>('')
  const [excludedCategory, setExcludedCategory] = useState<Category | ''>('')
  const [mustHave, setMustHave] = useState<Requirement[]>([])
  const [groupMode, setGroupMode] = useState(false)
  const [groupParticipants, setGroupParticipants] = useState<GroupDraft[]>([newGroupMember(), newGroupMember(), newGroupMember()])
  const [activeGroupParticipant, setActiveGroupParticipant] = useState<number | null>(null)
  const [startMode, setStartMode] = useState<StartMode>('now')
  const [startAt, setStartAt] = useState('')
  const [flightAt, setFlightAt] = useState('')
  const [airportBuffer, setAirportBuffer] = useState(120)
  const [airportTransferMode, setAirportTransferMode] = useState<'auto' | 'pedestrian'>('auto')
  const [language, setLanguage] = useState<Language>('ru')
  const [languageNotice, setLanguageNotice] = useState(false)
  const [health, setHealth] = useState<HealthResponse | null>(null)
  const [healthError, setHealthError] = useState(false)
  const [result, setResult] = useState<RecommendResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [selectedPoiId, setSelectedPoiId] = useState<string | null>(null)
  const activeRequest = useRef<AbortController | null>(null)

  function invalidateResults() {
    activeRequest.current?.abort()
    setLoading(false)
    setResult(null)
    setError(null)
    setSelectedPoiId(null)
  }

  useEffect(() => {
    const controller = new AbortController()
    getHealth(controller.signal).then(setHealth).catch(() => { if (!controller.signal.aborted) setHealthError(true) })
    return () => controller.abort()
  }, [])

  useEffect(() => {
    document.documentElement.lang = language
    document.title = `Qala ${uiCopy[language].brandNearby} — ${uiCopy[language].city}`
  }, [language])

  useEffect(() => {
    if (loading || (!result && !error)) return
    const frame = window.requestAnimationFrame(() => {
      document.getElementById('results-panel')?.scrollIntoView({
        behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth',
        block: 'start',
      })
    })
    return () => window.cancelAnimationFrame(frame)
  }, [loading, result, error])

  function useDeviceLocation() {
    setLocationError(null)
    if (!navigator.geolocation) {
      setLocationError(uiCopy[language].errors.geoUnsupported)
      return
    }
    setLocationPending(true)
    navigator.geolocation.getCurrentPosition(
      ({ coords }) => {
        setLocationPending(false)
        const { latitude: lat, longitude: lon, accuracy } = coords
        if (lat < 50.9 || lat > 51.4 || lon < 71 || lon > 71.9) {
          invalidateResults()
          setCoordinates(null)
          setLocationError(uiCopy[language].errors.outsideCity)
          return
        }
        invalidateResults()
        setCoordinates({ lat, lon, accuracy })
        if (groupMode) setGroupParticipants((members) => members.map((member, index) => index === 0 ? { ...member, lat, lon } : member))
      },
      () => {
        setLocationPending(false)
        setLocationError(uiCopy[language].errors.geoFailed)
      },
      { enableHighAccuracy: false, timeout: 10000, maximumAge: 60000 },
    )
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setLanguageNotice(false)
    const previousOriginName = result?.context_used.origin?.name
    setError(null)
    setResult(null)
    setSelectedPoiId(null)
    if (!query.trim()) {
      setError(uiCopy[language].errors.emptyRequest)
      return
    }
    if (groupMode && groupParticipants.some((member) => member.lat == null || member.lon == null)) {
      setError(uiCopy[language].errors.groupPoints)
      return
    }
    let startsAt: string | undefined
    if (startMode === 'later') {
      const plannedTime = new Date(startAt)
      const now = Date.now()
      if (!startAt || !Number.isFinite(plannedTime.getTime())) { setError(uiCopy[language].errors.startRequired); return }
      if (plannedTime.getTime() < now) { setError(uiCopy[language].errors.startPast); return }
      if (plannedTime.getTime() > now + 7 * 24 * 60 * 60 * 1000) { setError(uiCopy[language].errors.startDistant); return }
      startsAt = plannedTime.toISOString()
    }
    let flightDepartureAt: string | undefined
    if (flightAt) {
      const departure = new Date(flightAt)
      if (!Number.isFinite(departure.getTime()) || departure.getTime() <= (startsAt ? new Date(startsAt).getTime() : Date.now())) {
        setError(uiCopy[language].errors.flightOrder)
        return
      }
      if (departure.getTime() > Date.now() + 7 * 24 * 60 * 60 * 1000) {
        setError(uiCopy[language].errors.flightDistant)
        return
      }
      flightDepartureAt = departure.toISOString()
    }
    activeRequest.current?.abort()
    const controller = new AbortController()
    activeRequest.current = controller
    setLoading(true)
    try {
      const requestQuery = prepareQuery(query.trim())
      const sharedRequest = {
        query: requestQuery, language, limit: 3,
        ...(maxTravel ? { max_travel_minutes: maxTravel } : {}),
        ...(startsAt ? { starts_at: startsAt } : {}),
        ...(flightDepartureAt ? { flight_departure_at: flightDepartureAt } : {}),
        ...((flightDepartureAt || /вылет|рейс|flight|plane|ұшу|ұшақ/i.test(requestQuery)) ? { airport_arrival_buffer_minutes: airportBuffer } : {}),
        ...((flightDepartureAt || /вылет|рейс|flight|plane|ұшу|ұшақ/i.test(requestQuery)) ? { airport_transfer_mode: airportTransferMode } : {}),
        ...(categoryFilter ? { categories: [categoryFilter] } : {}),
        ...(excludedCategory && excludedCategory !== categoryFilter ? { exclude_categories: [excludedCategory] } : {}),
        ...(mustHave.length ? { must_have: mustHave } : {}),
      }
      const response = groupMode
        ? await getGroupRecommendations({ ...sharedRequest, participants: groupParticipants.map((member): GroupParticipant => ({
          lat: member.lat!, lon: member.lon!, interests: member.interest ? [member.interest] : [],
        })) }, controller.signal)
        : await getRecommendations({
          ...sharedRequest,
          ...(coordinates && !hasNamedStartingPlace(requestQuery) ? { lat: coordinates.lat, lon: coordinates.lon } : {}),
          ...(/(?:^|[^\p{L}\p{N}])там(?![\p{L}\p{N}])/iu.test(requestQuery) && previousOriginName && !hasNamedStartingPlace(requestQuery) ? { reference_place: previousOriginName } : {}),
        }, controller.signal)
      if (!controller.signal.aborted) setResult(response)
    } catch (requestError) {
      if (!controller.signal.aborted) setError(displayError(requestError, language))
    } finally {
      if (!controller.signal.aborted) setLoading(false)
    }
  }

  const originName = result?.context_used.origin?.name
  const namedStart = hasNamedStartingPlace(query)
  const flightIntent = /вылет|рейс|flight|plane|ұшу|ұшақ/i.test(query) || Boolean(flightAt)
  const displayLanguage = language
  const copy = resultCopy[displayLanguage]
  const ui = uiCopy[language]

  function changeLanguage(next: Language) {
    if (next === language) return
    activeRequest.current?.abort()
    setLanguageNotice(Boolean(result))
    setLanguage(next)
    setLoading(false)
    setResult(null)
    setError(null)
    setLocationError(null)
    setSelectedPoiId(null)
  }

  function showOnMap(id: string) {
    setSelectedPoiId(id)
    document.getElementById('map-panel')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  function selectMode(mode: 'single' | 'group') {
    activeRequest.current?.abort()
    setLoading(false)
    setGroupMode(mode === 'group')
    setActiveGroupParticipant(null)
    setResult(null)
    setError(null)
    setLocationError(null)
    setSelectedPoiId(null)
  }

  function setGroupLocation(index: number, lat: number, lon: number) {
    if (lat < 50.9 || lat > 51.4 || lon < 71 || lon > 71.9) { setError(uiCopy[language].errors.groupOutside); return }
    invalidateResults()
    setGroupParticipants((members) => members.map((member, memberIndex) => memberIndex === index ? { ...member, lat, lon } : member))
    const next = groupParticipants.findIndex((member, memberIndex) => memberIndex !== index && member.lat == null)
    setActiveGroupParticipant(next >= 0 ? next : null)
    if (next < 0) document.getElementById('planner-heading')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <a className="brand" href="#top" aria-label={ui.brandAria}><span className="brand-mark">Q</span><span>qala<span className="brand-muted">{ui.brandNearby}</span></span></a>
        <div className="topbar-right"><label className="top-language"><span className="sr-only">{ui.languageLabel}</span><select aria-label={ui.languageLabel} value={language} onChange={(event) => changeLanguage(event.target.value as Language)}><option value="ru">Русский</option><option value="kk">Қазақша</option><option value="en">English</option></select></label><span className="city-pill"><span className="status-dot" /> {ui.city}</span></div>
      </header>
      <main id="top">
        <section className="hero-section"><div className="hero-copy"><span className="eyebrow">{ui.eyebrow}</span><h1>{ui.hero}</h1></div></section>
        <div className="workspace-grid">
          <section className="planner-panel" aria-labelledby="planner-heading">
            <h2 id="planner-heading" className="sr-only">{ui.planner}</h2>
            <form onSubmit={submit}>
              <div className="search-modes" role="group" aria-label={ui.modeLabel}>
                <button type="button" aria-pressed={!groupMode} className={!groupMode ? 'active' : ''} onClick={() => selectMode('single')}>{ui.single}</button>
                <button type="button" aria-pressed={groupMode} className={groupMode ? 'active' : ''} onClick={() => selectMode('group')}>{ui.group}</button>
              </div>
              <label className="input-label query-label"><span className="sr-only">{ui.request}</span>
                <textarea value={query} onChange={(event) => setQuery(event.target.value)} placeholder={groupMode ? ui.groupPlaceholder : ui.requestPlaceholder} maxLength={500} rows={3} aria-required="true" aria-invalid={error === ui.errors.emptyRequest} />
              </label>
              <div className="quick-actions"><button type="button" className="example-button" onClick={() => setQuery(ui.exampleQuery)}>{ui.example}</button><button type="button" className="secondary-button" onClick={useDeviceLocation} disabled={locationPending}>{locationPending ? ui.locating : coordinates ? ui.refreshLocation : ui.myLocation}</button></div>
              {languageNotice && <p className="location-status" role="status">{ui.languageChanged}</p>}
              {coordinates && <p className="location-status">{groupMode ? ui.locationGroup : namedStart ? ui.locationNamed : ui.locationFound} <button type="button" onClick={() => { invalidateResults(); setCoordinates(null); setLocationError(null); if (groupMode) setGroupParticipants((members) => members.map((member, index) => index === 0 ? { ...member, lat: null, lon: null } : member)) }}>{ui.disconnect}</button></p>}
              {locationError && <p className="field-error" role="alert">{locationError}</p>}
              {groupMode && <div className="group-planner">
                <div className="group-title"><strong>{ui.groupStarts}</strong><span>{ui.groupHint}</span></div>
                {groupParticipants.map((member, index) => <div className="group-member" key={index}>
                  <span className="group-member-number">{index + 1}</span>
                  <div className="group-member-info"><strong>{index === 0 ? ui.you : ui.participant(index + 1)}</strong><span>{member.lat == null ? ui.pointMissing : ui.pointChosen}</span></div>
                  <button type="button" className={activeGroupParticipant === index ? 'group-pick active' : 'group-pick'} onClick={() => { setActiveGroupParticipant(index); document.getElementById('map-panel')?.scrollIntoView({ behavior: 'smooth', block: 'start' }) }}>{member.lat == null ? ui.onMap : ui.edit}</button>
                  <label className="input-label group-interest">{ui.interest}
                    <select value={member.interest} onChange={(event) => { invalidateResults(); setGroupParticipants((members) => members.map((item, memberIndex) => memberIndex === index ? { ...item, interest: event.target.value as Category | '' } : item)) }}>
                      <option value="">{ui.any}</option>{categoryOptions.map((category) => <option key={category} value={category}>{resultCopy[language].categories[category]}</option>)}
                    </select>
                  </label>
                </div>)}
                <div className="group-controls"><button type="button" disabled={groupParticipants.length >= 5} onClick={() => { invalidateResults(); setGroupParticipants((members) => [...members, newGroupMember()]) }}>{ui.addParticipant}</button>{groupParticipants.length > 3 && <button type="button" onClick={() => { invalidateResults(); setGroupParticipants((members) => members.slice(0, -1)); setActiveGroupParticipant(null) }}>{ui.removeParticipant}</button>}</div>
              </div>}
              <details className="advanced-options">
                <summary>{ui.refine}</summary>
                <div className="advanced-content">
                  <div className="form-row">
                    <label className="input-label">{ui.maxWalk}
                      <select value={maxTravel} onChange={(event) => setMaxTravel(event.target.value ? Number(event.target.value) : '')}>
                        <option value="">{ui.automatic}</option>{[10, 15, 20, 30, 45, 60].map((minutes) => <option key={minutes} value={minutes}>{ui.minutes(minutes)}</option>)}
                      </select>
                    </label>
                    <label className="input-label">{ui.startWalk}
                      <select value={startMode} onChange={(event) => setStartMode(event.target.value as StartMode)}><option value="now">{ui.nowOrQuery}</option><option value="later">{ui.chooseTime}</option></select>
                    </label>
                  </div>
                  {startMode === 'later' && <label className="input-label scheduled-start">{ui.dateTime}<input type="datetime-local" value={startAt} onChange={(event) => setStartAt(event.target.value)} required /></label>}
                  {flightIntent && <div className="form-row">
                    <label className="input-label">{ui.flightTime}
                      <input type="datetime-local" value={flightAt} onChange={(event) => setFlightAt(event.target.value)} />
                    </label>
                    <label className="input-label">{ui.airportBuffer}
                      <select value={airportBuffer} onChange={(event) => setAirportBuffer(Number(event.target.value))}>
                        <option value={120}>{ui.defaultBuffer}</option>{[60, 90, 180, 240].map((minutes) => <option key={minutes} value={minutes}>{ui.minutes(minutes)}</option>)}
                      </select>
                    </label>
                    <label className="input-label">{ui.toAirport}
                      <select value={airportTransferMode} onChange={(event) => setAirportTransferMode(event.target.value as 'auto' | 'pedestrian')}><option value="auto">{ui.byCar}</option><option value="pedestrian">{ui.onFoot}</option></select>
                    </label>
                    <p>{ui.flightNote}</p>
                  </div>}
                  <details className="extra-options">
                    <summary>{ui.moreFilters}{categoryFilter || excludedCategory || mustHave.length ? ` · ${ui.chosen}` : ''}</summary>
                    <div className="form-row">
                      <label className="input-label">{ui.showOnly}
                        <select value={categoryFilter} onChange={(event) => { const next = event.target.value as Category | ''; setCategoryFilter(next); if (next === excludedCategory) setExcludedCategory('') }}><option value="">{ui.anyPlace}</option>{categoryOptions.map((category) => <option key={category} value={category}>{resultCopy[language].categories[category]}</option>)}</select>
                      </label>
                      <label className="input-label">{ui.exclude}
                        <select value={excludedCategory} onChange={(event) => setExcludedCategory(event.target.value as Category | '')}><option value="">{ui.noExclusions}</option>{categoryOptions.filter((category) => category !== categoryFilter).map((category) => <option key={category} value={category}>{resultCopy[language].categories[category]}</option>)}</select>
                      </label>
                    </div>
                    <div className="requirement-filter"><span>{ui.confirmedOnly}</span><div>{(Object.keys(requirementLabels.ru) as Requirement[]).map((requirement) => <button type="button" key={requirement} aria-pressed={mustHave.includes(requirement)} className={mustHave.includes(requirement) ? 'active' : ''} onClick={() => setMustHave((values) => values.includes(requirement) ? values.filter((value) => value !== requirement) : [...values, requirement])}>{requirementLabels[language][requirement]}</button>)}</div></div>
                  </details>
                </div>
              </details>
              <button className={loading ? 'primary-button searching' : 'primary-button'} type="submit" disabled={loading} aria-busy={loading}>{loading ? ui.searching : ui.findPlaces}{loading ? <span className="button-spinner" aria-hidden="true" /> : <span className="button-arrow" aria-hidden="true">↗</span>}</button>
              <details className="privacy-note"><summary>{ui.privacyTitle}</summary><p>{ui.privacy}</p></details>
            </form>
          </section>
          {(loading || result || error) && <section className="results-panel" id="results-panel" aria-labelledby="results-heading">
            <div className="results-heading"><h2 id="results-heading">{copy.placesHeading}</h2><div className="api-state" aria-live="polite"><span className={health?.status === 'ready' ? 'api-indicator ready' : 'api-indicator'} />{health?.status === 'ready' ? copy.online : health?.status === 'awaiting_poi' ? copy.loadingData : healthError ? copy.unavailable : copy.checking}</div></div>
            {error && <div className="error-panel" role="alert"><strong>{copy.requestFailed}</strong><p>{error}</p></div>}
            {loading && <div className="loading-panel" role="status"><span className="spinner" aria-hidden="true" /><span>{copy.searching}</span><span className="loading-track" aria-hidden="true"><span /></span></div>}
            {!loading && result && (result.recommendations.length > 0 ?
              <div className="results-content">
                <div className="results-summary"><strong>{copy.placeCount(result.recommendations.length)}</strong><span>{result.context_used.participant_count && result.context_used.participant_count > 1 ? copy.groupCount(result.context_used.participant_count) : originName || copy.deviceOrigin}</span><span>{result.context_used.time_budget_minutes != null ? formatBudget(result.context_used.time_budget_minutes, displayLanguage) : copy.timeFromQuery}</span>{result.context_used.starts_at && <span>{formatStart(result.context_used.starts_at, displayLanguage)}</span>}</div>
                {(result.context_used.routing_fallback_used || (result.context_used.poi_catalog_stale && result.recommendations.some((item) => !item.poi.id.startsWith('2gis/')))) && <div className="result-cautions" role="status">{result.context_used.routing_fallback_used && <span>{copy.approximateRoute}</span>}{result.context_used.poi_catalog_stale && result.recommendations.some((item) => !item.poi.id.startsWith('2gis/')) && <span>{copy.staleCatalog}</span>}</div>}
                <div className="recommendation-list">{result.recommendations.map((recommendation, index) => <RecommendationCard key={recommendation.poi.id} recommendation={recommendation} index={index} selected={selectedPoiId === recommendation.poi.id} language={displayLanguage} routeEstimated={result.context_used.routing_fallback_used === true} interestSpecified={groupInterestFlags(result.context_used.interests)} onShowMap={() => showOnMap(recommendation.poi.id)} />)}</div>
                <details className="result-details"><summary>{copy.selectionDetails}</summary><div>
                  <p>{copy.selectedFor(result.context_used.time_budget_minutes != null ? formatBudget(result.context_used.time_budget_minutes, displayLanguage) : copy.timeFromQuery)}{result.context_used.max_travel_minutes ? ` · ${copy.travelLimit(result.context_used.max_travel_minutes)}` : ''}{result.context_used.starts_at ? ` · ${copy.startAt(formatStart(result.context_used.starts_at, displayLanguage))}` : ''}.</p>
                  {result.notices.map((notice, index) => <p key={index}>{notice}</p>)}
                  {result.context_used.search_tag_method && result.context_used.search_tag_method !== 'not_used' && Boolean(result.context_used.provider_search_queries?.length) && <p>{copy.searchPlan[result.context_used.search_tag_method]} {copy.searchQueries} {result.context_used.provider_search_queries?.join(', ')}.</p>}
                  {result.context_used.selection_method && <p>{copy.selectionMode[result.context_used.selection_method]}</p>}
                  <p>{copy.sources} {result.context_used.source_license_urls ? Object.entries(result.context_used.source_license_urls).map(([provider, url], index) => <span key={provider}>{index > 0 ? ' · ' : ''}<a href={url} target="_blank" rel="noopener noreferrer">{provider === '2gis' ? '2GIS' : 'OpenStreetMap'}</a></span>) : <a href={result.source_license_url} target="_blank" rel="noopener noreferrer">{result.source}</a>}. {result.context_used.fallback_used ? `${copy.fallback} ` : ''}{copy.generated[result.generated_with]}</p>
                </div></details>
              </div> :
              <div className="empty-results"><strong>{result.context_used.flight_plan ? copy.emptyFlight : copy.emptyPlaces}</strong><p>{result.context_used.flight_plan ? copy.emptyFlightHint : copy.emptyHint}</p>{result.notices.map((notice, index) => <p key={index}>{notice}</p>)}</div>)}
          </section>}
          <MapPanel result={result} device={coordinates} selectedPoiId={selectedPoiId} language={displayLanguage} onSelectPoi={setSelectedPoiId} groupParticipants={groupMode ? groupParticipants : emptyGroup} activeGroupParticipant={activeGroupParticipant} onPickGroupLocation={(lat, lon) => { if (activeGroupParticipant != null) setGroupLocation(activeGroupParticipant, lat, lon) }} />
        </div>
      </main>
      <footer className="footer"><span>{ui.footer}</span><span>{ui.hoursFooter}</span></footer>
    </div>
  )
}

export default App
