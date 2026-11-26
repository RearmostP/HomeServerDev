const USERNAME_PATTERN = /^[A-Za-z][A-Za-z0-9_]{2,23}$/;
const WINDOWS_RESERVED_NAMES = new Set([
  "con", "prn", "aux", "nul",
  ...Array.from({ length: 9 }, (_, index) => `com${index + 1}`),
  ...Array.from({ length: 9 }, (_, index) => `lpt${index + 1}`),
]);

export const USERNAME_ERROR =
  "שם המשתמש חייב להכיל 3–24 תווים, להתחיל באות אנגלית, ולהכיל רק אותיות אנגליות, ספרות או קו תחתון. שמות התקנים שמורים של Windows אינם מותרים (למשל CON, PRN, AUX, NUL, COM1–COM9 ו-LPT1–LPT9).";
export const PASSWORD_ERROR = "הסיסמה חייבת להכיל לפחות 8 תווים.";
export const USERNAME_TAKEN_ERROR = "שם המשתמש כבר תפוס. בחר שם אחר.";

export function getAuthFieldError(name, value, registering) {
  if (name === "username" &&
      (!USERNAME_PATTERN.test(value) || WINDOWS_RESERVED_NAMES.has(value.toLowerCase()))) {
    return USERNAME_ERROR;
  }
  if (name === "password" && registering && value.length < 8) {
    return PASSWORD_ERROR;
  }
  return "";
}

export function updateAuthField(input, registering, message) {
  const fieldError = message ?? getAuthFieldError(input.name, input.value, registering);
  input.setCustomValidity(fieldError);
  const errorElement = document.getElementById(`${input.name}-error`);
  errorElement.textContent = fieldError;
  errorElement.hidden = !fieldError;
  if (fieldError) input.setAttribute("aria-invalid", "true");
  else input.removeAttribute("aria-invalid");
}

export function handleAuthError(form, error, registering) {
  const username = form.elements.username;
  if (error.code === "username_taken") {
    updateAuthField(username, registering, error.message || USERNAME_TAKEN_ERROR);
    username.focus();
    return;
  }
  const message = getAuthFieldError("username", username.value, registering);
  if (message) updateAuthField(username, registering, message);
}

export async function submitCredentials(form, authenticate) {
  const { username, email, password } = form.elements;
  await authenticate({
    username: username.value,
    email: email.value,
    password: password.value,
  });
  password.value = "";
}
