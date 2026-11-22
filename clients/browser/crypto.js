const bytes = new TextEncoder();
const subtle = () => crypto.subtle;
export const imageTypes = new Set(["image/jpeg", "image/png", "image/webp", "image/gif", "image/avif"]);

function encode(value) {
  return btoa(String.fromCharCode(...new Uint8Array(value)));
}

function decode(value) {
  return Uint8Array.from(atob(value.replaceAll("-", "+").replaceAll("_", "/")), char => char.charCodeAt(0));
}

async function userWrapKey(exportKey) {
  const source = await subtle().importKey("raw", decode(exportKey), "HKDF", false, ["deriveKey"]);
  return subtle().deriveKey({
    name: "HKDF", hash: "SHA-256", salt: new Uint8Array(32),
    info: bytes.encode("home-gallery/private-key/v1"),
  }, source, { name: "AES-GCM", length: 256 }, false, ["encrypt", "decrypt"]);
}

async function encrypt(key, value, purpose) {
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const ciphertext = await subtle().encrypt({ name: "AES-GCM", iv, additionalData: bytes.encode(purpose) }, key, value);
  return { iv: encode(iv), ciphertext };
}

function decrypt(key, value, iv, purpose) {
  return subtle().decrypt({ name: "AES-GCM", iv: decode(iv), additionalData: bytes.encode(purpose) }, key, value);
}

export async function generateIdentity(exportKey, username) {
  const keys = await subtle().generateKey({
    name: "RSA-OAEP", modulusLength: 3072, publicExponent: new Uint8Array([1, 0, 1]), hash: "SHA-256",
  }, true, ["encrypt", "decrypt"]);
  const publicKey = encode(await subtle().exportKey("spki", keys.publicKey));
  const pkcs8 = await subtle().exportKey("pkcs8", keys.privateKey);
  const locked = await encrypt(await userWrapKey(exportKey), pkcs8, "identity:" + username);
  return { publicKey, privateKey: JSON.stringify({ iv: locked.iv, data: encode(locked.ciphertext) }) };
}

export async function openIdentity(exportKey, username, wrapped) {
  const { iv, data } = JSON.parse(wrapped);
  const pkcs8 = await decrypt(await userWrapKey(exportKey), decode(data), iv, "identity:" + username);
  return subtle().importKey("pkcs8", pkcs8, { name: "RSA-OAEP", hash: "SHA-256" }, false, ["decrypt"]);
}

export function newAlbumKey() {
  return crypto.getRandomValues(new Uint8Array(32));
}

export async function wrapAlbumKey(rawKey, publicKey) {
  const key = await subtle().importKey("spki", decode(publicKey), { name: "RSA-OAEP", hash: "SHA-256" }, false, ["encrypt"]);
  return encode(await subtle().encrypt({ name: "RSA-OAEP" }, key, rawKey));
}

export function openAlbumKey(privateKey, wrapped) {
  return subtle().decrypt({ name: "RSA-OAEP" }, privateKey, decode(wrapped));
}

function aes(raw) {
  return subtle().importKey("raw", raw, "AES-GCM", false, ["encrypt", "decrypt"]);
}

export async function encryptPhoto(rawAlbumKey, file) {
  const rawPhotoKey = crypto.getRandomValues(new Uint8Array(32));
  const photoKey = await aes(rawPhotoKey);
  const photo = await encrypt(photoKey, await file.arrayBuffer(), "home-gallery/photo/v1");
  const details = await encrypt(photoKey, bytes.encode(JSON.stringify({
    type: file.type, date: file.lastModified || Date.now(), name: file.name,
  })), "home-gallery/details/v1");
  const wrapped = await encrypt(await aes(rawAlbumKey), rawPhotoKey, "home-gallery/photo-key/v1");
  return {
    ciphertext: new Blob([photo.ciphertext]),
    metadata: JSON.stringify({
      iv: photo.iv, key: encode(wrapped.ciphertext), keyIv: wrapped.iv,
      details: encode(details.ciphertext), detailsIv: details.iv,
    }),
  };
}

export async function openPhoto(rawAlbumKey, record) {
  const envelope = JSON.parse(record.metadata);
  const key = await aes(await decrypt(await aes(rawAlbumKey), decode(envelope.key), envelope.keyIv, "home-gallery/photo-key/v1"));
  const details = JSON.parse(new TextDecoder().decode(await decrypt(key, decode(envelope.details), envelope.detailsIv, "home-gallery/details/v1")));
  if (!imageTypes.has(details.type)) throw new Error("סוג תמונה לא נתמך");
  return { ...details, async blob(ciphertext) {
    return new Blob([await decrypt(key, ciphertext, envelope.iv, "home-gallery/photo/v1")], { type: details.type });
  } };
}
