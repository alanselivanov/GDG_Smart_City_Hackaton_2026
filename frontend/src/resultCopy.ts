import type { Category, Language } from './types'

type Copy = {
  categories: Record<Category, string>
  placesHeading: string
  placeCount: (count: number) => string
  deviceOrigin: string
  timeFromQuery: string
  walk: (minutes: number) => string
  fromStart: (distance: string) => string
  why: string
  action: string
  visitTitle: string
  visitWalk: string
  visitPlace: string
  visitTotal: string
  visitNote: string
  genericName: string
  missing: string
  open: string
  closed: string
  unknown: string
  showMap: string
  showDetails: string
  hideDetails: string
  openOsm: string
  dataLink: (provider: string) => string
  online: string
  loadingData: string
  unavailable: string
  checking: string
  requestFailed: string
  searching: string
  selectionDetails: string
  selectedFor: (budget: string) => string
  travelLimit: (minutes: number) => string
  startAt: (date: string) => string
  sources: string
  fallback: string
  generated: Record<'llm_verified' | 'mixed' | 'grounded_templates', string>
  emptyFlight: string
  emptyPlaces: string
  emptyFlightHint: string
  emptyHint: string
  waitingTitle: string
  waitingHint: string
}

export const resultCopy: Record<Language, Copy> = {
  ru: {
    categories: { cafe: 'Кафе', food: 'Еда', park: 'Парки', museum: 'Музеи', family: 'С детьми', landmark: 'Достопримечательности', culture: 'Культура', viewpoint: 'Смотровые', activity: 'Активности', nightlife: 'Ночная жизнь', shopping: 'Магазины' },
    placesHeading: 'Подходящие места', placeCount: (n) => `${n} ${n === 1 ? 'место' : 'места'}`,
    deviceOrigin: 'Ваша геопозиция', timeFromQuery: 'Время из запроса',
    walk: (n) => `${n} мин пешком`, fromStart: (distance) => `${distance} от старта`,
    why: 'Почему:', action: 'Что делать:',
    visitTitle: 'Оценка времени', visitWalk: 'Пешком до места', visitPlace: 'На месте', visitTotal: 'Всего',
    visitNote: 'Время на месте — ориентир. Обратная дорога не включена.',
    genericName: 'Название места обобщено.', missing: 'Что не подтверждено:',
    open: 'По расписанию открыто', closed: 'По расписанию закрыто', unknown: 'Открытость неизвестна',
    showMap: 'На карте ↗', showDetails: 'Подробнее', hideDetails: 'Скрыть',
    openOsm: 'Открыть в OSM ↗', dataLink: (provider) => `Данные: ${provider} ↗`,
    online: 'Сервис онлайн', loadingData: 'Данные загружаются', unavailable: 'Сервис недоступен', checking: 'Проверяем сервис',
    requestFailed: 'Не получилось найти места', searching: 'Подбираем варианты и проверяем время пути…',
    selectionDetails: 'Как мы подобрали места и что проверить?', selectedFor: (budget) => `Учтено: ${budget} на прогулку`,
    travelLimit: (n) => `до ${n} мин пешком`, startAt: (date) => `начало ${date}`,
    sources: 'Данные:', fallback: '2GIS сейчас недоступен, использованы данные OSM.',
    generated: { llm_verified: 'Текст сгенерирован и проверен ИИ по данным мест.', mixed: 'Текст частично сгенерирован и проверен ИИ, частично составлен по данным мест.', grounded_templates: 'Текст составлен по данным мест.' },
    emptyFlight: 'Подходящих мест перед вылетом нет', emptyPlaces: 'Подходящих мест пока нет',
    emptyFlightHint: 'Проверьте расчёт ниже. Если время рейса или нужный запас отличаются, откройте «Уточнить поиск» и укажите их.',
    emptyHint: 'Попробуйте увеличить время в запросе, разрешить более долгую дорогу или назвать другую точку старта.',
    waitingTitle: 'Места появятся здесь', waitingHint: 'Начните с запроса выше.',
  },
  kk: {
    categories: { cafe: 'Кафе', food: 'Тамақтану', park: 'Саябақтар', museum: 'Мұражайлар', family: 'Балалармен', landmark: 'Көрікті орындар', culture: 'Мәдениет', viewpoint: 'Көру алаңдары', activity: 'Белсенді демалыс', nightlife: 'Түнгі демалыс', shopping: 'Дүкендер' },
    placesHeading: 'Сәйкес орындар', placeCount: (n) => `${n} орын`,
    deviceOrigin: 'Сіздің геолокацияңыз', timeFromQuery: 'Сұраудағы уақыт',
    walk: (n) => `${n} мин жаяу`, fromStart: (distance) => `бастау нүктесінен ${distance}`,
    why: 'Неге:', action: 'Не істеуге болады:',
    visitTitle: 'Уақыт шамасы', visitWalk: 'Орынға дейін жаяу', visitPlace: 'Орынның өзінде', visitTotal: 'Барлығы',
    visitNote: 'Орынға бөлінген уақыт — болжам. Қайтар жол есепке алынбаған.',
    genericName: 'Орын атауы жалпыланған.', missing: 'Расталмаған ақпарат:',
    open: 'Кесте бойынша ашық', closed: 'Кесте бойынша жабық', unknown: 'Ашық екені белгісіз',
    showMap: 'Картадан көру ↗', showDetails: 'Толығырақ', hideDetails: 'Жасыру',
    openOsm: 'OSM-де ашу ↗', dataLink: (provider) => `Дереккөз: ${provider} ↗`,
    online: 'Қызмет жұмыс істеп тұр', loadingData: 'Деректер жүктелуде', unavailable: 'Қызмет қолжетімсіз', checking: 'Қызмет тексерілуде',
    requestFailed: 'Орындарды табу мүмкін болмады', searching: 'Орындар мен жаяу жол уақыты тексерілуде…',
    selectionDetails: 'Орындар қалай таңдалды және нені тексеру керек?', selectedFor: (budget) => `Ескерілгені: серуенге ${budget}`,
    travelLimit: (n) => `жаяу жүруге ${n} мин дейін`, startAt: (date) => `басталуы ${date}`,
    sources: 'Деректер:', fallback: '2GIS қолжетімсіз, OSM деректері қолданылды.',
    generated: { llm_verified: 'Мәтін орын деректері бойынша ЖИ көмегімен жасалып, тексерілді.', mixed: 'Мәтіннің бір бөлігі ЖИ көмегімен жасалып, тексерілді; қалғаны орын деректерінен құрастырылды.', grounded_templates: 'Мәтін орын деректерінен құрастырылды.' },
    emptyFlight: 'Ұшуға дейін сәйкес орын табылмады', emptyPlaces: 'Әзірге сәйкес орын жоқ',
    emptyFlightHint: 'Төмендегі есепті тексеріңіз. Рейс уақыты не қажет қор басқа болса, «Іздеуді нақтылау» бөлімінде көрсетіңіз.',
    emptyHint: 'Уақытты ұзартыңыз, ұзағырақ жаяу жүруге рұқсат беріңіз немесе басқа бастау орнын көрсетіңіз.',
    waitingTitle: 'Орындар осында көрсетіледі', waitingHint: 'Жоғарыда сұрау енгізіңіз.',
  },
  en: {
    categories: { cafe: 'Cafes', food: 'Food', park: 'Parks', museum: 'Museums', family: 'With children', landmark: 'Landmarks', culture: 'Culture', viewpoint: 'Viewpoints', activity: 'Activities', nightlife: 'Nightlife', shopping: 'Shopping' },
    placesHeading: 'Recommended places', placeCount: (n) => `${n} ${n === 1 ? 'place' : 'places'}`,
    deviceOrigin: 'Your location', timeFromQuery: 'Time from your request',
    walk: (n) => `${n} min walk`, fromStart: (distance) => `${distance} from start`,
    why: 'Why:', action: 'What to do:',
    visitTitle: 'Time estimate', visitWalk: 'Walk to place', visitPlace: 'At the place', visitTotal: 'Total',
    visitNote: 'Time at the place is an estimate. The return trip is not included.',
    genericName: 'The place name is generic.', missing: 'Not confirmed:',
    open: 'Open according to listed hours', closed: 'Closed according to listed hours', unknown: 'Opening status unknown',
    showMap: 'On map ↗', showDetails: 'Details', hideDetails: 'Hide',
    openOsm: 'Open in OSM ↗', dataLink: (provider) => `Source: ${provider} ↗`,
    online: 'Service online', loadingData: 'Loading place data', unavailable: 'Service unavailable', checking: 'Checking service',
    requestFailed: 'Could not find places', searching: 'Finding places and checking walking times…',
    selectionDetails: 'How were these places chosen?', selectedFor: (budget) => `Considered: ${budget} for the outing`,
    travelLimit: (n) => `up to ${n} min on foot`, startAt: (date) => `starts ${date}`,
    sources: 'Sources:', fallback: '2GIS is unavailable; OSM data was used.',
    generated: { llm_verified: 'Text was generated and checked against place data.', mixed: 'Some text was generated and checked; the rest was composed from place data.', grounded_templates: 'Text was composed from place data.' },
    emptyFlight: 'No suitable place before your flight', emptyPlaces: 'No suitable places yet',
    emptyFlightHint: 'Check the calculation below. If your flight time or required buffer differs, enter them under “Refine search”.',
    emptyHint: 'Try allowing more time, a longer walk, or a different starting point.',
    waitingTitle: 'Places will appear here', waitingHint: 'Enter a request above.',
  },
}

export function formatBudget(minutes: number, language: Language): string {
  if (minutes < 60) return `${minutes} ${language === 'en' ? 'min' : 'мин'}`
  const hours = Math.floor(minutes / 60)
  const rest = minutes % 60
  const unit = language === 'ru' ? 'ч' : language === 'kk' ? 'сағ' : 'h'
  return rest ? `${hours} ${unit} ${rest} ${language === 'en' ? 'min' : 'мин'}` : `${hours} ${unit}`
}

export function formatDistance(meters: number, language: Language): string {
  if (meters < 1000) return `${meters} ${language === 'en' ? 'm' : 'м'}`
  return `${(meters / 1000).toFixed(1).replace('.', language === 'en' ? '.' : ',')} ${language === 'en' ? 'km' : 'км'}`
}

export function formatStart(iso: string, language: Language): string {
  return new Date(iso).toLocaleString({ ru: 'ru-RU', kk: 'kk-KZ', en: 'en-US' }[language], {
    day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit',
  })
}
