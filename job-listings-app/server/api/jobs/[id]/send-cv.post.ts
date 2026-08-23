// Proxies to job-search-automation's POST /jobs/{id}/send-cv.
//
// Generates a CV tailored to this specific job posting (via the same
// Ollama model used for scoring) and sends it as a PDF to the owning
// profile's Telegram chat — same routing rule as send-telegram.post.ts:
// the caller never supplies a chat_id, the backend always resolves it from
// the job's own profile.
import type { ApiFetchError } from "@/lib/types";

export default defineEventHandler(async (event) => {
  const { backendUrl } = useRuntimeConfig();
  const id = getRouterParam(event, "id");

  try {
    return await $fetch(`${backendUrl}/jobs/${id}/send-cv`, {
      method: "POST",
    });
  } catch (err) {
    const error = err as ApiFetchError;
    const status = error?.response?.status;

    // 400 covers both "no resume data configured for this profile" and
    // the usual Telegram-not-configured cases; 404 covers a bad job id.
    // Either way surface the backend's own reason instead of a generic one.
    if (status === 400 || status === 404) {
      throw createError({
        statusCode: status,
        statusMessage:
          error?.response?._data?.detail ??
          "Could not generate or send the tailored CV",
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
