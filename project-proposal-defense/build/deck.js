(() => {
  'use strict';
  const SOURCES = {
    repo:{short:'Репозиторий',title:'Brainrot Studio',url:'https://github.com/AndreyTamplon/brainrot-studio',detail:'Код проекта, README и участники команды.'},
    design:{short:'Архитектура',title:'Brainrot Studio: архитектура и контракты',url:'https://github.com/AndreyTamplon/brainrot-studio/blob/main/docs/design.md',detail:'Артефакты, роли агентов, восстановление, медиа и ограничения локального MVP.'},
    validation:{short:'Проверки',title:'Brainrot Studio: результаты проверок',url:'https://github.com/AndreyTamplon/brainrot-studio/blob/main/docs/validation.md',detail:'Зафиксированные проверки: Python и frontend от 18.10.2026, Docker и runtime от 03.10.2026.'},
    engine:{short:'Оркестрация',title:'brainrot/engine.py',url:'https://github.com/AndreyTamplon/brainrot-studio/blob/main/brainrot/engine.py',detail:'LlmAgent, AgentTool, обратные вызовы, основные инструменты и условия завершения.'},
    config:{short:'Конфигурация',title:'brainrot/config.py',url:'https://github.com/AndreyTamplon/brainrot-studio/blob/main/brainrot/config.py',detail:'Модели и значения бюджета по умолчанию.'},
    provider:{short:'Адаптер',title:'brainrot/provider.py',url:'https://github.com/AndreyTamplon/brainrot-studio/blob/main/brainrot/provider.py',detail:'OpenRouterLlm связывает Google ADK с OpenRouter; Gateway выполняет модельные вызовы и учет расходов.'},
    locks:{short:'Версии Python',title:'Версии Python-зависимостей',url:'https://github.com/AndreyTamplon/brainrot-studio/blob/main/uv.lock',detail:'Зафиксированы FastAPI 0.141.1, Google ADK 2.11.0, faster-whisper 1.2.1, PyAV 18.1.0 и Pillow 12.3.0.'},
    frontlock:{short:'Версии UI',title:'Версии интерфейса',url:'https://github.com/AndreyTamplon/brainrot-studio/blob/main/frontend/package-lock.json',detail:'React 19.3.0, TypeScript 5.9.3, Vite 7.3.6. Собранная статика копируется в финальный Docker-образ и отдается через FastAPI.'},
    compose:{short:'Docker Compose',title:'compose.yaml',url:'https://github.com/AndreyTamplon/brainrot-studio/blob/main/compose.yaml',detail:'Один сервис studio, локальный порт 8000 и подключенный каталог data.'},
    'meta-status':{short:'Статус Meta',title:'Минюст России: перечень экстремистских организаций',url:'https://minjust.gov.ru/ru/documents/7822/',detail:'Пункт 96: Meta Platforms Inc. по реализации продуктов Facebook и Instagram. Формулировка сноски соответствует принятому в российских СМИ обозначению статуса компании; решение суда от 21.03.2022.'},
    'mymuse-site':{short:'Интерфейс My Muse',title:'My Muse: публичный каталог сервиса',url:'https://my-muse.ai/',detail:'Изображение: снимок публичной главной страницы my-muse.ai от 21.10.2026. © My Muse / HOLYWATER TECH. Показатель ускорения производства подтверждается отдельно кейсом Google Cloud.'},
    neurodoc:{short:'Кино Mail',title:'Кино Mail запускает нейродоксериал «Нейро_Док»',url:'https://kino.mail.ru/news/126426-kino-mail-zapuskaet-pervyj-v-rossii-nejrodokserial/',detail:'Официальный анонс: короткие вертикальные эпизоды с генеративной графикой и нейросетевой реконструкцией. Премьера состоялась 26.05.2026 в сообществе ProКино в MAX. Наличие мобильного формата в других каталогах само по себе не подтверждает применение ИИ.'},
    meta:{short:'Meta',title:'Introducing Vibes: A New Way to Discover and Create AI Videos',url:'https://about.fb.com/news/2025/09/introducing-vibes-ai-videos/',detail:'Анонс Meta от 25.09.2025. Изображение: опубликованная анимация Vibes, статичный кадр. © Meta.'},
    coke:{short:'Coca-Cola',title:'Coca-Cola: AI-powered storytelling in the 2025 holiday campaign',url:'https://www.coca-colacompany.com/media-center/coca-cola-refreshes-givers-of-the-season-embraces-ai-powered-storytelling-in-global-holiday-campaign',detail:'Релиз от 03.11.2025. Иллюстрация: превью опубликованного компанией видео со сравнением рекламы 2024 и 2025 годов. © The Coca-Cola Company.'},
    netflix:{short:'Netflix',title:'Netflix, Q2 2025 earnings call transcript',url:'https://s22.q4cdn.com/959853165/files/doc_financials/2025/q2/Netflix-Inc-_Earnings-Call_Transcript.pdf',detail:'17.07.2025, страница 12. Тед Сарандос описывает применение генеративного ИИ для VFX сцены обрушения здания в «Этернавте».'},
    'eternaut-image':{short:'Кадр',title:'Иллюстрация сцены из «Этернавта»',url:'https://www.securitylab.lat/news/561533.php',detail:'Изображение сцены обрушения из публикации SecurityLab; © Netflix / правообладатели сериала. Факт применения ИИ подтвержден отдельно стенограммой Netflix.'},
    holywater:{short:'Google Cloud',title:'HOLYWATER TECH: AI production pipeline for My Muse',url:'https://cloud.google.com/customers/holywater',detail:'Партнерский кейс. Описаны агенты Gemini, раскадровка и генерация видео. Ускорение в 8 раз является заявлением участников кейса. Изображение каталога: Google Cloud / HOLYWATER.'},
    'kp-market':{short:'Рынок РФ',title:'Мобильные сериалы появились у российских платформ',url:'https://www.kinopoisk.ru/media/news/4012361/',detail:'Кинопоиск, 17.02.2026. Описывает каталоги и производство мобильных сериалов на Кинопоиске, Иви, Wink и Кионе. Само наличие формата не подтверждает использование ИИ в каждом проекте.'},
    'kp-ai':{short:'Микродрамы',title:'Вертикальные сериалы и рынок микродрам',url:'https://www.kinopoisk.ru/media/article/4011590/',detail:'Кинопоиск, 12.08.2025. Раздел «Экономика» содержит комментарий Никиты Ерункова о нейросетевом производстве; раздел о России описывает «ЖЭК» со сценарием ChatGPT.'},
    zhek:{short:'«ЖЭК»',title:'Валерия Гай Германика анонсировала «ЖЭК», сериал по сценарию ChatGPT',url:'https://srsly.ru/article/show/38394/',detail:'SRSLY, 06.05.2025. Фото со съемок из публикации: на тарелке указан ChatGPT как автор сценария. Объем человеческой редакторской работы в материале не раскрывается.'},
    mts:{short:'KION',title:'KION запустил производство вертикальных сериалов',url:'https://media.mts.ru/society/211983-vertikalnie-seriali-kion',detail:'МТС, 21.11.2025. Официальный материал о вертикальных проектах и каталоге KION.'},
    movieagent:{short:'arXiv:2503.07314',title:'Automated Movie Generation via Multi-Agent CoT Planning',url:'https://arxiv.org/pdf/2503.07314',detail:'Wu, Zhu, Shou, 10.03.2025. Схема адаптирована по Figure 1, Figure 2 и §3.2: входные данные, иерархия агентов, структурированные результаты и генерация. Исходный Figure 1 доступен по кнопке на слайде. Изображение предоставлено пользователем; авторы Wu, Zhu, Shou, CC BY 4.0.'},
    frameworkers:{short:'arXiv:2608.29814',title:'FRAMEWORKERS: A Dynamic Multi-Agent Framework for AI-Generated Video Production',url:'https://arxiv.org/pdf/2608.29814',detail:'Li и соавторы, 30.08.2026. Схема адаптирована по Figure 1 и §3.1-3.4. Показаны Director, Task Stack, Assistant, Workspace и группы субагентов. Исходный Figure 1 предоставлен пользователем и доступен по кнопке. Это архитектура из статьи, а не Brainrot Studio.'},
    c4:{short:'C4',title:'The C4 model: diagrams',url:'https://c4model.com/diagrams',detail:'Контекст, контейнеры, компоненты; вспомогательные динамические диаграммы и развертывание. Основа выбора представлений для этой презентации.'},
    'c4-containers':{short:'C4: контейнеры',title:'C4: Container diagram',url:'https://c4model.com/diagrams/container',detail:'В C4 контейнером называют приложение или хранилище данных. Развертывание является отдельным представлением.'},
    iso:{short:'ISO 42010',title:'ISO/IEC/IEEE 42010:2022, Architecture description',url:'https://www.iso.org/standard/74393.html',detail:'Рамка описания архитектуры. Дополнительная учебная опора: «АПС справочник.pdf», разделы К69-К72, C4 и модель N+1.'}
  };
  const NOTES = {
    cover:{speech:'Мы представляем Brainrot Studio, учебный проект по созданию вертикальных роликов. Пользователь задает тему и параметры, а система ведет производство через несколько специализированных агентов. Начнем с того, где подобные процессы уже применяют.',preparation:'Команда из четырех человек указана на обложке. Распределите блоки заранее: каждый участник должен представить хотя бы один слайд.'},
    world:{speech:'ИИ уже участвует в создании видео для разных площадок. Meta представила ленту Vibes. Coca-Cola использовала генеративные версии праздничной рекламы. Netflix сообщил о применении генеративного ИИ в VFX для одной сцены «Этернавта». Эти примеры различаются по масштабу и роли технологии. Нас интересует организация производства, когда над результатом работают несколько моделей и инструментов.'},
    muse:{speech:'Близкий коммерческий пример дает My Muse. В кейсе Google Cloud описан процесс, где агенты анализируют книги и фиксируют сведения о персонажах и локациях, затем подключаются раскадровка и видео. Участники кейса заявляют ускорение производства сериалов в восемь раз. Для нас здесь важны сохранение контекста и передача результатов между этапами.',preparation:'Ускорение относится к заявленному кейсу HOLYWATER. Мы не переносим эту цифру на наш проект.'},
    russia:{speech:'В России вертикальные сериалы есть у Кинопоиска, Иви, Wink и KION. Прямой пример ИИ-производства дает «Нейро_Док» от Кино Mail: он выходит короткими вертикальными эпизодами в MAX. Конкретный пример работы с LLM на сценарном этапе дает «ЖЭК» Валерии Гай Германики. В публикациях и на фотографии съемочной тарелки автором сценария указан ChatGPT. Упоминания нейросетевого производства есть и в обзоре Кинопоиска. При этом наличие микросериалов в каталоге платформы само по себе ничего не говорит о способе их создания.'},
    movie:{speech:'MovieAgent получает синопсис и банк персонажей с изображениями и образцами голоса. Director разбивает историю на подсценарии. Scene Plan задает границы сцен, их настроение и визуальные условия. Shot Plan описывает композицию, движение камеры и реплики для каждого кадра. Эти результаты передаются генеративным моделям. В статье каждый уровень использует CoT-планирование и выдает структурированный результат. Для нашего проекта здесь полезно разделение ответственности и сохранение результатов каждого этапа.',preparation:'Схема адаптирована по Figure 1, Figure 2 и §3.2. Исходный Figure 1 открывается кнопкой «Рисунок из статьи». Работа является препринтом; результаты авторов не относятся к нашему MVP.'},
    frame:{speech:'FrameWorkers устроен вокруг изменяемого плана. Director редактирует стек задач, учитывая запрос и текущее состояние работы. Assistant получает следующую исполнимую задачу, подбирает входные данные в Workspace и вызывает специалиста. Затем он проверяет и сохраняет результат, возвращая директору сводку. Каталог содержит агентов для разных этапов производства. Ошибка или новый запрос могут изменить оставшиеся задачи. Для нас это пример связи планирования, выполнения и сохраненного состояния.',preparation:'По Figure 1 и §3.1-3.4. В статье Director сначала обучают с SFT и GRPO; runtime-перепланирование описано отдельно. Наш проект не реализует обучение директора или универсальный динамический стек этой работы.'},
    problem:{speech:'Выпуск готового ролика требует времени и ресурсов. Причина в зависимостях между этапами: после изменений приходится заново проверять связанные результаты. Нужно сохранить единство сцены в тексте, изображениях и звуке, уложить речь и титры в длительность, проверить факты и подобрать достоверные иллюстрации. При этом правки требуют пересчета зависимостей и расходуют бюджет. Новая реплика является одним примером этой общей задачи: озвучку и таймлайн придется обновить, а подходящее изображение можно оставить. Мы проектируем систему так, чтобы она управляла этими связями.'},
    product:{speech:'Brainrot Studio является мультиагентной системой создания вертикального видео с LLM-агентами. Автор задает тему и параметры через браузер, получает ролик, субтитры и отчет. Он может просмотреть результат и запросить адресную доработку. Пунктиром показан сценарий правок, доступный в текущем интерфейсе. Система сохраняет материалы задания, чтобы не начинать всю работу заново. Внешние интеграции и внутренние компоненты раскрыты на следующем слайде.'},
    logical:{speech:'На этом уровне раскрыт агентный движок с предыдущего слайда. Все пять ролей являются LLM-агентами. Продюсер назначает работу четырем специалистам через AgentTool. Исследователь собирает сведения и источники, сценарист пишет реплики и сцены, визуализатор подбирает иллюстрации, монтажер готовит сборку и проверку. У каждого есть свои инструкции и инструменты. Структурированные результаты сохраняются как артефакты, по которым продюсер выбирает продолжение или доработку.',preparation:'Это логические компоненты одного приложения. TTS, Whisper и FFmpeg остаются инструментами и моделями без самостоятельного агентного цикла.'},
    technical:{speech:'Это компоненты текущего MVP. FastAPI принимает запросы и отдает собранный веб-интерфейс. Очередь хранит идентификаторы заданий, а отдельная фоновая asyncio-задача worker берет и выполняет их по одному. Worker вызывает агентный движок на Google ADK. Движок использует локальные инструменты медиа и внешние модели через OpenRouter. MiMo Pro и Flash выполняют агентные роли, Gemini рецензирует материалы, Fish Audio синтезирует речь персонажей. Wikimedia Commons дает готовые иллюстрации. Данные сохраняются в SQLite и файлах.',preparation:'Компонент worker выделен логически: сейчас это asyncio-задача внутри процесса API, не отдельный контейнер. React исполняется в браузере; его production-статика входит в Docker-образ и отдается FastAPI. Dockerfile собирает образ, Compose запускает один сервис с томом data. Версии Python-библиотек взяты из uv.lock, UI из package-lock.json. Dockerfile не фиксирует версии SQLite, системного FFmpeg и patch-версию Python. Docker daemon при подготовке не запущен; фактические версии среды не заявляем. Контейнер C4 означает приложение или хранилище и не равен Docker-контейнеру.'},
    flow:{speech:'Исследование дает материал для сценария. После принятия сценария озвучка и подбор иллюстраций могут работать параллельно. Затем монтажер вызывает сборку и проверку. При замечаниях управление возвращается продюсеру: текст или длительность он передает сценаристу, иллюстрацию визуализатору, композицию монтажеру. LLM нужны для интерпретации свободного запроса, написания сценария и выбора доработки. Whisper измеряет речь, а FFmpeg исполняет типизированный план. Число вызовов, расходы и повторные рендеры ограничены кодом.',preparation:'Слайд раскрывается за три шага: сценарий; параллельные ветки и сборка; проверка с возвратом. Ссылки на MovieAgent и FrameWorkers показывают научные подходы к разделению ролей и работе с состоянием. В нашем MVP фиксированные роли и ограниченный цикл доработок. Не называйте все этапы полностью независимыми: у них есть предусловия и связи по версиям артефактов.'},
    demo:{speech:'Покажем готовый ролик, материалы задания и отчет. Затем запросим изменение оформления субтитров и посмотрим, какие результаты система переиспользует.',preparation:'До выступления запустите приложение и подготовьте завершенное задание. За 80 секунд: покажите 15 секунд ролика, источники и отчет, запросите «Сделай субтитры белыми» и объясните переиспользование аудио. При долгом рендере покажите уже подготовленную версию с этой правкой. Кнопка предназначена для перехода докладчика на его компьютере. Адрес можно изменить в настройках через «?». Платные генерации презентация сама не запускает.'},
    limits:{speech:'Ограничения разделены на масштаб работы и оценку качества. Приложение запускается локально, рассчитано на одного пользователя и выполняет задания одним worker. Авторизация и изоляция пользовательских заданий пока не реализованы. Отдельная граница касается качества: рецензирующая модель может пропустить фактическую ошибку, а голос и юмор требуют просмотра человеком. Следующий слайд показывает доработки, которые мы планируем к финальной защите.'},
    roadmap:{speech:'К финальной защите мы планируем доработать обработку заданий и подготовить очередь к нескольким исполнителям. Для human-in-the-loop добавим подтверждение сценария до озвучки, чтобы пользователь мог остановить нежелательный вариант до следующих платных этапов. Основа многопользовательского режима потребует авторизации и изоляции заданий. Эти пункты описывают следующую версию. В текущем MVP остается один локальный пользователь.'},
    potential:{speech:'Дальше можно проверить применимость подхода в рекламе, коротких образовательных объяснениях и локализации. Переход к микросериалам потребует памяти о сюжете и персонажах между эпизодами. Для каждого направления понадобятся свои шаблоны, данные и критерии качества. Это возможные следующие версии, которые мы предлагаем исследовать после завершения текущего объема проекта.'},
    models:{speech:'Google ADK управляет агентами, а OpenRouter является внешним шлюзом. MiMo Pro используется для продюсера, сценариста и монтажера; MiMo Flash для исследователя и визуализатора. Gemini отдельно проверяет сценарий, изображения и реальную аудиодорожку. Whisper small работает локально. Названия в таблице соответствуют конфигурации проекта.',preparation:'Уточнения: исследователь и визуализатор могут перейти на Pro после повторяющихся ошибок инструмента. Для стандартного голоса нового рассказчика без образца используется google/gemini-3.8-flash-lite-tts. Поле tts_model конкретного рассказчика имеет приоритет над общей настройкой. Для исследования и спорных рецензий есть отдельные проверки и арбитраж.'},
    validation:{speech:'В документации зафиксирован прогон от 18 октября: 163 теста Python, пять тестов интерфейса, production-сборка и Ruff. Этот прогон не вызывал платные API. Docker и настоящий рендер проверяли отдельно 3 октября. Эти даты относятся к сохраненным результатам, а не к повторному запуску во время подготовки презентации. Для полной приемки модельных сценариев остается отдельная работа.'},
    budgets:{speech:'Внешний Gateway учитывает расходы всех моделей. По умолчанию задание ограничено полутора долларами, общий лимит десять долларов. На один проход есть предел 65 агентных вызовов и 100 действий. Возможны первичная сборка и две доработки. Статус ready требует актуальных проверок; иначе система может завершить работу как needs_review. После неопределенной сетевой ошибки резерв расходов остается до сверки.'}
  };
  const allSlides = [...document.querySelectorAll('.slide')];
  const mainSlides = allSlides.filter(slide => !slide.hasAttribute('data-backup'));
  const mainCount = mainSlides.length;
  let current = 0;
  let build = 0;
  let presenterWindow = null;
  const startedAt = Date.now();
  const escape = value => String(value).replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  const sourceKeys = slide => (slide.dataset.sources || '').split(',').filter(Boolean);
  const maxBuild = slide => Math.max(0,...[...slide.querySelectorAll('[data-build]')].map(el=>Number(el.dataset.build)));
  const el = id => document.getElementById(id);
  let demoUrl = 'http://127.0.0.1:8000';
  try{const stored=localStorage.getItem('brainrot-proposal-demo-url');if(stored&&/^https?:\/\//i.test(stored))demoUrl=stored;}catch{}
  function setDemoUrl(value){
    try{const parsed=new URL(value);if(!['http:','https:'].includes(parsed.protocol))return false;demoUrl=parsed.href.replace(/\/$/,'');}catch{return false;}
    el('demo-link').href=demoUrl;el('demo-url-setting').value=demoUrl;
    try{localStorage.setItem('brainrot-proposal-demo-url',demoUrl);}catch{}
    return true;
  }
  setDemoUrl(demoUrl);
  allSlides.forEach(slide=>{
    const footer=document.createElement('footer');footer.className='slide-foot';
    const evidenceLink=(key,label)=>`<a href="${escape(SOURCES[key].url)}" target="_blank" rel="noopener">${escape(label)}</a>`;
    const evidence={
      world:`Источники: ${evidenceLink('meta','анонс Meta* Vibes')} · ${evidenceLink('coke','кампания Coca-Cola')} · ${evidenceLink('netflix','VFX Netflix')} · ${evidenceLink('eternaut-image','кадр сериала')}.`,
      muse:`${evidenceLink('holywater','Google Cloud: кейс HOLYWATER / My Muse')} · ${evidenceLink('mymuse-site','снимок интерфейса сервиса')}.`,
      russia:`Мобильный формат: ${evidenceLink('kp-market','Кинопоиск')}, ${evidenceLink('mts','KION')}. ИИ в производстве: ${evidenceLink('zhek','«ЖЭК»')}, ${evidenceLink('neurodoc','«Нейро_Док»')}.`
    };
    if(evidence[slide.dataset.notes]){footer.classList.add('explained');footer.innerHTML=evidence[slide.dataset.notes];slide.append(footer);return;}
    const section=document.createElement('span');if(slide.dataset.notes!=='cover')section.textContent=slide.dataset.section;footer.append(section);
    const links=document.createElement('span');links.className='source-links';
    sourceKeys(slide).forEach(key=>{const source=SOURCES[key];if(!source)return;const link=document.createElement('a');link.href=source.url;link.textContent=source.short;link.target='_blank';link.rel='noopener';links.append(link);});
    footer.append(links);slide.append(footer);
  });
  function fit(){const availableWidth=Math.max(220,innerWidth-(innerWidth<760?16:48));const availableHeight=Math.max(130,innerHeight-(innerWidth<760?86:112));const scale=Math.min(availableWidth/1600,availableHeight/900);document.documentElement.style.setProperty('--scale',scale);el('stage').style.width=(1600*scale)+'px';el('stage').style.height=(900*scale)+'px';}
  function render(){
    allSlides.forEach((slide,index)=>{const active=index===current;slide.classList.toggle('active',active);slide.inert=!active;slide.setAttribute('aria-hidden',String(!active));});
    const slide=allSlides[current];
    slide.querySelectorAll('[data-build]').forEach(part=>part.classList.toggle('is-hidden',Number(part.dataset.build)>build));
    el('counter').textContent=current<mainCount?`${current+1} / ${mainCount}`:`Резерв ${current-mainCount+1} / ${allSlides.length-mainCount}`;
    el('progress').style.width=Math.min(100,((Math.min(current,mainCount-1)+1)/mainCount)*100)+'%';
    el('build-label').textContent=maxBuild(slide)?`Шаг ${build+1} / ${maxBuild(slide)+1}`:'';
    document.title=`${slide.dataset.title} · Brainrot Studio`;
    try{history.replaceState(null,'',`#${current+1}`);}catch{}
    document.querySelectorAll('.overview-item').forEach((button,index)=>button.classList.toggle('current',index===current));
    if(el('notes-dialog').open)populateNotes();
    if(el('sources-dialog').open)populateSources();
    updatePresenter();
    window.dispatchEvent(new CustomEvent('brainrot-slidechange',{detail:{index:current,build,title:slide.dataset.title}}));
  }
  function goTo(index,step=0){current=Math.max(0,Math.min(allSlides.length-1,index));build=Math.max(0,Math.min(maxBuild(allSlides[current]),step));render();}
  function next(){if(build<maxBuild(allSlides[current])){build++;render();}else if(current+1<allSlides.length&&(current+1<mainCount||current>=mainCount)){goTo(current+1);}}
  function previous(){if(build>0){build--;render();}else if(current>0)goTo(current-1,maxBuild(allSlides[current-1]));}
  function openDialog(id){document.querySelectorAll('dialog[open]').forEach(dialog=>dialog.close());el(id).showModal();}
  function populateNotes(){const slide=allSlides[current],note=NOTES[slide.dataset.notes]||{};el('notes-content').innerHTML=`<div class="notes-meta">${escape(slide.dataset.section)} · ${current<mainCount?'Слайд '+(current+1):'Резерв'}${Number(slide.dataset.duration)?' · '+slide.dataset.duration+' сек.':''}</div><h3>Речь</h3><p>${escape(note.speech||'')}</p>${note.preparation?`<h3>Подготовка и уточнения</h3><p>${escape(note.preparation)}</p>`:''}<h3>Дальше</h3><p>${escape(allSlides[current+1]?.dataset.title||'Конец резервных материалов')}</p>`;}
  function populateSources(){const slide=allSlides[current],keys=sourceKeys(slide);el('sources-content').innerHTML=`<p>${escape(slide.dataset.title)}</p>`+(keys.length?keys.map(key=>{const source=SOURCES[key];return source?`<div class="source-item"><a href="${escape(source.url)}" target="_blank" rel="noopener">${escape(source.title)}</a><p>${escape(source.detail)}</p></div>`:'';}).join(''):'<p>План команды, согласованный при подготовке Project Proposal.</p>');}
  function toggleDialog(id,prepare){if(el(id).open){el(id).close();return;}if(prepare)prepare();openDialog(id);}
  allSlides.forEach((slide,index)=>{const button=document.createElement('button');button.className='overview-item';button.innerHTML=`<span class="overview-number">${index<mainCount?String(index+1).padStart(2,'0'):'Р'+(index-mainCount+1)}</span><span class="overview-name">${escape(slide.dataset.title)}${slide.hasAttribute('data-backup')?'<br><span class="muted">Резерв</span>':''}</span>`;button.addEventListener('click',()=>{goTo(index);el('overview-dialog').close();});el('overview-grid').append(button);});
  document.querySelectorAll('[data-figure]').forEach(button=>button.addEventListener('click',()=>{
    const name=button.dataset.figure;
    document.querySelectorAll('.paper-original').forEach(img=>img.classList.toggle('visible',img.id==='figure-'+name));
    el('figure-title').textContent=name==='movieagent'?'MovieAgent · Figure 1':'FrameWorkers · Figure 1';
    el('figure-credit').textContent=name==='movieagent'?'Wu, Zhu, Shou. Automated Movie Generation via Multi-Agent CoT Planning, 2025. Рисунок из статьи; изображение предоставлено пользователем.':'Li и соавторы. FrameWorkers, 2026. Рисунок из статьи; изображение предоставлено пользователем.';
    openDialog('figure-dialog');
  }));
  el('prev').addEventListener('click',previous);el('next').addEventListener('click',next);
  el('overview-button').addEventListener('click',()=>toggleDialog('overview-dialog'));
  el('notes-button').addEventListener('click',()=>toggleDialog('notes-dialog',populateNotes));
  el('sources-button').addEventListener('click',()=>toggleDialog('sources-dialog',populateSources));
  el('help-button').addEventListener('click',()=>toggleDialog('help-dialog'));
  document.querySelectorAll('[data-close]').forEach(button=>button.addEventListener('click',()=>button.closest('dialog').close()));
  document.querySelectorAll('dialog').forEach(dialog=>dialog.addEventListener('click',event=>{if(event.target===dialog){const rect=dialog.getBoundingClientRect();if(event.clientX<rect.left||event.clientX>rect.right||event.clientY<rect.top||event.clientY>rect.bottom)dialog.close();}}));
  async function fullscreen(){try{if(document.fullscreenElement)await document.exitFullscreen();else await document.documentElement.requestFullscreen();}catch{}}
  el('fullscreen-button').addEventListener('click',fullscreen);el('print-button').addEventListener('click',()=>{el('help-dialog').close();window.print();});
  el('save-demo-url').addEventListener('click',()=>{const input=el('demo-url-setting');if(!setDemoUrl(input.value)){input.setCustomValidity('Укажите адрес http:// или https://');input.reportValidity();}else input.setCustomValidity('');});
  el('demo-url-setting').addEventListener('input',()=>el('demo-url-setting').setCustomValidity(''));
  const blackout=()=>el('blackout').classList.toggle('on');el('blackout-close').addEventListener('click',blackout);
  const clock=()=>{const elapsed=Math.floor((Date.now()-startedAt)/1000);return `${Math.floor(elapsed/60)}:${String(elapsed%60).padStart(2,'0')}`;};
  function openPresenter(){
    presenterWindow=window.open('','brainrot-presenter','width=1100,height=790');if(!presenterWindow)return;
    presenterWindow.document.open();presenterWindow.document.write(`<!doctype html><html lang="ru"><head><meta charset="utf-8"><title>Brainrot Studio: докладчик</title><style>body{font:20px/1.65 Arial,sans-serif;background:#111513;color:#f2f3ea;margin:0;padding:34px}header{display:flex;justify-content:space-between;color:#d9f56b;font-size:18px}h1{font-size:32px;line-height:1.2;margin:25px 0}h2{font-size:17px;color:#b4beb3;font-weight:400;margin:28px 0 5px}p{margin:7px 0;font-size:22px}button{background:#d9f56b;color:#111513;border:0;border-radius:5px;padding:12px 22px;font:18px Arial;cursor:pointer;margin-right:9px}#prep{font-size:17px;color:#b4beb3}#upnext{font-size:19px}nav{margin:20px 0}</style></head><body><header><span id="count"></span><span id="clock"></span></header><h1 id="title"></h1><nav><button id="p-prev">Назад</button><button id="p-next">Дальше</button></nav><p id="speech"></p><p id="prep"></p><h2>Следующий слайд</h2><p id="upnext"></p></body></html>`);presenterWindow.document.close();
    presenterWindow.document.getElementById('p-prev').onclick=previous;presenterWindow.document.getElementById('p-next').onclick=next;
    presenterWindow.addEventListener('keydown',event=>{if(['ArrowRight','PageDown',' '].includes(event.key)){event.preventDefault();next();}if(['ArrowLeft','PageUp'].includes(event.key)){event.preventDefault();previous();}});
    updatePresenter();
  }
  function updatePresenter(){if(!presenterWindow||presenterWindow.closed)return;try{const doc=presenterWindow.document,slide=allSlides[current],note=NOTES[slide.dataset.notes]||{};doc.getElementById('count').textContent=el('counter').textContent+(maxBuild(slide)?` · шаг ${build+1}`:'');doc.getElementById('clock').textContent=clock();doc.getElementById('title').textContent=slide.dataset.title;doc.getElementById('speech').textContent=note.speech||'';doc.getElementById('prep').textContent=note.preparation||'';doc.getElementById('upnext').textContent=allSlides[current+1]?.dataset.title||'Конец';}catch{}}
  el('presenter-button').addEventListener('click',()=>{el('help-dialog').close();openPresenter();});setInterval(updatePresenter,1000);
  document.addEventListener('keydown',event=>{
    if(event.ctrlKey||event.metaKey||event.altKey||['INPUT','TEXTAREA','SELECT'].includes(document.activeElement?.tagName))return;
    if(el('blackout').classList.contains('on')){if(['b','B','Escape'].includes(event.key))blackout();return;}
    if(document.querySelector('dialog[open]'))return;
    if(['ArrowRight','PageDown',' '].includes(event.key)){event.preventDefault();next();}
    else if(['ArrowLeft','PageUp'].includes(event.key)){event.preventDefault();previous();}
    else if(event.key==='Home'){event.preventDefault();goTo(0);}
    else if(event.key==='End'){event.preventDefault();goTo(mainCount-1);}
    else if(event.key.toLowerCase()==='f')fullscreen();
    else if(event.key.toLowerCase()==='n'){populateNotes();openDialog('notes-dialog');}
    else if(event.key.toLowerCase()==='s'){populateSources();openDialog('sources-dialog');}
    else if(event.key.toLowerCase()==='o')openDialog('overview-dialog');
    else if(event.key.toLowerCase()==='p')openPresenter();
    else if(event.key.toLowerCase()==='d')window.open(demoUrl,'_blank','noopener');
    else if(event.key.toLowerCase()==='b')blackout();
    else if(event.key==='?')openDialog('help-dialog');
  });
  window.addEventListener('resize',fit);window.addEventListener('hashchange',()=>{const match=location.hash.match(/^#(?:slide-)?(\d+)$/);if(match)goTo(Number(match[1])-1);});
  window.brainrotDeck={goTo,next,previous,openPresenter,get state(){return {current,build,mainCount,total:allSlides.length,demoUrl};},sources:SOURCES,notes:NOTES};
  const initial=location.hash.match(/^#(?:slide-)?(\d+)$/);if(initial)current=Math.max(0,Math.min(allSlides.length-1,Number(initial[1])-1));fit();render();
})();
