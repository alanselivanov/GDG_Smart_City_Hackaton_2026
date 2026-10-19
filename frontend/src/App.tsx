import { useEffect, useRef, useState, type FormEvent } from 'react'
import { ApiError, getHealth, getRecommendations } from './api'
import MapPanel from './MapPanel'
import { formatBudget, formatDistance, formatStart, resultCopy } from './resultCopy'
import type { HealthResponse, Language, RecommendResponse, Recommendation } from './types'
import './App.css'

type Coordinates = { lat: number; lon: number; accuracy?: number }
type StartMode = 'now' | 'later'

function displayError(error: unknown): string {
  if (!(error instanceof ApiError)) return 'Что-то пошло не так. Попробуйте ещё раз.'
  if (error.message.includes('Provide device lat/lon or mention a starting place')) {
    return 'Напишите в запросе, откуда начать (например, «Я возле Мега Силквей»), или разрешите геолокацию.'
  }
  if (error.message.includes("'там' needs reference_place")) {
    return 'Напишите конкретное название места вместо «там».'
  }
  if (error.message.includes('LLM_API_KEY')) return 'Текстовый поиск сейчас недоступен. Попробуйте позже.'
  if (error.message.includes('POI data unavailable')) return 'Данные о местах пока недоступны. Попробуйте позже.'
  if (error.message.startsWith('Place search unavailable')) return 'Поиск названного места сейчас недоступен. Уточните название или используйте геолокацию без названия места в запросе.'
  if (error.message.startsWith('Several places have this name') || error.message.startsWith('Place name is ambiguous')) return 'Найдено несколько мест с таким названием. Уточните его в запросе.'
  if (error.message.includes('Requested time must be between')) return 'Укажите время от 20 минут до 6 часов.'
  if (error.status === 503 && error.message.startsWith('Routing failed')) return 'Сервис пеших маршрутов сейчас недоступен. Попробуйте позже.'
  return error.message
}

function compactWhy(recommendation: Recommendation): string | null {
  const routeSentence = /^«[^»]+» — [^.]+\.\s*/u
  if (routeSentence.test(recommendation.why)) {
    return recommendation.why.replace(routeSentence, '').trim() || null
  }
  return recommendation.why
}

function prepareQuery(text: string): string {
  // The local POI uses the Latin name; this common Russian spelling otherwise
  // sends the backend to an external geocoder that may be unavailable.
  return text
    .replace(/Мег[аи][\s-]+Силк[\s-]?(?:вей|вэй)/giu, 'Mega Silk Way')
    .replace(/((?:возле|около|у|рядом\s+с|неподал[её]ку\s+от)\s+)Мег[аи](?![\p{L}\p{N}])/giu, '$1Mega Silk Way')
    .replace(/(^|[\s,.;])около\s+((?:\d+\s*)?)(час(?:а|ов)?|минут(?:а|ы|у)?)/giu, '$1примерно $2$3')
}

function hasNamedStartingPlace(text: string): boolean {
  return /(?:^|[\s,.;])(?:я\s+)?(?:сейчас\s+)?(?:нахожусь\s+)?(?:возле|около|у(?!\s+меня\b)|рядом\s+с|неподал[её]ку\s+от|near|by|at)\s+(?:(?:здания|здании|трц|тц|музея|парка|мечети)\s+)?[^\s,;.!?—–]+/iu.test(text)
    || /(?:^|[\s,.;])(?:я\s+)?(?:сейчас\s+)?(?:нахожусь\s+)?(?:в|на|inside)\s+(?:здании|трц|тц|музее|парке)\s+[^\s,;.!?—–]+/iu.test(text)
}

function RecommendationCard({ recommendation, index, selected, language, onShowMap }: { recommendation: Recommendation; index: number; selected: boolean; language: Language; onShowMap: () => void }) {
  const { poi } = recommendation
  const copy = resultCopy[language]
  const [showDetails, setShowDetails] = useState(false)
  const mapUrl = `https://www.openstreetmap.org/?mlat=${poi.lat}&mlon=${poi.lon}#map=16/${poi.lat}/${poi.lon}`
  const provider = poi.id.startsWith('2gis/') ? '2GIS' : 'OpenStreetMap'
  const preview = compactWhy(recommendation)

  return (
    <article className={selected ? 'recommendation-card selected' : 'recommendation-card'} id={`card-${index}`}>
      <div className="card-body">
        <div className="card-topline"><span className="card-number">{String(index + 1).padStart(2, '0')}</span><span className="category-badge">{copy.categories[poi.category]}</span></div>
        <h3>{poi.name}</h3>
        <div className="card-facts"><strong>{copy.walk(recommendation.walking_minutes)}</strong><span>{copy.fromStart(formatDistance(recommendation.distance_m, language))}</span></div>
        {preview && <p className="card-reason"><strong>{copy.why}</strong> <span className="card-reason-text">{preview}</span></p>}
        <div className="card-status"><span className={recommendation.open_status === 'open' ? 'hours-known' : recommendation.open_status === 'closed' ? 'hours-closed' : 'hours-unknown'}>
          {recommendation.open_status === 'open' ? copy.open : recommendation.open_status === 'closed' ? copy.closed : copy.unknown}
        </span><span>{provider === '2GIS' ? '2GIS' : 'OSM'}</span>{provider === '2GIS' && poi.rating != null && poi.rating > 0 && <span>★ {poi.rating.toFixed(1).replace('.', ',')}</span>}</div>
        <div className="card-actions"><button type="button" onClick={onShowMap}>{copy.showMap}</button><button type="button" className="details-toggle" aria-expanded={showDetails} aria-controls={`details-${index}`} onClick={() => setShowDetails((value) => !value)}>{showDetails ? copy.hideDetails : copy.showDetails} <span aria-hidden="true">{showDetails ? '−' : '+'}</span></button></div>
        <div className="card-details-body" id={`details-${index}`} hidden={!showDetails}>
          <p><strong>{copy.why}</strong> {recommendation.why}</p>
          <p><strong>{copy.action}</strong> {recommendation.what_to_do}</p>
          <section className="visit-estimate" aria-label={copy.visitTitle}>
            <div className="visit-estimate-heading">
              <span>{copy.visitTitle}</span>
              <div className="visit-estimate-total"><span>{copy.visitTotal}</span><strong>≈ {formatBudget(recommendation.walking_minutes + recommendation.visit_minutes, language)}</strong></div>
            </div>
            <div className="visit-estimate-breakdown">
              <div className="visit-estimate-part"><span>{copy.visitWalk}</span><strong>{formatBudget(recommendation.walking_minutes, language)}</strong></div>
              <span className="visit-estimate-plus" aria-hidden="true">+</span>
              <div className="visit-estimate-part"><span>{copy.visitPlace}</span><strong>≈ {formatBudget(recommendation.visit_minutes, language)}</strong></div>
            </div>
            <p className="visit-estimate-note">{copy.visitNote}</p>
          </section>
          {poi.name_is_generic && <p>{copy.genericName}</p>}
          {recommendation.missing_information.length > 0 && <p><strong>{copy.missing}</strong> {recommendation.missing_information.join(' ')}</p>}
          <div className="card-source-links"><a href={mapUrl} target="_blank" rel="noopener noreferrer">{copy.openOsm}</a><a href={poi.source_url} target="_blank" rel="noopener noreferrer">{copy.dataLink(provider)}</a></div>
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
  const [startMode, setStartMode] = useState<StartMode>('now')
  const [startAt, setStartAt] = useState('')
  const [flightAt, setFlightAt] = useState('')
  const [airportBuffer, setAirportBuffer] = useState(120)
  const [language, setLanguage] = useState<Language>('ru')
  const [health, setHealth] = useState<HealthResponse | null>(null)
  const [healthError, setHealthError] = useState(false)
  const [result, setResult] = useState<RecommendResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [selectedPoiId, setSelectedPoiId] = useState<string | null>(null)
  const activeRequest = useRef<AbortController | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    getHealth(controller.signal).then(setHealth).catch(() => { if (!controller.signal.aborted) setHealthError(true) })
    return () => controller.abort()
  }, [])

  function useDeviceLocation() {
    setLocationError(null)
    if (!navigator.geolocation) {
      setLocationError('Браузер не поддерживает геолокацию. Напишите место в запросе.')
      return
    }
    setLocationPending(true)
    navigator.geolocation.getCurrentPosition(
      ({ coords }) => {
        setLocationPending(false)
        const { latitude: lat, longitude: lon, accuracy } = coords
        if (lat < 50.9 || lat > 51.4 || lon < 71 || lon > 71.9) {
          setCoordinates(null)
          setLocationError('Сейчас рекомендации доступны только для Астаны. Напишите место в городе в запросе.')
          return
        }
        setCoordinates({ lat, lon, accuracy })
      },
      () => {
        setLocationPending(false)
        setLocationError('Не удалось получить геолокацию. Напишите место в запросе.')
      },
      { enableHighAccuracy: false, timeout: 10000, maximumAge: 60000 },
    )
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError(null)
    setResult(null)
    setSelectedPoiId(null)
    if (!query.trim()) {
      setError('Напишите, что хотите сделать. Место можно указать прямо в запросе.')
      return
    }
    let startsAt: string | undefined
    if (startMode === 'later') {
      const plannedTime = new Date(startAt)
      const now = Date.now()
      if (!startAt || !Number.isFinite(plannedTime.getTime())) { setError('Выберите дату и время начала прогулки.'); return }
      if (plannedTime.getTime() < now) { setError('Время начала должно быть в будущем.'); return }
      if (plannedTime.getTime() > now + 7 * 24 * 60 * 60 * 1000) { setError('Можно запланировать прогулку не дальше чем на 7 дней.'); return }
      startsAt = plannedTime.toISOString()
    }
    let flightDepartureAt: string | undefined
    if (flightAt) {
      const departure = new Date(flightAt)
      if (!Number.isFinite(departure.getTime()) || departure.getTime() <= (startsAt ? new Date(startsAt).getTime() : Date.now())) {
        setError('Время вылета должно быть позже начала прогулки.')
        return
      }
      if (departure.getTime() > Date.now() + 7 * 24 * 60 * 60 * 1000) {
        setError('Можно указать вылет не дальше чем на 7 дней.')
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
      const response = await getRecommendations({
        query: requestQuery, language, limit: 3,
        ...(coordinates && !hasNamedStartingPlace(requestQuery) ? { lat: coordinates.lat, lon: coordinates.lon } : {}),
        ...(maxTravel ? { max_travel_minutes: maxTravel } : {}),
        ...(startsAt ? { starts_at: startsAt } : {}),
        ...(flightDepartureAt ? { flight_departure_at: flightDepartureAt } : {}),
        ...((flightDepartureAt || /вылет|рейс|flight|plane|ұшу|ұшақ/i.test(requestQuery)) ? { airport_arrival_buffer_minutes: airportBuffer } : {}),
      }, controller.signal)
      if (!controller.signal.aborted) setResult(response)
    } catch (requestError) {
      if (!controller.signal.aborted) setError(displayError(requestError))
    } finally {
      if (!controller.signal.aborted) setLoading(false)
    }
  }

  const originName = result?.context_used.origin?.name
  const namedStart = hasNamedStartingPlace(query)
  const flightIntent = /вылет|рейс|flight|plane|ұшу|ұшақ/i.test(query) || Boolean(flightAt)
  const displayLanguage = result?.language ?? language
  const copy = resultCopy[displayLanguage]

  function showOnMap(id: string) {
    setSelectedPoiId(id)
    document.getElementById('map-panel')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <a className="brand" href="#top" aria-label="Qala рядом — начало страницы"><span className="brand-mark">Q</span><span>qala<span className="brand-muted">рядом</span></span></a>
        <div className="topbar-right"><span className="city-pill"><span className="status-dot" /> Астана</span></div>
      </header>
      <main id="top">
        <section className="hero-section"><div className="hero-copy"><span className="eyebrow">QALA РЯДОМ · АСТАНА</span><h1>Куда пойдём?</h1><p>Места рядом — по вашему запросу.</p></div><div className="hero-art" aria-hidden="true"><span className="hero-art-orbit orbit-one" /><span className="hero-art-orbit orbit-two" /><span className="hero-art-dot dot-one" /><span className="hero-art-dot dot-two" /><span className="hero-art-dot dot-three" /></div></section>
        <div className="workspace-grid">
          <section className="planner-panel" aria-labelledby="planner-heading">
            <div className="section-heading"><span className="step-number">1</span><div><h2 id="planner-heading">Что ищем?</h2></div></div>
            <form onSubmit={submit}>
              <label className="input-label query-label"><span className="sr-only">Ваш запрос</span>
                <textarea value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Например: поесть возле Меги завтра в 14:00" maxLength={500} rows={3} required />
              </label>
              <div className="quick-actions"><button type="button" className="example-button" onClick={() => setQuery('Я возле Мега Силквей, хочу погулять 2 часа пешком')}>Пример ↗</button><button type="button" className="secondary-button" onClick={useDeviceLocation} disabled={locationPending}>{locationPending ? 'Определяем…' : coordinates ? 'Обновить геопозицию' : '◎ Моя геопозиция'}</button></div>
              {coordinates && <p className="location-status">{namedStart ? 'На карте — вы и старт из запроса. Подбор идёт от старта из запроса.' : 'Геопозиция определена.'} <button type="button" onClick={() => { setCoordinates(null); setLocationError(null); setResult(null); setSelectedPoiId(null) }}>Отключить</button></p>}
              {locationError && <p className="field-error" role="alert">{locationError}</p>}
              <details className="advanced-options">
                <summary>Уточнить поиск</summary>
                <div className="advanced-content">
                  <div className="form-row">
                    <label className="input-label">Максимум пешком до места
                      <select value={maxTravel} onChange={(event) => setMaxTravel(event.target.value ? Number(event.target.value) : '')}>
                        <option value="">Подобрать автоматически</option><option value={10}>10 минут</option><option value={15}>15 минут</option><option value={20}>20 минут</option><option value={30}>30 минут</option><option value={45}>45 минут</option><option value={60}>60 минут</option>
                      </select>
                    </label>
                    <label className="input-label">Начало прогулки
                      <select value={startMode} onChange={(event) => setStartMode(event.target.value as StartMode)}><option value="now">Сейчас или из запроса</option><option value="later">Выбрать время</option></select>
                    </label>
                  </div>
                  {startMode === 'later' && <label className="input-label scheduled-start">Дата и время (по времени вашего устройства)<input type="datetime-local" value={startAt} onChange={(event) => setStartAt(event.target.value)} required /></label>}
                  {flightIntent && <div className="form-row">
                    <label className="input-label">Точное время вылета, если известно (по времени вашего устройства)
                      <input type="datetime-local" value={flightAt} onChange={(event) => setFlightAt(event.target.value)} />
                    </label>
                    <label className="input-label">Сколько минут нужно быть в аэропорту до рейса
                      <select value={airportBuffer} onChange={(event) => setAirportBuffer(Number(event.target.value))}>
                        <option value={120}>120 мин — по умолчанию</option><option value={60}>60 мин</option><option value={90}>90 мин</option><option value={180}>180 мин</option><option value={240}>240 мин</option>
                      </select>
                    </label>
                    <p>Выбирайте запас по требованиям своей авиакомпании. Дорога в аэропорт учитывается отдельно.</p>
                  </div>}
                  <label className="input-label language-field">Язык рекомендаций
                    <select value={language} onChange={(event) => setLanguage(event.target.value as Language)}><option value="ru">Русский</option><option value="kk">Қазақша</option><option value="en">English</option></select>
                  </label>
                </div>
              </details>
              <button className="primary-button" type="submit" disabled={loading}>{loading ? 'Ищем…' : 'Найти места'}<span aria-hidden="true">↗</span></button>
              <details className="privacy-note"><summary>Данные и приватность</summary><p>Запрос и настройки отправляются на сервер. Координаты — только после вашего разрешения; если в запросе названо место, подбор идёт от него. Фронтенд не сохраняет координаты после закрытия страницы. Карта загружается из OpenStreetMap.</p></details>
            </form>
          </section>
          <MapPanel result={result} device={coordinates} selectedPoiId={selectedPoiId} language={displayLanguage} onSelectPoi={setSelectedPoiId} />
          <section className="results-panel" aria-labelledby="results-heading">
            <div className="section-heading"><span className="step-number">3</span><div><h2 id="results-heading">{copy.placesHeading}</h2></div></div>
            <div className="api-state" aria-live="polite"><span className={health?.status === 'ready' ? 'api-indicator ready' : 'api-indicator'} />{health?.status === 'ready' ? copy.online : health?.status === 'awaiting_poi' ? copy.loadingData : healthError ? copy.unavailable : copy.checking}</div>
            {error && <div className="error-panel" role="alert"><strong>{copy.requestFailed}</strong><p>{error}</p></div>}
            {loading && <div className="loading-panel" role="status"><span className="spinner" />{copy.searching}</div>}
            {!loading && result && (result.recommendations.length > 0 ?
              <div className="results-content">
                <div className="results-summary"><strong>{copy.placeCount(result.recommendations.length)}</strong><span>{originName || copy.deviceOrigin}</span><span>{result.context_used.time_budget_minutes != null ? formatBudget(result.context_used.time_budget_minutes, displayLanguage) : copy.timeFromQuery}</span>{result.context_used.starts_at && <span>{formatStart(result.context_used.starts_at, displayLanguage)}</span>}</div>
                <div className="recommendation-list">{result.recommendations.map((recommendation, index) => <RecommendationCard key={recommendation.poi.id} recommendation={recommendation} index={index} selected={selectedPoiId === recommendation.poi.id} language={displayLanguage} onShowMap={() => showOnMap(recommendation.poi.id)} />)}</div>
                <details className="result-details"><summary>{copy.selectionDetails}</summary><div>
                  <p>{copy.selectedFor(result.context_used.time_budget_minutes != null ? formatBudget(result.context_used.time_budget_minutes, displayLanguage) : copy.timeFromQuery)}{result.context_used.max_travel_minutes ? ` · ${copy.travelLimit(result.context_used.max_travel_minutes)}` : ''}{result.context_used.starts_at ? ` · ${copy.startAt(formatStart(result.context_used.starts_at, displayLanguage))}` : ''}.</p>
                  {result.notices.map((notice, index) => <p key={index}>{notice}</p>)}
                  <p>{copy.sources} {result.context_used.source_license_urls ? Object.entries(result.context_used.source_license_urls).map(([provider, url], index) => <span key={provider}>{index > 0 ? ' · ' : ''}<a href={url} target="_blank" rel="noopener noreferrer">{provider === '2gis' ? '2GIS' : 'OpenStreetMap'}</a></span>) : <a href={result.source_license_url} target="_blank" rel="noopener noreferrer">{result.source}</a>}. {result.context_used.fallback_used ? `${copy.fallback} ` : ''}{copy.generated[result.generated_with]}</p>
                </div></details>
              </div> :
              <div className="empty-results"><strong>{result.context_used.flight_plan ? copy.emptyFlight : copy.emptyPlaces}</strong><p>{result.context_used.flight_plan ? copy.emptyFlightHint : copy.emptyHint}</p>{result.notices.map((notice, index) => <p key={index}>{notice}</p>)}</div>)}
            {!loading && !result && !error && <div className="empty-state"><span className="empty-graphic" aria-hidden="true">↗</span><div><h3>{copy.waitingTitle}</h3><p>{copy.waitingHint}</p></div></div>}
          </section>
        </div>
      </main>
      <footer className="footer"><span>Qala рядом · Астана</span><span>Часы работы уточняйте перед визитом.</span></footer>
    </div>
  )
}

export default App
