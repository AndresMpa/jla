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

  const RUN_POLL_INTERVAL_MS = 3000;
  // A full scan (several job providers + an Ollama scoring pass per
  // listing) can legitimately take a while, but it shouldn't take forever -
  // this bounds it so a stuck backend run can't leave the UI polling (and
  // "running") indefinitely.
  const RUN_POLL_MAX_MS = 20 * 60 * 1000;

  let runPollTimer: ReturnType<typeof setInterval> | null = null;

  function stopRunPoll() {
    if (runPollTimer !== null) {
      clearInterval(runPollTimer);
      runPollTimer = null;
    }
  }

  // Cleared on unmount so navigating away mid-search can't leave an
  // orphaned timer firing requests forever in the background.
  onUnmounted(stopRunPoll);

  // POST /run only confirms the pipeline *started* - it runs in the
  // background on the server and can take minutes (several job providers
  // + an Ollama scoring pass per listing). Without this poll, `running`
  // would flip back to false right after the POST resolves, so the button
  // re-enables and looks idle while the backend is still working.
  function pollUntilDone(): Promise<void> {
    return new Promise((resolve) => {
      const startedAt = Date.now();
      runPollTimer = setInterval(async () => {
        if (Date.now() - startedAt > RUN_POLL_MAX_MS) {
          stopRunPoll();
          runError.value =
            "The search is taking too long — check the backend logs.";
          resolve();
          return;
        }
        try {
          const { running: stillRunning } = await $fetch<{ running: boolean }>(
            "/api/run/status",
          );
          if (!stillRunning) {
            stopRunPoll();
            resolve();
          }
        } catch {
          // Transient network hiccup while polling - keep trying rather
          // than abandoning the poll and leaving the UI stuck "running"
          // (the RUN_POLL_MAX_MS ceiling above still bounds the total wait).
        }
      }, RUN_POLL_INTERVAL_MS);
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
