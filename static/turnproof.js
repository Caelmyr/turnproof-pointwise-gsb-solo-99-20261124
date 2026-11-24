"use strict";

const el = id => document.getElementById(id);
const esc = value => String(value ?? "").replace(/[&<>"']/g, part => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
})[part]);
const desk = "/turndesk";
const state = { project: null, slot: 0, capture: null, mode: "capture", proof: null, proofs: [],
  interval: null, saving: false, exposure: null, noticeTimer: null,
  cropPlan: null, cropProposal: null, viewSource: false };

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

function activeCropPlan() {
  if (state.proof) return state.proof.crop_plan || null;
  return state.cropPlan;
}

function cropUrl(slot) {
  const plan = activeCropPlan();
  if (!plan) return null;
  if (state.proof) {
    const entry = state.proof.frames[slot];
    return desk + path("/proofs/" + state.proof.id + "/frames/" + entry.angle + "/crop.png");
  }
  return desk + path("/slots/" + slot + "/crop.png?revision=" + state.project.revision);
}

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
  const crop = await api("/projects/" + identifier + "/crop-plan");
  setPlaying(false);
  state.project = record;
  state.proofs = proofs;
  state.mode = "capture";
  state.proof = null;
  state.cropPlan = crop.plan;
  state.cropProposal = null;
  state.viewSource = false;
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
    if (result.project) state.cropPlan = result.project.crop_plan || null;
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

function anchorMarker(plan, width, height) {
  const left = 100 * (plan.anchor[0] + 0.5) / width;
  const top = 100 * (plan.anchor[1] + 0.5) / height;
  return `<span class="mark anchor" style="left:${left}%;top:${top}%" aria-hidden="true"></span>`;
}

function frameMarkup(frame, clickable = false, cropPlan = null, slotIndex = state.slot, sourceFallback = false) {
  if (!frame) return '<span class="stage-empty">这个台位还没有原片</span>';
  if (cropPlan && !sourceFallback) {
    const window = cropPlan.frames.find(item => item.slot === slotIndex);
    if (window) {
      return `<div class="stage-image" style="--ratio:${window.width / window.height}">
        <img src="${cropUrl(slotIndex)}" width="${window.width}" height="${window.height}" alt="${esc(frame.name)} · 16:9 裁图">
        ${anchorMarker(cropPlan, window.width, window.height)}</div>`;
    }
  }
  return `<div class="stage-image${clickable ? " clickable" : ""}" style="--ratio:${frame.width / frame.height}">
    <img src="${captureUrl(frame)}" width="${frame.width}" height="${frame.height}" alt="${esc(frame.name)}"${clickable ? ' id="captureRaster"' : ""}>
    ${marker(frame)}</div>`;
}

function preloadNext(frame) {
  if (!frame) return;
  const plan = activeCropPlan();
  const nextIndex = (state.slot + 1) % angleFrames().length;
  const image = new Image();
  image.src = plan && !state.viewSource && cropUrl(nextIndex) ? cropUrl(nextIndex) : captureUrl(frame);
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
    stage.innerHTML = `<div class="stage-grid"><figure>${frameMarkup(selected.frame, false, null, state.slot)}
      <figcaption>${selected.angle}° · ${esc(selected.frame?.name || "无原片")}</figcaption></figure>
      <figure>${frameMarkup(next.frame, false, null, (state.slot + 1) % frames.length)}<figcaption>${next.angle}° · ${esc(next.frame?.name || "无原片")}</figcaption></figure></div>`;
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
    if (state.proof) {
      show(selected.movement);
    } else {
      api(path("/slots/" + index + "/transition")).then(result => show(result.movement)).catch(error => notice(error.message));
    }
    return;
  }

  el("viewLabel").textContent = selected.angle + "°";
  const plan = activeCropPlan();
  const frame = state.mode === "capture" && !state.proof ? getCapture() : selected.frame;
  if (state.mode === "capture" && !state.proof) {
    stage.innerHTML = frameMarkup(frame, true);
  } else {
    stage.innerHTML = frameMarkup(frame, false, plan, state.slot, state.viewSource);
  }
  if (state.mode === "playback") {
    detail.textContent = `${state.slot + 1} / ${frames.length} · ${frame ? frame.name : "该台位缺片"}`;
    const toggle = plan
      ? button(state.viewSource ? "看 16:9 裁图" : "切回原片核对底座", "toggleView", "primary")
      : "";
    actions.innerHTML = button("上一张", "previous") + button(state.interval ? "暂停" : "循环播放", "play", "primary")
      + button("下一张", "next") + toggle;
    preloadNext(next.frame);
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
  if (state.proof) {
    const frame = selected.frame;
    const mark = frame.mark ? `x ${frame.mark[0]} · y ${frame.mark[1]}` : "未标底座";
    const suffix = "/proofs/" + state.proof.id;
    el("inspectorTitle").textContent = "封存原片";
    const crop = state.proof.crop_plan;
    const cropLine = crop
      ? `<p>16:9 裁图 ${crop.width} × ${crop.height} px · 底座同点 x ${crop.anchor[0]} · y ${crop.anchor[1]}</p>
         <div class="action-row"><a class="button" href="${desk + path("/proofs/" + state.proof.id + "/frames/" + selected.angle + "/crop.png?download")}" download>下载本角度 PNG</a>
         <a class="button" href="${desk + path("/proofs/" + state.proof.id + "/frames/" + selected.angle + "/source.png?download")}" download>下载原片</a></div>`
      : "";
    inspector.innerHTML = `<strong>${esc(frame.name)}</strong><p>${frame.width} × ${frame.height} px · ${mark}</p>
      <p>${selected.locked ? "锁定台位" : "已采用"}${frame.preferred ? " · 细节首选" : ""}</p>
      <p>封存来源 · 修订 ${state.proof.source_revision}</p>${cropLine}
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
  const cropStatus = state.cropPlan
    ? `<div class="crop-status"><p>已确认 16:9 裁窗 ${state.cropPlan.width} × ${state.cropPlan.height} px · 底座同点 x ${state.cropPlan.anchor[0]} · y ${state.cropPlan.anchor[1]}</p>
       <div class="action-row">${button("清除裁窗重算", "clearCrop")}</div></div>`
    : '<p class="caption">顶部「16:9 裁窗」可按构图落点统一规划。</p>';
  inspector.innerHTML = `<div class="capture-list">${cards || '<p>从一张照片开始。</p>'}</div>
    <div class="action-row">${button("＋ 导入原片", "upload")}${selected.frame ? button(selected.locked ? "解锁台位" : "锁定台位", "lock") : ""}</div>
    <a class="input-link" href="/prepare?${prep}">打开照片准备 ↗</a>
    ${cropStatus}
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
  el("seal").hidden = Boolean(state.proof);
  el("seal").disabled = ready !== frames.length;
  el("cropPlan").hidden = Boolean(state.proof);
  el("coverage").textContent = `${ready} / ${frames.length} 台位已有原片`
    + (state.cropPlan ? ` · 16:9 裁窗 ${state.cropPlan.width}×${state.cropPlan.height}` : "");
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
  state.viewSource = false;
  switchMode("playback");
}

const actions = {
  upload: () => { el("upload").value = ""; el("upload").click(); },
  lock: () => change("/slots/" + state.slot, "PATCH", {locked: !state.project.slots[state.slot].locked}),
  use: () => change("/slots/" + state.slot, "PATCH", {selected: state.capture}),
  prefer: () => change("/captures/" + state.capture, "PATCH", {preferred: !getCapture().preferred}),
  clearMark: () => change("/captures/" + state.capture, "PATCH", {mark: null}),
  clearCrop: safe(async () => {
    state.project = await api(path("/crop-plan"), "DELETE", {revision: state.project.revision});
    state.cropPlan = null;
    state.cropProposal = null;
    render();
    notice("已清除裁窗，手选照片原样保留。");
  }),
  toggleView: () => { state.viewSource = !state.viewSource; render(); },
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
  state.viewSource = false;
  switchMode("capture");
  selectSlot(state.slot);
};
el("contact").onclick = () => {
  const suffix = state.proof ? "/proofs/" + state.proof.id + "/contact.png" : "/contact.png";
  const url = desk + path(suffix);
  el("contactImage").src = url + "?revision=" + state.project.revision;
  el("contactDownload").href = url + "?download";
  el("contactDialog").showModal();
};
el("seal").onclick = () => {
  el("proofTitle").value = state.project.title + " · 检查稿";
  el("proofDialog").showModal();
};

function cropInputs() {
  return {
    anchor_x: Number(el("cropAnchorX").value),
    anchor_y: Number(el("cropAnchorY").value),
    tolerance: Number(el("cropTolerance").value),
  };
}

function blockedMarkup(blocked) {
  if (blocked.kind === "incomplete") {
    const frames = blocked.missing_frames.map(angle => `<li>${angle}° 台位还没有采用原片</li>`).join("");
    const marks = blocked.missing_marks.map(item => `<li>${item.angle}° · ${esc(item.name)} 未标底座定位点</li>`).join("");
    return `<div class="crop-blocked"><strong>这次交付被挡住了：</strong><ul>${frames}${marks}</ul>
      <p class="caption">手选照片原样保留，补齐后重新计算即可。</p></div>`;
  }
  const top = blocked.at_largest_window;
  const vertical = top.details.filter(item => !item.vertical_ok)
    .map(item => `<li>${item.angle}°：纵向落点需要 y=${top.anchor_y_px}px，底座 y=${item.mark[1]} 超出原片上下余量</li>`).join("");
  const horizontal = top.details.filter(item => !item.within_tolerance)
    .map(item => `<li>${item.angle}°：横向可行锚点 ${item.anchor_x_range[0]}–${item.anchor_x_range[1]}px，落在容许带 ${blocked.at_largest_window.tolerance_band.join("–")}px 之外</li>`).join("");
  const clash = top.image_intersection === null
    ? `<li>各台位要求的横向锚点没有共同像素区间（最大尝试窗口 ${top.window.join("×")}）</li>` : "";
  return `<div class="crop-blocked"><strong>找不到一组都能裁出来的窗口：</strong><ul>${vertical}${horizontal}${clash}</ul>
    <p class="caption">可放宽横向容许百分点或调整构图落点后重试；原片与手选不会被改动。</p></div>`;
}

function cropResultMarkup(plan) {
  return `<div class="crop-ok">
    <strong>统一裁窗 ${plan.width} × ${plan.height} px · 16:9</strong>
    <p>底座在每张成图的同一像素：x ${plan.anchor[0]} · y ${plan.anchor[1]}
      （横向 ${plan.anchor_pct[0]}% · 纵向 ${plan.anchor_pct[1]}%）</p>
    <p class="caption">每台位窗口都在各自原片内，无缩放、无补边。确认后在循环回看里检查。</p>
  </div>`;
}

el("cropPlan").onclick = () => {
  el("cropResult").hidden = true;
  el("cropResult").innerHTML = "";
  state.cropProposal = state.cropPlan;
  el("cropConfirm").disabled = !state.cropPlan;
  if (state.cropPlan) {
    el("cropResult").innerHTML = cropResultMarkup(state.cropPlan);
    el("cropResult").hidden = false;
  }
  el("cropDialog").showModal();
};

el("cropCalc").onclick = safe(async () => {
  const result = await api(path("/crop-plan"), "POST", {revision: state.project.revision, ...cropInputs()});
  el("cropResult").hidden = false;
  if (result.plan) {
    state.cropProposal = result.plan;
    el("cropResult").innerHTML = cropResultMarkup(result.plan);
    el("cropConfirm").disabled = false;
  } else {
    state.cropProposal = null;
    el("cropResult").innerHTML = blockedMarkup(result.blocked);
    el("cropConfirm").disabled = true;
  }
});

el("cropForm").onsubmit = safe(async event => {
  event.preventDefault();
  if (!state.cropProposal) return;
  state.project = await api(path("/crop-plan"), "PUT",
    {revision: state.project.revision, plan: state.cropProposal});
  state.cropPlan = state.project.crop_plan;
  state.viewSource = false;
  el("cropDialog").close();
  switchMode("playback");
  notice("裁窗已确认，可在循环回看里切原片核对底座。");
});
el("projectForm").onsubmit = safe(async event => {
  event.preventDefault();
  const title = el("newTitle").value;
  const count = Number(el("newCount").value);
  const project = await api("/projects", "POST", {title, count});
  el("newDialog").close();
  await openProject(project.id);
});
el("proofForm").onsubmit = safe(async event => {
  event.preventDefault();
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
