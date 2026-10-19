export type RoutePoint = [number, number]

// Valhalla returns the road geometry as a polyline with six decimal places.
function decodePolyline6(shape: string): RoutePoint[] {
  const points: RoutePoint[] = []
  let index = 0
  let latitude = 0
  let longitude = 0

  function nextDelta(): number {
    let value = 0
    let shift = 0
    let chunk: number
    do {
      if (index >= shape.length || shift > 30) throw new Error('Invalid route shape')
      chunk = shape.charCodeAt(index++) - 63
      value |= (chunk & 31) << shift
      shift += 5
    } while (chunk >= 32)
    return value & 1 ? ~(value >> 1) : value >> 1
  }

  while (index < shape.length) {
    latitude += nextDelta()
    longitude += nextDelta()
    points.push([latitude / 1_000_000, longitude / 1_000_000])
  }
  if (points.length < 2) throw new Error('Empty route shape')
  return points
}

export async function getPedestrianRoute(start: RoutePoint, destination: RoutePoint, signal: AbortSignal): Promise<RoutePoint[]> {
  const service = (import.meta.env.VITE_ROUTING_URL || 'https://valhalla1.openstreetmap.de').replace(/\/$/, '')
  const response = await fetch(`${service}/route`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      locations: [{ lat: start[0], lon: start[1] }, { lat: destination[0], lon: destination[1] }],
      costing: 'pedestrian',
      directions_type: 'none',
    }),
    signal,
  })
  if (!response.ok) throw new Error('Pedestrian route unavailable')
  const data: unknown = await response.json()
  const shape = (data as { trip?: { legs?: { shape?: unknown }[] } })?.trip?.legs?.[0]?.shape
  if (typeof shape !== 'string') throw new Error('Pedestrian route has no geometry')
  return decodePolyline6(shape)
}
