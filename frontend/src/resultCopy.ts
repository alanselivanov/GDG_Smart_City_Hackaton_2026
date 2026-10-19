import type { Category, Language } from './types'

type Copy = {
  categories: Record<Category, string>
  placesHeading: string
  placeCount: (count: number) => string
  groupCount: (count: number) => string
  deviceOrigin: string
  timeFromQuery: string
  walk: (minutes: number) => string
  groupWalk: (minutes: number) => string
  fromStart: (distance: string) => string
  groupFromStart: (distance: string) => string
  why: string
  action: string
  textSource: Record<'grounded_fallback' | 'llm_verified', string>
  interestMatched: string
  interestNotMatched: string
  staleCatalog: string
  approximateRoute: string
  visitTitle: string
  visitWalk: string
  visitPlace: string
  visitTotal: string
  visitNote: string
  placeData: string
  requirements: string
  confirmed: string
  unconfirmed: string
  facts: string
  website: string
  phone: string
  groupWalks: string
  groupMeet: string
  airportTransfer: string
  leaveAirportBy: string
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
  searchPlan: Record<'ai_tags' | 'rules_fallback', string>
  searchQueries: string
  selectionMode: Record<'ai_scored' | 'rules_fallback' | 'single_candidate' | 'no_candidates', string>
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
    placesHeading: 'Подходящие места', placeCount: (n) => `${n} ${n % 100 >= 11 && n % 100 <= 14 ? 'мест' : n % 10 === 1 ? 'место' : n % 10 >= 2 && n % 10 <= 4 ? 'места' : 'мест'}`, groupCount: (n) => `${n} ${n === 5 ? 'участников' : 'участника'}`,
    deviceOrigin: 'Ваша геопозиция', timeFromQuery: 'Время из запроса',
    walk: (n) => `${n} мин пешком`, groupWalk: (n) => `до ${n} мин пешком`, fromStart: (distance) => `${distance} от старта`, groupFromStart: (distance) => `до ${distance} от старта`,
    why: 'Почему подходит:', action: 'Что делать:',
    textSource: { grounded_fallback: 'Текст составлен по данным места.', llm_verified: 'Текст сформулирован ИИ и проверен по данным места.' },
    interestMatched: 'интерес совпадает', interestNotMatched: 'интерес не совпадает',
    staleCatalog: 'Данные OSM могут быть устаревшими', approximateRoute: 'Путь рассчитан приблизительно',
    visitTitle: 'Оценка времени', visitWalk: 'Пешком до места', visitPlace: 'На месте', visitTotal: 'Всего',
    visitNote: 'Оценка для одного места; обратная дорога не учтена.',
    placeData: 'Данные и ограничения', requirements: 'Ваши условия', confirmed: 'подтверждено', unconfirmed: 'не подтверждено', facts: 'Подтверждённые сведения', website: 'Сайт ↗', phone: 'Телефон:',
    groupWalks: 'Путь участников', groupMeet: 'Встреча около', airportTransfer: 'До аэропорта', leaveAirportBy: 'Выехать не позже',
    genericName: 'Название места обобщено.', missing: 'Что не подтверждено:',
    open: 'По расписанию открыто', closed: 'По расписанию закрыто', unknown: 'Открытость неизвестна',
    showMap: 'На карте ↗', showDetails: 'Подробнее', hideDetails: 'Скрыть',
    openOsm: 'Открыть в OSM ↗', dataLink: (provider) => `Данные: ${provider} ↗`,
    online: 'Каталог мест доступен', loadingData: 'Данные загружаются', unavailable: 'Сервис недоступен', checking: 'Проверяем сервис',
    requestFailed: 'Не получилось найти места', searching: 'Подбираем варианты и проверяем время пути…',
    selectionDetails: 'Как мы подобрали места и что проверить?', selectedFor: (budget) => `Учтено: ${budget} на прогулку`,
    travelLimit: (n) => `до ${n} мин пешком`, startAt: (date) => `начало ${date}`,
    sources: 'Данные:', fallback: 'Подходящих мест из 2GIS не получено; использованы данные OSM.',
    searchPlan: { ai_tags: 'ИИ выделил признаки запроса.', rules_fallback: 'Признаки запроса определены правилами.' },
    searchQueries: 'Поиск в 2GIS:',
    selectionMode: { ai_scored: 'Места оценил и выбрал ИИ из проверенных кандидатов.', rules_fallback: 'Места выбраны по правилам: оценка ИИ недоступна или не прошла проверку.', single_candidate: 'Найден один подходящий кандидат.', no_candidates: 'Подходящих кандидатов не найдено.' },
    generated: { llm_verified: 'Текст сгенерирован и проверен ИИ по данным мест.', mixed: 'Текст частично сгенерирован и проверен ИИ, частично составлен по данным мест.', grounded_templates: 'Текст составлен по данным мест.' },
    emptyFlight: 'Подходящих мест перед вылетом нет', emptyPlaces: 'Подходящих мест пока нет',
    emptyFlightHint: 'Проверьте расчёт ниже. Если время рейса или нужный запас отличаются, откройте «Уточнить поиск» и укажите их.',
    emptyHint: 'Попробуйте увеличить время в запросе, разрешить более долгую дорогу или назвать другую точку старта.',
    waitingTitle: 'Места появятся здесь', waitingHint: 'Начните с запроса выше.',
  },
  kk: {
    categories: { cafe: 'Кафе', food: 'Тамақтану', park: 'Саябақтар', museum: 'Мұражайлар', family: 'Балалармен', landmark: 'Көрікті орындар', culture: 'Мәдениет', viewpoint: 'Көру алаңдары', activity: 'Белсенді демалыс', nightlife: 'Түнгі демалыс', shopping: 'Дүкендер' },
    placesHeading: 'Сәйкес орындар', placeCount: (n) => `${n} орын`, groupCount: (n) => `${n} қатысушы`,
    deviceOrigin: 'Сіздің геолокацияңыз', timeFromQuery: 'Сұраудағы уақыт',
    walk: (n) => `${n} мин жаяу`, groupWalk: (n) => `${n} мин дейін жаяу`, fromStart: (distance) => `бастау нүктесінен ${distance}`, groupFromStart: (distance) => `бастау нүктесінен ${distance} дейін`,
    why: 'Неге сәйкес келеді:', action: 'Не істеуге болады:',
    textSource: { grounded_fallback: 'Мәтін орын деректерінен құрастырылған.', llm_verified: 'Мәтін ЖИ көмегімен жазылып, орын деректері бойынша тексерілген.' },
    interestMatched: 'қызығушылық сәйкес', interestNotMatched: 'қызығушылық сәйкес емес',
    staleCatalog: 'OSM деректері ескірген болуы мүмкін', approximateRoute: 'Жол шамамен есептелген',
    visitTitle: 'Уақыт шамасы', visitWalk: 'Орынға дейін жаяу', visitPlace: 'Орынның өзінде', visitTotal: 'Барлығы',
    visitNote: 'Бұл бір орынға арналған болжам; қайтар жол есепке алынбаған.',
    placeData: 'Деректер мен шектеулер', requirements: 'Сіздің шарттарыңыз', confirmed: 'расталған', unconfirmed: 'расталмаған', facts: 'Расталған мәліметтер', website: 'Сайт ↗', phone: 'Телефон:',
    groupWalks: 'Қатысушылардың жолы', groupMeet: 'Кездесу уақыты', airportTransfer: 'Әуежайға дейін', leaveAirportBy: 'Кешікпей шығу',
    genericName: 'Орын атауы жалпыланған.', missing: 'Расталмаған ақпарат:',
    open: 'Кесте бойынша ашық', closed: 'Кесте бойынша жабық', unknown: 'Ашық екені белгісіз',
    showMap: 'Картадан көру ↗', showDetails: 'Толығырақ', hideDetails: 'Жасыру',
    openOsm: 'OSM-де ашу ↗', dataLink: (provider) => `Дереккөз: ${provider} ↗`,
    online: 'Орындар каталогы қолжетімді', loadingData: 'Деректер жүктелуде', unavailable: 'Қызмет қолжетімсіз', checking: 'Қызмет тексерілуде',
    requestFailed: 'Орындарды табу мүмкін болмады', searching: 'Орындар мен жаяу жол уақыты тексерілуде…',
    selectionDetails: 'Орындар қалай таңдалды және нені тексеру керек?', selectedFor: (budget) => `Ескерілгені: серуенге ${budget}`,
    travelLimit: (n) => `жаяу жүруге ${n} мин дейін`, startAt: (date) => `басталуы ${date}`,
    sources: 'Деректер:', fallback: '2GIS-тен сәйкес орындар алынбады; OSM деректері қолданылды.',
    searchPlan: { ai_tags: 'ЖИ сұраудың белгілерін анықтады.', rules_fallback: 'Сұраудың белгілері ережелер бойынша анықталды.' },
    searchQueries: '2GIS ішіндегі іздеу:',
    selectionMode: { ai_scored: 'ЖИ орындарды тексерілген үміткерлер арасынан бағалап таңдады.', rules_fallback: 'Орындар ережелер бойынша таңдалды: ЖИ бағалауы қолжетімсіз не тексеруден өтпеді.', single_candidate: 'Бір ғана сәйкес орын табылды.', no_candidates: 'Сәйкес орын табылмады.' },
    generated: { llm_verified: 'Мәтін орын деректері бойынша ЖИ көмегімен жасалып, тексерілді.', mixed: 'Мәтіннің бір бөлігі ЖИ көмегімен жасалып, тексерілді; қалғаны орын деректерінен құрастырылды.', grounded_templates: 'Мәтін орын деректерінен құрастырылды.' },
    emptyFlight: 'Ұшуға дейін сәйкес орын табылмады', emptyPlaces: 'Әзірге сәйкес орын жоқ',
    emptyFlightHint: 'Төмендегі есепті тексеріңіз. Рейс уақыты не қажет қор басқа болса, «Іздеуді нақтылау» бөлімінде көрсетіңіз.',
    emptyHint: 'Уақытты ұзартыңыз, ұзағырақ жаяу жүруге рұқсат беріңіз немесе басқа бастау орнын көрсетіңіз.',
    waitingTitle: 'Орындар осында көрсетіледі', waitingHint: 'Жоғарыда сұрау енгізіңіз.',
  },
  en: {
    categories: { cafe: 'Cafes', food: 'Food', park: 'Parks', museum: 'Museums', family: 'With children', landmark: 'Landmarks', culture: 'Culture', viewpoint: 'Viewpoints', activity: 'Activities', nightlife: 'Nightlife', shopping: 'Shopping' },
    placesHeading: 'Recommended places', placeCount: (n) => `${n} ${n === 1 ? 'place' : 'places'}`, groupCount: (n) => `${n} people`,
    deviceOrigin: 'Your location', timeFromQuery: 'Time from your request',
    walk: (n) => `${n} min walk`, groupWalk: (n) => `up to ${n} min walk`, fromStart: (distance) => `${distance} from start`, groupFromStart: (distance) => `up to ${distance} from start`,
    why: 'Why it fits:', action: 'What to do:',
    textSource: { grounded_fallback: 'Text composed from place data.', llm_verified: 'Text written by AI and checked against place data.' },
    interestMatched: 'interest matches', interestNotMatched: 'interest differs',
    staleCatalog: 'OSM data may be outdated', approximateRoute: 'Walking route is estimated',
    visitTitle: 'Time estimate', visitWalk: 'Walk to place', visitPlace: 'At the place', visitTotal: 'Total',
    visitNote: 'Estimate for one place; the return trip is not included.',
    placeData: 'Data and limitations', requirements: 'Your requirements', confirmed: 'confirmed', unconfirmed: 'unconfirmed', facts: 'Verified facts', website: 'Website ↗', phone: 'Phone:',
    groupWalks: 'Walk for each person', groupMeet: 'Meet around', airportTransfer: 'To the airport', leaveAirportBy: 'Leave by',
    genericName: 'The place name is generic.', missing: 'Not confirmed:',
    open: 'Open according to listed hours', closed: 'Closed according to listed hours', unknown: 'Opening status unknown',
    showMap: 'On map ↗', showDetails: 'Details', hideDetails: 'Hide',
    openOsm: 'Open in OSM ↗', dataLink: (provider) => `Source: ${provider} ↗`,
    online: 'Place catalog available', loadingData: 'Loading place data', unavailable: 'Service unavailable', checking: 'Checking service',
    requestFailed: 'Could not find places', searching: 'Finding places and checking walking times…',
    selectionDetails: 'How were these places chosen?', selectedFor: (budget) => `Considered: ${budget} for the outing`,
    travelLimit: (n) => `up to ${n} min on foot`, startAt: (date) => `starts ${date}`,
    sources: 'Sources:', fallback: 'No suitable 2GIS places were retrieved; OSM data was used.',
    searchPlan: { ai_tags: 'AI extracted the request tags.', rules_fallback: 'Request tags were determined by rules.' },
    searchQueries: '2GIS search:',
    selectionMode: { ai_scored: 'AI scored and chose these places from verified candidates.', rules_fallback: 'Places were selected by rules because AI scoring was unavailable or invalid.', single_candidate: 'Only one eligible place was found.', no_candidates: 'No eligible places were found.' },
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
  const date = new Date(iso)
  if (language === 'kk') {
    const months = ['қаңтар', 'ақпан', 'наурыз', 'сәуір', 'мамыр', 'маусым', 'шілде', 'тамыз', 'қыркүйек', 'қазан', 'қараша', 'желтоқсан']
    return `${date.getDate()} ${months[date.getMonth()]}, ${date.toLocaleTimeString('kk-KZ', { hour: '2-digit', minute: '2-digit', hour12: false })}`
  }
  return date.toLocaleString({ ru: 'ru-RU', en: 'en-US' }[language], {
    day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit',
  })
}
