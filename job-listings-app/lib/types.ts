// Mirrors JobOut from job-search-automation's API (see ../job-search-automation/src/job_search/api.py)
interface Job {
  id: number;
  profile: string;
  source: string;
  title: string;
  company: string;
  url: string;
  description: string;
  tags: string[];
  salary: string | null;
  location: string;
  postedDate: string;
  fitScore: number | null;
  incomeScore: number | null;
  score: number | null;
  reasoning: string | null;
  outreachDraft: string | null;
}

// Mirrors AppConfig.to_dict() from job-search-automation (see
// ../job-search-automation/src/job_search/config.py). System-wide settings
// only — candidate data now lives in ProfileSettings, one per person.
interface AppSettings {
  ollama: {
    url: string;
    model: string;
    cv_model: string;
    timeout: number;
  };
  providers: {
    remoteok: boolean;
    remotive: boolean;
    weworkremotely: boolean;
    python_jobs: boolean;
    vuejobs: boolean;
    hackernews: boolean;
    arbeitnow: boolean;
  };
  weworkremotely: {
    categories: string[];
  };
  scoring: {
    min_score_to_keep: number;
    fit_weight: number;
    income_weight: number;
  };
  output_base_dir: string;
  database: {
    url: string;
  };
}

// Mirrors ProfileConfig.to_dict() from job-search-automation. One entry per
// person/role being searched for (profiles/<name>.yaml).
interface ProfileSettings {
  name: string;
  profile: string;
  keywords: {
    target: string[];
    exclude: string[];
    seniority: string[];
    ai: string[];
    tech: string[];
  };
  output: {
    csv_filename: string;
    md_filename: string;
  };
  telegram: {
    enabled: boolean;
    chat_id: string | null;
  };
}

// Minimal shape of the errors Nuxt's $fetch (ofetch, under the hood) throws
// that we actually read from. Defined locally instead of importing ofetch's
// own FetchError type, since ofetch isn't a direct dependency here.
interface ApiFetchError {
  data?: { statusMessage?: string };
  response?: { status?: number; _data?: { detail?: string } };
}

export type { ApiFetchError, AppSettings, Job, ProfileSettings };
