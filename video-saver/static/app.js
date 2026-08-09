/* 视频提取 —— 交互逻辑 */
(() => {
  "use strict";

  const $ = (s) => document.querySelector(s);

  const el = {
    form: $("#parseForm"),
    input: $("#linkInput"),
    submit: $("#submitBtn"),
    tip: $("#formTip"),
    result: $("#resultCard"),
    thumb: $("#thumb"),
    cover: $("#cover"),
    platformBadge: $("#platformBadge"),
    typeBadge: $("#typeBadge"),
    title: $("#resultTitle"),
    meta: $("#resultMeta"),
    downloadBtn: $("#downloadBtn"),
    progressWrap: $("#progressWrap"),
    progressFill: $("#progressFill"),
    progressText: $("#progressText"),
    doneWrap: $("#doneWrap"),
    doneText: $("#doneText"),
    saveLink: $("#saveLink"),
    cookieBtn: $("#cookieBtn"),
    cookieFile: $("#cookieFile"),
    cookieStatus: $("#cookieStatus"),
  };

  const state = { cookieId: null, parse: null, pollTimer: null };

  /* ---------- 提示 ---------- */
  function setTip(text, isErr) {
    el.tip.textContent = text || "";
    el.tip.classList.toggle("err", !!isErr);
  }

  function setLoading(loading) {
    el.submit.disabled = loading;
    el.submit.textContent = loading ? "解析中…" : "解析";
    el.input.disabled = loading;
    // 解析进行中禁用下载，避免误点旧结果
    el.downloadBtn.disabled = loading;
  }

  function fmtSize(bytes) {
    if (!bytes && bytes !== 0) return "";
    if (bytes < 1024) return bytes + " B";
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " KB";
    return (bytes / 1024 / 1024).toFixed(1) + " MB";
  }

  function setProgress(pct, text) {
    el.progressFill.style.width = Math.max(0, Math.min(100, pct)) + "%";
    el.progressText.textContent = text || "";
  }

  /* ---------- 解析 ---------- */
  el.form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const text = el.input.value.trim();
    if (!text) { setTip("请先粘贴分享链接", true); return; }

    setTip("");
    setLoading(true);
    try {
      const res = await fetch("/api/parse", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text, cookie_id: state.cookieId }),
      });
      const data = await res.json();
      if (!data.ok) { setTip(data.error || "解析失败", true); return; }
      state.parse = data.data;
      renderResult(data.data);
    } catch (err) {
      setTip("网络错误：" + err.message, true);
    } finally {
      setLoading(false);
    }
  });

  function renderResult(d) {
    if (d.cover) {
      const src = d.platform === "douyin"
        ? "/api/proxy?url=" + encodeURIComponent(d.cover)
        : d.cover;
      el.cover.onerror = () => { el.thumb.style.display = "none"; };
      el.cover.src = src;
      el.thumb.style.display = "";
    } else {
      el.thumb.style.display = "none";
    }

    el.platformBadge.textContent = d.platform_name || "其他平台";
    el.typeBadge.textContent = d.type === "images" ? "图文 · " + d.count + " 张" : "视频";
    el.title.textContent = d.title || "作品";
    el.meta.textContent = d.author ? "作者：" + d.author : "";

    el.result.classList.remove("hidden");
    el.downloadBtn.disabled = false;
    el.downloadBtn.textContent = "下载";
    el.progressWrap.classList.add("hidden");
    el.doneWrap.classList.add("hidden");
  }

  /* ---------- 下载 ---------- */
  el.downloadBtn.addEventListener("click", async () => {
    const d = state.parse;
    if (!d) return;

    el.downloadBtn.disabled = true;
    el.doneWrap.classList.add("hidden");
    el.progressWrap.classList.remove("hidden");
    setProgress(0, "正在准备…");
    setTip("");

    try {
      const res = await fetch("/api/download", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          platform: d.platform,
          type: d.type,
          title: d.title,
          urls: d.urls,
          source_url: d.source_url,
          cookie_id: state.cookieId,
        }),
      });
      const data = await res.json();
      if (!data.ok) { setTip(data.error || "下载失败", true); el.downloadBtn.disabled = false; return; }
      pollTask(data.task_id);
    } catch (err) {
      setTip("网络错误：" + err.message, true);
      el.downloadBtn.disabled = false;
    }
  });

  function pollTask(taskId) {
    clearInterval(state.pollTimer);
    state.pollTimer = setInterval(async () => {
      try {
        const res = await fetch("/api/task/" + taskId);
        const t = await res.json();
        if (t.status === "done") {
          clearInterval(state.pollTimer);
          el.progressWrap.classList.add("hidden");
          el.doneWrap.classList.remove("hidden");
          const size = t.filesize ? "（" + fmtSize(t.filesize) + "）" : "";
          el.doneText.textContent = "已保存：" + t.filename + size;
          el.saveLink.href = "/api/files/" + encodeURIComponent(t.filename);
        } else if (t.status === "error") {
          clearInterval(state.pollTimer);
          el.progressWrap.classList.add("hidden");
          setTip(t.error || "下载失败", true);
          el.downloadBtn.disabled = false;
          el.downloadBtn.textContent = "重试";
        } else if (typeof t.progress === "number") {
          const text = t.total ? fmtSize(t.downloaded) + " / " + fmtSize(t.total) : "下载中…";
          setProgress(t.progress, text);
        }
      } catch (err) {
        /* 轮询失败忽略，下一轮再试 */
      }
    }, 600);
  }

  /* ---------- Cookie ---------- */
  el.cookieBtn.addEventListener("click", () => el.cookieFile.click());

  el.cookieFile.addEventListener("change", async () => {
    const f = el.cookieFile.files[0];
    if (!f) return;
    const fd = new FormData();
    fd.append("file", f);
    try {
      const res = await fetch("/api/cookies", { method: "POST", body: fd });
      const d = await res.json();
      if (!d.ok) { setTip(d.error || "Cookie 上传失败", true); return; }
      state.cookieId = d.cookie_id;
      el.cookieStatus.classList.add("on");
      setTip("Cookie 已启用，重新解析即可");
    } catch (err) {
      setTip("Cookie 上传失败", true);
    }
    el.cookieFile.value = "";
  });
})();
