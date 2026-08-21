// 影藏 PolyFlix —— 前端逻辑

const state = {
    mode: "zip",  // "zip" = 文件隐藏模式；"dual" = 双视频模式
    mp4: null,
    hiddenFiles: [],
    config: { outerPassword: "", innerArchive: "none", innerPassword: "" }
};

// ---- 页脚年份 + 版本号 ----
document.getElementById("year").textContent = new Date().getFullYear();
const versionEl = document.getElementById("version");
const updateHintEl = document.getElementById("update-hint");
let currentVersion = "";        // 本地版本号（无 v 前缀）

// 版本号格式 YY.M.D（如 26.8.12），按数字段比较。返回 1/-1/0。
function compareVersions(a, b) {
    const pa = (a || "").split(".").map(n => parseInt(n, 10) || 0);
    const pb = (b || "").split(".").map(n => parseInt(n, 10) || 0);
    const len = Math.max(pa.length, pb.length);
    for (let i = 0; i < len; i++) {
        const da = pa[i] || 0;
        const db = pb[i] || 0;
        if (da !== db) return da > db ? 1 : -1;
    }
    return 0;
}

// 渲染更新提示（检测完成后调用）
// state: "new" | "latest" | "checking" | "error" | ""  newVer: 远程版本号
function renderUpdateHint(state, newVer) {
    if (!updateHintEl) return;
    updateHintEl.className = "footer-update-hint";
    switch (state) {
        case "new":
            updateHintEl.classList.add("hint-new");
            updateHintEl.innerHTML =
                `<a href="https://github.com/hcllmsx/PolyFlix/releases" target="_blank" rel="noopener">` +
                `有新版本 v${newVer}，点击下载</a>`;
            break;
        case "latest":
            updateHintEl.classList.add("hint-latest");
            updateHintEl.textContent = "已是最新";
            break;
        case "checking":
            updateHintEl.classList.add("hint-checking");
            updateHintEl.textContent = "检查中…";
            break;
        case "error":
            updateHintEl.classList.add("hint-error");
            updateHintEl.textContent = "检查失败，点击重试";
            break;
        default:
            updateHintEl.textContent = "";
    }
}

// 检查更新：fetch 仓库根目录 VERSION 文件
// raw URL：https://raw.githubusercontent.com/<owner>/<repo>/main/VERSION
const UPDATE_URL = "https://raw.githubusercontent.com/hcllmsx/PolyFlix/main/VERSION";

async function checkForUpdate(manual = false) {
    if (!currentVersion) return;
    renderUpdateHint("checking");
    try {
        // 加时间戳防 CDN 缓存
        const r = await fetch(`${UPDATE_URL}?t=${Date.now()}`, { cache: "no-store" });
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const remote = (await r.text()).trim();
        if (!remote) throw new Error("空响应");
        if (compareVersions(remote, currentVersion) > 0) {
            renderUpdateHint("new", remote);
            if (manual) showToast(`发现新版本 v${remote}，已显示在页脚`, "success");
        } else {
            renderUpdateHint("latest");
            if (manual) showToast("已是最新版本", "success");
        }
        addClientLog(`更新检查完成：本地 ${currentVersion}，远程 ${remote}`);
    } catch (e) {
        renderUpdateHint("error");
        if (manual) showToast(`检查更新失败：${e.message || e}`, "error");
        addClientLog(`更新检查失败: ${e.message || e}`, "error");
    }
}

// 点击版本号 → 手动触发检测
versionEl.style.cursor = "pointer";
versionEl.addEventListener("click", () => checkForUpdate(true));
updateHintEl.addEventListener("click", e => {
    // "检查失败，点击重试" 也触发重新检测（链接除外）
    if (e.target === updateHintEl) checkForUpdate(true);
});

fetch("/api/version").then(r => r.json()).then(d => {
    if (versionEl && d.version) {
        currentVersion = d.version;
        versionEl.textContent = "v" + d.version;
        // 启动后自动检测一次（静默，不弹 toast）
        checkForUpdate(false);
    }
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

// 检测是否运行在 pywebview（打包后的 exe）环境中
function isExeMode() {
    return typeof window.pywebview !== "undefined";
}

// ---- Toast 提示 ----
const toastEl = document.getElementById("toast");
const toastIcon = document.getElementById("toast-icon");
const toastMsg = document.getElementById("toast-msg");
let toastTimer = null;

function showToast(msg, type = "loading") {
    // type: loading | success | error
    toastEl.className = "toast " + type;
    const icons = { loading: "◌", success: "✓", error: "✕" };
    toastIcon.textContent = icons[type] || "";
    toastMsg.textContent = msg;
    // 触发过渡：先 display:flex 再加 visible
    requestAnimationFrame(() => {
        toastEl.classList.add("visible");
    });
    if (toastTimer) { clearTimeout(toastTimer); toastTimer = null; }
    if (type !== "loading") {
        toastTimer = setTimeout(() => {
            toastEl.classList.remove("visible");
        }, 3000);
    }
}

function hideToast() {
    toastEl.classList.remove("visible");
    if (toastTimer) { clearTimeout(toastTimer); toastTimer = null; }
}

// ---- 模态警告对话框 ----
const modalOverlay = document.getElementById("modal-overlay");
const modalTitle = document.getElementById("modal-title");
const modalBody = document.getElementById("modal-body");
const modalBtn = document.getElementById("modal-btn");

function showModal(title, bodyHtml) {
    modalTitle.textContent = title;
    modalBody.innerHTML = bodyHtml;
    modalOverlay.classList.add("visible");
}
modalBtn.addEventListener("click", () => modalOverlay.classList.remove("visible"));
modalOverlay.addEventListener("click", e => {
    if (e.target === modalOverlay) modalOverlay.classList.remove("visible");
});

// PolyFlix 产物警告
function showPolyflixWarning(filename) {
    const body =
        `<span class="modal-file">${escapeHtml(filename)}</span> 已经是 PolyFlix 产物（视频 + 隐藏数据拼接），不能用作伪装视频。` +
        `<div class="modal-hint">` +
        `<b>原因：</b>再次作为封面会导致之前的隐藏文件被埋在文件中间，标准解压工具无法取出，造成数据永久丢失。<br><br>` +
        `<b>正确做法：</b><br>` +
        `• 使用原始视频作为伪装视频<br>` +
        `• 如需添加更多隐藏文件，请用原始视频重新构建（把所有要隐藏的文件一起放进去）` +
        `</div>`;
    showModal("不能使用 PolyFlix 产物作为伪装视频", body);
}

// 检测文件是否是 PolyFlix 产物（两种模式）。
// 两种产物在外观上都是合法的 MP4，这里识别其隐藏数据标记。
async function isPflxProduct(file) {
    if (!file || !file.slice) return false;
    try {
        const size = file.size;
        if (size < 28) return false;
        let offset = 0;
        let guard = 0;  // 防御恶意/损坏文件的死循环
        while (offset < size && guard++ < 4096) {
            const buf = await file.slice(offset, offset + 16).arrayBuffer();
            if (buf.byteLength < 8) return false;
            const dv = new DataView(buf);
            const b = new Uint8Array(buf);
            const size32 = dv.getUint32(0);
            let boxSize, hdrLen;
            if (size32 === 1) {
                if (buf.byteLength < 16) return false;
                boxSize = Number(dv.getBigUint64(8));
                hdrLen = 16;
            } else if (size32 === 0) {
                boxSize = size - offset;
                hdrLen = 8;
            } else {
                boxSize = size32;
                hdrLen = 8;
            }
            if (boxSize < hdrLen || offset + boxSize > size) return false;
            const t = String.fromCharCode(b[4], b[5], b[6], b[7]);
            if (t === "free" && boxSize - hdrLen >= 20) {
                const h = new Uint8Array(await file.slice(offset + hdrLen, offset + hdrLen + 20).arrayBuffer());
                if (h.length >= 4 && String.fromCharCode(h[0], h[1], h[2], h[3]) === "PFLX") return true;
            }
            offset += boxSize;
        }
        return false;
    } catch (e) {
        return false;
    }
}

async function isPolyflixProduct(file) {
    // exe 模式返回的对象没有 slice 方法，跳过（Python 端已检测）
    if (!file || !file.slice) return false;
    try {
        const size = file.size;
        if (size < 22) return false;  // 结构最小 22 字节
        // ---- 模式一：文件隐藏 ----
        const scanSize = Math.min(size, 66560);
        const start = Math.max(0, size - scanSize);
        const blob = file.slice(start, size);
        const buf = await blob.arrayBuffer();
        const bytes = new Uint8Array(buf);
        // 从后往前找 PK\x05\x06 签名
        for (let i = bytes.length - 4; i >= 0; i--) {
            if (bytes[i] === 0x50 && bytes[i + 1] === 0x4B &&
                bytes[i + 2] === 0x05 && bytes[i + 3] === 0x06) {
                return true;
            }
        }
        // ---- 模式二：双视频 ----
        return await isPflxProduct(file);
    } catch (e) {
        return false;
    }
}

// ---- 密码确认弹窗（构建前提醒牢记密码）----
const PWD_WARN_KEY = "polyflix.pwdWarnDismissed";
const pwdModalOverlay = document.getElementById("pwd-modal-overlay");
const pwdModalEl = document.getElementById("pwd-modal");
const pwdBtnBack = document.getElementById("pwd-btn-back");
const pwdBtnOnce = document.getElementById("pwd-btn-once");
const pwdBtnNever = document.getElementById("pwd-btn-never");

function isPwdWarnDismissed() {
    try { return localStorage.getItem(PWD_WARN_KEY) === "1"; } catch (e) { return false; }
}
function setPwdWarnDismissed() {
    try { localStorage.setItem(PWD_WARN_KEY, "1"); } catch (e) { /* localStorage 不可用时忽略 */ }
}

// 弹窗左右晃动（点击外部非按钮区时触发，提示用户必须点按钮）
// 用 Web Animations API，避免 CSS 优先级冲突和 transition 干扰
function shakePwdModal() {
    const keyframes = [
        { transform: "scale(1) translateX(0)" },
        { transform: "scale(1) translateX(-12px)" },
        { transform: "scale(1) translateX(12px)" },
        { transform: "scale(1) translateX(-8px)" },
        { transform: "scale(1) translateX(8px)" },
        { transform: "scale(1) translateX(-4px)" },
        { transform: "scale(1) translateX(0)" },
    ];
    pwdModalEl.animate(keyframes, { duration: 450, easing: "ease" });
}

// 返回 Promise：true=继续构建，false=取消构建
function showPwdConfirmDialog() {
    return new Promise(resolve => {
        pwdModalOverlay.classList.add("visible");
        const cleanup = () => {
            pwdModalOverlay.classList.remove("visible");
            pwdModalOverlay.removeEventListener("click", onOverlayClick);
            pwdBtnBack.removeEventListener("click", onBack);
            pwdBtnOnce.removeEventListener("click", onOnce);
            pwdBtnNever.removeEventListener("click", onNever);
        };
        const onBack = () => { cleanup(); resolve(false); };
        const onOnce = () => { cleanup(); resolve(true); };
        const onNever = () => { setPwdWarnDismissed(); cleanup(); resolve(true); };
        // 点击遮罩层（弹窗外部）→ 晃动，不关闭
        const onOverlayClick = e => {
            if (e.target === pwdModalOverlay) {
                e.stopPropagation();
                shakePwdModal();
            }
        };
        pwdBtnBack.addEventListener("click", onBack);
        pwdBtnOnce.addEventListener("click", onOnce);
        pwdBtnNever.addEventListener("click", onNever);
        pwdModalOverlay.addEventListener("click", onOverlayClick);
    });
}

// ---- 模式切换：zip（文件隐藏）/ dual（双视频） ----
const modeSwitch = document.getElementById("mode-switch");
const VIDEO_EXTS = ["mp4", "mkv", "flv", "webm", "avi", "mov", "ts", "m4v", "wmv", "mpg", "mpeg", "3gp", "rmvb", "vob"];

modeSwitch.querySelectorAll(".mode-btn").forEach(btn => {
    btn.addEventListener("click", () => setMode(btn.dataset.mode));
});

function setMode(mode) {
    if (state.mode === mode) return;
    state.mode = mode;
    modeSwitch.querySelectorAll(".mode-btn").forEach(b =>
        b.classList.toggle("active", b.dataset.mode === mode));
    // 切换模式时清空隐藏文件（两种模式语义不同，避免误构建）
    if (state.hiddenFiles.length) {
        state.hiddenFiles = [];
        renderHiddenFiles();
        addClientLog("切换模式：已清空已选隐藏文件");
    }
    // 第二步文案与选择器
    document.getElementById("step2-title").textContent =
        mode === "dual" ? "选择隐藏的视频（任意视频格式，不转码）" : "选择要隐藏的文件（任意格式）";
    document.getElementById("hidden-dz-icon").textContent = mode === "dual" ? "🎞️" : "📁";
    document.getElementById("hidden-dz-text").innerHTML = mode === "dual"
        ? '拖放要隐藏的视频到此处<br><span class="dz-sub">单个文件，支持任意视频格式</span>'
        : '拖放文件到此处<br><span class="dz-sub">可多选</span>';
    document.getElementById("input-hidden").accept = mode === "dual"
        ? "video/*," + VIDEO_EXTS.map(e => "." + e).join(",")
        : "";
    // 配置面板与结构图：zip-only / dual-only 显隐
    document.querySelectorAll(".zip-only").forEach(el => { el.style.display = mode === "dual" ? "none" : ""; });
    document.querySelectorAll(".dual-only").forEach(el => { el.style.display = mode === "dual" ? "" : "none"; });
    // split-group 默认就是 display:none，切回 zip 时恢复由 updateDiagram 负责
    updateDiagram();
    addClientLog(`切换到${mode === "dual" ? "双视频模式" : "文件隐藏模式"}`);
}

function isDualMode() { return state.mode === "dual"; }

// 双视频模式：文件名看起来不像视频时给出提醒（不阻断，载荷本质可以是任意文件）
function looksLikeVideo(name) {
    const ext = (name.split(".").pop() || "").toLowerCase();
    return VIDEO_EXTS.includes(ext);
}

// ---- 拖放区 ----
// exe 模式：点击 → pywebview 原生文件对话框（拿本地路径，不走 HTTP 上传）
// 浏览器模式：点击 → <input type="file">；支持拖放
function setupDropZone(zoneId, inputId, onFiles, onPywebviewSelect) {
    const zone = document.getElementById(zoneId);
    const input = document.getElementById(inputId);

    zone.addEventListener("click", async () => {
        if (isExeMode() && onPywebviewSelect) {
            try {
                const files = await onPywebviewSelect();
                if (files && files.length) onFiles(files);
            } catch (e) {
                addClientLog(`选择文件出错: ${e.message || e}`, "error");
            }
        } else {
            input.click();
        }
    });
    input.addEventListener("change", () => {
        if (input.files.length) onFiles(input.files);
        input.value = "";  // 重置，使再次选择同一文件也能触发 change
    });

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
setupDropZone("dz-mp4", "input-mp4", async files => {
    const file = files[0];

    // dev 模式 / 拖放：file 是 File 对象，用 JS 检测是否 PolyFlix 产物
    if (file.slice) {
        const isProduct = await isPolyflixProduct(file);
        if (isProduct) {
            addClientLog(`⚠️ 拒绝选择 PolyFlix 产物作为封面: ${file.name}`, "error");
            showPolyflixWarning(file.name);
            return;  // 不设置 state.mp4
        }
    }

    state.mp4 = file;
    const zone = document.getElementById("dz-mp4");
    zone.classList.add("has-file");
    document.getElementById("mp4-info").textContent = `${state.mp4.name} · ${fmtSize(state.mp4.size)}`;
    document.getElementById("mp4-name").textContent = state.mp4.name;
    document.getElementById("mp4-reselect").style.display = "block";
    addClientLog(`选择外壳伪装视频: ${state.mp4.name} (${fmtSize(state.mp4.size)})`);
}, async () => {
    await waitForPywebviewApi();
    const r = await window.pywebview.api.select_mp4();
    if (!r) return null;

    // Python 端检测到 PolyFlix 产物
    if (r.error === "polyflix_product") {
        addClientLog(`⚠️ 拒绝选择 PolyFlix 产物作为封面: ${r.name}`, "error");
        showPolyflixWarning(r.name || "该文件");
        return null;  // 不触发 onFiles
    }

    return [r];  // 统一返回数组
});

// 隐藏文件选择：zip 模式追加多选；dual 模式单选替换
setupDropZone("dz-hidden", "input-hidden", files => {
    if (isDualMode()) {
        // 双视频模式：只取第一个，替换式选择
        const f = Array.from(files)[0];
        if (!f) return;
        if (!looksLikeVideo(f.name)) {
            addClientLog(`⚠️ 双视频模式建议选择视频文件（${f.name} 可能不是视频）`, "error");
        }
        state.hiddenFiles = [f];
        renderHiddenFiles();
        addClientLog(`选择隐藏视频: ${f.name} (${fmtSize(f.size)})`);
        return;
    }
    const incoming = Array.from(files);
    const existingKeys = new Set(state.hiddenFiles.map(f => `${f.name}|${f.size}|${f.path || f.lastModified || 0}`));
    let added = 0;
    for (const f of incoming) {
        const key = `${f.name}|${f.size}|${f.path || f.lastModified || 0}`;
        if (!existingKeys.has(key)) {
            state.hiddenFiles.push(f);
            existingKeys.add(key);
            added++;
        }
    }
    renderHiddenFiles();
    addClientLog(`选择隐藏文件: +${added}（本次），共 ${state.hiddenFiles.length} 个`);
    incoming.forEach(f => addClientLog(`  └ ${f.name} (${fmtSize(f.size)})`));
}, async () => {
    await waitForPywebviewApi();
    return await window.pywebview.api.select_hidden_files();
});

// 渲染隐藏文件列表（每条带删除按钮）
function renderHiddenFiles() {
    const zone = document.getElementById("dz-hidden");
    const info = document.getElementById("hidden-info");
    const reselectHint = document.getElementById("hidden-reselect");
    if (state.hiddenFiles.length > 0) {
        zone.classList.add("has-file");
        reselectHint.style.display = "flex";
        info.innerHTML = state.hiddenFiles.map((f, i) =>
            `<div class="file-item">` +
            `<span class="file-item-name">${escapeHtml(f.name)}</span>` +
            `<span class="file-item-size">${fmtSize(f.size)}</span>` +
            `<button class="file-remove-btn" data-idx="${i}" title="移除此文件">✕</button>` +
            `</div>`
        ).join("");
        // 绑定删除按钮
        info.querySelectorAll(".file-remove-btn").forEach(btn => {
            btn.addEventListener("click", e => {
                e.stopPropagation();  // 阻止冒泡到 dropzone，避免触发文件选择框
                const idx = parseInt(btn.dataset.idx, 10);
                const removed = state.hiddenFiles.splice(idx, 1);
                renderHiddenFiles();
                if (removed[0]) addClientLog(`移除文件: ${removed[0].name}`);
            });
        });
    } else {
        zone.classList.remove("has-file");
        reselectHint.style.display = "none";
        info.innerHTML = "";
    }
    document.getElementById("files-desc").textContent = `${state.hiddenFiles.length} 个文件`;
    // 双视频模式：结构图隐藏视频层显示隐藏视频名
    if (state.hiddenFiles.length === 1) {
        document.getElementById("freebox-desc").textContent =
            `${state.hiddenFiles[0].name}（原样保存，不压缩）`;
    } else {
        document.getElementById("freebox-desc").textContent = "原样保存，不压缩";
    }
}

// “清空全部”按钮
document.getElementById("clear-all-btn").addEventListener("click", e => {
    e.stopPropagation();  // 阻止冒泡到 dropzone
    const n = state.hiddenFiles.length;
    state.hiddenFiles = [];
    renderHiddenFiles();
    addClientLog(`清空全部隐藏文件（${n} 个）`);
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
    const freeboxLayer = document.getElementById("layer-freebox");
    const zipOuterLayer = document.querySelector(".layer-zip-outer");

    // 双视频模式：隐藏 ZIP/内层/文件层
    if (isDualMode()) {
        freeboxLayer.style.display = "flex";
        zipOuterLayer.style.display = "none";
        innerLayer.style.display = "none";
        filesLayer.style.display = "none";
        document.getElementById("hint").textContent =
            `当前：双视频模式。隐藏视频原样存进 MP4，用影现播放器打开产物即可播放。`;
        return;
    }

    freeboxLayer.style.display = "none";
    zipOuterLayer.style.display = "flex";
    filesLayer.style.display = "flex";

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
const logClose = document.getElementById("log-close");

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

// 关闭按钮：仅收起面板（不影响 Ctrl+F9 切换逻辑）
function closeLogPanel() {
    logPanelVisible = false;
    logPanel.classList.remove("visible");
    document.body.classList.remove("log-open");
}
logClose.addEventListener("click", closeLogPanel);

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

logExport.addEventListener("click", async () => {
    const text = logToText();
    if (!text) { alert("日志为空"); return; }
    const ts = new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19);
    const filename = `polyflix_log_${ts}.txt`;

    // exe 模式：走原生保存对话框
    if (isExeMode()) {
        await waitForPywebviewApi();
        try {
            // 第一步：弹保存对话框
            showToast("等待选择导出位置…", "loading");
            const picked = await window.pywebview.api.pick_text_save_path(filename);
            if (!picked || !picked.ok) {
                if (picked && picked.cancelled) {
                    hideToast();
                } else {
                    const errMsg = (picked && picked.error) ? picked.error : "未知错误";
                    showToast(`导出失败：${errMsg}`, "error");
                }
                return;
            }
            // 第二步：写文件
            showToast("正在导出日志…", "loading");
            const result = await window.pywebview.api.write_text_file(picked.path, text);
            if (result && result.ok) {
                addClientLog(`日志已导出: ${result.path}`);
                showToast(`已导出：${result.path}`, "success");
            } else {
                const errMsg = (result && result.error) ? result.error : "未知错误";
                showToast(`导出失败：${errMsg}`, "error");
            }
        } catch (e) {
            showToast(`导出失败：${e.message || e}`, "error");
        }
        return;
    }

    // 浏览器模式：Blob + <a download>
    const blob = new Blob([text], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
});

// 重置"不再提醒"状态：下次构建设密码时重新弹出密码确认弹窗
document.getElementById("log-reset-pwd-warn").addEventListener("click", () => {
    try {
        localStorage.removeItem(PWD_WARN_KEY);
        showToast("已重置密码提醒，下次构建将重新提示", "success");
        addClientLog('已重置密码提醒状态（清除"不再提醒"）');
    } catch (e) {
        showToast("重置失败", "error");
        addClientLog(`重置密码提醒失败: ${e.message || e}`, "error");
    }
});

// ---- 构建结果区 ----
const resultBox = document.getElementById("result");
const resultIcon = document.getElementById("result-icon");
const resultTitle = document.getElementById("result-title");
const resultDetail = document.getElementById("result-detail");
const redownloadBtn = document.getElementById("redownload-btn");
let lastDownloadUrl = null;
let lastDownloadName = null;
let lastDownloadId = null;

// 检测是否运行在 pywebview（打包后的 exe）环境中
function hasPywebviewApi() {
    return !!(window.pywebview && window.pywebview.api && typeof window.pywebview.api.pick_save_path === "function");
}

// 等待 pywebview API 就绪（页面加载后 API 需要一小会才注入；构建完成时通常早就好了）
function waitForPywebviewApi(maxWaitMs = 3000) {
    return new Promise(resolve => {
        if (hasPywebviewApi()) { resolve(true); return; }
        const start = Date.now();
        const tick = setInterval(() => {
            if (hasPywebviewApi()) { clearInterval(tick); resolve(true); }
            else if (Date.now() - start > maxWaitMs) { clearInterval(tick); resolve(false); }
        }, 100);
    });
}

async function triggerNativeDownload(url, name, downloadId) {
    // 打包后的 exe（pywebview）：浏览器原生下载不可靠，改用原生保存对话框
    if (window.pywebview !== undefined || hasPywebviewApi()) {
        await waitForPywebviewApi();
    }
    if (hasPywebviewApi()) {
        try {
            // 第一步：弹保存对话框（快速返回）
            addClientLog(`等待保存对话框…`);
            showToast("等待选择保存位置…", "loading");
            const picked = await window.pywebview.api.pick_save_path(downloadId, name);
            if (!picked || !picked.ok) {
                if (picked && picked.cancelled) {
                    addClientLog(`用户取消了保存`);
                    hideToast();
                } else {
                    const errMsg = (picked && picked.error) ? picked.error : "未知错误";
                    addClientLog(`保存失败: ${errMsg}`, "error");
                    showToast(`保存失败：${errMsg}`, "error");
                }
                return false;
            }

            // 第二步：写文件（可能耗时较长）
            const destPath = picked.path;
            addClientLog(`正在保存到: ${destPath}`);
            const shortName = destPath.split(/[\\/]/).pop();
            showToast(`正在保存文件…（${shortName}）`, "loading");
            const result = await window.pywebview.api.write_download(downloadId, destPath);
            if (result && result.ok) {
                addClientLog(`文件已保存到: ${result.path}`);
                showToast(`已保存：${result.path}`, "success");
                return true;
            } else {
                const errMsg = (result && result.error) ? result.error : "未知错误";
                addClientLog(`保存失败: ${errMsg}`, "error");
                showToast(`保存失败：${errMsg}`, "error");
                return false;
            }
        } catch (e) {
            addClientLog(`保存失败: ${e.message || e}`, "error");
            showToast(`保存失败：${e.message || e}`, "error");
            return false;
        }
    }

    // 浏览器（dev 模式）：用 <a download> 触发原生下载
    const a = document.createElement("a");
    a.href = url;
    a.download = name;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    return true;
}

redownloadBtn.addEventListener("click", () => {
    if (lastDownloadId) {
        triggerNativeDownload(lastDownloadUrl, lastDownloadName, lastDownloadId);
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

    // 特殊处理：大文件写入进度（“写入 xxx: NN%”，两种模式共用）
    const writeMatches = text.match(/写入 .*?: (\d+)%/g);
    if (writeMatches && writeMatches.length > 0) {
        const lastPct = parseInt(writeMatches[writeMatches.length - 1].match(/(\d+)%/)[1], 10);
        // 映射 0-100% → 50%-78%（写入阶段）
        const barPct = 50 + Math.round(lastPct * 0.28);
        setProgressStage(barPct, `正在写入数据… ${lastPct}%`);
    }

    const stages = [
        { kw: "构建成功", pct: 100, label: "完成 ✓" },
        { kw: "下载 ID", pct: 95, label: "准备下载…" },
        { kw: "拼接:", pct: 90, label: "拼接产物…" },
        { kw: "隐藏视频封装完成", pct: 80, label: "隐藏视频封装完成…" },
        { kw: "外层 ZIP 完成", pct: 80, label: "外层打包完成…" },
        { kw: "封装隐藏视频", pct: 55, label: "正在封装隐藏视频…" },
        { kw: "外层 ZIP [", pct: 58, label: "正在创建外层 ZIP…" },
        { kw: "外层 ZIP: 条目数", pct: 55, label: "开始创建外层 ZIP…" },
        { kw: "内层已分卷", pct: 52, label: "内层分卷完成…" },
        { kw: "内层 ZIP 完成", pct: 50, label: "内层打包完成…" },
        { kw: "7z 完成", pct: 50, label: "内层打包完成…" },
        { kw: "内层 ZIP [", pct: 48, label: "正在创建内层压缩包…" },
        { kw: "7z [", pct: 48, label: "正在创建内层压缩包…" },
        { kw: "内层压缩包:", pct: 47, label: "内层打包完成…" },
        { kw: "无内层", pct: 45, label: "开始创建外层 ZIP…" },
        { kw: "磁盘空间", pct: 38, label: "检查磁盘空间…" },
        { kw: "隐藏文件:", pct: 30, label: "准备隐藏文件…" },
        { kw: "模式: 双视频", pct: 25, label: "双视频模式…" },
        { kw: "MP4 复制完成", pct: 22, label: "MP4 准备完成…" },
        { kw: "MP4 硬链接完成", pct: 20, label: "MP4 准备完成…" },
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
// XHR 上传，支持真实进度（fetch 不支持上传进度）
function uploadBuild(fd, onProgress) {
    return new Promise((resolve, reject) => {
        const xhr = new XMLHttpRequest();
        if (onProgress && xhr.upload) {
            xhr.upload.addEventListener("progress", e => {
                if (e.lengthComputable) onProgress(e.loaded, e.total);
            });
        }
        xhr.addEventListener("load", () => {
            resolve({ ok: xhr.status >= 200 && xhr.status < 300, status: xhr.status, responseText: xhr.responseText });
        });
        xhr.addEventListener("error", () => reject(new Error("网络错误")));
        xhr.addEventListener("abort", () => reject(new Error("已取消")));
        xhr.open("POST", "/api/build");
        xhr.send(fd);
    });
}

document.getElementById("build-btn").addEventListener("click", async () => {
    if (!state.mp4) { alert("请先选择外壳伪装视频 MP4"); return; }
    if (state.hiddenFiles.length === 0) { alert("请选择要隐藏的文件"); return; }
    if (isDualMode() && state.hiddenFiles.length !== 1) {
        alert("双视频模式只能隐藏 1 个视频文件（当前 " + state.hiddenFiles.length + " 个）。需要隐藏多个文件请切换到文件隐藏模式。");
        return;
    }

    const innerVal = document.querySelector('input[name="inner"]:checked').value;
    const splitVal = parseInt(splitSize.value) || 100;
    const splitMB = splitUnit.value === "gb" ? splitVal * 1024 : splitVal;
    state.config = {
        mode: state.mode,  // zip | dual
        outerPassword: outerPwEnable.checked ? outerPw.value : "",
        innerArchive: innerVal,
        innerPassword: innerVal !== "none" ? innerPw.value : "",
        splitVolume: innerVal !== "none" && splitEnable.checked,
        splitSizeMB: innerVal !== "none" && splitEnable.checked ? splitMB : 0,
        compression: compression.value
    };

    // ---- 密码确认弹窗：设置了任何密码时，构建前提醒牢记密码 ----
    const hasOuterPwd = !!(state.config.outerPassword);
    const hasInnerPwd = !!(state.config.innerPassword);
    if ((hasOuterPwd || hasInnerPwd) && !isPwdWarnDismissed()) {
        addClientLog("等待用户确认密码提醒…");
        const confirmed = await showPwdConfirmDialog();
        if (!confirmed) {
            addClientLog("用户取消构建（密码提醒：我再看看）");
            return;  // 取消构建，返回检查
        }
        addClientLog("用户已确认密码提醒，继续构建");
    }

    const compName = { store: "存储", fastest: "最快", fast: "较快", normal: "标准", good: "较好", best: "最好" }[compression.value] || "标准";

    addClientLog(`========== 开始构建 ==========`);
    addClientLog(`模式: ${isDualMode() ? "双视频" : "文件隐藏（ZIP）"}`);
    addClientLog(`伪装视频: ${state.mp4.name}`);
    addClientLog(`隐藏文件: ${state.hiddenFiles.length} 个`);
    if (isDualMode()) {
        addClientLog(`配置: 隐藏视频=${state.hiddenFiles[0].name}，不压缩、不加密、不转码`);
    } else {
        addClientLog(`配置: 内层=${innerVal}, 压缩=${compName}, 外层密码=${state.config.outerPassword ? "是" : "否"}, 内层密码=${state.config.innerPassword ? "是" : "否"}, 分卷=${state.config.splitVolume ? splitMB + "MB/卷" : "否"}`);
    }

    const btn = document.getElementById("build-btn");
    btn.disabled = true;
    btn.innerHTML = '<span class="btn-spinner"></span>构建中…';
    resultBox.classList.remove("shown");
    document.body.classList.add("building");
    document.getElementById("size-hint").classList.remove("warn");
    document.getElementById("size-hint").innerHTML = "无文件大小上限（支持 &gt;4GB）。构建需要约源文件总大小 2 倍的磁盘空间。";

    let buildOk = false;
    let buildData = null;  // {download_id/downloadUrl, filename, size}
    // 清空服务端日志，避免上次构建的"构建成功"干扰本次进度判断
    try { await fetch("/api/log/clear", { method: "POST" }); } catch (e) { /* ignore */ }
    startProgress();
    startPolling();  // 开始轮询服务端日志，实时显示构建进度

    try {
        if (isExeMode()) {
            // ---- exe 模式：js_api 本地路径直读，不走 HTTP 上传 ----
            await waitForPywebviewApi();
            const mp4Path = state.mp4.path;
            const hiddenPaths = state.hiddenFiles.map(f => f.path);
            const result = await window.pywebview.api.start_build(
                mp4Path, JSON.stringify(hiddenPaths), JSON.stringify(state.config), state.mp4.name
            );
            if (result && result.ok) {
                buildData = {
                    download_id: result.download_id,
                    filename: result.filename,
                    size: result.size,
                };
                buildOk = true;
                addClientLog(`========== 构建成功 ==========`);
            } else {
                const errMsg = (result && result.error) ? result.error : "未知错误";
                addClientLog(`构建失败: ${errMsg}`, "error");
                showResult(false, "构建失败", escapeHtml(errMsg));
            }
        } else {
            // ---- 浏览器模式：XHR 上传，支持真实进度 ----
            const fd = new FormData();
            fd.append("mp4", state.mp4);
            state.hiddenFiles.forEach(f => fd.append("hidden_files", f));
            fd.append("config", JSON.stringify(state.config));

            const resp = await uploadBuild(fd, (loaded, total) => {
                // 上传阶段映射到进度条 8% → 35%
                const uploadPct = total > 0 ? loaded / total : 0;
                const barPct = 8 + uploadPct * 27;
                setProgressStage(barPct, `正在读取文件… ${fmtSize(loaded)} / ${fmtSize(total)}`);
            });

            if (!resp.ok) {
                let errInfo = "";
                try {
                    const errJson = JSON.parse(resp.responseText);
                    errInfo = errJson.error || JSON.stringify(errJson);
                    addClientLog(`构建失败: ${errInfo}`, "error");
                    if (errJson.traceback) {
                        showResult(false, "构建失败：" + errInfo,
                            `<pre style="margin-top:8px;white-space:pre-wrap;font-size:0.78rem;color:#f87171">${escapeHtml(errJson.traceback)}</pre>`);
                    } else {
                        showResult(false, "构建失败", escapeHtml(errInfo));
                    }
                } catch (_) {
                    errInfo = resp.responseText;
                    addClientLog(`构建失败 (HTTP ${resp.status}): ${errInfo}`, "error");
                    showResult(false, "构建失败 (HTTP " + resp.status + ")", escapeHtml(errInfo));
                }
                return;
            }

            buildData = JSON.parse(resp.responseText);
            buildData.download_id = buildData.downloadUrl.split("/").pop();
            buildOk = true;
            addClientLog(`========== 构建成功 ==========`);
        }
    } catch (e) {
        addClientLog(`错误: ${e.message || e}`, "error");
        showResult(false, "构建失败", escapeHtml(String(e.message || e)));
    } finally {
        finishProgress(buildOk);
        stopPolling();  // 停止轮询，做最后一次同步
        btn.disabled = false;
        btn.textContent = "构建伪装文件";
        document.body.classList.remove("building");
    }

    // ---- UI 已重置，现在处理下载 ----
    if (!buildData) return;

    lastDownloadName = buildData.filename;
    lastDownloadId = buildData.download_id;
    lastDownloadUrl = isExeMode() ? null : `/api/download/${buildData.download_id}`;
    addClientLog(`下载已触发: ${buildData.filename} (${fmtSize(buildData.size)})`);

    const downloadOk = await triggerNativeDownload(lastDownloadUrl, buildData.filename, lastDownloadId);

    const overhead = buildData.size - state.mp4.size;
    let steps;
    if (isDualMode() || buildData.mode === "dual") {
        steps = `双击 → 当普通视频播放；用 <b>影现播放器</b> 打开该文件 → 播放隐藏的视频`;
    } else {
        steps = `改后缀为 <code>.zip</code> 解压`;
        if (state.config.outerPassword) steps += `（输入外层密码）`;
        if (state.config.innerArchive !== "none") {
            const tool = state.config.innerArchive === "7z" ? "7-Zip" : "解压工具";
            steps += ` → 用 ${tool} 打开内层`;
            if (state.config.innerPassword) steps += `（输入内层密码）`;
        }
        steps += ` → 拿到隐藏文件。`;
    }

    const isWebview = isExeMode();
    const sizeInfo = `伪装文件大小：<b>${fmtSize(buildData.size)}</b> ` +
        `（视频 ${fmtSize(state.mp4.size)} + 隐藏部分 ${fmtSize(overhead)}）<br>` +
        `使用方法：双击当视频播放；${steps}<br>`;

    if (downloadOk) {
        const title = isWebview
            ? `完成！已保存：${buildData.filename}`
            : `完成！已开始下载：${buildData.filename}`;
        const hint = isWebview
            ? `若文件未保存到预期位置，点右侧"重新下载"按钮可重试。`
            : `若下载被取消，点右侧"重新下载"按钮即可重试。`;
        showResult(true, title, sizeInfo + hint);
    } else {
        // 用户取消保存 或 保存失败——构建本身是成功的，点"重新下载"可重试
        showResult(true, `构建成功，但文件未保存：${buildData.filename}`,
            sizeInfo + `点右侧"重新下载"按钮可再次选择保存位置。`);
    }
    redownloadBtn.style.display = "block";
});

// ---- 缓存清理 ----
// 本软件运行产生的缓存文件统一放在 %TEMP%/PolyFlix 目录下
// 点此按钮可手动清理（正在使用的构建文件会自动跳过，不影响当前操作）
const cacheCleanBtn = document.getElementById("cache-clean-btn");
cacheCleanBtn.addEventListener("click", async () => {
    cacheCleanBtn.disabled = true;
    const origText = cacheCleanBtn.textContent;
    cacheCleanBtn.textContent = "清理中…";
    try {
        const r = await fetch("/api/cache/clean", { method: "POST" });
        const data = await r.json();
        if (data.error) {
            showToast(`清理失败：${data.error}`, "error");
            addClientLog(`清理缓存失败: ${data.error}`, "error");
        } else {
            const freed = fmtSize(data.freed || 0);
            const removed = data.removed || 0;
            const skipped = data.skipped || 0;
            if (removed > 0) {
                showToast(`已清理 ${removed} 项，释放 ${freed}`, "success");
            } else {
                showToast(`缓存已是空的（跳过 ${skipped} 项使用中）`, "success");
            }
            addClientLog(`清理缓存: 删除 ${removed} 项，跳过 ${skipped} 项（使用中），释放 ${freed}`);
            addClientLog(`缓存目录：${data.path}`);
        }
    } catch (e) {
        showToast(`清理失败：${e.message || e}`, "error");
        addClientLog(`清理缓存出错: ${e.message || e}`, "error");
    } finally {
        cacheCleanBtn.disabled = false;
        cacheCleanBtn.textContent = origText;
    }
});

// ---- 右上角副标题 / 按钮切换 ----
// 默认显示副标题；鼠标持续移动 2s+ → 副标题渐变消失，显示按钮
// 鼠标直接进入右上角操作区 → 立即显示按钮（无需等 2s）
const headerActionArea = document.querySelector(".header-action-area");
const subtitleEl = document.querySelector(".subtitle");
const headerBtns = document.getElementById("header-btns");

let lastMouseMove = 0;        // 最近一次 mousemove 时间戳
let moveStartedAt = null;     // 本次连续移动的起始时间（null=未在移动）
let moveAccumDist = 0;        // 本次连续移动的累计距离（px）
let lastMouseX = 0;           // 上次鼠标 X
let lastMouseY = 0;           // 上次鼠标 Y
let inHeader = false;         // 鼠标是否在右上角操作区
let btnsShown = false;        // 按钮当前是否显示

// 移动需同时满足：持续 1.5s 以上 + 累计移动 50px 以上，避免误触发
const MOVE_TIME_MS = 1500;
const MOVE_DIST_PX = 50;

function showHeaderBtns() {
    if (btnsShown) return;
    btnsShown = true;
    subtitleEl.classList.add("faded");
    headerBtns.classList.add("visible");
}
function showSubtitle() {
    if (!btnsShown) return;
    btnsShown = false;
    subtitleEl.classList.remove("faded");
    headerBtns.classList.remove("visible");
}

document.addEventListener("mousemove", e => {
    const now = Date.now();
    if (moveStartedAt === null) {
        // 开始一段新的连续移动
        moveStartedAt = now;
        moveAccumDist = 0;
        lastMouseX = e.clientX;
        lastMouseY = e.clientY;
    } else {
        // 累加与上次的位移距离
        const dx = e.clientX - lastMouseX;
        const dy = e.clientY - lastMouseY;
        moveAccumDist += Math.sqrt(dx * dx + dy * dy);
        lastMouseX = e.clientX;
        lastMouseY = e.clientY;
    }
    lastMouseMove = now;
});

// 轮询检测：连续移动 1.5s+ 且累计 50px+ → 显示按钮；停止移动 3s → 恢复副标题
setInterval(() => {
    const now = Date.now();
    const idle = now - lastMouseMove;
    if (idle > 3000) {
        // 鼠标已停止
        moveStartedAt = null;
        moveAccumDist = 0;
        if (!inHeader) showSubtitle();
    } else {
        // 持续移动中：需同时满足时间和距离
        if (moveStartedAt &&
            now - moveStartedAt >= MOVE_TIME_MS &&
            moveAccumDist >= MOVE_DIST_PX) {
            showHeaderBtns();
        }
    }
}, 100);

// 鼠标进入右上角操作区 → 立即显示按钮
headerActionArea.addEventListener("mouseenter", () => { inHeader = true; showHeaderBtns(); });
headerActionArea.addEventListener("mouseleave", () => { inHeader = false; });

// ---- "新建文件"按钮：一键清空第一步和第二步，回到初始状态 ----
document.getElementById("new-file-btn").addEventListener("click", () => {
    // 第一步：清空 MP4
    state.mp4 = null;
    const mp4Zone = document.getElementById("dz-mp4");
    mp4Zone.classList.remove("has-file");
    document.getElementById("mp4-info").textContent = "";
    document.getElementById("mp4-name").textContent = "未选择";
    document.getElementById("mp4-reselect").style.display = "none";

    // 第二步：清空隐藏文件
    const hiddenCount = state.hiddenFiles.length;
    state.hiddenFiles = [];
    renderHiddenFiles();

    // 隐藏构建结果区
    resultBox.classList.remove("shown");
    resultBox.classList.remove("error");
    document.getElementById("redownload-btn").style.display = "none";

    // 重置空间提示
    document.getElementById("size-hint").classList.remove("warn");
    document.getElementById("size-hint").innerHTML = "无文件大小上限（支持 &gt;4GB）。构建需要约源文件总大小 2 倍的磁盘空间。";

    // 重置构建按钮（防止处于 disabled 状态）
    const buildBtn = document.getElementById("build-btn");
    buildBtn.disabled = false;
    buildBtn.textContent = "构建伪装文件";
    document.body.classList.remove("building");

    addClientLog(`新建文件：已清空伪装视频和 ${hiddenCount} 个隐藏文件，回到初始状态`);
    showToast("已清空，可重新开始", "success");
});

// ---- "关于"按钮：弹模态框显示软件信息、作者、社交平台、姊妹项目 ----
document.getElementById("about-btn").addEventListener("click", () => {
    // 版本号取 footer 已渲染的 #version 文本（由 /api/version 填充）
    const verEl = document.getElementById("version");
    const ver = verEl ? verEl.textContent.trim() : "";
    const body =
        `<div class="about-box">` +
        `<div class="about-logo">` +
        `<img src="/static/影藏PolyFlix-logo.png" alt="影藏 PolyFlix">` +
        `<div class="about-name">影藏 <span class="brand-en">PolyFlix</span></div>` +
        `<div class="about-author">作者： hcllmsx</div>` +
        `</div>` +
        `<div class="about-info">` +
        `<p>把秘密藏进一段能正常播放的 MP4 视频里。两种模式：</p>` +
        `<p class="about-item">· 文件隐藏模式（MP4+ZIP 拼接，改后缀 .zip 解压取出）</p>` +
        `<p class="about-item">· 双视频模式（隐藏视频原样存进 MP4，配合姊妹项目影现播放器直接播放）</p>` +
        `<p><b>Bilibili：</b> 火车啦啦 ` +
        `<a href="https://space.bilibili.com/255947051" target="_blank" rel="noopener">` +
        `https://space.bilibili.com/255947051</a></p>` +
        `<p><b>本项目仓库：</b><br>` +
        `<a href="https://github.com/hcllmsx/PolyFlix" target="_blank" rel="noopener">` +
        `https://github.com/hcllmsx/PolyFlix</a></p>` +
        `<p><b>姊妹项目 · 影现播放器 PolyFlixPlayer</b><br>` +
        `<a href="https://github.com/hcllmsx/PolyFlixPlayer" target="_blank" rel="noopener">` +
        `https://github.com/hcllmsx/PolyFlixPlayer</a></p>` +
        `</div>` +
        `</div>`;
    showModal(`影藏 PolyFlix${ver ? " " + ver : ""}`, body);
    // 关于框专属样式：加宽、左对齐；隐藏警告图标与底部按钮；右上角加 ✕ 关闭
    const modal = document.querySelector(".modal");
    modal.classList.add("modal-about");
    let closeX = modal.querySelector(".about-close");
    if (!closeX) {
        closeX = document.createElement("button");
        closeX.className = "about-close";
        closeX.textContent = "✕";
        closeX.title = "关闭";
        closeX.addEventListener("click", () => modalOverlay.classList.remove("visible"));
        modal.appendChild(closeX);
    }
});

// 页面加载完打个招呼
addClientLog("影藏 PolyFlix 已就绪。按 Ctrl+F9 可打开/关闭此日志面板。");
