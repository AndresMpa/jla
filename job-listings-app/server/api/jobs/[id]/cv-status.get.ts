// Proxies to job-search-automation's GET /jobs/{id}/cv-status. POST
// /jobs/{id}/send-cv only kicks off tailoring + PDF render + Telegram send
// in the background and returns almost instantly - this is how the
// frontend finds out when it's actually done (can take minutes: one Ollama
// completion + a PDF render + a Telegram upload).
import type { ApiFetchError } from "@/lib/types";

export default defineEventHandler(async (event) => {
  const { backendUrl } = useRuntimeConfig();
  const id = getRouterParam(event, "id");

  try {
    return await $fetch<{ status: string; detail: string }>(
      `${backendUrl}/jobs/${id}/cv-status`,
    );
  } catch (err) {
    const error = err as ApiFetchError;
    const status = error?.response?.status;
    if (status === 404) {
      throw createError({
        statusCode: 404,
        statusMessage: "No CV generation in progress or completed for this job",
        cause: err,
      });
    }
    throw createError({
      statusCode: 502,
      statusMessage: "Could not reach the job-search-automation backend",
      cause: err,
    });
  }
});
