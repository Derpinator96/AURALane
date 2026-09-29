// Workstation settings that take effect, kept in this browser only. Every read
// and write tolerates storage being unavailable: the default then applies.

const KEY = "auralane.settings";
export const DEFAULTS = { mrSequence: "t1c", refreshSeconds: 10 };
export const MR_SEQUENCES = [["t1c", "T1c"], ["t1", "T1"], ["t2", "T2"], ["flair", "FLAIR"]];
export const REFRESH_CHOICES = [[10, "Every 10 seconds"], [30, "Every 30 seconds"],
                                [60, "Every 60 seconds"], [0, "Only when I reload"]];

export function loadSettings() {
  try {
    return { ...DEFAULTS, ...JSON.parse(localStorage.getItem(KEY) || "{}") };
  } catch {
    return { ...DEFAULTS };
  }
}

export function saveSettings(settings) {
  try {
    localStorage.setItem(KEY, JSON.stringify(settings));
    return true;
  } catch {
    return false;
  }
}
