import { useEffect, useRef, useState, type KeyboardEvent as ReactKeyboardEvent } from 'react'
import { latLngBounds, type Map as LeafletMap } from 'leaflet'
import { Circle, CircleMarker, MapContainer, Popup, TileLayer, Tooltip, useMap } from 'react-leaflet'
import type { RecommendResponse } from './types'
import 'leaflet/dist/leaflet.css'

type Coordinates = { lat: number; lon: number; accuracy?: number }
type Props = {
  result: RecommendResponse | null
  device: Coordinates | null
  selectedPoiId: string | null
  onSelectPoi: (id: string) => void
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

export default function MapPanel({ result, device, selectedPoiId, onSelectPoi }: Props) {
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
      <div className="section-heading"><span className="step-number">2</span><div><h2 id="map-heading">Карта</h2></div></div>
      <div className="map-toolbar">
        <span>{origin?.name ? `Старт: ${origin.name}` : originIsDevice ? 'Старт: ваша геолокация' : device ? 'Ваше местоположение определено' : 'Астана · укажите старт для поиска'}</span>
        <div className="map-toolbar-actions">
          {device && <button type="button" onClick={() => mapRef.current?.flyTo([device.lat, device.lon], 15, { duration: 0.5 })}>Показать меня</button>}
          {expanded ? <button type="button" ref={closeButtonRef} className="map-expand-button" onClick={() => setExpanded(false)}>Закрыть ✕</button> : <button type="button" ref={expandButtonRef} className="map-expand-button" onClick={() => setExpanded(true)}>Во весь экран ⤢</button>}
        </div>
      </div>
      <MapContainer ref={mapRef} center={ASTANA} zoom={11} scrollWheelZoom={false} className="city-map" aria-label="Карта Астаны с точкой старта и рекомендациями">
        <TileLayer
          url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap contributors</a>'
        />
        <FitVisiblePlaces result={result} device={device} />
        {device && device.accuracy != null && device.accuracy <= 1000 && <Circle center={[device.lat, device.lon]} radius={device.accuracy} pathOptions={{ color: '#3d72be', fillColor: '#8db4e1', fillOpacity: 0.12, weight: 1 }} />}
        {device && <CircleMarker center={[device.lat, device.lon]} radius={9} pathOptions={{ color: '#fff', fillColor: '#3d72be', fillOpacity: 1, weight: 3 }}>
          <Tooltip permanent direction="top" offset={[0, -6]} className="map-point-label">Вы сейчас</Tooltip>
          <Popup>Ваше местоположение по данным устройства{device.accuracy ? ` · точность около ${Math.round(device.accuracy)} м` : ''}{originIsDevice ? ' · точка старта' : ''}</Popup>
        </CircleMarker>}
        {origin && !originIsDevice && <CircleMarker center={[origin.lat, origin.lon]} radius={11} pathOptions={{ color: '#fff', fillColor: '#163640', fillOpacity: 1, weight: 3 }}>
          <Tooltip permanent direction="top" offset={[0, -7]} className="map-point-label">Старт из запроса</Tooltip>
          <Popup><strong>{origin.name || 'Точка старта'}</strong><br />Место, которое вы назвали в запросе. Это не подтверждение вашего фактического местоположения.</Popup>
        </CircleMarker>}
        {result?.recommendations.map((item, index) => <CircleMarker
          key={item.poi.id}
          center={[item.poi.lat, item.poi.lon]}
          radius={selectedPoiId === item.poi.id ? 16 : 14}
          pathOptions={{ color: '#fff', fillColor: selectedPoiId === item.poi.id ? '#163640' : '#e56542', fillOpacity: 1, weight: 3 }}
          eventHandlers={{ click: () => onSelectPoi(item.poi.id) }}
        >
          <Tooltip permanent direction="center" className="map-number-label">{index + 1}</Tooltip>
          <Popup><strong>{item.poi.name}</strong><br />{item.walking_minutes} мин пешком от старта<br /><button type="button" className="map-popup-button" onClick={() => document.getElementById(`card-${index}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' })}>Показать карточку</button></Popup>
        </CircleMarker>)}
      </MapContainer>
      {(device || origin || result?.recommendations.length) && <div className="map-legend">{device && <span><i className="legend-dot device" />Вы сейчас</span>}{origin && !originIsDevice && <span><i className="legend-dot origin" />Старт из запроса</span>}{result?.recommendations.length ? <span><i className="legend-dot place" />Места</span> : null}</div>}
    </section>
  )
}
