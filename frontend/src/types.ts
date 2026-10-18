export type Background = {
  retired?: boolean;
  duration?: number;
  id: string;
  name: string;
  path: string;
  thumbnail: string;
  source: string;
  credit?: string;
  license?: string;
};
export type Speaker = {
  id: string;
  name: string;
  personality: string;
  portrait: string;
  voice: string;
  voice_label?: string;
  languages?: string[];
  voice_previews?: Record<string, string>;
  source?: string;
};
export type Catalog = { backgrounds: Background[]; speakers: Speaker[] };
export type Scene = {
  id: string;
  speaker_id: string;
  text: string;
  visual_query: string;
  visual_caption: string;
};
export type JobEvent = {
  id: number;
  time: number;
  agent: string;
  kind: string;
  detail: Record<string, unknown>;
};
export type Usage = {
  spent: number;
  held: number;
  tokens: number;
  calls: number;
  limit: number;
};
export type Job = {
  id: string;
  created: number;
  updated: number;
  status: string;
  stage: string;
  error?: string;
  parent_id?: string;
  request: {
    topic: string;
    background_id: string;
    speaker_ids: string[];
    subtitles: boolean;
    instructions: string;
    language: string;
    duration: number;
    budget: number;
  };
  artifacts: {
    video?: string;
    script?: { title: string; hook: string; scenes: Scene[] };
    research?: {
      summary: string;
      facts: string[];
      sources: { title: string; url: string; note: string }[];
    };
    frames?: { path: string; time: number }[];
    review?: { passed: boolean; summary: string; issues: string[] };
    audio_review?: { passed: boolean; summary: string; issues: { time: number; description: string }[] };
    technical?: { duration: number; width: number; height: number };
    quality?: {
      passed: boolean;
      issues: string[];
      background_loops: number;
      video: { frames: number; fps: number; black_frames: number; longest_freeze: number; caption_checks: number };
      speech: { word_offset_p95: number; peak_dbfs: number; similarity: number };
    };
    visuals?: Record<
      string,
      { path: string; source: string; license: string; title: string; artist?: string } | null
    >;
    final?: string;
    audio_duration?: number;
  };
  events?: JobEvent[];
  usage?: Usage;
};
export type Settings = {
  has_key: boolean;
  models: Record<string, string>;
  usage: Usage;
  max_run_budget: number;
};
export type JobSummary = Omit<Job, "artifacts" | "events" | "usage"> & { title: string };
