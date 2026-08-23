<script setup lang="ts">
import { Button } from "@/components/ui/button";
import type { ProfileSettings } from "@/lib/types";

definePageMeta({
  layout: "simple",
});

const { data: profiles } = await useFetch<ProfileSettings[]>("/api/profiles");
const selectedProfile = ref<string>("");

const {
  data,
  schemaMissing,
  initializing,
  initError,
  initDatabase,
  running,
  runError,
  startSearch,
} = useJobsFeed(selectedProfile);

const selectedTags = ref<string[]>([]);
const handleTag = (tag: string) => {
  const index = selectedTags.value.indexOf(tag);
  index === -1
    ? selectedTags.value.push(tag)
    : selectedTags.value.splice(index, 1);
};
const clearTags = () => (selectedTags.value = []);
</script>

<template>
  <div class="relative h-40">
    <div v-if="profiles && profiles.length > 1" class="absolute left-4 top-4 z-10">
      <label class="flex items-center gap-2 text-sm text-primary-foreground">
        Profile
        <select
          v-model="selectedProfile"
          class="rounded border border-gray-300 bg-primary-foreground px-2 py-1 text-foreground"
        >
          <option value="">All profiles</option>
          <option v-for="p in profiles" :key="p.name" :value="p.name">{{ p.name }}</option>
        </select>
      </label>
    </div>

    <div v-if="selectedTags.length !== 0" class="transition-opacity duration-500 ease-in-out">
      <JobFilter @remove-tag="handleTag" @clear-tags="clearTags" :selected-tags="selectedTags" />
    </div>

    <div v-if="data && data.length > 0" :class="selectedTags.length !== 0 ? 'mt-11' : 'mt-24'">
      <JobList :job-data="data" :selected-tags="selectedTags" @handle-tag="handleTag" />
    </div>

    <div v-else-if="schemaMissing" class="flex flex-col items-center justify-center gap-3 mt-24">
      <p class="text-sm text-primary-foreground">The database hasn't been set up yet.</p>
      <Button size="lg" :disabled="initializing" @click="initDatabase">
        {{ initializing ? "Setting up…" : "Initialize database" }}
      </Button>
      <p v-if="initError" class="text-sm text-destructive">{{ initError }}</p>
    </div>

    <div v-else-if="data" class="flex flex-col items-center justify-center gap-3 mt-24">
      <Button size="lg" :disabled="running" @click="startSearch">
        {{ running ? "Searching…" : "Start to search" }}
      </Button>
      <p v-if="runError" class="text-sm text-destructive">{{ runError }}</p>
    </div>
  </div>
</template>
