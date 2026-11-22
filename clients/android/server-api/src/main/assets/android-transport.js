(() => {
  const pending = new Map();
  const localFetch = window.fetch.bind(window);
  const inputChunk = 48 * 1024;
  const outputChunk = 64 * 1024;

  function complete(id, status, length) {
    const request = pending.get(id);
    if (!request) return;
    pending.delete(id);
    try {
      if (!status) throw new Error("לא ניתן להתחבר לשרת הגלריה");
      const parts = [];
      for (let offset = 0; offset < length; offset += outputChunk) {
        const encoded = GalleryNative.read(id, offset);
        if (!encoded) throw new Error("התשובה מהשרת נקטעה");
        parts.push(Uint8Array.from(atob(encoded), character => character.charCodeAt(0)));
      }
      request.resolve(new Response([204, 205, 304].includes(status) ? null : new Blob(parts), { status }));
    } catch (error) {
      request.reject(error);
    } finally {
      GalleryNative.release(id);
    }
  }

  Object.defineProperty(window, "galleryNativeComplete", { value: complete });
  let active = 0;
  const waiting = [];
  function dispatch(action) {
    return new Promise((resolve, reject) => {
      const run = () => {
        active++;
        action().then(resolve, reject).finally(() => {
          active--;
          waiting.shift()?.();
        });
      };
      if (active < 4) run();
      else waiting.push(run);
    });
  }

  window.fetch = async (input, options) => {
    const url = new URL(typeof input === "string" ? input : input.url, location.href);
    if (url.origin !== location.origin || !url.pathname.startsWith("/api/")) return localFetch(input, options);
    if (url.search) throw new Error("כתובת שרת לא תקינה");
    return dispatch(async () => {
      const request = new Request(url.href, options);
      const contentType = request.headers.get("Content-Type") || "";
      const bytes = request.body ? new Uint8Array(await request.arrayBuffer()) : new Uint8Array();
      const id = crypto.randomUUID();
      return new Promise((resolve, reject) => {
        pending.set(id, { resolve, reject });
        try {
          for (let offset = 0; offset < bytes.length; offset += inputChunk) {
            const chunk = btoa(String.fromCharCode(...bytes.subarray(offset, offset + inputChunk)));
            if (!GalleryNative.append(id, chunk)) throw new Error("גודל הקובץ עולה על המגבלה");
          }
          if (!GalleryNative.send(id, request.method, url.pathname, contentType)) {
            throw new Error("החיבור לשרת אינו זמין");
          }
        } catch (error) {
          pending.delete(id);
          GalleryNative.release(id);
          reject(error);
        }
      });
    });
  };
})();
