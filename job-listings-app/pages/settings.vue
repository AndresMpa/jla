<script setup lang="ts">
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { ApiFetchError, AppSettings, ProfileSettings } from "@/lib/types";

definePageMeta({
  layout: "simple",
});

const { data: settings, refresh } =
  await useFetch<AppSettings>("/api/settings");
// Candidate profiles (who's being searched for) now live in their own
// profiles/<name>.yaml files, managed via the job-search-automation API
// directly (GET/PUT/DELETE /profiles/{name}). This page just lists them
// read-only for now — a full editor here is a natural next step.
const { data: profiles } = await useFetch<ProfileSettings[]>("/api/profiles");

const saving = ref(false);
const saveError = ref("");
const saveOk = ref(false);

// Keyword/list fields are edited as one-item-per-line textareas.
const toLines = (arr: string[] | undefined) => (arr ?? []).join("\n");
const fromLines = (text: string) =>
  text
    .split("\n")
    .map((s) => s.trim())
    .filter(Boolean);

const form = reactive({
  ollamaUrl: "",
  ollamaModel: "",
  ollamaCvModel: "",
  ollamaTimeout: 300,
  providers: {
    remoteok: true,
    remotive: true,
    weworkremotely: true,
    python_jobs: true,
    vuejobs: true,
    hackernews: true,
    arbeitnow: true,
  },
  wwrCategories: "",
  minScoreToKeep: 6,
  fitWeight: 0.4,
  incomeWeight: 0.6,
  outputBaseDir: "profiles/output",
  databaseUrl: "",
});

function loadForm(s: AppSettings) {
  form.ollamaUrl = s.ollama.url;
  form.ollamaModel = s.ollama.model;
  form.ollamaCvModel = s.ollama.cv_model;
  form.ollamaTimeout = s.ollama.timeout;
  form.providers = { ...s.providers };
  form.wwrCategories = toLines(s.weworkremotely.categories);
  form.minScoreToKeep = s.scoring.min_score_to_keep;
  form.fitWeight = s.scoring.fit_weight;
  form.incomeWeight = s.scoring.income_weight;
  form.outputBaseDir = s.output_base_dir;
  form.databaseUrl = s.database.url;
}

watch(settings, (s) => s && loadForm(s), { immediate: true });

async function save() {
  saving.value = true;
  saveError.value = "";
  saveOk.value = false;

  const payload: AppSettings = {
    ollama: {
      url: form.ollamaUrl,
      model: form.ollamaModel,
      cv_model: form.ollamaCvModel,
      timeout: form.ollamaTimeout,
    },
    providers: { ...form.providers },
    weworkremotely: { categories: fromLines(form.wwrCategories) },
    scoring: {
      min_score_to_keep: form.minScoreToKeep,
      fit_weight: form.fitWeight,
      income_weight: form.incomeWeight,
    },
    output_base_dir: form.outputBaseDir,
    database: { url: form.databaseUrl },
  };

  try {
    await $fetch("/api/settings", { method: "PUT", body: payload });
    saveOk.value = true;
    await refresh();
  } catch (err) {
    const error = err as ApiFetchError;
    saveError.value = error?.data?.statusMessage || "Could not save settings";
  } finally {
    saving.value = false;
  }
}

const providerLabels: Record<keyof AppSettings["providers"], string> = {
  remoteok: "RemoteOK",
  remotive: "Remotive",
  weworkremotely: "We Work Remotely",
  python_jobs: "Python.org Jobs",
  vuejobs: "VueJobs",
  hackernews: "Hacker News",
  arbeitnow: "Arbeitnow",
};
</script>

<template>
  <div class="relative pb-20 max-w-3xl mx-auto px-4">
    <h1 class="text-3xl font-bold text-primary-foreground mb-8">Settings</h1>

    <div v-if="!settings" class="text-primary-foreground">Loading configuration…</div>

    <form v-else class="space-y-6" @submit.prevent="save">
      <Card class="bg-primary-foreground">
        <CardHeader><CardTitle>Profiles</CardTitle></CardHeader>
        <CardContent>
          <p class="text-sm text-muted-foreground mb-3">
            Each candidate profile (their bio and keyword lists) lives in its own
            <code>profiles/&lt;name&gt;.yaml</code> file, so several people can search for jobs
            at once. Manage them via the job-search-automation API
            (<code>GET/PUT/DELETE /profiles/{name}</code>) — this page only lists them.
          </p>
          <ul v-if="profiles && profiles.length" class="space-y-2">
            <li
              v-for="p in profiles"
              :key="p.name"
              class="rounded border border-gray-200 p-3 text-sm"
            >
              <span class="font-semibold">{{ p.name }}</span>
              <span class="text-muted-foreground"> — {{ p.keywords.target.length }} target keywords</span>
            </li>
          </ul>
          <p v-else class="text-sm text-muted-foreground">
            No profiles yet — copy <code>profiles/profile.yaml.example</code> to
            <code>profiles/&lt;name&gt;.yaml</code> to add one.
          </p>
        </CardContent>
      </Card>

      <Card class="bg-primary-foreground">
        <CardHeader><CardTitle>Ollama</CardTitle></CardHeader>
        <CardContent class="grid grid-cols-1 md:grid-cols-3 gap-4">
          <label class="flex flex-col gap-1 text-sm">
            URL (empty = auto-detect)
            <input v-model="form.ollamaUrl" class="rounded bg-primary-foreground border border-gray-300 p-2" />
          </label>
          <label class="flex flex-col gap-1 text-sm">
            Model
            <input v-model="form.ollamaModel" class="rounded bg-primary-foreground border border-gray-300 p-2" />
          </label>
          <label class="flex flex-col gap-1 text-sm">
            CV model (empty = use Model above)
            <input v-model="form.ollamaCvModel" class="rounded bg-primary-foreground border border-gray-300 p-2" />
          </label>
          <label class="flex flex-col gap-1 text-sm">
            Timeout (seconds)
            <input v-model.number="form.ollamaTimeout" type="number" class="rounded bg-primary-foreground border border-gray-300 p-2" />
          </label>
        </CardContent>
      </Card>

      <Card class="bg-primary-foreground">
        <CardHeader><CardTitle>Providers</CardTitle></CardHeader>
        <CardContent class="grid grid-cols-2 md:grid-cols-3 gap-3">
          <label
            v-for="(label, key) in providerLabels"
            :key="key"
            class="flex items-center gap-2 text-sm"
          >
            <input class="bg-primary-foreground" type="checkbox" v-model="form.providers[key]" />
            {{ label }}
          </label>
        </CardContent>
      </Card>

      <Card class="bg-primary-foreground">
        <CardHeader><CardTitle>We Work Remotely categories (one per line)</CardTitle></CardHeader>
        <CardContent>
          <textarea v-model="form.wwrCategories" rows="4" class="w-full rounded bg-primary-foreground border border-gray-300 p-2 font-mono text-sm" />
        </CardContent>
      </Card>

      <Card class="bg-primary-foreground">
        <CardHeader><CardTitle>Scoring</CardTitle></CardHeader>
        <CardContent class="grid grid-cols-1 md:grid-cols-3 gap-4">
          <label class="flex flex-col gap-1 text-sm">
            Minimum score to keep (0-10)
            <input v-model.number="form.minScoreToKeep" type="number" min="0" max="10" class="rounded bg-primary-foreground border border-gray-300 p-2" />
          </label>
          <label class="flex flex-col gap-1 text-sm">
            Fit weight
            <input v-model.number="form.fitWeight" type="number" step="0.1" min="0" max="1" class="rounded bg-primary-foreground border border-gray-300 p-2" />
          </label>
          <label class="flex flex-col gap-1 text-sm">
            Income weight
            <input v-model.number="form.incomeWeight" type="number" step="0.1" min="0" max="1" class="rounded bg-primary-foreground border border-gray-300 p-2" />
          </label>
        </CardContent>
      </Card>

      <Card class="bg-primary-foreground">
        <CardHeader><CardTitle>Output & database</CardTitle></CardHeader>
        <CardContent class="grid grid-cols-1 md:grid-cols-2 gap-4">
          <label class="flex flex-col gap-1 text-sm">
            Output base directory (each profile gets its own subfolder)
            <input v-model="form.outputBaseDir" class="rounded bg-primary-foreground border border-gray-300 p-2" />
          </label>
          <label class="flex flex-col gap-1 text-sm">
            Postgres URL (empty = DB disabled)
            <input v-model="form.databaseUrl" class="rounded bg-primary-foreground border border-gray-300 p-2 font-mono text-xs" />
          </label>
        </CardContent>
      </Card>

      <div class="flex items-center gap-4">
        <Button type="submit" :disabled="saving">
          {{ saving ? "Saving…" : "Save settings" }}
        </Button>
        <span v-if="saveOk" class="text-green-600 text-sm">Saved.</span>
        <span v-if="saveError" class="text-red-600 text-sm">{{ saveError }}</span>
      </div>
    </form>
  </div>
</template>
