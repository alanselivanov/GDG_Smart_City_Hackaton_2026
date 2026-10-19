import { useEffect, useRef, useState, type KeyboardEvent as ReactKeyboardEvent } from 'react'
import { latLngBounds, type Map as LeafletMap } from 'leaflet'
import { Circle, CircleMarker, MapContainer, Popup, TileLayer, Tooltip, useMap } from 'react-leaflet'
import type { Language, RecommendResponse } from './types'
import 'leaflet/dist/leaflet.css'

type Coordinates = { lat: number; lon: number; accuracy?: number }
type Props = {
  result: RecommendResponse | null
  device: Coordinates | null
  selectedPoiId: string | null
  language: Language
  onSelectPoi: (id: string) => void
}

const mapCopy = {
  ru: { heading: 'Карта', start: 'Старт:', deviceStart: 'Старт: ваша геолокация', deviceFound: 'Ваше местоположение определено', noStart: 'Астана · укажите старт для поиска', showMe: 'Показать меня', close: 'Закрыть ✕', expand: 'Во весь экран ⤢', aria: 'Карта Астаны с точкой старта и рекомендациями', now: 'Вы сейчас', devicePopup: 'Ваше местоположение по данным устройства', accuracy: 'точность около', startPoint: 'точка старта', queryStart: 'Старт из запроса', queryPoint: 'Точка старта', queryPopup: 'Место, которое вы назвали в запросе. Это не подтверждение вашего фактического местоположения.', walk: (n: number) => `${n} мин пешком от старта`, card: 'Показать карточку', places: 'Места' },
  kk: { heading: 'Карта', start: 'Бастау орны:', deviceStart: 'Бастау орны: сіздің геолокацияңыз', deviceFound: 'Орналасқан жеріңіз анықталды', noStart: 'Астана · іздеу үшін бастау орнын көрсетіңіз', showMe: 'Менің орным', close: 'Жабу ✕', expand: 'Толық экран ⤢', aria: 'Бастау орны мен ұсынылған орындар көрсетілген Астана картасы', now: 'Қазіргі орныңыз', devicePopup: 'Құрылғы анықтаған орналасқан жеріңіз', accuracy: 'дәлдігі шамамен', startPoint: 'бастау орны', queryStart: 'Сұраудағы бастау орны', queryPoint: 'Бастау орны', queryPopup: 'Сұрауда атаған орын. Бұл сіздің нақты орналасқан жеріңізді растамайды.', walk: (n: number) => `бастау орнынан ${n} мин жаяу`, card: 'Карточканы көрсету', places: 'Орындар' },
  en: { heading: 'Map', start: 'Start:', deviceStart: 'Start: your location', deviceFound: 'Your location is available', noStart: 'Astana · enter a starting point', showMe: 'Show me', close: 'Close ✕', expand: 'Full screen ⤢', aria: 'Map of Astana with starting point and recommendations', now: 'You are here', devicePopup: 'Your location from this device', accuracy: 'accuracy about', startPoint: 'starting point', queryStart: 'Start from request', queryPoint: 'Starting point', queryPopup: 'The place named in your request. This does not confirm your actual location.', walk: (n: number) => `${n} min walk from start`, card: 'Show card', places: 'Places' },
}

const ASTANA: [number, number] = [51.135, 71.43]

function FitVisiblePlaces({ result, device }: Pick<Props, 'result' | 'device'>) {
  const map = useMap()

  useEffect(() => {
    const origin = result?.context_used.origin
    const points: [number, number][] = []
    if (origin) points.push([origin.lat, origin.lon])
    for (const item of result?.recommendations ?? []) points.push([item.poi.lat, item.poi.lon])
    if (!points.length && device) points.push([device.lat, device.lon])

    if (points.length > 1) map.fitBounds(latLngBounds(points), { padding: [45, 45], maxZoom: 15 })
    else map.setView(points[0] ?? ASTANA, points.length ? 14 : 11)
  }, [map, result, device])

  return null
}

export default function MapPanel({ result, device, selectedPoiId, language, onSelectPoi }: Props) {
  const copy = mapCopy[language]
  const mapRef = useRef<LeafletMap | null>(null)
  const panelRef = useRef<HTMLElement | null>(null)
  const expandButtonRef = useRef<HTMLButtonElement | null>(null)
  const closeButtonRef = useRef<HTMLButtonElement | null>(null)
  const hasOpenedRef = useRef(false)
  const [expanded, setExpanded] = useState(false)
  const origin = result?.context_used.origin
  const originIsDevice = origin?.source === 'device_location'

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
    const selected = result?.recommendations.find((item) => item.poi.id === selectedPoiId)
    if (selected) mapRef.current?.flyTo([selected.poi.lat, selected.poi.lon], 15, { duration: 0.5 })
  }, [selectedPoiId, result])

  return (
    <section ref={panelRef} className={expanded ? 'map-panel map-expanded' : 'map-panel'} id="map-panel" aria-labelledby="map-heading" role={expanded ? 'dialog' : undefined} aria-modal={expanded || undefined} onKeyDown={keepFocusInExpandedMap}>
      <div className="section-heading"><span className="step-number">2</span><div><h2 id="map-heading">{copy.heading}</h2></div></div>
      <div className="map-toolbar">
        <span>{origin?.name ? `${copy.start} ${origin.name}` : originIsDevice ? copy.deviceStart : device ? copy.deviceFound : copy.noStart}</span>
        <div className="map-toolbar-actions">
          {device && <button type="button" onClick={() => mapRef.current?.flyTo([device.lat, device.lon], 15, { duration: 0.5 })}>{copy.showMe}</button>}
          {expanded ? <button type="button" ref={closeButtonRef} className="map-expand-button" onClick={() => setExpanded(false)}>{copy.close}</button> : <button type="button" ref={expandButtonRef} className="map-expand-button" onClick={() => setExpanded(true)}>{copy.expand}</button>}
        </div>
      </div>
      <MapContainer ref={mapRef} center={ASTANA} zoom={11} scrollWheelZoom={false} className="city-map" aria-label={copy.aria}>
        <TileLayer
          url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap contributors</a>'
        />
        <FitVisiblePlaces result={result} device={device} />
        {device && device.accuracy != null && device.accuracy <= 1000 && <Circle center={[device.lat, device.lon]} radius={device.accuracy} pathOptions={{ color: '#3d72be', fillColor: '#8db4e1', fillOpacity: 0.12, weight: 1 }} />}
        {device && <CircleMarker center={[device.lat, device.lon]} radius={9} pathOptions={{ color: '#fff', fillColor: '#3d72be', fillOpacity: 1, weight: 3 }}>
          <Tooltip permanent direction="top" offset={[0, -6]} className="map-point-label">{copy.now}</Tooltip>
          <Popup>{copy.devicePopup}{device.accuracy ? ` · ${copy.accuracy} ${Math.round(device.accuracy)} м` : ''}{originIsDevice ? ` · ${copy.startPoint}` : ''}</Popup>
        </CircleMarker>}
        {origin && !originIsDevice && <CircleMarker center={[origin.lat, origin.lon]} radius={11} pathOptions={{ color: '#fff', fillColor: '#163640', fillOpacity: 1, weight: 3 }}>
          <Tooltip permanent direction="top" offset={[0, -7]} className="map-point-label">{copy.queryStart}</Tooltip>
          <Popup><strong>{origin.name || copy.queryPoint}</strong><br />{copy.queryPopup}</Popup>
        </CircleMarker>}
        {result?.recommendations.map((item, index) => <CircleMarker
          key={item.poi.id}
          center={[item.poi.lat, item.poi.lon]}
          radius={selectedPoiId === item.poi.id ? 16 : 14}
          pathOptions={{ color: '#fff', fillColor: selectedPoiId === item.poi.id ? '#163640' : '#e56542', fillOpacity: 1, weight: 3 }}
          eventHandlers={{ click: () => onSelectPoi(item.poi.id) }}
        >
          <Tooltip permanent direction="center" className="map-number-label">{index + 1}</Tooltip>
          <Popup><strong>{item.poi.name}</strong><br />{copy.walk(item.walking_minutes)}<br /><button type="button" className="map-popup-button" onClick={() => document.getElementById(`card-${index}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' })}>{copy.card}</button></Popup>
        </CircleMarker>)}
      </MapContainer>
      {(device || origin || result?.recommendations.length) && <div className="map-legend">{device && <span><i className="legend-dot device" />{copy.now}</span>}{origin && !originIsDevice && <span><i className="legend-dot origin" />{copy.queryStart}</span>}{result?.recommendations.length ? <span><i className="legend-dot place" />{copy.places}</span> : null}</div>}
    </section>
  )
}
