async function patchPaper(id, payload) {
  const res = await fetch(`/api/papers/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    throw new Error("Failed to update paper");
  }
  return res.json();
}

function wirePaperActions(root = document) {
  root.querySelectorAll(".toggle-read").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const article = btn.closest("[data-paper-id]");
      const id = article?.dataset.paperId;
      if (!id) return;
      const currentlyRead = btn.dataset.read === "true";
      const next = !currentlyRead;
      btn.disabled = true;
      try {
        await patchPaper(id, { is_read: next });
        btn.dataset.read = String(next);
        btn.textContent = next ? "Mark unread" : "Mark read";
        article.classList.toggle("is-read", next);
      } finally {
        btn.disabled = false;
      }
    });
  });

  root.querySelectorAll(".toggle-save").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const article = btn.closest("[data-paper-id]");
      const id = article?.dataset.paperId;
      if (!id) return;
      const currentlySaved = btn.dataset.saved === "true";
      const next = !currentlySaved;
      btn.disabled = true;
      try {
        await patchPaper(id, { is_saved: next });
        btn.dataset.saved = String(next);
        btn.textContent = next ? "Unsave" : "Save";
        if (!next && article.closest("#saved")) {
          article.style.opacity = "0";
          setTimeout(() => article.remove(), 220);
        }
      } finally {
        btn.disabled = false;
      }
    });
  });
}

function wireRunButton() {
  const form = document.querySelector('form[action="/research/run"]');
  const btn = document.getElementById("run-btn");
  if (!form || !btn) return;
  form.addEventListener("submit", () => {
    btn.classList.add("is-busy");
    btn.textContent = "Researching…";
  });
}

document.addEventListener("DOMContentLoaded", () => {
  wirePaperActions();
  wireRunButton();
});
