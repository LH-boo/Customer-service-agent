(() => {
  "use strict";

  const TOKEN_KEY = "h_token";
  const state = {
    token: localStorage.getItem(TOKEN_KEY) || "",
    patient: null,
    sessionId: "",
    sending: false,
    tickets: [],
    ticketCache: new Map(),
    activeTicket: null,
  };

  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

  const STATUS_TEXT = {
    pending: "待受理",
    processing: "处理中",
    waiting_human: "待人工处理",
    resolved: "已解决",
    closed: "已关闭",
    cancelled: "已取消",
  };
  const PRIORITY_TEXT = { low: "低", normal: "普通", high: "较高", urgent: "紧急" };
  const ACTION_TEXT = {
    create: "创建工单",
    assign: "分配部门",
    comment: "处理记录",
    reference: "制度依据",
    resolve: "处理完成",
    close: "关闭工单",
  };

  /* ---------------- 基础工具 ---------------- */
  function escapeHtml(text) {
    return String(text ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function formatText(text) {
    return escapeHtml(text).replace(/\n/g, "<br />");
  }

  function formatTime(value) {
    if (!value) return "-";
    const d = new Date(value);
    if (Number.isNaN(d.getTime())) return String(value).slice(0, 16).replace("T", " ");
    const pad = (n) => String(n).padStart(2, "0");
    return `${d.getMonth() + 1}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
  }

  function toast(message) {
    const el = $("#toast");
    el.textContent = message;
    el.classList.add("show");
    clearTimeout(el._timer);
    el._timer = setTimeout(() => el.classList.remove("show"), 2400);
  }

  async function api(path, options = {}) {
    const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
    if (state.token) headers.Authorization = `Bearer ${state.token}`;
    const resp = await fetch(path, { ...options, headers });
    if (resp.status === 401) {
      logout(false);
      throw new Error("登录已失效，请重新登录");
    }
    const text = await resp.text();
    const data = text ? JSON.parse(text) : null;
    if (!resp.ok) {
      throw new Error((data && (data.detail || data.error)) || `请求失败（${resp.status}）`);
    }
    return data;
  }

  function newSessionId() {
    const raw = crypto.randomUUID ? crypto.randomUUID().replace(/-/g, "") : String(Math.random()).slice(2);
    return raw.slice(0, 32);
  }

  function ensureSession(patientNo) {
    const key = `h_session_${patientNo}`;
    let sid = localStorage.getItem(key);
    if (!sid) {
      sid = newSessionId();
      localStorage.setItem(key, sid);
    }
    state.sessionId = sid;
  }

  /* ---------------- 登录 ---------------- */
  function showLogin() {
    $("#loginLayer").classList.remove("hidden");
    $("#app").classList.add("hidden");
  }

  function showApp() {
    $("#loginLayer").classList.add("hidden");
    $("#app").classList.remove("hidden");
    $("#userName").textContent = state.patient.name;
    $("#userNo").textContent = state.patient.patient_no;
    $("#avatar").textContent = state.patient.name.slice(0, 1);
    $("#avatar").title = `${state.patient.name} ${state.patient.patient_no}`;
  }

  async function doLogin(event) {
    event.preventDefault();
    const patientNo = $("#patientNo").value.trim();
    const phone = $("#phone").value.trim();
    const errorEl = $("#loginError");
    const btn = $("#loginBtn");
    errorEl.textContent = "";
    btn.disabled = true;
    btn.textContent = "登录中…";
    try {
      const data = await api("/api/auth/login", {
        method: "POST",
        body: JSON.stringify({ patient_no: patientNo, phone }),
      });
      state.token = data.access_token;
      state.patient = data.patient;
      localStorage.setItem(TOKEN_KEY, state.token);
      ensureSession(data.patient.patient_no);
      showApp();
      resetChat();
      await Promise.all([restoreHistory(), loadTickets()]);
    } catch (err) {
      errorEl.textContent = err.message;
    } finally {
      btn.disabled = false;
      btn.textContent = "登录并开始咨询";
    }
  }

  function logout(showTip = true) {
    state.token = "";
    state.patient = null;
    localStorage.removeItem(TOKEN_KEY);
    state.tickets = [];
    state.ticketCache.clear();
    state.activeTicket = null;
    showLogin();
    if (showTip) toast("已退出登录");
  }

  /* ---------------- 视图切换 ---------------- */
  function switchView(view) {
    $$(".nav-item").forEach((b) => b.classList.toggle("active", b.dataset.view === view));
    $("#chatView").classList.toggle("active", view === "chat");
    $("#ticketView").classList.toggle("active", view === "tickets");
    if (view === "tickets") loadTickets();
  }

  /* ---------------- 聊天 ---------------- */
  function greetingNode() {
    return `<div class="msg assistant">
      <div class="avatar-sm">仁</div>
      <div class="bubble">
        <p>您好，我是仁心医院患者服务中心的智能客服。我可以帮您查询预约、报告、费用，解答就医与医保政策，也可以受理投诉并创建工单。</p>
        <p class="muted">涉及取消预约等操作，我会先核实信息并与您二次确认。</p>
      </div>
    </div>`;
  }

  function resetChat() {
    $("#messages").innerHTML = greetingNode();
    updateQuickRow(true);
  }

  function updateQuickRow(visible) {
    $("#quickRow").classList.toggle("hidden", !visible);
  }

  function appendUserMessage(text) {
    const wrap = document.createElement("div");
    wrap.className = "msg user";
    wrap.innerHTML = `<div class="avatar-sm">我</div><div class="bubble">${formatText(text)}</div>`;
    $("#messages").appendChild(wrap);
    scrollBottom();
  }

  function appendTyping() {
    const wrap = document.createElement("div");
    wrap.className = "msg assistant";
    wrap.id = "typingMsg";
    wrap.innerHTML = `<div class="avatar-sm">仁</div><div class="bubble"><div class="typing"><i></i><i></i><i></i></div></div>`;
    $("#messages").appendChild(wrap);
    scrollBottom();
  }

  function removeTyping() {
    const el = $("#typingMsg");
    if (el) el.remove();
  }

  function appendAssistantMessage(data) {
    const wrap = document.createElement("div");
    wrap.className = "msg assistant";

    const chips = [];
    if (data.intent_label) {
      chips.push(`<span class="chip brand">${escapeHtml(data.intent_label)}</span>`);
    }
    if (data.priority && data.priority !== "normal" && !data.emergency) {
      chips.push(`<span class="chip warn">优先级：${PRIORITY_TEXT[data.priority] || data.priority}</span>`);
    }
    if (data.cached) chips.push(`<span class="chip">缓存命中</span>`);
    if (data.emergency) chips.push(`<span class="chip danger">紧急提示</span>`);
    if (data.need_human) chips.push(`<span class="chip warn">需人工跟进</span>`);
    if (data.ticket_id) {
      chips.push(
        `<span class="chip ticket" data-ticket="${escapeHtml(data.ticket_id)}">工单 ${escapeHtml(data.ticket_id)} · 查看进度</span>`
      );
    }

    let sourcesHtml = "";
    if (Array.isArray(data.sources) && data.sources.length) {
      const items = data.sources
        .map(
          (s) => `<div class="source-item">
              <strong>《${escapeHtml(s.title)}》·${escapeHtml(s.section)}</strong>
              <p>${escapeHtml(s.snippet || "")}</p>
            </div>`
        )
        .join("");
      sourcesHtml = `<details class="sources">
          <summary>知识库依据（${data.sources.length}）</summary>
          <div class="source-list">${items}</div>
        </details>`;
    }

    let traceHtml = "";
    if (Array.isArray(data.trace) && data.trace.length) {
      const items = data.trace.map((t) => `<li>${escapeHtml(t)}</li>`).join("");
      traceHtml = `<details class="trace-box">
          <summary>查看 Agent 执行过程</summary>
          <ul class="trace-list">${items}</ul>
        </details>`;
    }

    wrap.innerHTML = `
      <div class="avatar-sm">仁</div>
      <div class="bubble">
        <div>${formatText(data.answer || "")}</div>
        ${chips.length ? `<div class="msg-meta">${chips.join("")}</div>` : ""}
        ${sourcesHtml}
        ${traceHtml}
      </div>`;
    $("#messages").appendChild(wrap);
    scrollBottom();
  }

  function scrollBottom() {
    const box = $("#messages");
    box.scrollTop = box.scrollHeight;
  }

  async function sendMessage(text) {
    if (!text || state.sending) return;
    const input = $("#chatInput");
    state.sending = true;
    $("#sendBtn").disabled = true;
    input.disabled = true;
    appendUserMessage(text);
    updateQuickRow(false);
    appendTyping();
    try {
      const data = await api("/api/chat", {
        method: "POST",
        body: JSON.stringify({ message: text, session_id: state.sessionId }),
      });
      state.sessionId = data.session_id || state.sessionId;
      localStorage.setItem(`h_session_${state.patient.patient_no}`, state.sessionId);
      removeTyping();
      appendAssistantMessage(data);
      if (data.ticket_id) loadTickets();
    } catch (err) {
      removeTyping();
      appendAssistantMessage({ answer: `抱歉，${err.message}`, trace: [] });
    } finally {
      state.sending = false;
      $("#sendBtn").disabled = false;
      input.disabled = false;
      input.value = "";
      autoResize(input);
      input.focus();
    }
  }

  async function restoreHistory() {
    if (!state.patient) return;
    try {
      const rows = await api(`/api/chat/history?session_id=${encodeURIComponent(state.sessionId)}`);
      if (!Array.isArray(rows) || !rows.length) return;
      $("#messages").innerHTML = "";
      rows.forEach((row) => {
        if (row.role === "user") {
          appendUserMessage(row.content);
        } else {
          appendAssistantMessage({ answer: row.content, intent_label: "" });
        }
      });
      updateQuickRow(false);
    } catch (err) {
      /* 历史恢复失败不影响当前会话 */
    }
  }

  function autoResize(el) {
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 120)}px`;
  }

  /* ---------------- 工单 ---------------- */
  async function loadTickets() {
    if (!state.patient) return;
    try {
      const list = await api("/api/tickets");
      state.tickets = Array.isArray(list) ? list : [];
      renderTickets();
      const badge = $("#ticketBadge");
      badge.textContent = state.tickets.length;
      badge.classList.toggle("hidden", state.tickets.length === 0);
      if (state.activeTicket) {
        const still = state.tickets.find((t) => t.ticket_no === state.activeTicket);
        if (!still) closeDetail();
      }
    } catch (err) {
      $("#ticketList").innerHTML = `<div class="empty-state">${escapeHtml(err.message)}</div>`;
    }
  }

  function renderTickets() {
    const box = $("#ticketList");
    if (!state.tickets.length) {
      box.innerHTML = `<div class="empty-state">暂无工单。您可以在对话框中提交投诉建议，系统会自动创建工单。</div>`;
      return;
    }
    box.innerHTML = state.tickets
      .map((t) => {
        const status = STATUS_TEXT[t.status] || t.status;
        return `<div class="ticket-card ${state.activeTicket === t.ticket_no ? "active" : ""}" data-ticket="${escapeHtml(t.ticket_no)}">
          <div class="ticket-card-top">
            <span class="ticket-no">${escapeHtml(t.ticket_no)}</span>
            <span class="badge ${escapeHtml(t.status)}">${escapeHtml(status)}</span>
          </div>
          <div class="ticket-title">${escapeHtml(t.title)}</div>
          <div class="ticket-sub">
            <span>${escapeHtml(t.category)}</span>
            <span>${escapeHtml(t.department)}</span>
            <span>更新于 ${formatTime(t.updated_at)}</span>
          </div>
        </div>`;
      })
      .join("");
  }

  async function openTicket(ticketNo) {
    switchView("tickets");
    state.activeTicket = ticketNo;
    renderTickets();
    const box = $("#ticketDetail");
    let detail = state.ticketCache.get(ticketNo);
    if (!detail) {
      box.innerHTML = `<div class="empty-state">加载中…</div>`;
      try {
        detail = await api(`/api/tickets/${encodeURIComponent(ticketNo)}`);
        state.ticketCache.set(ticketNo, detail);
      } catch (err) {
        box.innerHTML = `<div class="empty-state">${escapeHtml(err.message)}</div>`;
        return;
      }
    }
    renderDetail(detail);
  }

  function renderDetail(t) {
    const status = STATUS_TEXT[t.status] || t.status;
    const logs = (t.logs || [])
      .map(
        (log) => `<li>
          <span class="log-time">${formatTime(log.created_at)}</span>
          <span class="log-op">${escapeHtml(log.operator)}</span>
          <div class="log-time">${escapeHtml(ACTION_TEXT[log.action] || log.action)}</div>
          <p>${escapeHtml(log.content)}</p>
        </li>`
      )
      .join("");
    $("#ticketDetail").innerHTML = `
      <div class="detail-head">
        <div>
          <span class="ticket-no">${escapeHtml(t.ticket_no)}</span>
          <h3>${escapeHtml(t.title)}</h3>
        </div>
        <span class="badge ${escapeHtml(t.status)}">${escapeHtml(status)}</span>
      </div>
      <div class="detail-meta">
        <div class="meta-box"><span>工单类型</span><strong>${escapeHtml(t.category)}</strong></div>
        <div class="meta-box"><span>处理部门</span><strong>${escapeHtml(t.department)}</strong></div>
        <div class="meta-box"><span>优先级</span><strong>${escapeHtml(PRIORITY_TEXT[t.priority] || t.priority)}</strong></div>
        <div class="meta-box"><span>创建时间</span><strong>${formatTime(t.created_at)}</strong></div>
      </div>
      <div class="detail-section">
        <h4>问题描述</h4>
        <div class="detail-content">${escapeHtml(t.content)}</div>
      </div>
      <div class="detail-section">
        <h4>处理进度</h4>
        <ul class="timeline">${logs || '<li><p>暂无流转记录</p></li>'}</ul>
      </div>`;
  }

  function closeDetail() {
    state.activeTicket = null;
    $("#ticketDetail").innerHTML = `<div class="empty-state">选择左侧工单查看详情</div>`;
  }

  /* ---------------- 事件绑定 ---------------- */
  function bindEvents() {
    $("#loginForm").addEventListener("submit", doLogin);
    $("#logoutBtn").addEventListener("click", () => logout(true));

    $$(".nav-item").forEach((btn) => {
      btn.addEventListener("click", () => switchView(btn.dataset.view));
    });

    $("#chatForm").addEventListener("submit", (e) => {
      e.preventDefault();
      const text = $("#chatInput").value.trim();
      if (text) sendMessage(text);
    });

    $("#chatInput").addEventListener("input", (e) => autoResize(e.target));
    $("#chatInput").addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
        e.preventDefault();
        $("#chatForm").requestSubmit();
      }
    });

    $("#quickRow").addEventListener("click", (e) => {
      const btn = e.target.closest("button[data-q]");
      if (btn) sendMessage(btn.dataset.q);
    });

    $("#messages").addEventListener("click", (e) => {
      const chip = e.target.closest("[data-ticket]");
      if (chip) openTicket(chip.dataset.ticket);
    });

    $("#ticketList").addEventListener("click", (e) => {
      const card = e.target.closest("[data-ticket]");
      if (card) openTicket(card.dataset.ticket);
    });

    $("#refreshTickets").addEventListener("click", async () => {
      state.ticketCache.clear();
      await loadTickets();
      toast("工单已刷新");
    });

    $("#newChatBtn").addEventListener("click", () => {
      if (!state.patient) return;
      state.sessionId = newSessionId();
      localStorage.setItem(`h_session_${state.patient.patient_no}`, state.sessionId);
      $("#messages").innerHTML = greetingNode();
      updateQuickRow(true);
      toast("已开启新会话");
    });
  }

  async function bootstrap() {
    bindEvents();
    if (!state.token) {
      showLogin();
      return;
    }
    try {
      state.patient = await api("/api/auth/me");
      ensureSession(state.patient.patient_no);
      showApp();
      resetChat();
      await Promise.all([restoreHistory(), loadTickets()]);
    } catch (err) {
      showLogin();
    }
  }

  document.addEventListener("DOMContentLoaded", bootstrap);
})();
