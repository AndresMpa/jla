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
  // Latest step reported over WS /ws/run/status (e.g. "[alice] Scoring
  // 3/12: Senior AI Engineer @ Acme") - the UI can show this next to the
  // "Searching…" button instead of a plain spinner with no indication of
  // what's actually happening.
  const runProgress = ref("");

  // A full scan (several job providers + an Ollama scoring pass per
  // listing) can legitimately take a while, but it shouldn't take forever -
  // this bounds it so a stuck backend run can't leave the UI "running"
  // indefinitely if the socket never gets a terminal message.
  const RUN_MAX_MS = 20 * 60 * 1000;

  async function startSearch() {
    running.value = true;
    runError.value = "";
    runProgress.value = "";
    try {
      await $fetch("/api/run", {
        method: "POST",
        query: profile.value ? { profile: profile.value } : {},
      });
      // POST /run only confirms the pipeline *started* - it runs in the
      // background and can take minutes. WS /ws/run/status streams every
      // step (fetching, per-profile scoring progress, report writes) and
      // resolves once the backend publishes "done" or "error".
      const timeout = new Promise<never>((_, reject) =>
        setTimeout(
          () => reject(new Error("The search is taking too long — check the backend logs.")),
          RUN_MAX_MS,
        ),
      );
      const result = await Promise.race([
        streamProgress("/ws/run/status", (message) => {
          runProgress.value = message.detail;
        }),
        timeout,
      ]);
      if (result.status === "error") {
        runError.value = result.detail || "The search failed. Please try again.";
      }
      await refresh();
    } catch (err) {
      runError.value =
        err instanceof Error ? err.message : "Could not start the search. Please try again.";
    } finally {
      running.value = false;
      runProgress.value = "";
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
    runProgress,
    startSearch,
  };
}
