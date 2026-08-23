// Proxies to job-search-automation's GET /run/status. POST /run kicks off
// the pipeline as a background task and returns almost instantly, so this
// is how the frontend knows the search is actually still running (can take
// minutes: multiple job providers + an Ollama scoring pass per listing).
export default defineEventHandler(async (_event) => {
  const { backendUrl } = useRuntimeConfig();
  try {
    return await $fetch<{ running: boolean }>(`${backendUrl}/run/status`);
  } catch (err) {
    throw createError({
      statusCode: 502,
      statusMessage: "Could not reach the job-search-automation backend",
      cause: err,
    });
  }
});
