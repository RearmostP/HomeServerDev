import * as opaque from "@serenity-kit/opaque";
import { generateIdentity, openIdentity, newAlbumKey, wrapAlbumKey, openAlbumKey, encryptPhoto, openPhoto, imageTypes } from "./crypto.js";

const byId = id => document.getElementById(id);
const items = byId("items");
const tabs = [...document.querySelectorAll("[data-tab]")];
const viewer = byId("viewer");
const urls = new Set();
let account, identity, activeAlbum, entries = [], position = 0, generation = 0;
let tab = "photos";
let registering = false;
let editAction;
let selecting = false;
const selectedPhotos = new Set();
let notice;

function status(message = "") {
  clearTimeout(notice);
  const element = byId("status");
  element.textContent = message;
  element.hidden = !message;
  if (message) notice = setTimeout(() => { element.hidden = true; }, 6500);
}

async function api(path, payload, binary = false) {
  const options = payload === undefined ? {} : { method: "POST" };
  if (payload instanceof FormData) options.body = payload;
  else if (payload !== undefined) {
    options.body = JSON.stringify(payload);
    options.headers = { "Content-Type": "application/json" };
  }
  const response = await fetch("/api/" + path, options);
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.error || "הפעולה נכשלה");
  }
  return binary ? response.arrayBuffer() : response.json();
}

function action(element, callback) {
  element.disabled = true;
  return Promise.resolve().then(callback).catch(error => status(error.message))
    .finally(() => { element.disabled = false; });
}

function node(tag, text, className) {
  const result = document.createElement(tag);
  if (text) result.textContent = text;
  if (className) result.className = className;
  return result;
}

function updateAuthForm() {
  const input = byId("credentials").elements;
  byId("email-field").hidden = !registering;
  input.email.required = registering;
  input.password.autocomplete = registering ? "new-password" : "current-password";
  input.password.minLength = registering ? 12 : 0;
  byId("submit-auth").textContent = registering ? "הרשמה" : "כניסה";
  byId("toggle-auth").textContent = registering ? "כבר יש לי חשבון" : "יצירת חשבון";
}

byId("toggle-auth").onclick = () => {
  registering = !registering;
  updateAuthForm();
};

async function register(username, email, password) {
  const start = opaque.client.startRegistration({ password });
  const response = await api("auth/register/start", { username, email, registrationRequest: start.registrationRequest });
  const result = opaque.client.finishRegistration({
    clientRegistrationState: start.clientRegistrationState,
    registrationResponse: response.registrationResponse, password,
  });
  const keys = await generateIdentity(result.exportKey, username);
  await api("auth/register/finish", {
    challenge: response.challenge, registrationRecord: result.registrationRecord, ...keys,
    albumKey: await wrapAlbumKey(newAlbumKey(), keys.publicKey),
  });
  registering = false;
  updateAuthForm();
}

async function login(username, password) {
  const start = opaque.client.startLogin({ password });
  const response = await api("auth/login/start", { username, startLoginRequest: start.startLoginRequest });
  const result = opaque.client.finishLogin({
    clientLoginState: start.clientLoginState, loginResponse: response.loginResponse, password,
  });
  if (!result) throw new Error("שם משתמש או סיסמה שגויים");
  const session = await api("auth/login/finish", {
    challenge: response.challenge, finishLoginRequest: result.finishLoginRequest,
    device: (navigator.userAgentData?.platform || navigator.platform || "דפדפן").slice(0, 120),
  });
  identity = await openIdentity(result.exportKey, username, session.privateKey);
  account = session.username;
  byId("account").textContent = account;
  byId("gallery").hidden = false;
  byId("auth").hidden = true;
  await render("photos");
}

byId("credentials").onsubmit = event => {
  event.preventDefault();
  const form = event.currentTarget;
  const { username, email, password } = Object.fromEntries(new FormData(form));
  form.elements.password.value = "";
  action(byId("submit-auth"), async () => {
    if (!globalThis.isSecureContext || !crypto.subtle) throw new Error("נדרש חיבור HTTPS");
    await opaque.ready;
    if (registering) await register(username, email, password);
    await login(username, password);
  });
};

function resetView() {
  if (viewer.open) viewer.close();
  byId("full-image").removeAttribute("src");
  for (const url of urls) URL.revokeObjectURL(url);
  urls.clear();
  items.replaceChildren();
  entries = [];
  selecting = false;
  selectedPhotos.clear();
  byId("selection").textContent = "בחירת תמונות";
  byId("copy-photos").hidden = true;
  return ++generation;
}

const albumRoute = album => "albums/" + album.owner + "/" + album.number + "/photos";

async function readEntries(album) {
  const key = await openAlbumKey(identity, album.wrapped_key);
  const result = await api(albumRoute(album));
  const opened = await Promise.allSettled(result.photos.map(async record => ({
    id: record.id, ...await openPhoto(key, record),
  })));
  if (opened.some(item => item.status === "rejected")) status("חלק מהתמונות לא נפתחו");
  return opened.filter(item => item.status === "fulfilled").map(item => item.value)
    .sort((left, right) => right.date - left.date);
}

async function setImage(image, entry, renderId) {
  try {
    const buffer = await api("photos/" + entry.id, undefined, true);
    const blob = await entry.blob(buffer);
    if (renderId !== generation) return;
    const url = URL.createObjectURL(blob);
    urls.add(url);
    image.src = url;
  } catch {
    if (renderId === generation) image.alt = "התמונה לא נטענה";
  }
}

let swipeStart;
viewer.addEventListener("touchstart", event => { swipeStart = event.touches[0].clientX; }, { passive: true });
viewer.addEventListener("touchend", event => {
  const delta = event.changedTouches[0].clientX - swipeStart;
  if (Math.abs(delta) > 45) showPhoto(position + (delta > 0 ? 1 : -1));
}, { passive: true });

function showPhoto(index) {
  if (index < 0 || index >= entries.length) return;
  position = index;
  const thumbnail = items.querySelector('[data-photo="' + index + '"] img');
  const image = node("img");
  image.id = "full-image";
  image.alt = entries[index].name;
  byId("full-image").replaceWith(image);
  if (thumbnail?.complete && thumbnail.getAttribute("src")) image.src = thumbnail.src;
  else setImage(image, entries[index], generation);
  byId("previous").disabled = index === 0;
  byId("next").disabled = index === entries.length - 1;
  if (!viewer.open) viewer.showModal();
}
byId("close-viewer").onclick = () => viewer.close();
byId("previous").onclick = () => showPhoto(position - 1);
byId("next").onclick = () => showPhoto(position + 1);
viewer.addEventListener("keydown", event => {
  if (event.key === "ArrowLeft") showPhoto(position + 1);
  if (event.key === "ArrowRight") showPhoto(position - 1);
});

async function renderPhotos(album, renderId) {
  const photos = await readEntries(album);
  if (renderId !== generation) return;
  entries = photos;
  byId("selection").hidden = !photos.length;
  if (!photos.length) items.append(node("p", "האלבום ריק", "empty"));
  const formatter = new Intl.DateTimeFormat("he", { dateStyle: "long" });
  const observer = new IntersectionObserver(records => {
    for (const record of records) {
      if (!record.isIntersecting) continue;
      observer.unobserve(record.target);
      if (renderId === generation) setImage(record.target, photos[Number(record.target.dataset.index)], renderId);
    }
  }, { rootMargin: "250px" });
  let lastDate, grid;
  photos.forEach((entry, index) => {
    const date = formatter.format(entry.date);
    if (date !== lastDate) {
      grid = node("div", "", "grid");
      items.append(node("h2", date), grid);
      lastDate = date;
    }
    const tile = node("button", "", "tile");
    tile.dataset.photo = index;
    tile.setAttribute("aria-label", entry.name);
    tile.onclick = () => {
      if (!selecting) return showPhoto(index);
      if (selectedPhotos.has(index)) selectedPhotos.delete(index);
      else selectedPhotos.add(index);
      tile.setAttribute("aria-pressed", String(selectedPhotos.has(index)));
      byId("copy-photos").hidden = !selectedPhotos.size;
    };
    const image = node("img");
    image.alt = entry.name;
    image.dataset.index = index;
    tile.append(image);
    grid.append(tile);
    observer.observe(image);
  });
  coverObserver = observer;
}

let coverObserver;
async function render(nextTab, selected) {
  coverObserver?.disconnect();
  const renderId = resetView();
  tab = nextTab;
  activeAlbum = null;
  for (const button of tabs) {
    if (button.dataset.tab === tab) button.setAttribute("aria-current", "page");
    else button.removeAttribute("aria-current");
  }
  for (const id of ["upload", "share", "new-album", "remove-album", "selection"]) byId(id).hidden = true;
  byId("title").textContent = selected?.name || tabs.find(button => button.dataset.tab === tab).textContent;
  if (tab === "devices") {
    const { devices } = await api("devices");
    if (renderId !== generation) return;
    for (const device of devices) {
      const row = node("article", "", "device");
      const label = device.label + (device.current ? " · מכשיר זה" : "") +
        " · " + new Date(device.seen * 1000).toLocaleString("he");
      const revoke = node("button", "ניתוק");
      revoke.onclick = () => action(revoke, async () => {
        await api("devices/revoke", { id: device.id });
        if (device.current) lock();
        else await render("devices");
      });
      row.append(node("span", label), revoke);
      items.append(row);
    }
    return;
  }
  const { albums } = await api("albums");
  if (renderId !== generation) return;
  const current = selected
    ? albums.find(album => album.owner === selected.owner && album.number === selected.number)
    : tab === "photos" && albums.find(album => album.owner === account && album.number === 1);
  if (current) {
    activeAlbum = current;
    const own = current.owner === account;
    byId("upload").hidden = !own;
    byId("share").hidden = !own;
    byId("remove-album").hidden = !own || current.number === 1;
    byId("title").textContent = selected ? current.name : "תמונות";
    return renderPhotos(current, renderId);
  }
  byId("new-album").hidden = tab !== "albums";
  const shown = albums.filter(album => tab === "shared" ? album.owner !== account || album.shared : album.owner === account);
  if (!shown.length) items.append(node("p", "אין אלבומים להצגה", "empty"));
  const grid = node("div", "", "grid");
  items.append(grid);
  const observer = new IntersectionObserver(records => {
    for (const record of records) {
      if (!record.isIntersecting) continue;
      observer.unobserve(record.target);
      const album = shown[Number(record.target.dataset.index)];
      api(albumRoute(album)).then(async response => {
        if (renderId !== generation || !response.photos.length) return;
        const raw = await openAlbumKey(identity, album.wrapped_key);
        const record = response.photos[0];
        const entry = await openPhoto(raw, record);
        const image = node("img");
        image.alt = "";
        await setImage(image, { id: record.id, ...entry }, renderId);
        if (renderId === generation && image.getAttribute("src")) recordTargetReplace(image);
      }).catch(() => {});
      function recordTargetReplace(image) { record.target.replaceChildren(image); }
    }
  }, { rootMargin: "150px" });
  coverObserver = observer;
  shown.forEach((album, index) => {
    const card = node("button", "", "album");
    const cover = node("span", "▧", "cover");
    cover.dataset.index = index;
    card.append(cover, node("strong", album.name), node("span", album.owner + " · " + album.count + " תמונות", "detail"));
    card.onclick = () => action(card, () => render(tab, album));
    grid.append(card);
    if (album.count) observer.observe(cover);
  });
}

for (const button of tabs) button.onclick = () => action(button, () => render(button.dataset.tab));

function edit(title, label, maxLength, callback) {
  byId("edit-title").textContent = title;
  byId("edit-label").textContent = label;
  byId("edit-input").maxLength = maxLength;
  byId("edit-input").value = "";
  editAction = callback;
  byId("edit").showModal();
}
byId("cancel-edit").onclick = () => byId("edit").close();
byId("edit-form").onsubmit = event => {
  event.preventDefault();
  const value = byId("edit-input").value.trim();
  if (!value) return;
  action(event.submitter, async () => {
    await editAction(value);
    byId("edit").close();
  });
};
byId("new-album").onclick = () => edit("אלבום חדש", "שם האלבום", 80, async name => {
  const { publicKey } = await api("users/" + account + "/key");
  const album = await api("albums", { name, albumKey: await wrapAlbumKey(newAlbumKey(), publicKey) });
  await render("albums", { owner: account, number: album.number, name });
});
byId("share").onclick = () => {
  const album = activeAlbum;
  edit("שיתוף אלבום", "שם המשתמש של החבר", 24, async username => {
    const { publicKey } = await api("users/" + encodeURIComponent(username) + "/key");
    const key = await openAlbumKey(identity, album.wrapped_key);
    await api("albums/" + album.number + "/share", { username, albumKey: await wrapAlbumKey(key, publicKey) });
    status("האלבום שותף");
  });
};
byId("remove-album").onclick = () => {
  const album = activeAlbum;
  if (!confirm("למחוק את האלבום ואת כל התמונות שבו?")) return;
  action(byId("remove-album"), async () => {
    await api("albums/" + album.number + "/delete", {});
    await render("albums");
  });
};
byId("selection").onclick = () => {
  selecting = !selecting;
  selectedPhotos.clear();
  byId("selection").textContent = selecting ? "ביטול בחירה" : "בחירת תמונות";
  byId("copy-photos").hidden = true;
  for (const tile of items.querySelectorAll("[data-photo]")) {
    if (selecting) tile.setAttribute("aria-pressed", "false");
    else tile.removeAttribute("aria-pressed");
  }
};

async function sendPhoto(album, rawKey, file) {
  const payload = await encryptPhoto(rawKey, file);
  const data = new FormData();
  data.append("ciphertext", payload.ciphertext);
  data.append("metadata", payload.metadata);
  data.append("albumVersion", album.wrapped_key);
  await api("albums/" + album.number + "/photos", data);
}

byId("copy-photos").onclick = () => action(byId("copy-photos"), async () => {
  const source = activeAlbum;
  const photos = [...selectedPhotos].map(index => entries[index]);
  const { albums } = await api("albums");
  const targets = albums.filter(album => album.owner === account &&
    (source.owner !== account || album.number !== source.number));
  if (!targets.length) return status("צור אלבום נוסף לפני הוספת התמונות");
  const select = byId("copy-target");
  select.replaceChildren(...targets.map(album => {
    const option = node("option", album.name);
    option.value = album.number;
    return option;
  }));
  const dialog = byId("copy-dialog");
  byId("copy-form").onsubmit = event => {
    event.preventDefault();
    const target = targets.find(album => album.number === Number(select.value));
    action(event.submitter, async () => {
      const key = await openAlbumKey(identity, target.wrapped_key);
      let copied = 0;
      try {
        for (const photo of photos) {
          status("מוסיף " + (copied + 1) + " מתוך " + photos.length);
          const blob = await photo.blob(await api("photos/" + photo.id, undefined, true));
          await sendPhoto(target, key, new File([blob], photo.name, { type: photo.type, lastModified: photo.date }));
          copied++;
        }
      } catch (error) {
        throw new Error("נוספו " + copied + " תמונות. " + error.message);
      } finally {
        dialog.close();
      }
      if (selecting) byId("selection").click();
      status(copied + " תמונות נוספו לאלבום");
    });
  };
  dialog.showModal();
});
byId("cancel-copy").onclick = () => byId("copy-dialog").close();

byId("files").onchange = event => {
  const input = event.currentTarget;
  const files = [...input.files];
  const album = activeAlbum;
  const uploadTab = tab;
  const renderId = generation;
  action(input, async () => {
    if (!album || !files.length) return;
    const rawKey = await openAlbumKey(identity, album.wrapped_key);
    let uploaded = 0;
    try {
      for (const file of files) {
        if (!account) break;
        if (!imageTypes.has(file.type) || file.size > 25 * 1024 * 1024) {
          throw new Error("ניתן להעלות JPEG, PNG, WebP, GIF ו־AVIF עד 25MB לתמונה");
        }
        status("מצפין ומעלה " + (uploaded + 1) + " מתוך " + files.length);
        await sendPhoto(album, rawKey, file);
        uploaded++;
      }
    } finally {
      input.value = "";
      if (uploaded && generation === renderId) await render(uploadTab, album);
    }
    status(uploaded + " תמונות הועלו");
  });
};

function lock() {
  coverObserver?.disconnect();
  resetView();
  identity = account = activeAlbum = null;
  byId("gallery").hidden = true;
  byId("auth").hidden = false;
}
byId("logout").onclick = () => action(byId("logout"), async () => {
  await api("logout", {});
  lock();
});
