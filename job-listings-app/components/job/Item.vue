<script setup lang="ts">
import { FileText, Send } from "lucide-vue-next";
import { computed, ref } from "vue";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import type { ApiFetchError, Job } from "@/lib/types";

const props = defineProps<{
  job: Job;
  tags?: string[];
}>();

defineEmits<{ addTag: [tag: string] }>();

// Sending an offer to Telegram: this button is the only place in the UI that
// triggers it, and the backend routes it to whichever profile owns the job
// (job.profile) — never a chat picked here — so each profile's owner only
// ever gets their own offers.
const sendState = ref<"idle" | "sending" | "sent" | "error">("idle");
const sendErrorMessage = ref("");

async function sendToTelegram() {
  if (sendState.value === "sending") return;
  sendState.value = "sending";
  sendErrorMessage.value = "";
  try {
    await $fetch(`/api/jobs/${props.job.id}/send-telegram`, { method: "POST" });
    sendState.value = "sent";
  } catch (err) {
    const error = err as ApiFetchError;
    sendErrorMessage.value =
      error?.data?.statusMessage ?? "Could not send this offer to Telegram";
    sendState.value = "error";
  }
}

// "Send tailored CV": generates an ATS-formatted resume tailored to THIS
// job posting (LLM rewrites summary/skill order/bullet phrasing only — it
// never invents employers, dates, or degrees, see cv.py) and delivers it
// as a PDF to the profile's Telegram chat. Can take a while (one LLM
// completion), so this has its own independent loading state from the
// "Send to Telegram" button above.
const cvState = ref<"idle" | "sending" | "sent" | "error">("idle");
const cvErrorMessage = ref("");

async function sendTailoredCv() {
  if (cvState.value === "sending") return;
  cvState.value = "sending";
  cvErrorMessage.value = "";
  try {
    await $fetch(`/api/jobs/${props.job.id}/send-cv`, { method: "POST" });
    cvState.value = "sent";
  } catch (err) {
    const error = err as ApiFetchError;
    cvErrorMessage.value =
      error?.data?.statusMessage ?? "Could not generate or send the tailored CV";
    cvState.value = "error";
  }
}

const initials = computed(
  () =>
    props.job.company
      .split(/\s+/)
      .filter(Boolean)
      .slice(0, 2)
      .map((w) => w[0]?.toUpperCase())
      .join("") || "?",
);

const scoreTier = computed(() => {
  const income = props.job.incomeScore ?? 0;
  if (income >= 8) return "🟢🟢🟢";
  if (income >= 6) return "🟢🟢";
  return "🟢";
});

const chips = computed(() => [props.job.source, ...props.job.tags]);

const showOutreach = ref(false);
</script>

<template>
  <li
    class="mx-auto my-12 md:my-0 w-11/12 md:w-9/12 rounded shadow-xl bg-primary-foreground"
  >
    <Card
      class="bg-primary-foreground py-3 border-l-[5px] border-transparent hover:border-primary transition-colors duration-300"
    >
      <CardContent
        class="flex flex-col md:flex-row my-auto items-start md:items-center"
      >
        <div class="relative">
          <figure class="bottom-0 -right-7 absolute md:static">
            <div
              class="mx-8 md:mx-5 flex h-12 w-12 items-center justify-center rounded-full bg-primary text-primary-foreground font-bold"
            >
              {{ initials }}
            </div>
          </figure>
        </div>

        <div class="flex flex-col">
          <div class="flex flex-row items-center flex-wrap">
            <h3 class="text-lg text-primary font-bold">
              {{ job.company || "Unknown company" }}
            </h3>

            <div class="flex items-center justify-center mx-5">
              <Badge v-if="job.score !== null" class="uppercase bg-primary mx-2">
                {{ scoreTier }} {{ job.score }}/10
              </Badge>
            </div>
          </div>

          <a :href="job.url" target="_blank" rel="noopener noreferrer">
            <h2 class="mb-2 mt-2 text-2xl font-bold hover:text-primary">
              {{ job.title }}
            </h2>
          </a>

          <p class="text-lg font-extralight">
            <span v-if="job.salary">{{ job.salary }}</span>
            <span v-if="job.salary" class="mx-2">-</span>
            <span>{{ job.location || "Remote" }}</span>
          </p>

          <p v-if="job.reasoning" class="text-sm mt-2 max-w-2xl">
            {{ job.reasoning }}
          </p>

          <button
            v-if="job.outreachDraft"
            type="button"
            class="text-primary text-sm mt-2 text-left underline w-fit"
            @click="showOutreach = !showOutreach"
          >
            {{ showOutreach ? "Hide" : "Show" }} outreach draft
          </button>
          <p
            v-if="showOutreach && job.outreachDraft"
            class="text-sm mt-2 max-w-2xl whitespace-pre-line border-l-2 border-primary pl-3"
          >
            {{ job.outreachDraft }}
          </p>

          <div class="flex items-center gap-2 mt-3">
            <Button
              type="button"
              size="sm"
              variant="outline"
              class="rounded border-2 border-primary text-primary hover:bg-primary hover:text-primary-foreground disabled:opacity-60"
              :disabled="sendState === 'sending' || sendState === 'sent'"
              @click="sendToTelegram"
            >
              <Send class="h-4 w-4" />
              {{
                sendState === "sending"
                  ? "Sending…"
                  : sendState === "sent"
                    ? "Sent to Telegram"
                    : "Send to Telegram"
              }}
            </Button>
            <p v-if="sendState === 'error'" class="text-sm text-destructive">
              {{ sendErrorMessage }}
            </p>

            <Button
              type="button"
              size="sm"
              variant="outline"
              class="rounded border-2 border-primary text-primary hover:bg-primary hover:text-primary-foreground disabled:opacity-60"
              :disabled="cvState === 'sending' || cvState === 'sent'"
              @click="sendTailoredCv"
            >
              <FileText class="h-4 w-4" />
              {{
                cvState === "sending"
                  ? "Tailoring CV…"
                  : cvState === "sent"
                    ? "CV sent"
                    : "Send tailored CV"
              }}
            </Button>
            <p v-if="cvState === 'error'" class="text-sm text-destructive">
              {{ cvErrorMessage }}
            </p>
          </div>
        </div>

        <div
          class="block md:hidden w-full my-5 border-t-2 border-gray-200"
        ></div>

        <div class="block md:flex md:ml-auto md:flex-wrap md:max-w-xs">
          <Button
            v-for="(chip, index) in chips"
            :key="chip + index"
            @click="$emit('addTag', chip)"
            :class="[
              (tags ?? []).includes(chip)
                ? 'bg-primary text-primary-foreground'
                : 'text-primary',
              'my-2 mx-2 font-bold text-lg rounded hover:bg-primary hover:text-primary-foreground',
            ]"
            variant="outline"
          >
            {{ chip }}
          </Button>
        </div>
      </CardContent>
    </Card>
  </li>
</template>
