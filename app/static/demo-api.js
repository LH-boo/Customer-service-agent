/* 静态演示模式：GitHub Pages 没有后端，用浏览器本地数据模拟 /api 接口，让前端界面完整可用。 */
(() => {
  "use strict";

  const params = new URLSearchParams(location.search);
  const isDemo = /(^|\.)github\.io$/i.test(location.hostname) || params.has("demo");
  if (!isDemo) return;

  const realFetch = window.fetch.bind(window);

  const PATIENTS = {
    P2026001: { id: 1, patient_no: "P2026001", name: "张伟", phone: "13800000001", phone_masked: "138****0001" },
    P2026002: { id: 2, patient_no: "P2026002", name: "李静", phone: "13800000002", phone_masked: "138****0002" },
  };
  const TOKEN_PREFIX = "demo-token-";

  const reply = (payload, status = 200) =>
    new Response(JSON.stringify(payload), {
      status,
      headers: { "Content-Type": "application/json; charset=utf-8" },
    });

  const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

  const publicPatient = (p) => ({
    id: p.id,
    patient_no: p.patient_no,
    name: p.name,
    phone_masked: p.phone_masked,
  });

  function currentPatient(headers) {
    const raw = (headers && (headers.Authorization || headers.authorization)) || "";
    const token = String(raw).replace(/^Bearer\s+/i, "");
    if (!token.startsWith(TOKEN_PREFIX)) return null;
    return PATIENTS[token.slice(TOKEN_PREFIX.length)] || null;
  }

  /* ---------------- 本地工单存储 ---------------- */
  const TICKET_KEY = "h_demo_tickets";

  function allTickets() {
    try {
      return JSON.parse(localStorage.getItem(TICKET_KEY) || "{}");
    } catch (err) {
      return {};
    }
  }

  function saveTickets(data) {
    localStorage.setItem(TICKET_KEY, JSON.stringify(data));
  }

  function seedTickets() {
    const store = allTickets();
    if (store.__seeded) return;
    const now = Date.now();
    store.__seeded = true;
    store[1] = [
      {
        ticket_no: "TK20261115001",
        title: "门诊叫号等待时间过长",
        content: "候诊区等待超过 1 小时，希望改进叫号提示。",
        category: "投诉建议",
        priority: "normal",
        department: "门诊服务中心",
        status: "resolved",
        need_human: true,
        created_at: new Date(now - 3 * 864e5).toISOString(),
        updated_at: new Date(now - 2 * 864e5).toISOString(),
        logs: [
          {
            operator: "智能客服 Agent",
            action: "create",
            content: "根据患者反馈创建投诉建议工单，转门诊服务中心。",
            created_at: new Date(now - 3 * 864e5).toISOString(),
          },
          {
            operator: "门诊服务中心 · 王敏",
            action: "resolve",
            content: "已电话回访患者，说明叫号规则并致歉，患者表示理解。",
            created_at: new Date(now - 2 * 864e5).toISOString(),
          },
        ],
      },
    ];
    store[2] = [];
    saveTickets(store);
  }

  function patientTickets(pid) {
    seedTickets();
    const store = allTickets();
    return store[pid] || [];
  }

  function ticketItem(t) {
    return {
      ticket_no: t.ticket_no,
      title: t.title,
      category: t.category,
      priority: t.priority,
      department: t.department,
      status: t.status,
      need_human: t.need_human,
      created_at: t.created_at,
      updated_at: t.updated_at,
    };
  }

  function createTicket(pid, data) {
    const store = allTickets();
    seedTickets();
    const fresh = allTickets();
    const list = fresh[pid] || (fresh[pid] = store[pid] || []);
    const now = new Date();
    const date = `${now.getFullYear()}${String(now.getMonth() + 1).padStart(2, "0")}${String(now.getDate()).padStart(2, "0")}`;
    let seq = list.length + 1;
    let ticketNo = `TK${date}${String(seq).padStart(3, "0")}`;
    while (list.some((t) => t.ticket_no === ticketNo)) {
      seq += 1;
      ticketNo = `TK${date}${String(seq).padStart(3, "0")}`;
    }
    const iso = now.toISOString();
    const ticket = {
      ticket_no: ticketNo,
      title: data.title,
      content: data.content,
      category: data.category,
      priority: data.priority,
      department: data.department,
      status: "waiting_human",
      need_human: true,
      created_at: iso,
      updated_at: iso,
      logs: [
        {
          operator: "智能客服 Agent",
          action: "create",
          content: `根据患者反馈创建${data.category}工单，转${data.department}。`,
          created_at: iso,
        },
        {
          operator: "智能客服 Agent",
          action: "assign",
          content: `工单已分配至${data.department}，工作人员将通过预留手机号与您联系。`,
          created_at: iso,
        },
      ],
    };
    list.unshift(ticket);
    saveTickets(fresh);
    return ticket;
  }

  /* ---------------- 演示业务数据 ---------------- */
  const DEMO_DATA = {
    1: {
      appointments: [
        { no: "AP20260001", department: "内科", doctor: "王丽华", when: "明天 14:30" },
        { no: "AP20260003", department: "内科", doctor: "李国强", when: "3 天后 16:00" },
      ],
      reports: [
        { name: "血常规（五分类）", department: "检验科", status: "检测处理中", updated: "2 小时前" },
        { name: "胸部 CT（平扫）", department: "放射科", status: "报告已出具", updated: "1 天前" },
      ],
      charges: { visit: "V20261118001", total: 510, insurance: 161, self: 349 },
    },
    2: {
      appointments: [{ no: "AP20260004", department: "儿科", doctor: "陈晓", when: "明天 09:00" }],
      reports: [{ name: "尿常规", department: "检验科", status: "报告已出具", updated: "5 小时前" }],
      charges: { visit: "V20261118002", total: 120, insurance: 84, self: 36 },
    },
  };

  const pendingKey = (pid) => `h_demo_pending_cancel_${pid}`;

  /* ---------------- 意图与回复 ---------------- */
  function buildReply(patient, message) {
    const q = message;
    const has = (words) => words.some((w) => q.includes(w));
    const data = DEMO_DATA[patient.id] || DEMO_DATA[1];
    const appointment = data.appointments[0];

    /* 1. 急危重症 */
    if (has(["胸痛", "胸口疼", "呼吸困难", "喘不上气", "大出血", "昏迷", "晕倒", "抽搐", "自杀", "轻生", "中毒", "车祸", "窒息", "休克", "半边瘫"])) {
      return {
        answer:
          "您描述的情况可能属于急危重症，请立即拨打 120 或前往最近的医院急诊科，不要等待在线回复。\n\n本系统仅提供就医指引，不提供诊断、处方或治疗方案。",
        intent: "other",
        intent_label: "紧急提示",
        priority: "urgent",
        emergency: true,
        need_human: true,
        sources: [],
        trace: ["classify：命中紧急关键词", "safety：急危重症拦截，不进入普通工单流程", "review：提示立即拨打 120"],
      };
    }

    /* 2. 待确认的取消预约 */
    const pending = localStorage.getItem(pendingKey(patient.id));
    if (pending) {
      const info = JSON.parse(pending);
      if (has(["不取消", "不要取消", "算了", "先不", "不用了", "我再想想", "不退了"])) {
        localStorage.removeItem(pendingKey(patient.id));
        return {
          answer: `好的，已为您保留预约 ${info.no}（${info.department} ${info.when}），未做任何变更。`,
          intent: "appointment_cancel",
          intent_label: "预约取消",
          priority: "normal",
          sources: [],
          trace: ["classify：识别为「不取消」", "confirm：清除待确认动作，预约保持不变"],
        };
      }
      if (has(["确认", "确定", "是的", "取消", "可以", "同意", "好"])) {
        localStorage.removeItem(pendingKey(patient.id));
        return {
          answer: `已为您取消预约 ${info.no}（${info.department} · ${info.doctor || "—"}｜${info.when}），号源已释放。\n\n如需重新预约，随时告诉我。`,
          intent: "appointment_cancel",
          intent_label: "预约取消",
          priority: "normal",
          sources: [],
          trace: [
            "classify：识别为「确认取消」",
            "confirm：校验预约归属、状态与 2 小时规则",
            "tools：调用 cancel_appointment，预约状态更新为已取消",
            "review：告知取消结果",
          ],
        };
      }
      localStorage.removeItem(pendingKey(patient.id));
    }

    /* 3. 投诉建议 → 建单 */
    if (has(["投诉", "建议", "态度", "等待", "白跑", "没有通知", "未通知", "停诊", "临时调整", "排队", "叫号", "不满", "差评", "投诉我"])) {
      const title = q.length > 26 ? `${q.slice(0, 26)}…` : q;
      const ticket = createTicket(patient.id, {
        title,
        content: q,
        category: "投诉建议",
        priority: "high",
        department: "门诊服务中心",
      });
      return {
        answer: `很抱歉给您带来不便。我已为您创建服务工单：

• 工单编号：${ticket.ticket_no}
• 处理部门：${ticket.department}
• 处理时限：一般投诉 24 小时内响应，复杂投诉 3 个工作日内答复

您可以在「我的工单」查看流转进度，工作人员会通过预留手机号与您联系。`,
        intent: "complaint",
        intent_label: "投诉建议",
        priority: "high",
        ticket_id: ticket.ticket_no,
        ticket_status: ticket.status,
        need_human: true,
        sources: [
          {
            title: "医院服务制度",
            source: "data/knowledge/service_policy.md",
            section: "投诉处理时限",
            snippet: "一般投诉 24 小时内响应，复杂投诉 3 个工作日内答复，处理结果电话回访患者。",
            score: 0.93,
          },
        ],
        trace: [
          "classify：识别为「投诉建议」，优先级 high",
          "safety：未命中紧急与隐私关键词",
          "tools：get_appointment 核实预约记录",
          "rag：检索《医院服务制度》投诉处理时限",
          `ticket：创建工单 ${ticket.ticket_no}，分配门诊服务中心`,
          "review：生成答复并标记转人工",
        ],
      };
    }

    /* 4. 报告查询 */
    if (has(["报告", "结果", "化验", "CT", "B超", "检查单", "什么时候出来"])) {
      const rows = data.reports.map((r) => `• ${r.name}｜${r.department}｜${r.status}｜更新于 ${r.updated}`).join("\n");
      return {
        answer: `为您查到最近的检查报告状态：

${rows}

报告出具后可在自助机或检验科窗口领取。报告内容需由医生解读，本系统不提供结果判断或诊断建议。`,
        intent: "report",
        intent_label: "检查报告",
        priority: "normal",
        sources: [
          {
            title: "就诊指南",
            source: "data/knowledge/visit_guide.md",
            section: "检查报告领取",
            snippet: "检验类报告通常在采样后 4-6 小时出具，影像类报告以短信通知为准。",
            score: 0.88,
          },
        ],
        trace: [
          "classify：识别为「检查报告」",
          "safety：通过",
          "tools：调用 get_report_status（按 patient_id 隔离）",
          "review：仅返回状态，不解读结果",
        ],
      };
    }

    /* 5. 费用 / 医保 */
    if (has(["费用", "多少钱", "收费", "发票", "退费", "自费", "明细"])) {
      const c = data.charges;
      return {
        answer: `您最近一次就诊（${c.visit}）费用如下：

• 总费用：${c.total} 元
• 医保统筹支付：${c.insurance} 元
• 个人自付：${c.self} 元

如需费用明细或退费，请携带就诊卡到财务收费处 8 号窗口办理；对费用有异议也可在此提交工单。`,
        intent: "fee",
        intent_label: "费用咨询",
        priority: "normal",
        sources: [
          {
            title: "医保与收费政策",
            source: "data/knowledge/insurance.md",
            section: "门诊费用结算",
            snippet: "门诊费用实行医保直接结算，个人自付部分可通过自助机、窗口或线上支付。",
            score: 0.9,
          },
        ],
        trace: ["classify：识别为「费用咨询」", "safety：通过", "tools：调用 get_charge_detail", "review：最小化返回费用信息"],
      };
    }

    if (has(["医保", "报销", "统筹", "异地就医", "慢特病"])) {
      return {
        answer:
          "门诊医保报销规则（以杭州职工医保为例）：\n\n• 普通门诊：起付线以上、限额以内按比例报销，社区医院比例更高；\n• 检查、检验项目需属于医保目录范围，目录外项目需自费；\n• 异地就医需提前办理备案，可在「国家医保服务平台」或医保办公室 12 号窗口办理。\n\n具体比例以参保地政策为准，可携带医保卡到医保办公室查询。",
        intent: "insurance",
        intent_label: "医保咨询",
        priority: "normal",
        sources: [
          {
            title: "医保与收费政策",
            source: "data/knowledge/insurance.md",
            section: "门诊报销",
            snippet: "普通门诊统筹起付线以上部分按比例报销，具体比例与参保类型、就诊机构级别相关。",
            score: 0.91,
          },
        ],
        trace: ["classify：识别为「医保咨询」", "safety：通过", "rag：混合检索知识库（BM25 + 向量 + RRF）", "review：补充政策以参保地为准的说明"],
      };
    }

    /* 6. 取消预约（首次） */
    if (has(["取消", "退号", "不去了"])) {
      if (!appointment) {
        return {
          answer: "当前没有查到您待就诊的预约记录。如需帮助，请提供预约单号，或到门诊服务中心 1 层 A 区咨询。",
          intent: "appointment_cancel",
          intent_label: "预约取消",
          priority: "normal",
          sources: [],
          trace: ["classify：识别为「预约取消」", "tools：调用 get_appointment，未查到可取消预约"],
        };
      }
      localStorage.setItem(pendingKey(patient.id), JSON.stringify(appointment));
      return {
        answer: `我查到您有一条预约：

• ${appointment.no}｜${appointment.department}${appointment.doctor ? ` · ${appointment.doctor}` : ""}｜${appointment.when}

取消规则：需在就诊时间前 2 小时操作，取消后号源将释放。\n请回复「确认取消」我再为您办理；回复「不取消」则保持原预约不变。`,
        intent: "appointment_cancel",
        intent_label: "预约取消",
        priority: "normal",
        sources: [
          {
            title: "预约挂号须知",
            source: "data/knowledge/appointment.md",
            section: "取消与退号",
            snippet: "就诊前 2 小时可在线取消预约，超时需到窗口办理；累计爽约将影响后续预约。",
            score: 0.89,
          },
        ],
        trace: [
          "classify：识别为「预约取消」",
          "safety：通过",
          "tools：调用 get_appointment（只读，不执行取消）",
          "confirm：写入待确认动作，等待患者二次确认",
        ],
      };
    }

    /* 7. 预约查询 */
    if (has(["预约", "挂号", "号源", "看病"])) {
      const rows = data.appointments.map((a) => `• ${a.no}｜${a.department}${a.doctor ? ` · ${a.doctor}` : ""}｜${a.when}`).join("\n");
      return {
        answer: `您当前的预约记录：

${rows}

就诊当天请提前 15 分钟到院，携带身份证或就诊卡到自助机取号。如需取消，请告诉我预约单号。`,
        intent: "appointment",
        intent_label: "预约查询",
        priority: "normal",
        sources: [],
        trace: ["classify：识别为「预约查询」", "tools：调用 get_appointment", "review：返回预约信息并提示取号流程"],
      };
    }

    /* 8. 就诊指南 */
    if (has(["准备", "材料", "流程", "第一次", "带什么", "就诊", "几点", "怎么走"])) {
      return {
        answer:
          "首次就诊建议准备：\n\n1. 身份证或医保卡（电子医保凭证也可）；\n2. 既往病历、检查报告与正在服用的药物清单；\n3. 提前 15 分钟到院，先到自助机取号再候诊；\n4. 需空腹检查的项目请按预约短信要求禁食。\n\n门诊楼 1 层设导医台，可现场咨询就诊路线。",
        intent: "medical_guide",
        intent_label: "就诊指南",
        priority: "normal",
        sources: [
          {
            title: "就诊指南",
            source: "data/knowledge/visit_guide.md",
            section: "首次就诊",
            snippet: "首次就诊请携带有效身份证件，提前 15 分钟到院完成取号与建档。",
            score: 0.92,
          },
        ],
        trace: ["classify：识别为「就诊指南」", "safety：通过", "rag：检索知识库并生成答复", "review：补充就医边界说明"],
      };
    }

    /* 9. 科室咨询 */
    if (has(["科室", "哪个科", "挂什么科"])) {
      return {
        answer:
          "常见科室对应：\n\n• 内科：感冒发热、咳嗽、高血压、糖尿病等；\n• 外科：外伤、骨折、需手术的疾病；\n• 儿科：0-14 岁儿童常见病与保健；\n\n不确定时可描述症状，我帮您参考；也可到 1 层导医台由护士分诊。",
        intent: "department",
        intent_label: "科室咨询",
        priority: "normal",
        sources: [],
        trace: ["classify：识别为「科室咨询」", "tools：调用 get_department_info", "review：提示以现场分诊为准"],
      };
    }

    /* 10. 兜底 */
    return {
      answer:
        "我可以帮您查询预约、检查报告、费用明细，解答就诊与医保政策，也可以受理投诉建议并创建工单。\n\n请补充更具体的信息，例如预约单号、检查项目或遇到的问题。",
      intent: "other",
      intent_label: "其他咨询",
      priority: "normal",
      sources: [],
      trace: ["classify：未命中明确意图，归类为「其他咨询」", "review：引导补充信息"],
    };
  }

  /* ---------------- fetch 拦截 ---------------- */
  window.fetch = async function (input, init = {}) {
    const url = typeof input === "string" ? input : (input && input.url) || "";
    const path = url.replace(/^https?:\/\/[^/]+/i, "");
    const [pathname, search] = path.split("?");
    const route = pathname.replace(/^.*?(\/api\/)/, "$1");
    if (!route.startsWith("/api/")) return realFetch(input, init);

    const method = String(init.method || (input && input.method) || "GET").toUpperCase();
    const headers = init.headers || {};
    const patient = currentPatient(headers);
    let body = {};
    if (init.body) {
      try {
        body = JSON.parse(init.body);
      } catch (err) {
        body = {};
      }
    }

    await delay(280);

    if (route === "/api/auth/login" && method === "POST") {
      const candidate = PATIENTS[String(body.patient_no || "").trim()];
      if (!candidate || candidate.phone !== String(body.phone || "").trim()) {
        return reply({ detail: "患者编号或手机号不正确" }, 401);
      }
      return reply({
        access_token: `${TOKEN_PREFIX}${candidate.patient_no}`,
        token_type: "bearer",
        patient: publicPatient(candidate),
      });
    }

    if (!patient) return reply({ detail: "登录已失效，请重新登录" }, 401);

    if (route === "/api/auth/me" && method === "GET") {
      return reply(publicPatient(patient));
    }

    if (route === "/api/chat/history" && method === "GET") {
      return reply([]);
    }

    if (route === "/api/chat" && method === "POST") {
      const message = String(body.message || "").trim();
      const sessionId = body.session_id || Math.random().toString(16).slice(2, 18);
      return reply({ session_id: sessionId, ...buildReply(patient, message) });
    }

    if (route === "/api/tickets" && method === "GET") {
      const list = patientTickets(patient.id)
        .slice()
        .sort((a, b) => new Date(b.updated_at) - new Date(a.updated_at))
        .map(ticketItem);
      return reply(list);
    }

    if (route.startsWith("/api/tickets/") && method === "GET") {
      const no = decodeURIComponent(route.slice("/api/tickets/".length));
      const ticket = patientTickets(patient.id).find((t) => t.ticket_no === no);
      if (!ticket) return reply({ detail: "工单不存在或无权访问" }, 404);
      return reply(ticket);
    }

    return realFetch(input, init);
  };

  /* 页面加载后提示当前为静态演示 */
  document.addEventListener("DOMContentLoaded", () => {
    const badge = document.createElement("div");
    badge.textContent = "静态演示模式 · 数据保存在本地浏览器";
    badge.style.cssText =
      "position:fixed;right:14px;bottom:12px;z-index:9999;padding:6px 10px;border-radius:999px;" +
      "background:rgba(23,54,86,.82);color:#fff;font-size:12px;line-height:1;letter-spacing:.2px;" +
      "box-shadow:0 6px 18px rgba(15,35,60,.18);pointer-events:none;";
    document.body.appendChild(badge);
  });
})();
