const $ = (id) => document.getElementById(id);
let current = null;

function showError(message) {
  $("error").textContent = message;
  $("error").hidden = !message;
}

function renderRows(rows) {
  $("rows").replaceChildren(
    ...rows.flatMap((row) => {
      const dt = document.createElement("dt");
      dt.textContent = row.label;
      const dd = document.createElement("dd");
      dd.textContent = row.value;
      dd.dataset.ok = String(row.ok);
      return [dt, dd];
    })
  );
}

async function pick(file) {
  if (!file) return;
  current = file;
  showError("");
  $("changes").replaceChildren();
  try {
    const info = await StudioMP4.analyze(file);
    $("fileName").textContent = file.name;
    renderRows(StudioMP4.report(info));
    $("result").hidden = false;
  } catch (err) {
    $("result").hidden = true;
    showError(err.message || String(err));
  }
}

$("file").addEventListener("change", (e) => pick(e.target.files[0]));

const drop = $("drop");
drop.addEventListener("dragover", (e) => {
  e.preventDefault();
  drop.classList.add("over");
});
drop.addEventListener("dragleave", () => drop.classList.remove("over"));
drop.addEventListener("drop", (e) => {
  e.preventDefault();
  drop.classList.remove("over");
  pick(e.dataTransfer.files[0]);
});

$("prepare").addEventListener("click", async () => {
  if (!current) return;
  const button = $("prepare");
  button.disabled = true;
  button.textContent = "Preparing...";
  try {
    const { blob, changes } = await StudioMP4.prepare(current, { stripMetadata: $("stripMetadata").checked });
    $("changes").replaceChildren(
      ...changes.map((text) => {
        const li = document.createElement("li");
        li.textContent = text;
        return li;
      })
    );
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = current.name.replace(/\.[^.]+$/, "") + "-studio.mp4";
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 60000);
  } catch (err) {
    showError(err.message || String(err));
  } finally {
    button.disabled = false;
    button.textContent = "Prepare and download";
  }
});
