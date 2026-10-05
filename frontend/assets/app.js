const REQUIRED_PHOTOS = 6;
const API = "";

const panels = {
  photos: document.getElementById("panel-photos"),
  templates: document.getElementById("panel-templates"),
  result: document.getElementById("panel-result"),
};
const photoGrid = document.getElementById("photoGrid");
const templateGrid = document.getElementById("templateGrid");
const primaryBtn = document.getElementById("primaryBtn");
const backBtn = document.getElementById("backBtn");
const toast = document.getElementById("toast");
const loadingState = document.getElementById("loadingState");
const readyState = document.getElementById("readyState");
const errorState = document.getElementById("errorState");
const resultVideo = document.getElementById("resultVideo");
const errorText = document.getElementById("errorText");

const photos = Array.from({ length: REQUIRED_PHOTOS }, () => null);
let currentPage = "photos";
let jobId = null;
let selectedTemplateId = null;
let pollTimer = null;
let templatesCache = [];

function showToast(message) {
  toast.textContent = message;
  toast.hidden = false;
  window.clearTimeout(showToast.timer);
  showToast.timer = window.setTimeout(() => {
    toast.hidden = true;
  }, 3200);
}

function setPage(page) {
  currentPage = page;
  Object.entries(panels).forEach(([name, panel]) => {
    const visible = name === page;
    panel.hidden = !visible;
    panel.classList.toggle("is-visible", visible);
  });

  document.querySelectorAll(".step").forEach((step) => {
    const name = step.dataset.step;
    step.classList.toggle("is-active", name === page);
    step.classList.toggle(
      "is-done",
      (page === "templates" && name === "photos") ||
        (page === "result" && (name === "photos" || name === "templates"))
    );
  });

  backBtn.hidden = page === "photos" || page === "result";
  backBtn.textContent = "Kembali";
  updatePrimaryButton();
}

function filledCount() {
  return photos.filter(Boolean).length;
}

function updatePrimaryButton() {
  if (currentPage === "photos") {
    primaryBtn.textContent = "Lanjut";
    primaryBtn.disabled = filledCount() !== REQUIRED_PHOTOS;
  } else if (currentPage === "templates") {
    primaryBtn.textContent = "Buat video";
    primaryBtn.disabled = !selectedTemplateId;
  } else if (readyState.hidden === false) {
    primaryBtn.textContent = "Unduh video";
    primaryBtn.disabled = false;
  } else if (errorState.hidden === false) {
    primaryBtn.textContent = "Mulai lagi";
    primaryBtn.disabled = false;
  } else {
    primaryBtn.textContent = "Sedang dibuat...";
    primaryBtn.disabled = true;
  }
}

function renderPhotoSlots() {
  photoGrid.innerHTML = "";
  photos.forEach((file, index) => {
    const slot = document.createElement("label");
    slot.className = `photo-slot${file ? " is-filled" : ""}`;

    const input = document.createElement("input");
    input.type = "file";
    input.accept = "image/jpeg,image/png,image/webp,.jpg,.jpeg,.png,.webp";
    input.hidden = true;
    input.addEventListener("change", () => {
      const chosen = input.files && input.files[0];
      if (!chosen) return;
      photos[index] = chosen;
      renderPhotoSlots();
      updatePrimaryButton();
    });

    if (file) {
      const img = document.createElement("img");
      img.alt = `Foto ${index + 1}`;
      img.src = URL.createObjectURL(file);
      slot.append(img);

      const remove = document.createElement("button");
      remove.type = "button";
      remove.className = "remove-photo";
      remove.setAttribute("aria-label", `Hapus foto ${index + 1}`);
      remove.textContent = "×";
      remove.addEventListener("click", (event) => {
        event.preventDefault();
        event.stopPropagation();
        photos[index] = null;
        renderPhotoSlots();
        updatePrimaryButton();
      });
      slot.append(remove);
    } else {
      const label = document.createElement("div");
      label.className = "slot-label";
      label.innerHTML = `<span>+ Foto ${index + 1}</span><small>Sentuh untuk pilih</small>`;
      slot.append(label);
    }

    slot.append(input);
    photoGrid.append(slot);
  });
}

function templateSwatchClass(id) {
  const known = ["pelukan", "surat-cinta", "jalan-berdua", "deg-degan"];
  if (known.includes(id)) return id;
  return "pelukan";
}

function renderTemplateCards() {
  templateGrid.innerHTML = "";
  templatesCache.forEach((template) => {
    const card = document.createElement("button");
    card.type = "button";
    card.className = `template-card${selectedTemplateId === template.id ? " is-selected" : ""}`;
    card.innerHTML = `
      <div class="swatch ${templateSwatchClass(template.id)}"></div>
      <h2>${template.name}</h2>
      <p>${template.description}</p>
    `;
    card.addEventListener("click", () => {
      selectedTemplateId = template.id;
      renderTemplateCards();
      updatePrimaryButton();
    });
    templateGrid.append(card);
  });
}

async function loadTemplates() {
  const response = await fetch(`${API}/api/templates`);
  if (!response.ok) throw new Error("Template belum bisa dimuat.");
  const data = await response.json();
  templatesCache = data.templates || [];
  renderTemplateCards();
}

async function readError(response) {
  try {
    const data = await response.json();
    return data.detail || "Terjadi kendala. Coba lagi, ya.";
  } catch {
    return "Terjadi kendala. Coba lagi, ya.";
  }
}

async function uploadPhotos() {
  const form = new FormData();
  photos.forEach((file) => form.append("photos", file, file.name));
  const response = await fetch(`${API}/api/jobs/photos`, {
    method: "POST",
    body: form,
  });
  if (!response.ok) throw new Error(await readError(response));
  const data = await response.json();
  jobId = data.job.job_id;
}

async function chooseTemplateAndRender() {
  const templateResponse = await fetch(`${API}/api/jobs/${jobId}/template`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ template_id: selectedTemplateId }),
  });
  if (!templateResponse.ok) throw new Error(await readError(templateResponse));

  const renderResponse = await fetch(`${API}/api/jobs/${jobId}/render`, {
    method: "POST",
  });
  if (!renderResponse.ok) throw new Error(await readError(renderResponse));
}

function showResult(kind, extra = {}) {
  loadingState.hidden = kind !== "loading";
  readyState.hidden = kind !== "ready";
  errorState.hidden = kind !== "error";
  if (kind === "ready") {
    resultVideo.src = extra.videoUrl;
    backBtn.hidden = false;
    backBtn.textContent = "Buat lagi";
  }
  if (kind === "error") {
    errorText.textContent = extra.message || "Ada yang menghambat. Coba buat lagi, ya.";
    backBtn.hidden = false;
    backBtn.textContent = "Buat lagi";
  }
  if (kind === "loading") {
    backBtn.hidden = true;
  }
  updatePrimaryButton();
}

function pollJob() {
  window.clearInterval(pollTimer);
  pollTimer = window.setInterval(async () => {
    try {
      const response = await fetch(`${API}/api/jobs/${jobId}`);
      if (!response.ok) throw new Error(await readError(response));
      const job = await response.json();
      if (job.status === "ready") {
        window.clearInterval(pollTimer);
        showResult("ready", { videoUrl: job.video_url || job.download_url });
      } else if (job.status === "failed") {
        window.clearInterval(pollTimer);
        showResult("error", { message: job.error_message });
      }
    } catch (error) {
      window.clearInterval(pollTimer);
      showResult("error", { message: error.message });
    }
  }, 1500);
}

function resetAll() {
  window.clearInterval(pollTimer);
  photos.fill(null);
  jobId = null;
  selectedTemplateId = null;
  resultVideo.removeAttribute("src");
  showResult("loading");
  renderPhotoSlots();
  setPage("photos");
}

primaryBtn.addEventListener("click", async () => {
  try {
    if (currentPage === "photos") {
      primaryBtn.disabled = true;
      primaryBtn.textContent = "Menyimpan foto...";
      await uploadPhotos();
      await loadTemplates();
      setPage("templates");
      return;
    }

    if (currentPage === "templates") {
      primaryBtn.disabled = true;
      primaryBtn.textContent = "Menyiapkan...";
      await chooseTemplateAndRender();
      setPage("result");
      showResult("loading");
      pollJob();
      return;
    }

    if (!readyState.hidden) {
      window.location.href = `${API}/api/jobs/${jobId}/download`;
      return;
    }

    if (!errorState.hidden) {
      resetAll();
    }
  } catch (error) {
    showToast(error.message);
    updatePrimaryButton();
  }
});

backBtn.addEventListener("click", () => {
  if (currentPage === "templates") {
    setPage("photos");
    return;
  }
  resetAll();
});

renderPhotoSlots();
setPage("photos");
