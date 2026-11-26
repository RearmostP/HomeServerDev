import assert from "node:assert/strict";
import test from "node:test";

import {
  handleAuthError,
  getAuthFieldError,
  PASSWORD_ERROR,
  submitCredentials,
  USERNAME_ERROR,
  USERNAME_TAKEN_ERROR,
} from "./auth-form.js";

function fakeForm(password = "secret123") {
  return {
    elements: {
      username: { value: "Alice" },
      email: { value: "alice@example.com" },
      password: { value: password },
    },
  };
}

test("keeps the password when authentication fails", async () => {
  const form = fakeForm();
  await assert.rejects(
    submitCredentials(form, async credentials => {
      assert.equal(credentials.password, "secret123");
      throw new Error("login failed");
    }),
    /login failed/,
  );
  assert.equal(form.elements.password.value, "secret123");
});

test("clears the password after successful authentication", async () => {
  const form = fakeForm();
  await submitCredentials(form, async credentials => {
    assert.equal(credentials.password, "secret123");
  });
  assert.equal(form.elements.password.value, "");
});

test("explains invalid usernames and the Windows-reserved-name restriction", () => {
  assert.equal(getAuthFieldError("username", "1alice", false), USERNAME_ERROR);
  assert.equal(getAuthFieldError("username", "CON", true), USERNAME_ERROR);
  assert.equal(getAuthFieldError("username", "Alice_1", true), "");
  assert.match(USERNAME_ERROR, /3–24/);
  assert.match(USERNAME_ERROR, /אות אנגלית/);
  assert.match(USERNAME_ERROR, /Windows/);
});

test("explains the registration password minimum without adding other rules", () => {
  assert.equal(getAuthFieldError("password", "short7!", true), PASSWORD_ERROR);
  assert.equal(getAuthFieldError("password", "longer123", true), "");
  assert.equal(getAuthFieldError("password", "short7!", false), "");
  assert.match(PASSWORD_ERROR, /8/);
});

test("defines explicit feedback for a taken username", () => {
  assert.equal(USERNAME_TAKEN_ERROR, "שם המשתמש כבר תפוס. בחר שם אחר.");
});

test("associates a username conflict with the username field", () => {
  const fieldError = { textContent: "", hidden: true };
  const username = {
    name: "username",
    value: "Alice",
    focused: false,
    setCustomValidity(message) { this.validationMessage = message; },
    setAttribute(name, value) { this[name] = value; },
    removeAttribute(name) { delete this[name]; },
    focus() { this.focused = true; },
  };
  const previousDocument = globalThis.document;
  globalThis.document = { getElementById: () => fieldError };
  try {
    handleAuthError(
      { elements: { username } },
      { code: "username_taken", message: USERNAME_TAKEN_ERROR },
      true,
    );
    assert.equal(fieldError.textContent, USERNAME_TAKEN_ERROR);
    assert.equal(fieldError.hidden, false);
    assert.equal(username["aria-invalid"], "true");
    assert.equal(username.focused, true);
  } finally {
    if (previousDocument === undefined) delete globalThis.document;
    else globalThis.document = previousDocument;
  }
});
