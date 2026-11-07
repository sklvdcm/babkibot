const form = document.querySelector("#login-form");
const error = document.querySelector("#login-error");

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = form.querySelector("button");
  button.disabled = true;
  error.hidden = true;
  try {
    const response = await fetch("/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password: form.password.value }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "Не удалось войти");
    window.location.assign("/app");
  } catch (requestError) {
    error.textContent = requestError.message;
    error.hidden = false;
    form.password.focus();
  } finally {
    button.disabled = false;
  }
});
