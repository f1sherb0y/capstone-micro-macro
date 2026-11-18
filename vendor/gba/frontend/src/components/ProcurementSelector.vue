<template>
  <fieldset class="procurement-selector" :disabled="disabled">
    <legend>Procurement mode for the next simulation</legend>
    <p>Choose before creation. Each simulation keeps its mode for its entire run.</p>
    <label v-for="engine in engines" :key="engine.mode" class="procurement-option">
      <input type="radio" name="procurement-mode" :value="engine.mode"
        :checked="modelValue.mode === engine.mode"
        :disabled="!engine.available" @change="select(engine)" />
      <span><strong>{{ engine.label }}</strong>
        <small>{{ engine.reason }}</small>
        <b v-if="!engine.available">Not available yet</b>
      </span>
    </label>
    <p v-if="loading" role="status">Checking available procurement engines…</p>
    <p v-if="error" role="alert">{{ error }}
      <button type="button" @click="load">Retry</button>
    </p>
    <p v-if="!loading && !error && !ready" role="alert">
      The saved procurement mode is unavailable. Choose an available mode before creating a new simulation.
    </p>
  </fieldset>
</template>

<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { procurementApi } from "../api/procurementApi";

const props = defineProps({
  modelValue: { type: Object, required: true },
  disabled: { type: Boolean, default: false }
});
const emit = defineEmits(["update:modelValue", "ready"]);
const engines = ref([]);
const loading = ref(true);
const error = ref("");
const ready = computed(() => !loading.value && !error.value &&
  engines.value.some(engine => engine.mode === props.modelValue.mode && engine.available));
watch(ready, value => emit("ready", value), { immediate: true });

function select(engine) {
  emit("update:modelValue", {
    schema_version: "1.0", mode: engine.mode, scope: engine.scope,
    adapter_profile_id: engine.adapter_profile_id, failure_policy: "pause"
  });
}

async function load() {
  loading.value = true;
  error.value = "";
  try {
    const result = await procurementApi.engines();
    if (!Array.isArray(result)) throw new Error("Invalid procurement capability response.");
    engines.value = result;
  } catch (cause) {
    error.value = cause.message || "Cannot check procurement engine availability.";
  } finally {
    loading.value = false;
  }
}
onMounted(load);
</script>

<style scoped>
.procurement-selector { grid-column: 1 / -1; margin: 0; padding: 12px; border: 1px solid #cbd5e1; border-radius: 10px; min-width: 0; }
legend { font-size: 14px; line-height: 1.4; font-weight: 700; color: #173b52; }
p, small { font-size: 12px; line-height: 1.5; color: #475569; }
.procurement-option { display: flex; align-items: flex-start; gap: 9px; margin-top: 12px; cursor: pointer; }
input { margin-top: 4px; flex-shrink: 0; }
strong, small { display: block; }
b { font-size: 11px; color: #8a4b0f; }
</style>
