"use strict";

const el = id => document.getElementById(id);
const esc = value => String(value ?? "").replace(/[&<>"']/g, part => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
})[part]);
const desk = "/turndesk";
const state = { project: null, slot: 0, capture: null, mode: "capture", proof: null, proofs: [],
  ring: null, interval: null, saving: false, exposure: null, noticeTimer: null };

async function api(path, method = "GET", data) {
  const options = {method};
  if (data instanceof FormData) {
    options.body = data;
  } else if (data !== undefined) {
    options.headers = {"Content-Type": "application/json"};
    options.body = JSON.stringify(data);
  }
  const response = await fetch(desk + path, options);
  const result = await response.json();
  if (!response.ok) throw Error(result.error || "操作失败");
  return result;
}

function notice(message) {
  el("notice").textContent = message;
  el("notice").hidden = false;
  clearTimeout(state.noticeTimer);
  state.noticeTimer = setTimeout(() => { el("notice").hidden = true; }, 3800);
}

function safe(action) {
  return async (...args) => {
    try {
      await action(...args);
    } catch (error) {
      notice(error.message);
    }
  };
}

function path(suffix = "") { return "/projects/" + state.project.id + suffix; }
function captureUrl(capture, raster = "source.png") { return desk + path("/captures/" + capture.id + "/" + raster); }
function button(label, action, style = "") { return `<button class="${style}" data-action="${action}">${label}</button>`; }

function setPlaying(playing) {
  clearInterval(state.interval);
  state.interval = playing ? setInterval(() => step(1), 740) : null;
}

function angleFrames() {
  if (state.proof) {
    return state.proof.frames.map(item => ({
      angle: item.angle, frame: item.capture, locked: item.locked, movement: item.movement_to_next,
    }));
  }
  const index = new Map(state.project.captures.map(capture => [capture.id, capture]));
  if (state.ring) {
    return state.ring.slots.map((item, i) => ({
      angle: item.angle, frame: index.get(item.capture), locked: item.locked,
      movement: state.ring.movements[i],
    }));
  }
  return state.project.slots.map(slot => ({angle: slot.angle, frame: index.get(slot.selected), locked: slot.locked}));
}

function selectSlot(index) {
  state.slot = index;
  state.capture = angleFrames()[index].frame?.id ?? null;
  state.exposure = null;
  render();
}

function step(direction) {
  const length = angleFrames().length;
  selectSlot((state.slot + direction + length) % length);
}

function switchMode(mode) {
  if (mode !== "playback") setPlaying(false);
  state.mode = mode;
  render();
}

function getCapture() {
  return state.project.captures.find(item => item.id === state.capture);
}

async function refreshProjects() {
  const records = await api("/projects");
  el("projects").innerHTML = records.map(record => `<button class="project-button"
    data-project="${record.id}" aria-current="${record.id === state.project?.id}">${esc(record.title)}</button>`).join("");
}

async function openProject(identifier, slot = 0, capture = null) {
  const record = await api("/projects/" + identifier);
  const proofs = await api("/projects/" + identifier + "/proofs");
  setPlaying(false);
  state.project = record;
  state.proofs = proofs;
  state.mode = "capture";
  state.proof = null;
  state.ring = null;
  const index = Math.min(record.slots.length - 1, Math.max(0, slot));
  state.slot = index;
  state.capture = record.captures.find(item => item.slot === index && item.id === capture)?.id ?? record.slots[index].selected;
  state.exposure = null;
  localStorage.setItem("turnproofProject", identifier);
  await refreshProjects();
  render();
}

async function createDemo() {
  const project = await api("/demo", "POST");
  await openProject(project.id);
}

async function change(suffix, method, data) {
  if (state.saving) return;
  state.saving = true;
  const identifier = state.project.id;
  try {
    let result;
    if (data instanceof FormData) {
      data.append("revision", state.project.revision);
      result = await api(path(suffix), method, data);
    } else {
      result = await api(path(suffix), method, {revision: state.project.revision, ...data});
    }
    if (state.project.id !== identifier) return;
    state.project = result.project || result;
    if (result.capture && result.capture.slot === state.slot) state.capture = result.capture.id;
    render();
  } finally {
    state.saving = false;
  }
}

function marker(frame) {
  if (!frame.mark) return "";
  const left = 100 * (frame.mark[0] + 0.5) / frame.width;
  const top = 100 * (frame.mark[1] + 0.5) / frame.height;
  return `<span class="mark" style="left:${left}%;top:${top}%" aria-hidden="true"></span>`;
}

function frameMarkup(frame, clickable = false) {
  if (!frame) return '<span class="stage-empty">这个台位还没有原片</span>';
  return `<div class="stage-image${clickable ? " clickable" : ""}" style="--ratio:${frame.width / frame.height}">
    <img src="${captureUrl(frame)}" width="${frame.width}" height="${frame.height}" alt="${esc(frame.name)}"${clickable ? ' id="captureRaster"' : ""}>
    ${marker(frame)}</div>`;
}

function preloadNext(frame) {
  if (frame) {
    const image = new Image();
    image.src = captureUrl(frame);
  }
}

function renderStage(frames, selected, next) {
  const actions = el("viewerActions");
  const detail = el("viewDetail");
  const stage = el("stage");
  for (const [id, mode] of [["viewCapture", "capture"], ["viewTransition", "transition"], ["viewPlayback", "playback"]]) {
    el(id).setAttribute("aria-pressed", String(state.mode === mode));
  }
  if (state.mode === "transition") {
    el("viewLabel").textContent = `${selected.angle}° → ${next.angle}°${next.angle === 0 ? " · 末回首" : ""}`;
    stage.innerHTML = `<div class="stage-grid"><figure>${frameMarkup(selected.frame)}
      <figcaption>${selected.angle}° · ${esc(selected.frame?.name || "无原片")}</figcaption></figure>
      <figure>${frameMarkup(next.frame)}<figcaption>${next.angle}° · ${esc(next.frame?.name || "无原片")}</figcaption></figure></div>`;
    detail.textContent = "正在读定位点";
    actions.innerHTML = button("上一对", "previous") + button("下一对", "next");
    const project = state.project.id, index = state.slot, revision = state.project.revision;
    const show = movement => {
      if (state.project.id !== project || state.slot !== index ||
        state.project.revision !== revision || state.mode !== "transition") return;
      detail.textContent = movement
        ? `落点移动 ${movement.drift.toFixed(2)}% · 横 ${movement.dx.toFixed(2)}% / 纵 ${movement.dy.toFixed(2)}%`
        : "两张原片都标记底座后可读移动";
    };
    if (state.proof || state.ring) {
      show(selected.movement);
    } else {
      api(path("/slots/" + index + "/transition")).then(result => show(result.movement)).catch(error => notice(error.message));
    }
    return;
  }

  el("viewLabel").textContent = selected.angle + "°";
  const frame = state.mode === "capture" && !state.proof && !state.ring ? getCapture() : selected.frame;
  stage.innerHTML = frameMarkup(frame, state.mode === "capture" && !state.proof && !state.ring);
  if (state.mode === "playback") {
    detail.textContent = `${state.slot + 1} / ${frames.length} · ${frame ? frame.name : "该台位缺片"}`;
    actions.innerHTML = button("上一张", "previous") + button(state.interval ? "暂停" : "循环播放", "play", "primary") + button("下一张", "next");
    preloadNext(next.frame);
    return;
  }

  if (state.ring) {
    detail.textContent = frame?.mark
      ? `推荐预览 · 定位点 x ${frame.mark[0].toFixed(0)} · y ${frame.mark[1].toFixed(0)}（只读）`
      : "推荐预览 · 该原片缺定位点";
    actions.innerHTML = frame
      ? `<a class="button" href="${captureUrl(frame)}?download" download>下载原片</a>` : "";
    return;
  }
  detail.textContent = frame?.mark
    ? `定位点 x ${frame.mark[0].toFixed(0)} · y ${frame.mark[1].toFixed(0)} · ${frame.width} × ${frame.height} px`
    : frame ? "在原片上点取底座的同一位置" : "可导入单张 PNG、JPEG 或 TIFF";
  actions.innerHTML = frame
    ? `<a class="button" href="${captureUrl(frame)}?download" download>下载原片</a>` : "";
}

function exposureMarkup() {
  if (!state.exposure) return "";
  const {histogram, bright, dark} = state.exposure;
  const max = Math.max(...histogram, 1);
  return `<div class="exposure-chart" aria-label="原照明度直方图">${histogram.map(value =>
    `<span style="height:${100 * value / max}%"></span>`).join("")}</div>
    <p>近白 ${bright.toFixed(2)}% · 近黑 ${dark.toFixed(2)}%</p>`;
}

function renderInspector(selected) {
  el("angleTag").textContent = selected.angle + "°";
  const inspector = el("inspector");
  if (state.ring) {
    const frame = selected.frame;
    const mark = frame.mark ? `x ${frame.mark[0]} · y ${frame.mark[1]}` : "未标底座";
    const movement = selected.movement;
    el("inspectorTitle").textContent = "推荐圈原片";
    inspector.innerHTML = `<strong>${esc(frame.name)}</strong><p>${frame.width} × ${frame.height} px · ${mark}</p>
      <p>${selected.locked ? "锁定台位" : "推荐采用"}${frame.preferred ? " · 细节首选" : ""}</p>
      <p>到下一台位落点移动 ${movement ? movement.drift.toFixed(2) + "% · 横 " + movement.dx.toFixed(2) + "% / 纵 " + movement.dy.toFixed(2) + "%" : "缺证"}</p>
      <p class="caption">预览不会改动工作台上的手选；确认封存后才写入封存稿。</p>
      <div class="action-row">${button("确认封存这一圈", "ringSeal", "primary")}${button("放弃推荐", "ringCancel")}</div>`;
    return;
  }
  if (state.proof) {
    const frame = selected.frame;
    const mark = frame.mark ? `x ${frame.mark[0]} · y ${frame.mark[1]}` : "未标底座";
    const suffix = "/proofs/" + state.proof.id;
    el("inspectorTitle").textContent = "封存原片";
    inspector.innerHTML = `<strong>${esc(frame.name)}</strong><p>${frame.width} × ${frame.height} px · ${mark}</p>
      <p>${selected.locked ? "锁定台位" : "已采用"}${frame.preferred ? " · 细节首选" : ""}</p>
      <p>封存来源 · 修订 ${state.proof.source_revision}</p>
      <div class="action-row"><a class="button primary" href="${desk + path(suffix + "/spin.zip")}" download>下载交付 ZIP</a></div>`;
    return;
  }

  el("inspectorTitle").textContent = "台位原片";
  const options = state.project.captures.filter(frame => frame.slot === state.slot);
  const capture = getCapture();
  const cards = options.map(frame => `<button class="capture" data-capture="${frame.id}" aria-current="${frame.id === state.capture}">
    <img src="${captureUrl(frame, "thumb.jpg")}" alt=""><span><b>${esc(frame.name)}</b>
    <small>${frame.id === selected.frame?.id ? "已采用" + (selected.locked ? " · 已锁" : "") : "补拍"}${frame.preferred ? " · 细节首选" : ""}</small></span></button>`).join("");
  const preference = capture?.preferred ? "取消细节首选" : "标为细节首选";
  const prep = new URLSearchParams({turntable: state.project.id, slot: state.slot});
  inspector.innerHTML = `<div class="capture-list">${cards || '<p>从一张照片开始。</p>'}</div>
    <div class="action-row">${button("＋ 导入原片", "upload")}${selected.frame ? button(selected.locked ? "解锁台位" : "锁定台位", "lock") : ""}</div>
    <a class="input-link" href="/prepare?${prep}">打开照片准备 ↗</a>
    ${capture ? `<div class="capture-info">
      ${capture.origin?.preparation_result ? '<p>来源 · 照片准备</p>' : ""}
      <div class="action-row">
        ${capture.id !== selected.frame?.id && !selected.locked ? button("采用此原片", "use", "primary") : ""}
        ${button(preference, "prefer")}
        ${capture.mark ? button("清除定位点", "clearMark") : ""}
        ${button("曝光检测", "exposure")}
      </div>
      ${exposureMarkup()}
    </div>` : ""}`;
}

function render() {
  el("empty").hidden = Boolean(state.project);
  el("workspace").hidden = !state.project;
  if (!state.project) return;

  const frames = angleFrames();
  const selected = frames[state.slot];
  const ready = frames.filter(slot => slot.frame).length;
  const next = frames[(state.slot + 1) % frames.length];
  el("projectTitle").textContent = state.proof?.title || state.project.title;
  el("projectStatus").textContent = state.proof ? "已封存 · " + state.project.title :
    `${state.project.synthetic ? "合成样片 · " : ""}${frames.length} 个台位 · 修订 ${state.project.revision}`;
  el("backToReview").hidden = !state.proof;
  el("seal").hidden = Boolean(state.proof) || Boolean(state.ring);
  el("ringPlan").hidden = Boolean(state.proof);
  el("seal").disabled = ready !== frames.length;
  el("ringBanner").hidden = !state.ring;
  if (state.ring) {
    el("ringSummary").textContent =
      `上限 ${state.ring.limit}% · 细节首选 ${state.ring.preferred_count} 张 · 最大单步 ${state.ring.worst_drift.toFixed(2)}%`;
  }
  el("coverage").textContent = `${ready} / ${frames.length} 台位已有原片`;
  el("filmstrip").innerHTML = frames.map((slot, index) => `<button class="shot" data-slot="${index}" aria-current="${state.slot === index}">
    ${slot.frame ? `<img src="${captureUrl(slot.frame, "thumb.jpg")}" alt="">` : '<span class="shot-placeholder"></span>'}
    <b>${slot.angle}° <span>${slot.locked ? "锁定" : ""}</span></b></button>`).join("");
  const strip = el("filmstrip");
  const focused = strip.querySelector('[aria-current="true"]');
  const bounds = strip.getBoundingClientRect();
  const shot = focused.getBoundingClientRect();
  if (shot.left < bounds.left) strip.scrollLeft -= bounds.left - shot.left + 7;
  if (shot.right > bounds.right) strip.scrollLeft += shot.right - bounds.right + 7;
  el("proofCount").textContent = state.proofs.length + " 份";
  el("proofs").innerHTML = state.proofs.map(proof => `<button data-proof="${proof.id}"
    aria-current="${state.proof?.id === proof.id}"><span class="proof-title">${esc(proof.title)}</span>
    <span class="proof-meta"> · 修订 ${proof.source_revision}</span></button>`).join("")
    || '<span class="caption">已采用一整圈原片后即可封存。</span>';
  renderStage(frames, selected, next);
  renderInspector(selected);
}

async function openProof(identifier) {
  const proof = await api(path("/proofs/" + identifier));
  setPlaying(false);
  state.proof = proof;
  state.ring = null;
  switchMode("playback");
}

function closeRing(refresh = true) {
  state.ring = null;
  state.exposure = null;
  state.capture = state.project.slots[state.slot]?.selected ?? null;
  if (refresh) {
    switchMode("capture");
  }
}

async function submitRing() {
  const limit = Number(el("ringLimit").value);
  const errorBox = el("ringError");
  errorBox.hidden = true;
  try {
    const result = await api(path("/ring-plan"), "POST", {limit});
    if (!result.feasible) {
      errorBox.textContent = result.message;
      errorBox.hidden = false;
      notice(result.message);
      return;
    }
    el("ringDialog").close();
    state.ring = result;
    state.exposure = null;
    selectSlot(0);
    switchMode("playback");
    notice(result.message);
  } catch (error) {
    errorBox.textContent = error.message;
    errorBox.hidden = false;
  }
}

async function sealRing() {
  if (state.saving || !state.ring) return;
  const selected = state.ring.slots.map(item => item.capture);
  state.saving = true;
  try {
    const proof = await api(path("/proofs"), "POST", {
      title: el("proofTitle").value, revision: state.project.revision, selected,
    });
    state.proofs = await api(path("/proofs"));
    state.ring = null;
    el("proofDialog").close();
    await openProof(proof.id);
    notice("已按推荐原片封存，可回看和下载；工作台手选保持不变。");
  } catch (error) {
    notice(error.message);
  } finally {
    state.saving = false;
  }
}

const actions = {
  upload: () => { el("upload").value = ""; el("upload").click(); },
  lock: () => change("/slots/" + state.slot, "PATCH", {locked: !state.project.slots[state.slot].locked}),
  use: () => change("/slots/" + state.slot, "PATCH", {selected: state.capture}),
  prefer: () => change("/captures/" + state.capture, "PATCH", {preferred: !getCapture().preferred}),
  clearMark: () => change("/captures/" + state.capture, "PATCH", {mark: null}),
  exposure: async () => {
    const capture = state.capture, project = state.project.id;
    const data = await api(path("/captures/" + capture + "/exposure"));
    if (state.capture !== capture || state.project.id !== project || state.proof) return;
    state.exposure = data;
    renderInspector(angleFrames()[state.slot]);
  },
  next: () => step(1),
  previous: () => step(-1),
  play: () => { setPlaying(!state.interval); render(); },
};

document.addEventListener("click", safe(async event => {
  const button = event.target.closest("button");
  if (!button) return;
  const {project, slot, capture, proof, action, close} = button.dataset;
  if (project) return openProject(project);
  if (slot !== undefined) return selectSlot(Number(slot));
  if (capture) {
    state.capture = capture;
    state.exposure = null;
    switchMode("capture");
  }
  if (proof) return openProof(proof);
  if (action) return actions[action]();
  if (close) el(close).close();
}));

el("newProject").onclick = () => el("newDialog").showModal();
el("demoProject").onclick = safe(createDemo);
el("emptyDemo").onclick = safe(createDemo);
el("viewCapture").onclick = () => switchMode("capture");
el("viewTransition").onclick = () => switchMode("transition");
el("viewPlayback").onclick = () => switchMode("playback");
el("backToReview").onclick = () => {
  state.proof = null;
  switchMode("capture");
  selectSlot(state.slot);
};
el("contact").onclick = safe(async () => {
  let url, objectUrl = null, downloadUrl = null;
  if (state.proof) {
    url = desk + path("/proofs/" + state.proof.id + "/contact.png");
  } else if (state.ring) {
    const response = await fetch(desk + path("/ring-contact"), {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({selected: state.ring.slots.map(item => item.capture)}),
    });
    if (!response.ok) throw Error((await response.json()).error || "联系表生成失败");
    objectUrl = URL.createObjectURL(await response.blob());
    url = objectUrl;
    downloadUrl = objectUrl;
  } else {
    url = desk + path("/contact.png");
  }
  el("contactImage").onload = null;
  el("contactImage").src = url + (objectUrl ? "" : "?revision=" + state.project.revision);
  el("contactDownload").href = downloadUrl || (url + "?download");
  el("contactDialog").showModal();
  el("contactDialog").onclose = () => { if (objectUrl) URL.revokeObjectURL(objectUrl); };
});
el("seal").onclick = () => {
  el("proofTitle").value = state.project.title + " · 检查稿";
  el("proofDialog").showModal();
};
el("ringPlan").onclick = () => {
  el("ringError").hidden = true;
  el("ringDialog").showModal();
};
el("ringForm").onsubmit = safe(event => {
  event.preventDefault();
  return submitRing();
});
el("ringCancel").onclick = () => closeRing();
el("ringSeal").onclick = () => {
  if (!state.ring) return;
  el("proofTitle").value = state.project.title + " · 合格圈";
  el("proofDialog").showModal();
};
el("proofForm").onsubmit = safe(async event => {
  event.preventDefault();
  if (state.ring) return sealRing();
  if (state.saving) return;
  state.saving = true;
  try {
    const proof = await api(path("/proofs"), "POST", {title: el("proofTitle").value, revision: state.project.revision});
    state.proofs = await api(path("/proofs"));
    el("proofDialog").close();
    await openProof(proof.id);
    notice("已封存，可回看和下载。");
  } finally {
    state.saving = false;
  }
});
el("projectForm").onsubmit = safe(async event => {
  event.preventDefault();
  const title = el("newTitle").value;
  const count = Number(el("newCount").value);
  const project = await api("/projects", "POST", {title, count});
  el("newDialog").close();
  await openProject(project.id);
});
el("upload").onchange = safe(async () => {
  const file = el("upload").files[0];
  if (!file) return;
  const data = new FormData();
  data.append("image", file);
  data.append("slot", state.slot);
  await change("/captures", "POST", data);
  switchMode("capture");
});
el("stage").onclick = safe(async event => {
  if (event.target.id !== "captureRaster") return;
  const image = event.target;
  const frame = getCapture();
  const rect = image.getBoundingClientRect();
  const x = Math.min(frame.width - 1, Math.max(0, Math.floor(frame.width * (event.clientX - rect.left) / rect.width)));
  const y = Math.min(frame.height - 1, Math.max(0, Math.floor(frame.height * (event.clientY - rect.top) / rect.height)));
  await change("/captures/" + frame.id, "PATCH", {mark: [x, y]});
});

safe(async () => {
  await refreshProjects();
  const options = new URLSearchParams(location.search);
  const chosen = options.get("turntable") || localStorage.getItem("turnproofProject");
  if (!chosen) return;
  if (![...el("projects").querySelectorAll("button")].some(button => button.dataset.project === chosen)) return;
  const slot = Number(options.get("slot") || 0);
  await openProject(chosen, Number.isInteger(slot) ? slot : 0, options.get("capture"));
  if (options.has("turntable")) history.replaceState(null, "", "/");
})();
