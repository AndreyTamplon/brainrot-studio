import React, { useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  ArrowRight,
  AudioLines,
  Check,
  CheckCircle2,
  Circle,
  Clapperboard,
  Download,
  ExternalLink,
  Film,
  ImagePlus,
  Loader2,
  MessageSquare,
  Plus,
  RefreshCw,
  Settings2,
  SlidersHorizontal,
  Square,
  Subtitles,
  Upload,
  Users,
  WandSparkles,
  X,
} from "lucide-react";
import type {
  Background,
  Catalog,
  Job,
  JobSummary,
  JobEvent,
  Settings,
  Speaker,
} from "./types";
import "./style.css";
import { api, isTransientError, post } from "./api";
const money = (n = 0) => "$" + n.toFixed(3);
const labels: Record<string, string> = {
  queued: "В очереди",
  running: "В работе",
  ready: "Готово",
  failed: "Ошибка",
  cancelled: "Остановлен",
  interrupted: "Прерван",
  needs_review: "Нужна проверка",
};
const agents: Record<string, string> = {
  producer: "Продюсер",
  researcher: "Исследователь",
  research_search: "Поиск",
  writer: "Сценарист",
  visual_producer: "Визуализатор",
  speech: "Озвучка",
  editor: "Монтажёр",
  editor_review: "Проверка",
  specialist: "Подагенты",
  vision: "Проверка кадров",
  tts: "Синтез речи",
  script_review: "Проверка сценария",
  script_adjudication: "Перепроверка замечаний",
  audio_review: "Проверка звучания",
  visual_inspection: "Проверка картинок",
};
const stages: Record<string, string> = {
  planning: "Планирование",
  retrying: "Восстановление после сбоя",
  recovering: "Продолжение после перезапуска",
  interrupted: "Прерван",
  research: "Исследование",
  script: "Сценарий",
  visuals: "Визуал и озвучка",
  render: "Монтаж",
  review: "Проверка",
  complete: "Завершено",
  queued: "В очереди",
  cancelled: "Остановлен",
};
const media = (path: string) => "/media/" + path;
const playbackMetrics = (event: React.SyntheticEvent<HTMLVideoElement>) => {
  const video = event.currentTarget;
  const quality = video.getVideoPlaybackQuality?.();
  if (quality) video.dataset.playbackQuality = JSON.stringify({
    total: quality.totalVideoFrames,
    dropped: quality.droppedVideoFrames,
    corrupted: quality.corruptedVideoFrames,
    time: video.currentTime,
  });
};

function App() {
  const [catalog, setCatalog] = useState<Catalog>({
    backgrounds: [],
    speakers: [],
  });
  const [settings, setSettings] = useState<Settings | null>(null);
  const [jobs, setJobs] = useState<JobSummary[]>([]);
  const [selected, setSelected] = useState<string | null>(() =>
    new URLSearchParams(location.search).get("job"),
  );
  const [job, setJob] = useState<Job | null>(null);
  const [topic, setTopic] = useState("");
  const [background, setBackground] = useState("");
  const [speakers, setSpeakers] = useState<string[]>([]);
  const [subtitles, setSubtitles] = useState(true);
  const [instructions, setInstructions] = useState("");
  const [language, setLanguage] = useState("ru");
  const [duration, setDuration] = useState(30);
  useEffect(() => {
    setSpeakers(old => old.filter(id => {
      const speaker = catalog.speakers.find(s => s.id === id);
      return !speaker?.languages || speaker.languages.includes(language);
    }));
  }, [language, catalog.speakers]);
  const [tab, setTab] = useState("video");
  const [modal, setModal] = useState<"settings" | "speaker" | null>(null);
  const [error, setError] = useState("");
  const [connectionError, setConnectionError] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [busy, setBusy] = useState(false);
  const [revision, setRevision] = useState("");
  const uploadRef = useRef<HTMLInputElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const refresh = async () => {
    try {
      const [c, s, j] = await Promise.all([
        api<Catalog>("/catalog"),
        api<Settings>("/settings"),
        api<JobSummary[]>("/jobs?summary=true"),
      ]);
      setCatalog(c);
      setSettings(s);
      setJobs(j);
      setConnectionError(false);
      return c;
    } catch (e) {
      setConnectionError(true);
      throw e;
    }
  };
  useEffect(() => {
    refresh()
      .then((c) => {
        if (!selected) {
          setBackground(c.backgrounds.find((b: Background) => !b.retired)?.id || "");
          setSpeakers(c.speakers[0] ? [c.speakers[0].id] : []);
        }
      })
      .catch(() => {})
      .finally(() => setLoaded(true));
  }, []);
  useEffect(() => {
    const onFocus = () => refresh().catch(() => {});
    window.addEventListener("focus", onFocus);
    const timer = setInterval(onFocus, 7000);
    return () => {
      window.removeEventListener("focus", onFocus);
      clearInterval(timer);
    };
  }, []);
  useEffect(() => {
    const url = new URL(location.href);
    if (selected) url.searchParams.set("job", selected);
    else url.searchParams.delete("job");
    history.replaceState(null, "", url);
    if (!selected) {
      setJob(null);
      return;
    }
    let disposed = false;
    let initialized = false;
    const load = () =>
      api<Job>("/jobs/" + selected)
        .then((j) => {
          if (!disposed) {
            setJob(j);
            if (!initialized) {
              setBackground(j.request.background_id);
              setSubtitles(j.request.subtitles);
              initialized = true;
            }
          }
        })
        .catch((e) => {
          if (!disposed) {
            if (isTransientError(e)) setConnectionError(true);
            else setError(e.message);
          }
        });
    load();
    const stream = new EventSource("/api/jobs/" + selected + "/events");
    stream.onmessage = () => {
      load();
    };
    stream.addEventListener("done", () => {
      load();
      refresh().catch(() => {});
      stream.close();
    });
    stream.onerror = () => {
      stream.close();
      load();
    };
    const timer = setInterval(() => {
      load();
    }, 7000);
    return () => {
      disposed = true;
      stream.close();
      clearInterval(timer);
    };
  }, [selected]);
  const run = async (fn: () => Promise<void>) => {
    setError("");
    setBusy(true);
    try {
      await fn();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const create = () =>
    run(async () => {
      const j = await post<Job>("/jobs", {
        topic,
        background_id: background,
        speaker_ids: speakers,
        subtitles,
        instructions,
        language,
        duration,
        budget: settings?.max_run_budget || 1.5,
      });
      setSelected(j.id);
      setJob(j);
      setTab("agents");
      await refresh();
    });
  const revise = () =>
    run(async () => {
      if (!job) return;
      const j = await post<Job>(`/jobs/${job.id}/revisions`, {
        instructions: revision,
        subtitles,
        background_id: background || undefined,
      });
      setSelected(j.id);
      setRevision("");
      setTab("agents");
      await refresh();
    });
  const backgroundObj = catalog.backgrounds.find(
    (b) => b.id === (job?.request.background_id || background),
  );
  const activeSpeakers = catalog.speakers.filter((s) =>
    (job?.request.speaker_ids || speakers).includes(s.id),
  );
  const running = job && ["queued", "running"].includes(job.status);
  const toggleSpeaker = (id: string) =>
    setSpeakers((old) =>
      old.includes(id)
        ? old.filter((x) => x !== id)
        : old.length < 3
          ? [...old, id]
          : old,
    );
  const chooseJob = (j: JobSummary) => {
    window.scrollTo(0, 0);
    setError("");
    setSelected(j.id);
    setJob(null);
    setBackground(j.request.background_id);
    setSubtitles(j.request.subtitles);
    setRevision("");
    setTab("video");
  };
  const newProject = () => {
    if (!loaded) return;
    window.scrollTo(0, 0);
    setSelected(null);
    setJob(null);
    setTopic("");
    setInstructions("");
    setRevision("");
    setLanguage("ru");
    setDuration(30);
    setSubtitles(true);
    setBackground(catalog.backgrounds.find(b => !b.retired)?.id || "");
    const narrator = catalog.speakers.find(s => !s.languages || s.languages.includes("ru"));
    setSpeakers(narrator ? [narrator.id] : []);
    setError("");
    setTab("video");
  };
  const uploadBackground = (file: File) =>
    run(async () => {
      const form = new FormData();
      form.append("file", file);
      form.append("kind", "background");
      form.append("name", file.name.replace(/\.[^.]+$/, ""));
      const result = await api<{ id: string }>("/uploads", {
        method: "POST",
        body: form,
      });
      await refresh();
      setBackground(result.id);
    });

  return (
    <div className="app-shell">
      <header className="topbar">
        <a
          className="brand"
          href="/"
          onClick={(e) => {
            e.preventDefault();
            newProject();
          }}
        >
          <span className="brand-icon">
            <Clapperboard size={22} />
          </span>
          <strong>
            Brainrot<span> Studio</span>
          </strong>
        </a>
        <span className="local-label">
          <i /> LOCAL WORKSPACE
        </span>
        <div className="top-actions">
          <span className="budget" title={settings ? `Расходы: ${money(settings.usage.spent)}; резерв: ${money(settings.usage.held)}` : "Расходы и резерв"}>
            {settings ? money(settings.usage.spent + settings.usage.held) : "…"} <span>/ {settings ? `$${settings.usage.limit}` : "…"}</span>
          </span>
          <button
            className="icon-button"
            title="Настройки"
            aria-label="Настройки"
            onClick={() => setModal("settings")}
          >
            <Settings2 size={19} />
          </button>
        </div>
      </header>
      <aside className="sidebar">
        <button
          className="new-button"
          disabled={!loaded}
          onClick={newProject}
        >
          <Plus size={18} /> Новый ролик
        </button>
        <div className="sidebar-label">
          ПРОЕКТЫ <span>{jobs.length}</span>
        </div>
        <nav>
          {jobs.map((j) => (
            <button
              key={j.id}
              className={"job-nav " + (selected === j.id ? "active" : "")}
              onClick={() => chooseJob(j)}
            >
              <span className={"status-dot " + j.status} />
              <span>
                <b>{j.title}</b>
                <small>
                  {new Date(j.created * 1000).toLocaleDateString("ru", {
                    day: "numeric",
                    month: "short",
                  })}{" "}
                  {new Date(j.created * 1000).toLocaleTimeString("ru", {hour: "2-digit", minute: "2-digit"})}{" "}
                  · {labels[j.status]}
                </small>
              </span>
            </button>
          ))}
        </nav>
        {loaded && !jobs.length && (
          <div className="empty-history">
            <Film size={22} />
            <span>Пока нет роликов</span>
          </div>
        )}
        <div className="sidebar-bottom">
          <span className="engine-dot" /> MiMo · Google ADK
          <small>Pro + Flash</small>
        </div>
      </aside>
      <main>
        <div className="mobile-projects">
          <select
            aria-label="Проекты"
            disabled={!loaded}
            value={selected || ""}
            onChange={(e) => {
              const next = jobs.find((j) => j.id === e.target.value);
              if (next) chooseJob(next);
              else newProject();
            }}
          >
            <option value="">Новый ролик</option>
            {jobs.map((j) => (
              <option key={j.id} value={j.id}>
                {j.title}
              </option>
            ))}
          </select>
          <button
            className="icon-button"
            aria-label="Новый ролик"
            title="Новый ролик"
            disabled={!loaded}
            onClick={newProject}
          >
            <Plus size={20} />
          </button>
        </div>
        <div className="page-heading">
          <div>
            <div className="eyebrow">
              СТУДИЯ / {job ? "ПРОЕКТ" : "СОЗДАНИЕ"}
            </div>
            <h1>
              {!loaded || (selected && job?.id !== selected)
                ? "Загрузка проекта"
                : job
                ? job.artifacts.script?.title || job.request.topic
                : "Новый ролик"}
            </h1>
          </div>
          {job && (
            <span className={"status-badge " + job.status}>
              {running && <Loader2 size={14} className="spin" />}
              {labels[job.status]}
            </span>
          )}
        </div>
        {(error || connectionError) && (
          <div className="error-banner" role="alert">
            {error || "Нет связи со студией. Переподключение…"}
            <button
              className="icon-button"
              aria-label="Закрыть ошибку"
              onClick={() => setError("")}
            >
              <X size={16} />
            </button>
          </div>
        )}
        {!settings?.has_key && settings && (
          <div className="notice">
            <span>OpenRouter не подключён</span>
            <button onClick={() => setModal("settings")}>
              Добавить ключ <ArrowRight size={14} />
            </button>
          </div>
        )}
        {!loaded || (selected && job?.id !== selected) ? (
          <div className="loading-project" role="status"><Loader2 size={24} className="spin" /></div>
        ) : !job ? (
          <div className="studio-grid">
            <section className="configuration">
              <label className="field-title" htmlFor="topic">
                <span className="step-number">01</span> Тема ролика
              </label>
              <textarea
                id="topic"
                className="topic-input"
                placeholder="Почему нейросети галлюцинируют?"
                value={topic}
                maxLength={800}
                onChange={(e) => setTopic(e.target.value)}
                rows={3}
              />
              <div className="inline-fields">
                <label>
                  Длительность
                  <select
                    aria-label="Длительность"
                    value={duration}
                    onChange={(e) => setDuration(+e.target.value)}
                  >
                    {[15, 30, 45, 60, 90].map((v) => (
                      <option key={v} value={v}>
                        {v} секунд
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  Язык
                  <select
                    aria-label="Язык"
                    value={language}
                    onChange={(e) => setLanguage(e.target.value)}
                  >
                    <option value="ru">Русский</option>
                    <option value="en">English</option>
                  </select>
                </label>
              </div>
              <div className="section-title">
                <h2>
                  <span className="step-number">02</span> Фон
                </h2>
                <button
                  className="text-button"
                  onClick={() => uploadRef.current?.click()}
                  disabled={busy}
                >
                  <Upload size={14} /> Загрузить
                </button>
                <input
                  hidden
                  ref={uploadRef}
                  type="file"
                  accept="video/mp4,video/quicktime,video/webm"
                  onChange={(e) =>
                    e.target.files?.[0] && uploadBackground(e.target.files[0])
                  }
                />
              </div>
              <div className="background-grid">
                {catalog.backgrounds.filter(b => !b.retired).map((b) => (
                  <button
                    aria-pressed={background === b.id}
                    className={
                      "background-option " +
                      (background === b.id ? "selected" : "")
                    }
                    key={b.id}
                    onClick={() => {
                      setBackground(b.id);
                      if (b.duration && duration > b.duration) {
                        setDuration([90, 60, 45, 30, 15].find(v => v <= b.duration!) || 15);
                      }
                    }}
                  >
                    <img src={b.thumbnail} alt={b.name} />
                    <span>{b.name}{b.duration ? <span className="background-duration"> · {Math.floor(b.duration)} с</span> : null}</span>
                    {background === b.id && (
                      <span className="selection-check">
                        <Check size={12} />
                      </span>
                    )}
                  </button>
                ))}
              </div>
              {!catalog.backgrounds.some(b => !b.retired) && (
                <button
                  className="upload-empty"
                  onClick={() => uploadRef.current?.click()}
                >
                  <Upload size={23} /> Загрузить геймплей
                </button>
              )}
              <div className="section-title">
                <h2>
                  <span className="step-number">03</span> Рассказчики{" "}
                  <span className="muted-count">{speakers.length}/3</span>
                </h2>
                <button
                  className="text-button"
                  onClick={() => setModal("speaker")}
                >
                  <Plus size={14} /> Добавить
                </button>
              </div>
              <div className="speaker-grid">
                {catalog.speakers.map((s) => (
                  <button
                    aria-pressed={speakers.includes(s.id)}
                    key={s.id}
                    className={
                      "speaker-option " +
                      (speakers.includes(s.id) ? "selected" : "")
                    }
                  onClick={() => toggleSpeaker(s.id)}
                  disabled={!!s.languages && !s.languages.includes(language)}
                  title={`${s.personality}${s.languages?.length === 1 ? ' · English' : ''}`}
                  >
                    <div>
                      {s.portrait ? (
                        <img src={media(s.portrait)} alt="" />
                      ) : (
                        <Users size={35} />
                      )}
                    </div>
                  <span>{s.name}{s.languages?.length === 1 ? ' · EN' : ''}</span>
                    {speakers.includes(s.id) && (
                      <span className="selection-check">
                        <Check size={12} />
                      </span>
                    )}
                  </button>
                ))}
              </div>
              <div className="voice-previews">
                {catalog.speakers.filter(s => speakers.includes(s.id) && s.voice_previews?.[language]).map(s => (
                  <label key={`${s.id}-${language}`}>
                    <span>{s.name} · {language.toUpperCase()}</span>
                    <audio controls preload="metadata" src={media(s.voice_previews![language])}
                      aria-label={`Образец голоса: ${s.name}`} />
                  </label>
                ))}
              </div>
              <div className="format-row">
                <span>
                  <Users size={16} />
                  {speakers.length > 1 ? "Диалог" : "Монолог"}
                </span>
                <label className="toggle-label">
                  <Subtitles size={17} /> Субтитры
                  <input
                    type="checkbox"
                    checked={subtitles}
                    onChange={(e) => setSubtitles(e.target.checked)}
                  />
                  <span className="switch" />
                </label>
              </div>
              <label htmlFor="instructions" className="field-title small">
                <SlidersHorizontal size={16} /> Пожелания{" "}
                <span className="optional">необязательно</span>
              </label>
              <textarea
                id="instructions"
                value={instructions}
                onChange={(e) => setInstructions(e.target.value)}
                maxLength={2500}
                placeholder="Тон, сюжет, обязательные факты…"
                rows={3}
              />
              <div className="create-row">
                <span>
                  Лимит ролика <b>{money(settings?.max_run_budget || 1.5)}</b>
                </span>
                <button
                  className="primary"
                  disabled={
                    busy ||
                    topic.trim().length < 3 ||
                    !background ||
                    !speakers.length ||
                    !settings?.has_key
                  }
                  onClick={create}
                >
                  {busy ? (
                    <Loader2 className="spin" size={17} />
                  ) : (
                    <WandSparkles size={17} />
                  )}{" "}
                  Создать ролик
                </button>
              </div>
            </section>
            <section className="preview-section">
              <div className="preview-heading">
                <h2>Предпросмотр</h2>
                <span>9:16 · 1080p</span>
              </div>
              <Preview
                background={backgroundObj}
                speakers={activeSpeakers}
                subtitles={subtitles}
                topic={topic}
                duration={duration}
              />
              <div className="preview-footer">
                <span>
                  <AudioLines size={15} />{" "}
                  {speakers.length > 1 ? "Несколько голосов" : "Один голос"}
                </span>
                <span>{duration} сек</span>
              </div>
              <div className="model-strip">
                <span>
                  Продюсер / сценарист <b>MiMo Pro</b>
                </span>
                <span>
                  Исследование / визуал <b>MiMo Flash</b>
                </span>
              </div>
            </section>
          </div>
        ) : (
          <div className="project-view">
            <div className="project-toolbar">
              <div className="tabs" role="tablist">
                {[
                  ["video", "Видео"],
                  ["script", "Сценарий"],
                  ["agents", "Агенты"],
                  ["sources", "Источники"],
                ].map(([id, label]) => (
                  <button
                    role="tab"
                    aria-selected={tab === id}
                    key={id}
                    className={tab === id ? "active" : ""}
                    onClick={() => setTab(id)}
                  >
                    {label}
                    {id === "agents" && running && <i />}
                  </button>
                ))}
              </div>
              <div className="project-actions">
                {running ? (
                  <button
                    className="text-button"
                    onClick={() =>
                      run(async () => {
                        await post(`/jobs/${job.id}/cancel`);
                        await refresh();
                      })
                    }
                  >
                    <Square size={14} /> Остановить
                  </button>
                ) : (
                  [
                    "failed",
                    "cancelled",
                    "interrupted",
                    "needs_review",
                  ].includes(job.status) && (
                    <button
                      className="text-button"
                      disabled={busy}
                      onClick={() =>
                        run(async () => {
                          await post(`/jobs/${job.id}/resume`);
                          setJob({ ...job, status: "queued" });
                          await refresh();
                        })
                      }
                    >
                      <RefreshCw size={14} /> Продолжить
                    </button>
                  )
                )}
                {job.artifacts.video && (
                  <a className="icon-button" title="Скачать субтитры SRT"
                    aria-label="Скачать субтитры SRT" download
                    href={media(job.artifacts.video.replace(/video\.mp4$/, "captions.srt"))}>
                    <Subtitles size={18} />
                  </a>
                )}
                {job.artifacts.quality && (
                  <a className="icon-button" title="Скачать отчёт проверки"
                    aria-label="Скачать отчёт проверки" href={`/api/jobs/${job.id}/quality`}>
                    <CheckCircle2 size={18} />
                  </a>
                )}
                {job.artifacts.video && (
                  <a
                    className="primary compact"
                    href={`/api/jobs/${job.id}/download`}
                  >
                    <Download size={16} /> MP4
                  </a>
                )}
              </div>
            </div>
            {job.error && <div className="error-banner">{job.error}</div>}
            <div className="job-stats">
              <span>
                <Circle size={12} />
                {stages[job.stage] || job.stage}
              </span>
              <span>{job.usage?.calls || 0} запросов</span>
              <span>
                {money(job.usage?.spent)}
                {(job.usage?.held || 0) > 0 &&
                  ` + ${money(job.usage?.held)} резерв`}
              </span>
              <span>
                {job.artifacts.technical?.duration?.toFixed(1) ||
                  job.request.duration}{" "}
                сек
              </span>
            </div>
            {tab === "video" && (
              <div className="result-grid">
                <div className="result-player">
                  {job.artifacts.video ? (
                    <video
                      controls
                      playsInline
                      preload="metadata"
                      onTimeUpdate={playbackMetrics}
                      onEnded={playbackMetrics}
                      onError={() => setError("Браузер не смог воспроизвести видео. Скачайте MP4 и проверьте файл.")}
                      src={media(job.artifacts.video)}
                      poster={
                        job.artifacts.frames?.[0] &&
                        media(job.artifacts.frames[0].path)
                      }
                    />
                  ) : (
                    <Preview
                      background={backgroundObj}
                      speakers={activeSpeakers}
                      subtitles={job.request.subtitles}
                      topic={job.request.topic}
                      duration={job.request.duration}
                      pending={!!running}
                    />
                  )}
                </div>
                <section className="result-details">
                  <h2>{running ? "Производство" : "Результат"}</h2>
                  <p>
                    {job.artifacts.script?.hook || job.request.topic}
                  </p>
                  {job.artifacts.review && (
                    <div
                      className={
                        "review " +
                        (job.artifacts.review.passed ? "passed" : "")
                      }
                    >
                      <h3>
                        {job.artifacts.review.passed ? (
                          <CheckCircle2 size={18} />
                        ) : (
                          <MessageSquare size={18} />
                        )}{" "}
                        Проверка монтажа
                      </h3>
                      <p>{job.artifacts.review.summary}</p>
                      {job.artifacts.review.issues.map((s, i) => (
                        <p key={i} className="review-issue">
                          {s}
                        </p>
                      ))}
                    </div>
                  )}
                  {job.artifacts.frames && (
                    <div className="frame-strip">
                      {job.artifacts.frames.map((f) => (
                        <img
                          key={f.path}
                          src={media(f.path)}
                          title={`${f.time} сек`}
                          alt={`Контрольный кадр ${f.time} сек`}
                        />
                      ))}
                    </div>
                  )}
                  {job.artifacts.quality && (
                    <div className="review">
                      <h3><AudioLines size={18} /> Аудио и видео</h3>
                      <p>{job.artifacts.quality.video.frames} кадров · {job.artifacts.quality.video.fps} fps · {job.artifacts.quality.video.black_frames} чёрных кадров</p>
                      <p>Повторы фона: {job.artifacts.quality.background_loops} · Максимум без движения: {job.artifacts.quality.video.longest_freeze.toFixed(2)} с</p>
                      <p>Синхронизация слов, p95: {Math.round(job.artifacts.quality.speech.word_offset_p95 * 1000)} мс · Пик: {job.artifacts.quality.speech.peak_dbfs} dBFS</p>
                      <p>Проверено титров: {job.artifacts.quality.video.caption_checks}</p>
                      {job.artifacts.quality.issues.map(issue => <p className="review-issue" key={issue}>{issue}</p>)}
                    </div>
                  )}
                  {job.artifacts.audio_review && (
                    <div className={`review ${job.artifacts.audio_review.passed ? "passed" : ""}`}>
                      <b>Проверка звучания</b>
                      <p>{job.artifacts.audio_review.summary}</p>
                      {job.artifacts.audio_review.issues.map((issue, i) => <p className="review-issue" key={i}>{issue.time.toFixed(1)} с: {issue.description}</p>)}
                    </div>
                  )}
                  {!running && job.artifacts.video && (
                    <div className="revision">
                      <h3>Правки</h3>
                      <textarea
                        value={revision}
                        onChange={(e) => setRevision(e.target.value)}
                        placeholder="Например: сделай титры белыми"
                        rows={3}
                      />
                      <div className="revision-options">
                        <select
                          aria-label="Фон для новой версии"
                          value={background}
                          onChange={(e) => setBackground(e.target.value)}
                        >
                          {catalog.backgrounds.filter(b => !b.retired).map((b) => (
                            <option value={b.id} key={b.id}>
                              {b.name}
                            </option>
                          ))}
                        </select>
                        <label>
                          <input
                            type="checkbox"
                            checked={subtitles}
                            onChange={(e) => setSubtitles(e.target.checked)}
                          />{" "}
                          Субтитры
                        </label>
                      </div>
                      <button
                        className="secondary"
                        disabled={busy || revision.trim().length < 3}
                        onClick={revise}
                      >
                        <RefreshCw size={15} /> Новая версия
                      </button>
                    </div>
                  )}
                </section>
              </div>
            )}
            {tab === "script" && (
              <div className="script-view">
                {job.artifacts.script ? (
                  <>
                    <div className="script-summary">
                      <h2>{job.artifacts.script.title}</h2>
                      <span>{job.artifacts.script.scenes.length} сцен</span>
                    </div>
                    {job.artifacts.script.scenes.map((s, i) => {
                      const speaker = catalog.speakers.find(
                        (x) => x.id === s.speaker_id,
                      );
                      return (
                        <div className="script-scene" key={s.id}>
                          <span className="scene-index">
                            {String(i + 1).padStart(2, "0")}
                          </span>
                          <div className="scene-speaker">
                            {speaker?.portrait && (
                              <img src={media(speaker.portrait)} alt="" />
                            )}
                            <b>{speaker?.name || s.speaker_id}</b>
                          </div>
                          <div>
                            <p>{s.text}</p>
                            {s.visual_caption && (
                              <small>
                                <ImagePlus size={13} />
                                {s.visual_caption}
                              </small>
                            )}
                          </div>
                        </div>
                      );
                    })}
                  </>
                ) : (
                  <Empty text="Сценарий ещё не готов" />
                )}
              </div>
            )}
            {tab === "agents" && (
              <div className="agents-view">
                <div className="agent-roster">
                  {[
                    ["producer", "MiMo Pro"],
                    ["researcher", "MiMo Flash"],
                    ["writer", "MiMo Pro"],
                    ["visual_producer", "MiMo Flash"],
                    ["editor", "MiMo Pro"],
                  ].map(([id, model]) => {
                    const last = job.events
                      ?.filter((e) => e.agent === id)
                      .at(-1);
                    return (
                      <div
                        key={id}
                        className={"agent-item " + (last ? "engaged" : "")}
                      >
                        <div className="agent-symbol">
                          {id === "producer" ? (
                            <Clapperboard size={19} />
                          ) : id === "writer" ? (
                            <MessageSquare size={19} />
                          ) : (
                            <Circle size={19} />
                          )}
                        </div>
                        <b>{agents[id]}</b>
                        <small>{model}</small>
                        <span>{last ? "Вызван" : "Ожидает"}</span>
                      </div>
                    );
                  })}
                </div>
                <div className="event-log">
                  <div className="log-heading">
                    <h2>Журнал выполнения</h2>
                    {running && (
                      <span>
                        <i className="live-dot" /> LIVE
                      </span>
                    )}
                  </div>
                  {job.events
                    ?.filter(
                      (e) => !["model_start", "model_end"].includes(e.kind),
                    )
                    .map((e) => (
                      <EventRow key={e.id} event={e} />
                    ))}
                  {!job.events?.length && <Empty text="Ожидание запуска" />}
                  <div ref={bottomRef} />
                </div>
              </div>
            )}
            {tab === "sources" && (
              <div className="sources-view">
                <h2>Материалы исследования</h2>
                {job.artifacts.research?.summary && (
                  <p>{job.artifacts.research.summary}</p>
                )}
                {job.artifacts.research?.sources.map((s, i) => (
                  <a
                    key={s.url}
                    className="source-row"
                    href={s.url}
                    target="_blank"
                    rel="noreferrer"
                  >
                    <span>{i + 1}</span>
                    <div>
                      <b>{s.title}</b>
                      <small>{s.url}</small>
                    </div>
                    <ExternalLink size={16} />
                  </a>
                ))}
                <h2>Визуальные материалы</h2>
                {Object.entries(job.artifacts.visuals || {})
                  .filter(([, v]) => v)
                  .map(([id, v]) => (
                    <a
                      className="source-row"
                      key={id}
                      href={v!.source}
                      target="_blank"
                      rel="noreferrer"
                    >
                      <img src={media(v!.path)} alt="" />
                      <div>
                        <b>{v!.title}</b>
                        <small>{[v!.artist, v!.license].filter(Boolean).join(" · ")}</small>
                      </div>
                      <ExternalLink size={16} />
                    </a>
                  ))}
                {backgroundObj && (
                  <div className="asset-credit">
                    {backgroundObj.source.startsWith("https://") ? <a href={backgroundObj.source} target="_blank" rel="noreferrer">{backgroundObj.name} <ExternalLink size={14} /></a> : <b>{backgroundObj.name}</b>}
                    <p>{backgroundObj.credit || backgroundObj.source}</p>
                    <small>{backgroundObj.license}</small>
                  </div>
                )}
                <h2>Персонажи</h2>
                {catalog.speakers.filter((s) => job.request.speaker_ids.includes(s.id)).map((s) => (
                  <div className="asset-credit" key={s.id}>
                    {s.source?.startsWith("https://") ? <a href={s.source} target="_blank" rel="noreferrer">{s.name} <ExternalLink size={14} /></a> : <b>{s.name}</b>}
                    <small>{s.voice_label || s.voice}</small>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </main>
      {modal && (
        <div className="modal-backdrop" onClick={() => setModal(null)}>
          <section
            className="modal"
            role="dialog"
            aria-modal="true"
            aria-label={modal === "settings" ? "Настройки" : "Новый рассказчик"}
            onClick={(e) => e.stopPropagation()}
          >
            <div className="modal-header">
              <h2>{modal === "settings" ? "Настройки" : "Новый рассказчик"}</h2>
              <button
                className="icon-button"
                aria-label="Закрыть"
                onClick={() => setModal(null)}
              >
                <X size={20} />
              </button>
            </div>
            {modal === "settings" ? (
              <SettingsForm
                settings={settings}
                done={async () => {
                  await refresh();
                  setModal(null);
                }}
              />
            ) : (
              <SpeakerForm
                done={async () => {
                  await refresh();
                  setModal(null);
                }}
              />
            )}
          </section>
        </div>
      )}
    </div>
  );
}

function Preview({
  background,
  speakers,
  subtitles,
  topic,
  duration,
  pending = false,
}: {
  background?: Background;
  speakers: Speaker[];
  subtitles: boolean;
  topic: string;
  duration: number;
  pending?: boolean;
}) {
  return (
    <div className="phone-preview">
      {background ? (
        <video
          key={background.path}
          src={media(background.path)}
          autoPlay
          loop
          muted
          playsInline
          poster={background.thumbnail}
        />
      ) : (
        <div className="preview-placeholder">
          <Film size={38} />
        </div>
      )}
      <div className="preview-shade" />
      <span className="preview-tag">{pending ? "В работе" : "ПРЕВЬЮ"}</span>
      {subtitles && (
        <div className="sample-caption">
          {topic ? topic.split(" ").slice(0, 4).join(" ") : "ЭТОТ ФАКТ"}{" "}
          <em>{topic ? "" : "ТЕБЯ УДИВИТ"}</em>
        </div>
      )}
      <div
        className={
          "preview-characters " + (speakers.length > 1 ? "dialogue" : "")
        }
      >
        {speakers.map((s) =>
          s.portrait ? (
            <img key={s.id} src={media(s.portrait)} alt={s.name} />
          ) : null,
        )}
      </div>
      {pending && (
        <div className="pending-overlay">
          <Loader2 className="spin" size={25} />
        </div>
      )}
      <div className="preview-bottom">
        <span>
          {speakers.map((s) => s.name).join(" × ") || "Без персонажа"}
        </span>
        <span>
          {pending
            ? "--:--"
            : `${String(Math.floor(duration / 60)).padStart(2, "0")}:${String(duration % 60).padStart(2, "0")}`}
        </span>
      </div>
    </div>
  );
}
function Empty({ text }: { text: string }) {
  return (
    <div className="empty-state">
      <Clapperboard size={25} />
      <p>{text}</p>
    </div>
  );
}
function EventRow({ event: e }: { event: JobEvent }) {
  const d = e.detail;
  const text =
    typeof d.text === "string"
      ? d.text
      : typeof d.summary === "string"
        ? d.summary
        : typeof d.query === "string"
          ? `Поиск: ${d.query}`
          : typeof d.tool === "string"
            ? d.tool
            : typeof d.reason === "string"
              ? d.reason
              : typeof d.name === "string"
                ? `Сохранено: ${d.name}`
                : e.kind === "scene_ready"
                  ? `Готово: ${d.scene_id}, ${Number(d.duration).toFixed(1)} сек`
                  : e.kind === "cache_hit"
                    ? `Повторное использование ${d.scene_id}`
                    : e.kind === "render"
                      ? `Рендер, попытка ${d.attempt}`
                      : e.kind === "started"
                        ? "Начало работы"
                        : e.kind;
  return (
    <div className="event-row">
      <time>
        {new Date(e.time * 1000).toLocaleTimeString("ru", {
          hour: "2-digit",
          minute: "2-digit",
          second: "2-digit",
        })}
      </time>
      <span className="event-agent">{agents[e.agent] || e.agent}</span>
      <p>{text}</p>
    </div>
  );
}
function SettingsForm({
  settings,
  done,
}: {
  settings: Settings | null;
  done: () => Promise<void>;
}) {
  const [key, setKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  return (
    <form
      onSubmit={async (e) => {
        e.preventDefault();
        setBusy(true);
        try {
          if (key) await post("/settings/key", { key });
          setKey("");
          await done();
        } catch (e) {
          setError((e as Error).message);
        } finally {
          setBusy(false);
        }
      }}
    >
      <label>
        OpenRouter API key
        <input
          type="password"
          name="key"
          autoComplete="off"
          value={key}
          onChange={(e) => setKey(e.target.value)}
          placeholder={settings?.has_key ? "Ключ подключён" : "sk-or-v1-…"}
        />
      </label>
      <div className="settings-models">
        {Object.entries(settings?.models || {}).map(([role, model]) => (
          <div key={role}>
            <span>{agents[role] || role}</span>
            <code>{model}</code>
          </div>
        ))}
      </div>
      <div className="settings-budget">
        <span>Общий лимит</span>
        <b>$10.00</b>
        <span>Подтверждено</span>
        <b>{money(settings?.usage.spent)}</b>
        <span>В резерве</span>
        <b>{money(settings?.usage.held)}</b>
      </div>
      {error && <p className="form-error">{error}</p>}
      <button className="primary" disabled={busy}>
        {busy ? <Loader2 size={16} className="spin" /> : <Check size={16} />}{" "}
        Сохранить
      </button>
    </form>
  );
}
function SpeakerForm({ done }: { done: () => Promise<void> }) {
  const [name, setName] = useState("");
  const [personality, setPersonality] = useState("");
  const [voice, setVoice] = useState("Puck");
  const [portrait, setPortrait] = useState<File | null>(null);
  const [sample, setSample] = useState<File | null>(null);
  const [referenceText, setReferenceText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const upload = async (file: File | null, kind: string) => {
    if (!file) return "";
    const f = new FormData();
    f.append("file", file);
    f.append("kind", kind);
    return (
      await api<{ path: string }>("/uploads", { method: "POST", body: f })
    ).path;
  };
  return (
    <form
      onSubmit={async (e) => {
        e.preventDefault();
        setBusy(true);
        try {
          const portraitPath = await upload(portrait, "portrait");
          const voicePath = await upload(sample, "voice");
          await post("/speakers", {
            name,
            personality,
            portrait: portraitPath,
            voice_reference: voicePath,
            reference_text: referenceText,
            voice,
          });
          await done();
        } catch (e) {
          setError((e as Error).message);
        } finally {
          setBusy(false);
        }
      }}
    >
      <label>
        Имя
        <input
          required
          maxLength={60}
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
      </label>
      <label>
        Характер
        <textarea
          rows={2}
          value={personality}
          onChange={(e) => setPersonality(e.target.value)}
        />
      </label>
      <label>
        Персонаж · PNG / JPG
        <input
          type="file"
          accept="image/png,image/jpeg,image/webp"
          onChange={(e) => setPortrait(e.target.files?.[0] || null)}
        />
      </label>
      <label>
        Голос
        <select value={voice} onChange={(e) => setVoice(e.target.value)}>
          {["Puck", "Charon", "Kore", "Fenrir", "Leda", "Aoede"].map((v) => (
            <option key={v}>{v}</option>
          ))}
        </select>
      </label>
      <label>
        Образец голоса · 3–45 секунд
        <input
          type="file"
          accept="audio/*"
          onChange={(e) => setSample(e.target.files?.[0] || null)}
        />
      </label>
      {sample && (
        <label>
          Текст образца
          <textarea
            rows={2}
            value={referenceText}
            onChange={(e) => setReferenceText(e.target.value)}
          />
        </label>
      )}
      {error && <p className="form-error">{error}</p>}
      <button className="primary" disabled={busy}>
        {busy ? <Loader2 size={16} className="spin" /> : <Plus size={16} />}{" "}
        Добавить
      </button>
    </form>
  );
}

createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
