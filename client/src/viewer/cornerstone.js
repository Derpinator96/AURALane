// One-time Cornerstone3D setup: core, the DICOM image loader and the tools
// used by the viewer. Cornerstone 5.11 (checked in node_modules). Called
// lazily by the viewer so the worklist never loads the imaging stack.
import * as core from "@cornerstonejs/core";
import * as tools from "@cornerstonejs/tools";
import * as dicomImageLoader from "@cornerstonejs/dicom-image-loader";

let ready = null;

// HealthImaging stores every frame HTJ2K. Asked for the default media type it
// decodes them and sends back uncompressed pixels (about 1 MB for a chest film);
// asked for HTJ2K it sends the stored bytes (about 300 KB, 45 KB for a brain MR
// slice) and this browser decodes them (OpenJPH, in the loader's web workers).
export const HTJ2K_ACCEPT = 'multipart/related; type="image/jphc"; transfer-syntax=1.2.840.10008.1.2.4.202';
const HTJ2K_SYNTAXES = new Set(["1.2.840.10008.1.2.4.201", "1.2.840.10008.1.2.4.202", "1.2.840.10008.1.2.4.203"]);
const htj2kFrames = new Set();

// At most six frame requests at a time: two for what the reader is looking at,
// four for the background load of the rest of the series.
const INTERACTIVE_REQUESTS = 2;
const BACKGROUND_REQUESTS = 4;

export function initCornerstone() {
  if (!ready) {
    ready = (async () => {
      await core.init();
      dicomImageLoader.init({
        maxWebWorkers: Math.min(4, navigator.hardwareConcurrency || 1),
        beforeSend: async (xhr, imageId) => (htj2kFrames.has(imageId) ? { Accept: HTJ2K_ACCEPT } : {}),
      });
      const pool = core.imageRetrievalPoolManager;
      const { Interaction, Thumbnail, Prefetch } = core.Enums.RequestType;
      pool.setMaxSimultaneousRequests(Interaction, INTERACTIVE_REQUESTS);
      pool.setMaxSimultaneousRequests(Thumbnail, 1);
      pool.setMaxSimultaneousRequests(Prefetch, BACKGROUND_REQUESTS);
      tools.init();
      for (const T of [tools.WindowLevelTool, tools.ZoomTool, tools.PanTool, tools.StackScrollTool]) {
        tools.addTool(T);
      }
    })();
  }
  return ready;
}

// Register a frame and its header. The imageId is the datastore's own frame
// URL: the loader fetches pixels from there, never through the API. A frame the
// header says is HTJ2K and that comes from HealthImaging is fetched as HTJ2K.
export function registerFrame(frameUrl, metadata) {
  const url = new URL(frameUrl, window.location.origin).href;
  const imageId = `wadors:${url}`;
  dicomImageLoader.wadors.metaDataManager.add(imageId, metadata);
  const syntax = metadata?.["00020010"]?.Value?.[0];
  if (HTJ2K_SYNTAXES.has(syntax) && url.includes("medical-imaging.")) htj2kFrames.add(imageId);
  return imageId;
}

// The rest of a series, loaded in the background after the first slice is on
// screen, nearest the reader's slice first. Stops when cancelled() says so.
export function loadInBackground(imageIds, start, cancelled) {
  const order = imageIds
    .map((id, i) => [Math.abs(i - start), id])
    .sort((a, b) => a[0] - b[0])
    .map(([, id]) => id)
    .slice(1);
  let next = 0;
  const worker = async () => {
    while (!cancelled() && next < order.length) {
      const id = order[next++];
      try {
        await core.imageLoader.loadAndCacheImage(id, { requestType: core.Enums.RequestType.Prefetch, priority: 10 });
      } catch {
        // A frame that fails to load is fetched again when the reader scrolls to it.
      }
    }
  };
  return Promise.all(Array.from({ length: BACKGROUND_REQUESTS }, worker));
}

export { core, tools };
