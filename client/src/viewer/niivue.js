// NiiVue is a 2 MB UMD script. It is loaded the first time a 3D view mounts, not
// on every page: the worklist and the 2D viewer never need it.

let loading = null;

export function ensureNiivue() {
  if (window.niivue || window.Niivue) return Promise.resolve();
  if (!loading) {
    loading = new Promise((resolve, reject) => {
      const el = document.createElement("script");
      el.src = "/js/niivue.umd.js";
      el.async = true;
      el.onload = () => resolve();
      el.onerror = () => {
        loading = null;
        reject(new Error("the 3D viewer could not be loaded"));
      };
      document.head.appendChild(el);
    });
  }
  return loading;
}

export function niivueClass() {
  return window.niivue?.Niivue || window.Niivue || null;
}
