import { useEffect, useMemo, useRef, useState, type KeyboardEvent as ReactKeyboardEvent } from 'react'
import { latLngBounds, type Map as LeafletMap } from 'leaflet'
import { Circle, CircleMarker, MapContainer, Polyline, Popup, TileLayer, Tooltip, ZoomControl, useMap, useMapEvents } from 'react-leaflet'
import type { Language, RecommendResponse } from './types'
import { getPedestrianRoute, type RoutePoint } from './pedestrianRoute'
import 'leaflet/dist/leaflet.css'

type Coordinates = { lat: number; lon: number; accuracy?: number }
type GroupMapMember = { lat: number | null; lon: number | null }
type Props = {
  result: RecommendResponse | null
  device: Coordinates | null
  selectedPoiId: string | null
  language: Language
  onSelectPoi: (id: string) => void
  groupParticipants: GroupMapMember[]
  activeGroupParticipant: number | null
  onPickGroupLocation: (lat: number, lon: number) => void
}

const mapCopy = {
  ru: { heading: 'Карта', start: 'Старт:', deviceStart: 'Старт: ваша геолокация', deviceFound: 'Ваше местоположение определено', noStart: 'Астана · укажите старт для поиска', showMe: 'Показать меня', close: 'Закрыть ✕', expand: 'Во весь экран ⤢', aria: 'Карта Астаны с точкой старта и рекомендациями', zoomIn: 'Приблизить', zoomOut: 'Отдалить', now: 'Вы сейчас', devicePopup: 'Ваше местоположение по данным устройства', accuracy: 'точность около', startPoint: 'точка старта', queryStart: 'Старт из запроса', queryPoint: 'Точка старта', queryPopup: 'Место, которое вы назвали в запросе. Это не подтверждение вашего фактического местоположения.', walk: (n: number) => `${n} мин пешком от старта`, card: 'Показать карточку', places: 'Места', groupPick: (n: number) => `Нажмите карту: участник ${n}`, groupStarts: 'Точки старта компании', groupMember: (n: number) => `Участник ${n} · точка старта`, groupLegend: 'Участники', routeLoading: 'Строим пеший путь…', routeReady: 'Пеший путь · Valhalla / OSM', routeUnavailable: 'Пеший путь сейчас недоступен', routeNeedsStart: 'Укажите старт, чтобы построить пеший путь' },
  kk: { heading: 'Карта', start: 'Бастау орны:', deviceStart: 'Бастау орны: сіздің геолокацияңыз', deviceFound: 'Орналасқан жеріңіз анықталды', noStart: 'Астана · іздеу үшін бастау орнын көрсетіңіз', showMe: 'Менің орным', close: 'Жабу ✕', expand: 'Толық экран ⤢', aria: 'Бастау орны мен ұсынылған орындар көрсетілген Астана картасы', zoomIn: 'Жақындату', zoomOut: 'Алыстату', now: 'Қазіргі орныңыз', devicePopup: 'Құрылғы анықтаған орналасқан жеріңіз', accuracy: 'дәлдігі шамамен', startPoint: 'бастау орны', queryStart: 'Сұраудағы бастау орны', queryPoint: 'Бастау орны', queryPopup: 'Сұрауда атаған орын. Бұл сіздің нақты орналасқан жеріңізді растамайды.', walk: (n: number) => `бастау орнынан ${n} мин жаяу`, card: 'Карточканы көрсету', places: 'Орындар', groupPick: (n: number) => `Картадан таңдаңыз: ${n}-қатысушы`, groupStarts: 'Топтың бастау нүктелері', groupMember: (n: number) => `${n}-қатысушы · бастау нүктесі`, groupLegend: 'Қатысушылар', routeLoading: 'Жаяу жол құрастырылуда…', routeReady: 'Жаяу жол · Valhalla / OSM', routeUnavailable: 'Жаяу жол қазір қолжетімсіз', routeNeedsStart: 'Жаяу жол үшін бастау нүктесін көрсетіңіз' },
  en: { heading: 'Map', start: 'Start:', deviceStart: 'Start: your location', deviceFound: 'Your location is available', noStart: 'Astana · enter a starting point', showMe: 'Show me', close: 'Close ✕', expand: 'Full screen ⤢', aria: 'Map of Astana with starting point and recommendations', zoomIn: 'Zoom in', zoomOut: 'Zoom out', now: 'You are here', devicePopup: 'Your location from this device', accuracy: 'accuracy about', startPoint: 'starting point', queryStart: 'Start from request', queryPoint: 'Starting point', queryPopup: 'The place named in your request. This does not confirm your actual location.', walk: (n: number) => `${n} min walk from start`, card: 'Show card', places: 'Places', groupPick: (n: number) => `Tap the map: person ${n}`, groupStarts: 'Group starting points', groupMember: (n: number) => `Person ${n} · starting point`, groupLegend: 'Group', routeLoading: 'Finding a walking route…', routeReady: 'Walking route · Valhalla / OSM', routeUnavailable: 'Walking route is unavailable', routeNeedsStart: 'Set a starting point to see a walking route' },
}

type RoutePath = { points: RoutePoint[]; memberIndex: number }
type RouteResult = { key: string; paths: RoutePath[] }
const routeColors = ['#1f5f48', '#e56542', '#356fa5', '#9a762c', '#805a9f']

function routeStarts(result: RecommendResponse | null, device: Coordinates | null, members: GroupMapMember[]) {
  const group = members.flatMap((member, index) => member.lat != null && member.lon != null ? [{ point: [member.lat, member.lon] as RoutePoint, memberIndex: index }] : [])
  const start = result?.context_used.origin || device
  return group.length ? group : start ? [{ point: [start.lat, start.lon] as RoutePoint, memberIndex: 0 }] : []
}

const ASTANA: [number, number] = [51.135, 71.43]

function FitVisiblePlaces({ result, device, groupParticipants }: Pick<Props, 'result' | 'device' | 'groupParticipants'>) {
  const map = useMap()

  useEffect(() => {
    const origin = result?.context_used.origin
    const points: [number, number][] = []
    if (origin) points.push([origin.lat, origin.lon])
    for (const member of groupParticipants) if (member.lat != null && member.lon != null) points.push([member.lat, member.lon])
    for (const item of result?.recommendations ?? []) points.push([item.poi.lat, item.poi.lon])
    if (!points.length && device) points.push([device.lat, device.lon])

    if (points.length > 1) map.fitBounds(latLngBounds(points), { padding: [45, 45], maxZoom: 15 })
    else map.setView(points[0] ?? ASTANA, points.length ? 14 : 11)
  }, [map, result, device, groupParticipants])

  return null
}

function GroupLocationPicker({ active, onPick }: { active: boolean; onPick: (lat: number, lon: number) => void }) {
  useMapEvents({ click(event) { if (active) onPick(event.latlng.lat, event.latlng.lng) } })
  return null
}

export default function MapPanel({ result, device, selectedPoiId, language, onSelectPoi, groupParticipants, activeGroupParticipant, onPickGroupLocation }: Props) {
  const copy = mapCopy[language]
  const mapRef = useRef<LeafletMap | null>(null)
  const panelRef = useRef<HTMLElement | null>(null)
  const expandButtonRef = useRef<HTMLButtonElement | null>(null)
  const closeButtonRef = useRef<HTMLButtonElement | null>(null)
  const hasOpenedRef = useRef(false)
  const [expanded, setExpanded] = useState(false)
  const [routeResult, setRouteResult] = useState<RouteResult | null>(null)
  const origin = result?.context_used.origin
  const originIsDevice = origin?.source === 'device_location'
  const selected = result?.recommendations.find((item) => item.poi.id === selectedPoiId)?.poi
  const starts = useMemo(() => routeStarts(result, device, groupParticipants), [result, device, groupParticipants])
  const routeKey = selected && starts.length ? `${selected.id}:${starts.map(({ point }) => point.join(',')).join(';')}` : null
  const routePaths = routeResult?.key === routeKey ? routeResult.paths : []
  const routeStatus = !selected ? 'idle' : !starts.length ? 'no_start' : routeResult?.key !== routeKey ? 'loading' : routePaths.length ? 'ready' : 'error'

  useEffect(() => {
    if (!expanded) {
      if (hasOpenedRef.current) expandButtonRef.current?.focus()
      hasOpenedRef.current = false
      return
    }
    hasOpenedRef.current = true
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    closeButtonRef.current?.focus()
    const handleEscape = (event: KeyboardEvent) => { if (event.key === 'Escape') setExpanded(false) }
    window.addEventListener('keydown', handleEscape)
    return () => {
      document.body.style.overflow = previousOverflow
      window.removeEventListener('keydown', handleEscape)
    }
  }, [expanded])

  function keepFocusInExpandedMap(event: ReactKeyboardEvent<HTMLElement>) {
    if (!expanded || event.key !== 'Tab') return
    const focusable = [...(panelRef.current?.querySelectorAll<HTMLElement>('button:not([disabled]), a[href], [tabindex]:not([tabindex="-1"])') ?? [])]
      .filter((element) => element.getClientRects().length > 0)
    if (!focusable.length) return
    const first = focusable[0]
    const last = focusable[focusable.length - 1]
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus() }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus() }
  }

  useEffect(() => {
    const frame = requestAnimationFrame(() => mapRef.current?.invalidateSize())
    const timer = window.setTimeout(() => mapRef.current?.invalidateSize(), 260)
    return () => { cancelAnimationFrame(frame); window.clearTimeout(timer) }
  }, [expanded])

  useEffect(() => {
    if (selected) mapRef.current?.flyTo([selected.lat, selected.lon], 15, { duration: 0.5 })
  }, [selected])

  useEffect(() => {
    if (!selected || !routeKey) return
    const controller = new AbortController()
    Promise.allSettled(starts.map(async ({ point, memberIndex }) => ({
      points: await getPedestrianRoute(point, [selected.lat, selected.lon], controller.signal), memberIndex,
    }))).then((outcomes) => {
      if (controller.signal.aborted) return
      const paths = outcomes.flatMap((outcome) => outcome.status === 'fulfilled' ? [outcome.value] : [])
      setRouteResult({ key: routeKey, paths })
      if (paths.length) mapRef.current?.fitBounds(latLngBounds(paths.flatMap((path) => path.points)), { padding: [45, 45], maxZoom: 15 })
    })
    return () => controller.abort()
  }, [routeKey, selected, starts])

  function showCard(id: string, cardId: string) {
    onSelectPoi(id)
    setExpanded(false)
    requestAnimationFrame(() => {
      const card = document.getElementById(cardId)
      card?.scrollIntoView({ behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth', block: 'center' })
      card?.focus({ preventScroll: true })
    })
  }

  return (
    <section ref={panelRef} className={expanded ? 'map-panel map-expanded' : 'map-panel'} id="map-panel" aria-labelledby="map-heading" role={expanded ? 'dialog' : undefined} aria-modal={expanded || undefined} onKeyDown={keepFocusInExpandedMap}>
      <div className="map-heading"><h2 id="map-heading">{copy.heading}</h2></div>
      <div className="map-toolbar">
        <span>{activeGroupParticipant != null ? copy.groupPick(activeGroupParticipant + 1) : groupParticipants.length ? copy.groupStarts : origin?.name ? `${copy.start} ${origin.name}` : originIsDevice ? copy.deviceStart : device ? copy.deviceFound : copy.noStart}</span>
        <div className="map-toolbar-actions">
          {device && <button type="button" onClick={() => mapRef.current?.flyTo([device.lat, device.lon], 15, { duration: 0.5 })}>{copy.showMe}</button>}
          {expanded ? <button type="button" ref={closeButtonRef} className="map-expand-button" onClick={() => setExpanded(false)}>{copy.close}</button> : <button type="button" ref={expandButtonRef} className="map-expand-button" onClick={() => setExpanded(true)}>{copy.expand}</button>}
        </div>
      </div>
      <MapContainer ref={mapRef} center={ASTANA} zoom={11} zoomControl={false} scrollWheelZoom={false} className={activeGroupParticipant != null ? 'city-map picking-location' : 'city-map'} aria-label={copy.aria}>
        <ZoomControl position="topleft" zoomInTitle={copy.zoomIn} zoomOutTitle={copy.zoomOut} />
        <TileLayer
          url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap contributors</a>'
        />
        <FitVisiblePlaces result={result} device={device} groupParticipants={groupParticipants} />
        <GroupLocationPicker active={activeGroupParticipant != null} onPick={onPickGroupLocation} />
        {routePaths.map((path) => <Polyline key={path.memberIndex} positions={path.points} pathOptions={{ color: routeColors[path.memberIndex % routeColors.length], weight: 5, opacity: 0.85 }} />)}
        {device && device.accuracy != null && device.accuracy <= 1000 && <Circle center={[device.lat, device.lon]} radius={device.accuracy} pathOptions={{ color: '#3d72be', fillColor: '#8db4e1', fillOpacity: 0.12, weight: 1 }} />}
        {device && <CircleMarker center={[device.lat, device.lon]} radius={9} pathOptions={{ color: '#fff', fillColor: '#3d72be', fillOpacity: 1, weight: 3 }}>
          <Tooltip permanent direction="top" offset={[0, -6]} className="map-point-label">{copy.now}</Tooltip>
          <Popup>{copy.devicePopup}{device.accuracy ? ` · ${copy.accuracy} ${Math.round(device.accuracy)} м` : ''}{originIsDevice ? ` · ${copy.startPoint}` : ''}</Popup>
        </CircleMarker>}
        {origin && !originIsDevice && <CircleMarker center={[origin.lat, origin.lon]} radius={11} pathOptions={{ color: '#fff', fillColor: '#163640', fillOpacity: 1, weight: 3 }}>
          <Tooltip permanent direction="top" offset={[0, -7]} className="map-point-label">{copy.queryStart}</Tooltip>
          <Popup><strong>{origin.name || copy.queryPoint}</strong><br />{copy.queryPopup}</Popup>
        </CircleMarker>}
        {groupParticipants.map((member, index) => member.lat != null && member.lon != null ? <CircleMarker key={`participant-${index}`} center={[member.lat, member.lon]} radius={11} pathOptions={{ color: '#fff', fillColor: '#296749', fillOpacity: 1, weight: 3 }}>
          <Tooltip permanent direction="center" className="map-number-label">{index + 1}</Tooltip>
          <Popup>{copy.groupMember(index + 1)}</Popup>
        </CircleMarker> : null)}
        {result?.recommendations.map((item, index) => <CircleMarker
          key={item.poi.id}
          center={[item.poi.lat, item.poi.lon]}
          radius={selectedPoiId === item.poi.id ? 16 : 14}
          pathOptions={{ color: '#fff', fillColor: selectedPoiId === item.poi.id ? '#163640' : '#e56542', fillOpacity: 1, weight: 3 }}
          eventHandlers={{ click: () => onSelectPoi(item.poi.id) }}
        >
          <Tooltip permanent direction="center" className="map-number-label">{index + 1}</Tooltip>
          <Popup><strong>{item.poi.name}</strong><br />{copy.walk(item.walking_minutes)}<br /><button type="button" className="map-popup-button" onClick={() => showCard(item.poi.id, `card-${index}`)}>{copy.card}</button></Popup>
        </CircleMarker>)}
      </MapContainer>
      {(Boolean(device || origin) || groupParticipants.some((member) => member.lat != null) || (result?.recommendations.length ?? 0) > 0) && <div className="map-legend" aria-live="polite">{device && <span><i className="legend-dot device" />{copy.now}</span>}{origin && !originIsDevice && <span><i className="legend-dot origin" />{copy.queryStart}</span>}{groupParticipants.some((member) => member.lat != null) && <span><i className="legend-dot group" />{copy.groupLegend}</span>}{result?.recommendations.length ? <span><i className="legend-dot place" />{copy.places}</span> : null}{routeStatus !== 'idle' && <span className="route-status"><i className="legend-route" />{routeStatus === 'ready' ? copy.routeReady : routeStatus === 'loading' ? copy.routeLoading : routeStatus === 'no_start' ? copy.routeNeedsStart : copy.routeUnavailable}</span>}</div>}
    </section>
  )
}
