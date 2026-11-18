<template>
  <aside v-if="simulationId" class="procurement-receipt" aria-live="polite">
    <template v-if="state">
      <strong>{{ state.effective_mode === "gba_native" ? "GBA native" : "codedemo micro" }} · Locked from creation</strong>
      <span>Simulation {{ state.simulation_id }} · {{ state.scope === "full_procurement" ? "Full procurement scope" : state.scope }}</span>
      <small>Create a new simulation to use another mode.</small>
    </template>
    <span v-else-if="error" role="alert">{{ error }}</span>
    <span v-else>Loading this simulation’s procurement mode…</span>
  </aside>
</template>

<script setup>
import { ref, watch } from "vue";
import { procurementApi } from "../api/procurementApi";
const props = defineProps({ simulationId: { type: String, default: "" } });
const state = ref(null);
const error = ref("");
let version = 0;
watch(() => props.simulationId, async id => {
  const current = ++version;
  state.value = null;
  error.value = "";
  if (!id) return;
  try {
    const receipt = await procurementApi.state(id);
    if (current === version) state.value = receipt;
  } catch (cause) {
    if (current === version) error.value = cause.message || "Cannot read this simulation’s procurement mode.";
  }
}, { immediate: true });
</script>

<style scoped>
.procurement-receipt { grid-column: 1 / -1; display: grid; gap: 5px; padding: 12px 16px; margin-bottom: 14px; border: 1px solid #b6d4de; border-radius: 10px; background: #f0f8fa; color: #173b52; font-size: 13px; }
span, small { overflow-wrap: anywhere; }
</style>
