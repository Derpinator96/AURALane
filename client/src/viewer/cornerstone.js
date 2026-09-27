// One-time Cornerstone3D setup: core, the DICOM image loader and the tools
// used by the viewer. Cornerstone 5.11 (checked in node_modules). Called
// lazily by the viewer so the worklist never loads the imaging stack.
import * as core from "@cornerstonejs/core";
import * as tools from "@cornerstonejs/tools";
import * as dicomImageLoader from "@cornerstonejs/dicom-image-loader";

let ready = null;

export function initCornerstone() {
  if (!ready) {
    ready = (async () => {
      await core.init();
      dicomImageLoader.init({ maxWebWorkers: Math.min(4, navigator.hardwareConcurrency || 1) });
      tools.init();
      for (const T of [tools.WindowLevelTool, tools.ZoomTool, tools.PanTool, tools.StackScrollTool]) {
        tools.addTool(T);
      }
    })();
  }
  return ready;
}

// Register a frame and its header. The imageId is the datastore's own frame
// URL: the loader fetches pixels from there, never through the API.
export function registerFrame(frameUrl, metadata) {
  const url = new URL(frameUrl, window.location.origin).href;
  const imageId = `wadors:${url}`;
  dicomImageLoader.wadors.metaDataManager.add(imageId, metadata);
  return imageId;
}

export { core, tools };
