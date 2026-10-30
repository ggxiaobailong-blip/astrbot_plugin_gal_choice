const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => Array.from(document.querySelectorAll(selector));

const bridge = window.AstrBotPluginView;
let state = null;
let activeId = null;
let previewTimer = null;
let previewBusy = false;
let deleteArmed = false;
let deleteTimer = null;

const esc = (value) =>
  String(value ?? "").replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  })[ch]);

function toast(message, isError = false) {
  const el = $("#toast");
  el.textContent = message;
  el.classList.toggle("error", isError);
  el.hidden = false;
  clearTimeout(toast._timer);
  toast._timer = setTimeout(() => { el.hidden = true; }, 3200);
}

function activeProfile() {
  if (!state) return null;
  return state.characters.find((item) => item.id === activeId)
    || state.characters.find((item) => item.id === state.active)
    || state.characters[0]
    || null;
}

function applyState(next) {
  if (!next || !Array.isArray(next.characters)) return;
  state = next;
  activeId = state.characters.some((item) => item.id === activeId)
    ? activeId
    : state.active;
  renderCharacters();
  renderActiveProfile();
  renderBackgrounds();
  renderSettings();
  queuePreview();
}

async function apiGet(endpoint, params) {
  if (!bridge) throw new Error("没有检测到 AstrBot 插件页面桥接");
  return bridge.apiGet(endpoint, params);
}

async function apiPost(endpoint, body) {
  if (!bridge) throw new Error("没有检测到 AstrBot 插件页面桥接");
  return bridge.apiPost(endpoint, body);
}

async function uploadFile(endpoint, file) {
  if (!bridge) throw new Error("没有检测到 AstrBot 插件页面桥接");
  return bridge.upload(endpoint, file);
}

async function loadState() {
  try {
    const next = await apiGet("state");
    applyState(next);
  } catch (error) {
    toast(error?.message || "读取状态失败", true);
  }
}

function renderCharacters() {
  const list = $("#charList");
  if (!state) return;
  list.innerHTML = state.characters.map((profile) => {
    const preview = profile.default?.url || Object.values(profile.sprites || {}).find((s) => s.url)?.url || "";
    const avatar = preview
      ? `<img src="${esc(preview)}" alt="" />`
      : esc(profile.name.slice(0, 1));
    const active = profile.id === activeId ? " active" : "";
    return `
      <button class="char-card${active}" type="button" data-char="${esc(profile.id)}">
        <span class="char-avatar">${avatar}</span>
        <span class="char-meta">
          <span class="char-name">${esc(profile.name)}</span>
          <span class="char-sub">${profile.builtin ? "内置 · 只读" : "自定义 · 可上传"}</span>
        </span>
      </button>`;
  }).join("");
  $$(".char-card").forEach((button) => {
    button.addEventListener("click", () => activateCharacter(button.dataset.char));
  });
}

async function activateCharacter(id) {
  if (!id || id === activeId) return;
  try {
    const next = await apiPost("character/activate", { id });
    activeId = id;
    applyState(next);
  } catch (error) {
    toast(error?.message || "切换角色失败", true);
  }
}

function renderActiveProfile() {
  const profile = activeProfile();
  if (!profile) return;
  activeId = profile.id;
  $("#activeBadge").textContent = profile.builtin ? "内置角色" : profile.name;
  $("#deleteCharBtn").hidden = profile.builtin;
  resetDeleteButton();
  $("#charName").value = profile.name;
  $("#charName").disabled = profile.builtin;
  $("#renameCharBtn").disabled = profile.builtin;
  renderSprites(profile);
  renderLayout(profile);
  renderEmotionSelect(profile);
}

function resetDeleteButton() {
  clearTimeout(deleteTimer);
  deleteArmed = false;
  const button = $("#deleteCharBtn");
  button.textContent = "删除当前角色";
  button.classList.remove("armed");
}

function renderSprites(profile) {
  const grid = $("#spriteGrid");
  const groups = state?.emotion_groups || (state?.emotions || []).map((id) => ({ id, label: id, tag: id, tags: [] }));
  const files = profile.files || [];
  const slots = [
    { key: "default", label: "默认", sub: "没有匹配到情绪时" },
    ...groups.map((item) => ({ key: item.id, label: item.label, sub: item.tag, tags: item.tags || [] })),
  ];
  grid.innerHTML = slots.map((slot) => {
    const data = slot.key === "default"
      ? profile.default
      : profile.sprites?.[slot.key];
    const url = data?.url || "";
    const missing = !data?.file;
    const thumb = url
      ? `<img src="${esc(url)}" alt="" />`
      : `<span>${missing ? "未设置" : "无预览"}</span>`;
    let controls = "";
    if (!profile.builtin) {
      const options = [
        `<option value="">上传新图</option>`,
        ...files.map((file) => {
          const label = file.group
            ? `${(groups.find((g) => g.id === file.group) || {}).label || file.group} · ${file.label}`
            : file.label;
          const selected = data?.file === file.file ? " selected" : "";
          return `<option value="${esc(file.file)}"${selected}>${esc(label)}</option>`;
        }),
      ].join("");
      controls = `
        <label class="btn small ghost file-btn">上传
          <input type="file" accept="image/*" data-emotion="${esc(slot.key)}" hidden />
        </label>
        <select class="share-select" data-emotion="${esc(slot.key)}" title="把已上传的图共用给这个情绪">
          ${options}
        </select>`;
    } else {
      controls = `<span class="muted" style="font-size:11px">内置只读</span>`;
    }
    const tagHint = slot.tags?.length ? `${slot.tags.length} 个标签共用` : slot.sub;
    return `
      <div class="sprite-card">
        <div class="sprite-thumb${url ? "" : " empty"}">${thumb}</div>
        <div class="sprite-label">${esc(slot.label)} <em>${esc(missing && !profile.builtin ? "回退默认" : tagHint)}</em></div>
        ${controls}
      </div>`;
  }).join("");
  grid.querySelectorAll('input[type="file"]').forEach((input) => {
    input.addEventListener("change", () => {
      const file = input.files?.[0];
      if (file) uploadSprite(profile.id, input.dataset.emotion, file, input);
    });
  });
  grid.querySelectorAll(".share-select").forEach((select) => {
    select.addEventListener("change", () => {
      if (select.value) bindSprite(profile.id, select.dataset.emotion, select.value);
    });
  });
}

async function bindSprite(profileId, emotion, file) {
  try {
    const next = await apiPost("sprite/bind", { id: profileId, emotion, file });
    applyState(next);
    toast("已把这张立绘共用给该情绪");
    queuePreview(60);
  } catch (error) {
    toast(error?.message || "共用立绘失败", true);
  }
}

async function uploadSprite(profileId, emotion, file, input) {
  const endpoint = `upload/sprite/${profileId}/${emotion}`;
  try {
    input.disabled = true;
    const next = await uploadFile(endpoint, file);
    applyState(next);
    toast(`${emotion === "default" ? "默认立绘" : emotion + " 差分"}已上传`);
    queuePreview(60);
  } catch (error) {
    toast(error?.message || "上传失败", true);
  } finally {
    input.disabled = false;
    input.value = "";
  }
}

function renderLayout(profile) {
  const layout = profile.layout || {};
  const set = (id, value, labelId, suffix) => {
    const input = $(`#${id}`);
    input.value = value;
    const label = $(`#${labelId}`);
    if (label) label.textContent = `${value}${suffix}`;
  };
  set("left", layout.left ?? 31, "leftVal", "%");
  set("top", layout.top ?? 22, "topVal", "px");
  set("height", layout.height ?? 907, "heightVal", "px");
  set("maxWidth", layout.max_width ?? 62, "widthVal", "%");
}

function readLayout() {
  return {
    left: Number($("#left").value),
    top: Number($("#top").value),
    height: Number($("#height").value),
    max_width: Number($("#maxWidth").value),
  };
}

function bindLayoutLabels() {
  const bind = (id, labelId, suffix) => {
    const input = $(`#${id}`);
    input.addEventListener("input", () => {
      $(`#${labelId}`).textContent = `${input.value}${suffix}`;
      renderDraft();
    });
  };
  bind("left", "leftVal", "%");
  bind("top", "topVal", "px");
  bind("height", "heightVal", "px");
  bind("maxWidth", "widthVal", "%");
}

function renderEmotionSelect(profile) {
  const select = $("#previewEmotion");
  const groups = state?.emotion_groups || (state?.emotions || []).map((id) => ({ id, label: id }));
  const current = select.value || groups[0]?.id || "calm";
  select.innerHTML = groups.map((item) => `<option value="${esc(item.id)}">${esc(item.label)}</option>`).join("");
  select.value = groups.some((item) => item.id === current) ? current : (groups[0]?.id || "calm");
}

function renderBackgrounds() {
  const grid = $("#backgroundGrid");
  if (!state) return;
  const active = state.active_background || "";
  const cards = (state.backgrounds || []).map((bg) => `
    <button class="bg-card${bg.name === active ? " active" : ""}" type="button" data-bg="${esc(bg.name)}">
      <img src="${esc(bg.url)}" alt="" />
      <span class="bg-name">${esc(bg.label)}${bg.kind === "custom" ? " · 自定义" : ""}</span>
    </button>`).join("");
  grid.innerHTML = cards || `<p class="muted">还没有背景，上传一张吧。</p>`;
  grid.querySelectorAll(".bg-card").forEach((button) => {
    button.addEventListener("click", () => selectBackground(button.dataset.bg));
  });
  $("#backgroundMode").value = state.background_mode || "session";
}

async function selectBackground(name) {
  try {
    const next = await apiPost("background/select", { name });
    applyState(next);
    toast(name ? "背景已固定" : "已改为跟随背景模式");
  } catch (error) {
    toast(error?.message || "选择背景失败", true);
  }
}

function renderSettings() {
  if (!state) return;
  const settings = state.settings || {};
  $("#botLabel").value = settings.bot_label || "小鲸鱼";
  $("#freeHint").value = settings.free_option_hint || "✎ 自己说点什么…";
  $("#boxAlpha").value = settings.box_alpha ?? 0.94;
  $("#alphaVal").textContent = Number($("#boxAlpha").value).toFixed(2);
  $("#imageQuality").value = settings.image_quality ?? 90;
  $("#qualityVal").textContent = $("#imageQuality").value;
  $("#dialogueMaxLines").value = String(settings.dialogue_max_lines ?? 3);
  $("#voiceLineGap").value = settings.voice_line_gap_ms ?? 1000;
  $("#gapVal").textContent = `${$("#voiceLineGap").value}ms`;
  $("#debounceEnabled").checked = settings.gal_debounce_enabled ?? true;
  $("#debounceSeconds").value = settings.gal_debounce_seconds ?? 1;
  $("#debounceVal").textContent = `${Number($("#debounceSeconds").value).toFixed(1)}s`;
  $("#debounceMax").value = settings.gal_debounce_max_seconds ?? 5;
  $("#debounceMaxVal").textContent = `${Number($("#debounceMax").value).toFixed(1)}s`;
  $("#renderEndpoint").value = settings.render_endpoint || "";
  $("#backgroundMode").value = state.background_mode || "session";
}

function queuePreview(delay = 0) {
  clearTimeout(previewTimer);
  previewTimer = setTimeout(() => { renderDraft(); }, delay);
}

function showDraft() {
  $("#draftStage").hidden = false;
  $("#previewImage").hidden = true;
  $("#previewEmpty").hidden = true;
}

function renderDraft() {
  const profile = activeProfile();
  if (!profile || !state) return;
  const layout = readLayout();
  const emotion = $("#previewEmotion").value;
  const char = profile.sprites?.[emotion]?.url || profile.default?.url || "";
  const backgrounds = state.backgrounds || [];
  const bg = backgrounds.find((item) => item.name === state.active_background) || backgrounds[0];
  const bgImg = $("#draftBg");
  const charImg = $("#draftChar");
  const box = $("#draftCharBox");
  if (bgImg.getAttribute("src") !== (bg?.url || "")) bgImg.src = bg?.url || "";
  bgImg.hidden = !bg?.url;
  charImg.src = char;
  box.hidden = !char;
  box.style.left = `${layout.left}%`;
  box.style.top = `${(layout.top / 720) * 100}%`;
  box.style.width = `${layout.max_width}%`;
  box.style.height = `${(layout.height / 720) * 100}%`;
  $("#draftQuote").textContent = $("#previewQuote").value || "（玩家原话）";
  $("#draftSay").textContent = $("#previewSay").value || "（角色台词）";
  $("#draftSpeaker").textContent = (state.settings || {}).bot_label || "鲸鱼娘";
  showDraft();
}

async function renderPreview() {
  const profile = activeProfile();
  if (!profile || previewBusy) return;
  previewBusy = true;
  const empty = $("#previewEmpty");
  const image = $("#previewImage");
  empty.hidden = false;
  empty.textContent = "正在生成最终图…（通常 5~10 秒）";
  try {
    const result = await apiPost("preview", {
      quote: $("#previewQuote").value,
      say: $("#previewSay").value,
      emotion: $("#previewEmotion").value,
      layout: readLayout(),
      options: ["先从作息调整开始", "试试睡前放松练习", "聊聊压力和心事", "要不要看医生"],
    });
    if (!result?.url) throw new Error("预览没有返回图片");
    image.onload = () => { empty.hidden = true; };
    image.onerror = () => { empty.hidden = false; empty.textContent = "最终图加载失败"; image.hidden = true; };
    image.src = result.url;
    image.hidden = false;
    $("#draftStage").hidden = true;
    empty.hidden = true;
  } catch (error) {
    empty.hidden = true;
    toast(error?.message || "最终图生成失败", true);
  } finally {
    previewBusy = false;
  }
}

async function saveLayout() {
  const profile = activeProfile();
  if (!profile) return;
  try {
    const next = await apiPost("character/save", { id: profile.id, layout: readLayout() });
    applyState(next);
    toast("位置已保存");
  } catch (error) {
    toast(error?.message || "保存位置失败", true);
  }
}

async function saveSettings() {
  try {
    const next = await apiPost("settings/save", {
      bot_label: $("#botLabel").value,
      free_option_hint: $("#freeHint").value,
      box_alpha: Number($("#boxAlpha").value),
      image_quality: Number($("#imageQuality").value),
      dialogue_max_lines: Number($("#dialogueMaxLines").value),
      voice_line_gap_ms: Number($("#voiceLineGap").value),
      gal_debounce_enabled: $("#debounceEnabled").checked,
      gal_debounce_seconds: Number($("#debounceSeconds").value),
      gal_debounce_max_seconds: Number($("#debounceMax").value),
      render_endpoint: $("#renderEndpoint").value.trim(),
      background_mode: $("#backgroundMode").value,
    });
    applyState(next);
    toast("外观设置已保存");
  } catch (error) {
    toast(error?.message || "保存设置失败", true);
  }
}

function showCreateRow() {
  const row = $("#createRow");
  row.hidden = false;
  const input = $("#newCharName");
  input.value = "";
  input.focus();
}

function hideCreateRow() {
  $("#createRow").hidden = true;
}

async function createCharacter() {
  const input = $("#newCharName");
  const name = input.value.trim();
  if (!name) {
    toast("先给角色起个名字", true);
    input.focus();
    return;
  }
  try {
    const next = await apiPost("character/create", { name });
    hideCreateRow();
    applyState(next);
    toast("角色已创建，先上传默认立绘");
  } catch (error) {
    toast(error?.message || "新建角色失败", true);
  }
}

async function deleteCharacter() {
  const profile = activeProfile();
  if (!profile || profile.builtin) return;
  if (!deleteArmed) {
    deleteArmed = true;
    const button = $("#deleteCharBtn");
    button.textContent = "再点一次确认删除";
    button.classList.add("armed");
    clearTimeout(deleteTimer);
    deleteTimer = setTimeout(resetDeleteButton, 4000);
    toast(`确认删除「${profile.name}」？再点一次`);
    return;
  }
  resetDeleteButton();
  try {
    const next = await apiPost("character/delete", { id: profile.id });
    activeId = null;
    applyState(next);
    toast("角色已删除");
  } catch (error) {
    toast(error?.message || "删除角色失败", true);
  }
}

async function uploadBackground(file) {
  try {
    const next = await uploadFile("upload/background", file);
    applyState(next);
    const created = next?.background;
    if (created) {
      const selected = await apiPost("background/select", { name: created });
      applyState(selected);
    }
    toast("背景已上传并选中");
  } catch (error) {
    toast(error?.message || "上传背景失败", true);
  }
}

async function renameCharacter() {
  const profile = activeProfile();
  if (!profile || profile.builtin) return;
  const name = $("#charName").value.trim();
  if (!name) {
    toast("角色名不能为空", true);
    return;
  }
  try {
    const next = await apiPost("character/save", { id: profile.id, name });
    applyState(next);
    toast("角色名已更新");
  } catch (error) {
    toast(error?.message || "改名失败", true);
  }
}

function bindTabs() {
  $$(".tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      $$(".tab").forEach((item) => item.classList.toggle("active", item === tab));
      const name = tab.dataset.tab;
      ["role", "background", "appearance", "help"].forEach((key) => {
        $(`#panel-${key}`).hidden = key !== name;
      });
      if (name === "role") queuePreview(80);
    });
  });
}

function bindEvents() {
  $("#refreshBtn").addEventListener("click", loadState);
  $("#previewBtn").addEventListener("click", () => renderPreview());
  $("#saveLayoutBtn").addEventListener("click", saveLayout);
  $("#deleteCharBtn").addEventListener("click", deleteCharacter);
  $("#renameCharBtn").addEventListener("click", renameCharacter);
  $("#createCharBtn").addEventListener("click", showCreateRow);
  $("#confirmCreateBtn").addEventListener("click", createCharacter);
  $("#cancelCreateBtn").addEventListener("click", hideCreateRow);
  $("#newCharName").addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      createCharacter();
    } else if (event.key === "Escape") {
      hideCreateRow();
    }
  });
  $("#saveSettingsBtn").addEventListener("click", saveSettings);
  $("#followBgBtn").addEventListener("click", () => selectBackground(""));
  $("#backgroundUpload").addEventListener("change", (event) => {
    const file = event.target.files?.[0];
    if (file) uploadBackground(file);
    event.target.value = "";
  });
  $("#backgroundMode").addEventListener("change", saveSettings);
  $("#boxAlpha").addEventListener("input", () => {
    $("#alphaVal").textContent = Number($("#boxAlpha").value).toFixed(2);
  });
  $("#boxAlpha").addEventListener("change", () => queuePreview(0));
  $("#imageQuality").addEventListener("input", () => {
    $("#qualityVal").textContent = $("#imageQuality").value;
  });
  $("#voiceLineGap").addEventListener("input", () => {
    $("#gapVal").textContent = `${$("#voiceLineGap").value}ms`;
  });
  $("#debounceSeconds").addEventListener("input", () => {
    $("#debounceVal").textContent = `${Number($("#debounceSeconds").value).toFixed(1)}s`;
  });
  $("#debounceMax").addEventListener("input", () => {
    $("#debounceMaxVal").textContent = `${Number($("#debounceMax").value).toFixed(1)}s`;
  });
  $("#previewSay").addEventListener("input", () => queuePreview());
  $("#previewQuote").addEventListener("input", () => queuePreview());
  $("#previewEmotion").addEventListener("change", () => queuePreview(80));
  bindLayoutLabels();
  bindTabs();
}

async function init() {
  bindEvents();
  if (!bridge) {
    $("#previewEmpty").textContent = "没有检测到 AstrBot 插件页面桥接，请从插件详情页打开这个视图。";
    return;
  }
  try {
    await bridge.ready();
  } catch (error) {
    console.warn("bridge ready failed", error);
  }
  await loadState();
}

init();
