// 影藏 PolyFlix —— 前端逻辑

const state = {
    mp4: null,
    hiddenFiles: [],
    config: { outerPassword: "", innerArchive: "none", innerPassword: "" }
};

// ---- 页脚年份 + 版本号 ----
document.getElementById("year").textContent = new Date().getFullYear();
fetch("/api/version").then(r => r.json()).then(d => {
    const el = document.getElementById("version");
    if (el && d.version) el.textContent = "v" + d.version;
}).catch(() => {});

// ---- 文件大小格式化 ----
function fmtSize(b) {
    if (b < 1024) return b + " B";
    if (b < 1048576) return (b / 1024).toFixed(1) + " KB";
    if (b < 1073741824) return (b / 1048576).toFixed(2) + " MB";
    return (b / 1073741824).toFixed(2) + " GB";
}

function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, c => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
    }[c]));
}

function nowTime() {
    return new Date().toTimeString().slice(0, 8);
}

// ---- 拖放区 ----
function setupDropZone(zoneId, inputId, onFiles) {
    const zone = document.getElementById(zoneId);
    const input = document.getElementById(inputId);

    zone.addEventListener("click", () => input.click());
    input.addEventListener("change", () => { if (input.files.length) onFiles(input.files); });

    ["dragenter", "dragover"].forEach(e => zone.addEventListener(e, ev => {
        ev.preventDefault(); zone.classList.add("dragover");
    }));
    ["dragleave", "drop"].forEach(e => zone.addEventListener(e, ev => {
        ev.preventDefault(); zone.classList.remove("dragover");
    }));
    zone.addEventListener("drop", e => {
        if (e.dataTransfer.files.length) onFiles(e.dataTransfer.files);
    });
}

// MP4 选择
setupDropZone("dz-mp4", "input-mp4", files => {
    state.mp4 = files[0];
    document.getElementById("mp4-info").textContent = `${state.mp4.name} · ${fmtSize(state.mp4.size)}`;
    document.getElementById("mp4-name").textContent = state.mp4.name;
    addClientLog(`选择伪装视频: ${state.mp4.name} (${fmtSize(state.mp4.size)})`);
});

// 隐藏文件选择
setupDropZone("dz-hidden", "input-hidden", files => {
    state.hiddenFiles = Array.from(files);
    document.getElementById("hidden-info").innerHTML =
        state.hiddenFiles.map(f => `<div>${f.name} · ${fmtSize(f.size)}</div>`).join("");
    document.getElementById("files-desc").textContent = `${state.hiddenFiles.length} 个文件`;
    addClientLog(`选择隐藏文件: ${state.hiddenFiles.length} 个`);
    state.hiddenFiles.forEach(f => addClientLog(`  └ ${f.name} (${fmtSize(f.size)})`));
});

// ---- 配置控件 ----
const outerPwEnable = document.getElementById("outer-pw-enable");
const outerPw = document.getElementById("outer-pw");
const innerPw = document.getElementById("inner-pw");
const innerRadios = document.querySelectorAll('input[name="inner"]');
const splitGroup = document.getElementById("split-group");
const splitEnable = document.getElementById("split-enable");
const splitSize = document.getElementById("split-size");
const splitUnit = document.getElementById("split-unit");
const compression = document.getElementById("compression");

outerPwEnable.addEventListener("change", () => {
    outerPw.disabled = !outerPwEnable.checked;
    if (!outerPwEnable.checked) outerPw.value = "";
    updateDiagram();
});

innerRadios.forEach(r => r.addEventListener("change", () => {
    const val = document.querySelector('input[name="inner"]:checked').value;
    innerPw.disabled = (val === "none");
    if (val === "none") innerPw.value = "";
    splitEnable.disabled = (val === "none");
    if (val === "none") { splitEnable.checked = false; splitSize.disabled = true; splitUnit.disabled = true; }
    updateDiagram();
}));

splitEnable.addEventListener("change", () => {
    splitSize.disabled = !splitEnable.checked;
    splitUnit.disabled = !splitEnable.checked;
    if (!splitEnable.checked) splitSize.value = "1";
    updateDiagram();
});
splitSize.addEventListener("input", updateDiagram);
splitUnit.addEventListener("change", updateDiagram);
compression.addEventListener("change", updateDiagram);

function updateDiagram() {
    const val = document.querySelector('input[name="inner"]:checked').value;
    const innerLayer = document.getElementById("layer-inner");
    const filesLayer = document.querySelector(".layer-files");

    splitGroup.style.display = (val === "none") ? "none" : "block";

    if (val === "none") {
        innerLayer.style.display = "none";
        filesLayer.style.marginLeft = "22px";   // 缩进 1 级（在 ZIP 外层下）
    } else {
        innerLayer.style.display = "flex";
        filesLayer.style.marginLeft = "44px";   // 缩进 2 级（在内层下）
        document.getElementById("inner-name").textContent = val === "7z" ? "7z 内层" : "ZIP 内层";
        let desc = val === "7z" ? "用 7-Zip 打开" : "再解压一层";
        if (!splitEnable.disabled && splitEnable.checked) {
            desc += `，分卷 ${splitSize.value || 100}${splitUnit.value === "gb" ? "GB" : "MB"}/卷`;
        }
        document.getElementById("inner-desc").textContent = desc;
    }

    document.getElementById("inner-lock").style.display =
        (val !== "none" && innerPw.value) ? "inline" : "none";
    document.getElementById("outer-lock").style.display =
        (outerPwEnable.checked && outerPw.value) ? "inline" : "none";

    const hint = document.getElementById("hint");
    const splitUnitLabel = splitUnit.value === "gb" ? "GB" : "MB";
    const splitHint = (!splitEnable.disabled && splitEnable.checked) ? `，内层分卷 ${splitSize.value || 100}${splitUnitLabel}` : "";
    const compName = { store: "存储", fastest: "最快", fast: "较快", normal: "标准", good: "较好", best: "最好" }[compression.value] || "标准";
    if (val === "none" && !outerPwEnable.checked) {
        hint.textContent = `当前：MP4 + ZIP（${compName}，无密码）。选 7z/ZIP 可加内层密码、分卷。`;
    } else if (val === "none") {
        hint.textContent = `当前：MP4 + 带密码 ZIP（${compName}）。选 7z/ZIP 可再加内层密码、分卷。`;
    } else if (val === "7z") {
        hint.textContent = `当前：MP4 + ZIP + 7z（${compName}）${splitHint}。`;
    } else {
        hint.textContent = `当前：MP4 + ZIP + ZIP（${compName}）${splitHint}。`;
    }
}

outerPw.addEventListener("input", updateDiagram);
innerPw.addEventListener("input", updateDiagram);
updateDiagram();

// ---- 日志系统：客户端日志 + 服务端日志合并显示 ----
const logPanel = document.getElementById("log-panel");
const logBox = document.getElementById("debug-log");
const logClear = document.getElementById("log-clear");
const logCopy = document.getElementById("log-copy");
const logExport = document.getElementById("log-export");

// 统一日志条目数组：{t, level, msg, source: 'client'|'server'}
let logEntries = [];
let logPanelVisible = false;
let pollTimer = null;

function addClientLog(msg, level = "info") {
    logEntries.push({ t: nowTime(), level, msg, source: "client" });
    if (logPanelVisible) renderLog();
}

async function syncServerLog() {
    try {
        const r = await fetch("/api/log");
        const data = await r.json();
        const serverLog = data.log || [];
        // 去掉旧的服务端条目，追加最新拉取的
        logEntries = logEntries.filter(e => e.source !== "server");
        serverLog.forEach(e => logEntries.push({ ...e, source: "server" }));
        if (logPanelVisible) renderLog();
        // 根据服务端日志推断构建进度
        updateProgressFromLog(serverLog);
    } catch (e) { /* ignore */ }
}

function renderLog() {
    if (!logEntries.length) {
        logBox.innerHTML = '<span class="log-time">（暂无日志）</span>';
        return;
    }
    logBox.innerHTML = logEntries.map(e => {
        let cls = "";
        if (e.level === "error") cls = "log-err";
        else if (String(e.msg).includes("成功")) cls = "log-ok";
        const tag = e.source === "client" ? '<span class="log-client">[客户端]</span> ' : "";
        return `<span class="log-line"><span class="log-time">[${e.t}]</span> ${tag}<span class="${cls}">${escapeHtml(e.msg)}</span></span>`;
    }).join("\n");
    logBox.scrollTop = logBox.scrollHeight;
}

function logToText() {
    return logEntries.map(e => {
        const tag = e.source === "client" ? "[客户端]" : "[服务端]";
        return `[${e.t}] ${tag} ${e.msg}`;
    }).join("\n");
}

function toggleLogPanel() {
    logPanelVisible = !logPanelVisible;
    logPanel.classList.toggle("visible", logPanelVisible);
    document.body.classList.toggle("log-open", logPanelVisible);
    if (logPanelVisible) {
        syncServerLog();
        renderLog();
    }
}

// Ctrl+F9 切换日志面板
document.addEventListener("keydown", (e) => {
    if (e.ctrlKey && (e.key === "F9" || e.key === "f9" || e.keyCode === 120)) {
        e.preventDefault();
        toggleLogPanel();
    }
});

function startPolling() {
    if (pollTimer) return;
    pollTimer = setInterval(syncServerLog, 600);
}
function stopPolling() {
    if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
    syncServerLog();
}

logClear.addEventListener("click", async () => {
    try {
        await fetch("/api/log/clear", { method: "POST" });
    } catch (e) { /* ignore */ }
    logEntries = [];
    renderLog();
});

logCopy.addEventListener("click", async () => {
    const text = logToText();
    if (!text) { alert("日志为空"); return; }
    try {
        await navigator.clipboard.writeText(text);
        const orig = logCopy.textContent;
        logCopy.textContent = "已复制 ✓";
        setTimeout(() => logCopy.textContent = orig, 1500);
    } catch (e) {
        const ta = document.createElement("textarea");
        ta.value = text;
        document.body.appendChild(ta);
        ta.select();
        try { document.execCommand("copy"); logCopy.textContent = "已复制 ✓"; setTimeout(() => logCopy.textContent = "复制", 1500); }
        catch (_) { alert("复制失败，请手动选中复制"); }
        document.body.removeChild(ta);
    }
});

logExport.addEventListener("click", () => {
    const text = logToText();
    if (!text) { alert("日志为空"); return; }
    const blob = new Blob([text], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    const ts = new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19);
    a.href = url;
    a.download = `polyflix_log_${ts}.txt`;
    a.click();
    URL.revokeObjectURL(url);
});

// ---- 构建结果区 ----
const resultBox = document.getElementById("result");
const resultIcon = document.getElementById("result-icon");
const resultTitle = document.getElementById("result-title");
const resultDetail = document.getElementById("result-detail");
const redownloadBtn = document.getElementById("redownload-btn");
let lastDownloadUrl = null;
let lastDownloadName = null;

function triggerNativeDownload(url, name) {
    const a = document.createElement("a");
    a.href = url;
    a.download = name;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
}

redownloadBtn.addEventListener("click", () => {
    if (lastDownloadUrl) {
        triggerNativeDownload(lastDownloadUrl, lastDownloadName);
        addClientLog(`重新下载: ${lastDownloadName}`);
    }
});

function showResult(ok, title, detailHtml) {
    resultBox.classList.add("shown");
    resultBox.classList.toggle("error", !ok);
    resultIcon.textContent = ok ? "✅" : "❌";
    resultTitle.textContent = title;
    resultDetail.innerHTML = detailHtml;
    redownloadBtn.style.display = "none";
    document.getElementById("result-time").textContent = formatElapsed();
}

// ---- 进度条 ----
const progressBar = document.getElementById("progress-bar");
const progressFill = document.getElementById("progress-fill");
const progressLabel = document.getElementById("progress-label");
const progressTimerEl = document.getElementById("progress-timer");
let progressTarget = 0;
let progressCurrent = 0;
let progressSimTimer = null;   // 进度模拟器
let progressClockTimer = null; // 已用时计时器
let progressStartTime = null;
let progressActive = false;

function updateProgressFill() {
    progressFill.style.width = progressCurrent.toFixed(1) + "%";
}

function updateProgressClock() {
    if (!progressStartTime) { progressTimerEl.textContent = ""; return; }
    const sec = Math.floor((Date.now() - progressStartTime) / 1000);
    const m = Math.floor(sec / 60);
    const s = sec % 60;
    progressTimerEl.textContent = `已用时 ${m}:${s.toString().padStart(2, "0")}`;
}

function formatElapsed() {
    if (!progressStartTime) return "";
    const sec = Math.floor((Date.now() - progressStartTime) / 1000);
    const m = Math.floor(sec / 60);
    const s = sec % 60;
    return `已用时 ${m}:${s.toString().padStart(2, "0")}`;
}

function setProgressStage(pct, label) {
    if (pct > progressTarget) progressTarget = pct;
    if (label) progressLabel.textContent = label;
}

function startProgress() {
    progressActive = true;
    progressTarget = 5;
    progressCurrent = 0;
    progressStartTime = Date.now();
    progressLabel.textContent = "已收到请求…";
    updateProgressFill();
    updateProgressClock();
    if (progressSimTimer) clearInterval(progressSimTimer);
    if (progressClockTimer) clearInterval(progressClockTimer);
    progressSimTimer = setInterval(() => {
        const gap = progressTarget - progressCurrent;
        if (gap > 0.15) {
            // 平滑逼近目标，加一点常数让它不停滞
            progressCurrent += gap * 0.07 + 0.15;
            if (progressCurrent > progressTarget) progressCurrent = progressTarget;
            updateProgressFill();
        }
    }, 300);
    progressClockTimer = setInterval(updateProgressClock, 1000);
}

function finishProgress(ok) {
    progressActive = false;
    if (progressSimTimer) { clearInterval(progressSimTimer); progressSimTimer = null; }
    if (progressClockTimer) { clearInterval(progressClockTimer); progressClockTimer = null; }
    progressCurrent = 100;
    progressTarget = 100;
    updateProgressFill();
    progressLabel.textContent = ok ? "完成 ✓" : "构建失败";
    // 保留最终用时显示 1.2 秒后重置为就绪
    setTimeout(() => {
        progressFill.style.width = "0%";
        progressCurrent = 0;
        progressTarget = 0;
        progressLabel.textContent = "就绪";
        progressTimerEl.textContent = "";
        progressStartTime = null;
    }, 1200);
}

// 根据服务端日志关键词推断当前阶段
function updateProgressFromLog(serverLog) {
    if (!progressActive) return;
    const text = serverLog.map(e => String(e.msg)).join("\n");
    const stages = [
        { kw: "构建成功", pct: 100, label: "完成 ✓" },
        { kw: "下载 ID", pct: 95, label: "准备下载…" },
        { kw: "拼接:", pct: 90, label: "拼接 MP4 + ZIP…" },
        { kw: "外层 ZIP 完成", pct: 80, label: "外层打包完成…" },
        { kw: "外层 ZIP: 条目数", pct: 58, label: "正在创建外层 ZIP…" },
        { kw: "内层已分卷", pct: 55, label: "内层分卷完成…" },
        { kw: "内层压缩包:", pct: 52, label: "内层打包完成…" },
        { kw: "无内层", pct: 50, label: "正在创建外层 ZIP…" },
        { kw: "磁盘空间", pct: 38, label: "检查磁盘空间…" },
        { kw: "写入临时文件", pct: 35, label: "正在接收隐藏文件…" },
        { kw: "MP4 保存完成", pct: 22, label: "视频已接收，等待隐藏文件…" },
        { kw: "收到构建请求", pct: 8, label: "已收到请求…" },
    ];
    for (const s of stages) {
        if (text.includes(s.kw)) { setProgressStage(s.pct, s.label); break; }
    }
    // 磁盘空间不足警告
    const sizeHint = document.getElementById("size-hint");
    if (text.includes("磁盘空间不足")) {
        sizeHint.classList.add("warn");
        sizeHint.innerHTML = "⚠️ 磁盘空间不足，构建可能失败！请清理磁盘或选择&ldquo;存储&rdquo;方式。";
    }
}

// ---- 构建 ----
document.getElementById("build-btn").addEventListener("click", async () => {
    if (!state.mp4) { alert("请先选择伪装视频 MP4"); return; }
    if (state.hiddenFiles.length === 0) { alert("请选择要隐藏的文件"); return; }

    const innerVal = document.querySelector('input[name="inner"]:checked').value;
    const splitVal = parseInt(splitSize.value) || 100;
    const splitMB = splitUnit.value === "gb" ? splitVal * 1024 : splitVal;
    state.config = {
        outerPassword: outerPwEnable.checked ? outerPw.value : "",
        innerArchive: innerVal,
        innerPassword: innerVal !== "none" ? innerPw.value : "",
        splitVolume: innerVal !== "none" && splitEnable.checked,
        splitSizeMB: innerVal !== "none" && splitEnable.checked ? splitMB : 0,
        compression: compression.value
    };

    const compName = { store: "存储", fastest: "最快", fast: "较快", normal: "标准", good: "较好", best: "最好" }[compression.value] || "标准";

    addClientLog(`========== 开始构建 ==========`);
    addClientLog(`伪装视频: ${state.mp4.name}`);
    addClientLog(`隐藏文件: ${state.hiddenFiles.length} 个`);
    addClientLog(`配置: 内层=${innerVal}, 压缩=${compName}, 外层密码=${state.config.outerPassword ? "是" : "否"}, 内层密码=${state.config.innerPassword ? "是" : "否"}, 分卷=${state.config.splitVolume ? splitMB + "MB/卷" : "否"}`);

    const fd = new FormData();
    fd.append("mp4", state.mp4);
    state.hiddenFiles.forEach(f => fd.append("hidden_files", f));
    fd.append("config", JSON.stringify(state.config));

    const btn = document.getElementById("build-btn");
    btn.disabled = true;
    btn.innerHTML = '<span class="btn-spinner"></span>构建中…';
    resultBox.classList.remove("shown");
    document.body.classList.add("building");
    document.getElementById("size-hint").classList.remove("warn");
    document.getElementById("size-hint").innerHTML = "无文件大小上限（支持 &gt;4GB）。构建需要约源文件总大小 2 倍的磁盘空间。";

    let buildOk = false;
    // 清空服务端日志，避免上次构建的"构建成功"干扰本次进度判断
    try { await fetch("/api/log/clear", { method: "POST" }); } catch (e) { /* ignore */ }
    startProgress();
    startPolling();  // 开始轮询服务端日志，实时显示构建进度

    try {
        const resp = await fetch("/api/build", { method: "POST", body: fd });

        if (!resp.ok) {
            let errInfo = "";
            try {
                const errJson = await resp.json();
                errInfo = errJson.error || JSON.stringify(errJson);
                addClientLog(`构建失败: ${errInfo}`, "error");
                if (errJson.traceback) {
                    showResult(false, "构建失败：" + errInfo,
                        `<pre style="margin-top:8px;white-space:pre-wrap;font-size:0.78rem;color:#f87171">${escapeHtml(errJson.traceback)}</pre>`);
                } else {
                    showResult(false, "构建失败", escapeHtml(errInfo));
                }
            } catch (_) {
                errInfo = await resp.text();
                addClientLog(`构建失败 (HTTP ${resp.status}): ${errInfo}`, "error");
                showResult(false, "构建失败 (HTTP " + resp.status + ")", escapeHtml(errInfo));
            }
            return;
        }

        const data = await resp.json();
        lastDownloadUrl = data.downloadUrl;
        lastDownloadName = data.filename;
        triggerNativeDownload(data.downloadUrl, data.filename);
        addClientLog(`下载已触发: ${data.filename} (${fmtSize(data.size)})`);

        const overhead = data.size - state.mp4.size;
        let steps = `改后缀为 <code>.zip</code> 解压`;
        if (state.config.outerPassword) steps += `（输入外层密码）`;
        if (state.config.innerArchive !== "none") {
            const tool = state.config.innerArchive === "7z" ? "7-Zip" : "解压工具";
            steps += ` → 用 ${tool} 打开内层`;
            if (state.config.innerPassword) steps += `（输入内层密码）`;
        }
        steps += ` → 拿到隐藏文件。`;

        showResult(true, `完成！已开始下载：${data.filename}`,
            `伪装文件大小：<b>${fmtSize(data.size)}</b> ` +
            `（视频 ${fmtSize(state.mp4.size)} + 隐藏部分 ${fmtSize(overhead)}）<br>` +
            `使用方法：双击当视频播放；${steps}<br>` +
            `若下载被取消，点右侧“重新下载”按钮即可重试。`);
        redownloadBtn.style.display = "block";
        buildOk = true;
        addClientLog(`========== 构建成功 ==========`);
    } catch (e) {
        addClientLog(`网络错误: ${e.message || e}`, "error");
        showResult(false, "构建失败：网络错误", escapeHtml(String(e.message || e)));
    } finally {
        finishProgress(buildOk);
        stopPolling();  // 停止轮询，做最后一次同步
        btn.disabled = false;
        btn.textContent = "构建伪装文件";
        document.body.classList.remove("building");
    }
});

// 页面加载完打个招呼
addClientLog("影藏 PolyFlix 已就绪。按 Ctrl+F9 可打开/关闭此日志面板。");
