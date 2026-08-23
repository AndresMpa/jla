import type { Job } from "@/lib/types";

export function useJobsFeed(profile: Ref<string> | ComputedRef<string>) {
  const { data, error, refresh } = useFetch<Job[]>("/api/jobs", {
    query: computed(() => (profile.value ? { profile: profile.value } : {})),
  });

  const schemaMissing = computed(() => error.value?.statusCode === 503);

  const initializing = ref(false);
  const initError = ref("");
  async function initDatabase() {
    initializing.value = true;
    initError.value = "";
    try {
      await $fetch("/api/init-db", { method: "POST" });
      await refresh();
    } catch {
      initError.value = "Could not initialize the database. Please try again.";
    } finally {
      initializing.value = false;
    }
  }

  const running = ref(false);
  const runError = ref("");

  // POST /run only confirms the pipeline *started* - it runs in the
  // background on the server and can take minutes (several job providers
  // + an Ollama scoring pass per listing). Without this poll, `running`
  // would flip back to false right after the POST resolves, so the button
  // re-enables and looks idle while the backend is still working.
  function pollUntilDone(): Promise<void> {
    return new Promise((resolve) => {
      const interval = setInterval(async () => {
        try {
          const { running: stillRunning } = await $fetch<{ running: boolean }>(
            "/api/run/status",
          );
          if (!stillRunning) {
            clearInterval(interval);
            resolve();
          }
        } catch {
          // Transient network hiccup while polling - keep trying rather
          // than abandoning the poll and leaving the UI stuck "running".
        }
      }, 3000);
    });
  }

  async function startSearch() {
    running.value = true;
    runError.value = "";
    try {
      await $fetch("/api/run", {
        method: "POST",
        query: profile.value ? { profile: profile.value } : {},
      });
      await pollUntilDone();
      await refresh();
    } catch {
      runError.value = "Could not start the search. Please try again.";
    } finally {
      running.value = false;
    }
  }

  return {
    data,
    error,
    refresh,
    schemaMissing,
    initializing,
    initError,
    initDatabase,
    running,
    runError,
    startSearch,
  };
}
