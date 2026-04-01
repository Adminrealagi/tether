import { ref, watch } from "vue";
import { watchDebounced } from "@vueuse/core";
import { checkDirectory, type DirectoryCheck } from "@/api";

export function useDirectoryCheck(debounceMs = 400) {
  const input = ref("");
  const checking = ref(false);
  const probe = ref<DirectoryCheck | null>(null);
  const error = ref("");
  let requestId = 0;

  const reset = () => {
    probe.value = null;
    error.value = "";
    checking.value = false;
  };

  const check = async (path: string): Promise<DirectoryCheck | null> => {
    const trimmed = path.trim();
    const currentRequestId = ++requestId;
    if (!trimmed) {
      reset();
      return null;
    }

    checking.value = true;
    try {
      const status = await checkDirectory(trimmed);
      if (currentRequestId !== requestId) return null;
      probe.value = status;
      error.value = status.exists ? "" : "Directory not found";
      return status;
    } catch (err) {
      if (currentRequestId !== requestId) return null;
      probe.value = null;
      error.value = String(err);
      return null;
    } finally {
      if (currentRequestId === requestId) {
        checking.value = false;
      }
    }
  };

  watch(input, (value) => {
    requestId += 1;
    const trimmed = value.trim();
    if (!trimmed) {
      reset();
      return;
    }
    checking.value = true;
    error.value = "";
  });

  // Auto-check when input changes (debounced)
  watchDebounced(
    input,
    (value) => {
      const trimmed = value.trim();
      if (!trimmed) {
        return;
      }
      void check(trimmed);
    },
    { debounce: debounceMs }
  );

  return {
    input,
    checking,
    probe,
    error,
    check
  };
}
