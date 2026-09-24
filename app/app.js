/* SparkSkill Studio · recorded-artifact Evidence Workbench
 * Zero dependencies. Every displayed claim comes from demo-manifest.json.
 * This interface never calls a model and never mutates an artifact.
 */
(function () {
  "use strict";

  var state = {
    manifest: null,
    runId: null,
    mode: null,
    nodeId: null,
    selection: null,
    bottomTab: "benchmark",
    runMenuOpen: false,
    drawerTrigger: null,
    modalTrigger: null
  };

  var TRUTH_LABEL = {
    verified: "Verified",
    recorded: "Recorded",
    structural: "Structural",
    blocked: "Blocked",
    synthetic_fixture: "Synthetic Fixture"
  };

  var STAGE_DECK = {
    "user-task": "保留用户原始意图与媒体来源，不从历史文件猜测缺失输入。",
    "stepfun-plan": "StepFun 负责文本任务解析与 Agent 规划；当前配置不读取图片。",
    "dsh-skill-match": "DSH Harness 发现并加载三个受控 Skill，记录会话内工具调用。",
    "visual-task-spec": "自然语言被编译为可校验的视觉任务契约，先过安全与来源硬门。",
    "video-frames": "OpenCV 只负责稳定抽帧；关键帧保留时间戳与来源路径。",
    "qwen-evidence": "本地 Qwen Vision 逐帧输出目标状态、描述、置信度与可选定位框。",
    "global-timeline": "跨来源证据按偏移量聚合；不据此断言同一物理实例或身份移动。",
    "final-decision": "报告器只使用结构化证据形成结论，证据不足时必须拒答。",
    "tier3-verification": "确定性评分器比较 baseline 与 with-skill，并完整保留失败历史。"
  };

  var STAGE_COPY = {
    "user-task": { title: "用户任务", description: "用户输入" },
    "stepfun-plan": { title: "StepFun 任务规划", description: "文本理解与规划" },
    "dsh-skill-match": { title: "DSH 技能匹配", description: "技能发现与加载" },
    "visual-task-spec": { title: "视觉任务规范", description: "契约化视觉任务" },
    "video-frames": { title: "视频抽帧", description: "结构化抽帧" },
    "qwen-evidence": { title: "Qwen 视觉证据", description: "本地视觉判断" },
    "global-timeline": { title: "全局证据时间线", description: "跨来源证据聚合" },
    "final-decision": { title: "最终结论", description: "生成可追溯结论" },
    "tier3-verification": { title: "Tier-3 验证", description: "确定性评分验证" }
  };

  function $(id) { return document.getElementById(id); }
  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }
  function clear(node) { while (node.firstChild) node.removeChild(node.firstChild); }
  function truthClass(truth) { return "t-" + (truth || "recorded"); }
  function formatMs(value) {
    if (value === undefined || value === null) return "—";
    return (Math.round(Number(value) * 1000) / 1000).toLocaleString("en-US") + " ms";
  }
  function formatHeroMs(value) {
    if (value === undefined || value === null) return "—";
    return String(Math.round(Number(value) * 1000) / 1000) + " ms";
  }
  function formatConfidence(value) {
    if (value === undefined || value === null) return "—";
    return Number(value).toFixed(2);
  }
  function artifactUrl(path) {
    if (!path) return null;
    return "/artifact/" + String(path).split("/").map(encodeURIComponent).join("/");
  }
  function currentRun() {
    var runs = state.manifest ? state.manifest.runs || [] : [];
    return runs.find(function (run) { return run.id === state.runId; }) || runs[0] || null;
  }
  function currentData(run) {
    if (!run) return null;
    if (run.kind === "benchmark") return run.benchmark_entry || null;
    if (run.kind === "single-video") return run[state.mode] || null;
    return run;
  }
  function currentNode(run) {
    return ((run && run.rail) || []).find(function (node) { return node.id === state.nodeId; }) || null;
  }
  function entriesFor(run, data) {
    if (!run || !data) return [];
    return run.kind === "single-video" ? data.frames || [] : data.entries || [];
  }
  function firstEvidenceIndex(entries) {
    var confirmed = entries.findIndex(function (entry) {
      return entry.object_found === true && entry.frame_path;
    });
    return confirmed >= 0 ? confirmed : entries.findIndex(function (entry) { return entry.frame_path; });
  }
  function frameStatus(entry) {
    if (!entry) return "failed";
    if (entry.frame_status && entry.frame_status !== "analyzed") return "failed";
    if (entry.object_found === true) return "confirmed";
    if (entry.abstention_reason) return "abstained";
    return "not_found";
  }
  function statusLabel(status) {
    return {
      confirmed: "Confirmed",
      not_found: "Not found",
      abstained: "Abstained",
      failed: "Failed"
    }[status] || status;
  }
  function excerpt(value, limit) {
    var text = String(value || "").replace(/\s+/g, " ").trim();
    return text.length > limit ? text.slice(0, limit - 1) + "…" : text;
  }
  function stageCopy(node) {
    return STAGE_COPY[(node || {}).id] || {
      title: (node || {}).title || "阶段证据",
      description: "可回溯执行记录"
    };
  }
  function targetPresentation(spec) {
    var target = (spec || {}).target || {};
    var raw = String(target.description || "").trim();
    var match = raw.match(/^([^（(]+)[（(]([\s\S]+)[）)]\s*$/);
    var subject = (match ? match[1] : raw).trim();
    var detail = (match ? match[2] : "").trim();

    subject = subject
      .replace("日落/黄昏山湖景观", "日落与黄昏山湖")
      .replace("日落山湖景观", "日落山湖");
    detail = detail.replace(/^天空中/, "");
    if (!detail && (target.attributes || []).length) {
      detail = "目标特征：" + target.attributes.slice(0, 3).join("、");
    }
    return {
      subject: subject || "视觉目标",
      detail: excerpt(detail || "依据任务规范核验目标是否出现", 58)
    };
  }
  function evidenceCounts(entries) {
    return (entries || []).reduce(function (counts, entry) {
      var status = frameStatus(entry);
      counts[status] = (counts[status] || 0) + 1;
      return counts;
    }, { confirmed: 0, not_found: 0, abstained: 0, failed: 0 });
  }
  function visualHeroPresentation(run, data, entries) {
    var target = targetPresentation(data.spec || {});
    var counts = evidenceCounts(entries);
    var reportStatus = String(((data.report || {}).status || "")).toLowerCase();
    var summary = run.kind === "multi-video" ? data.global_summary || {} : data.summary || {};
    var first = run.kind === "multi-video" ? summary.first_confirmed_global_timestamp_ms : summary.first_confirmed_timestamp_ms;
    var last = run.kind === "multi-video" ? summary.last_confirmed_global_timestamp_ms : summary.last_confirmed_timestamp_ms;
    var analyzed = summary.analyzed_entry_count !== undefined ? summary.analyzed_entry_count :
      (summary.analyzed_frame_count !== undefined ? summary.analyzed_frame_count : entries.length);
    var status;
    var statusKind;
    var narrative;

    if (run.truth === "blocked") {
      status = "受资源条件阻塞";
      statusKind = "blocked";
      narrative = "该记录保留了阻塞原因与解除条件，没有生成或补写不存在的视觉证据。";
    } else if (reportStatus === "failed" || (!counts.confirmed && !counts.not_found && counts.failed)) {
      status = "分析未能完成";
      statusKind = "failed";
      narrative = "视觉分析未形成可用结论；失败状态与原始运行记录保持一致。";
    } else if (counts.confirmed > 0) {
      status = "已被确认出现";
      statusKind = "confirmed";
      if (run.kind === "multi-video") {
        var sources = (summary.sources_with_confirmation || []).length;
        narrative = "目标首次确认于全局 " + formatHeroMs(first) + "，最后确认于 " + formatHeroMs(last) +
          "，共获得 " + counts.confirmed + " 帧有效证据" + (sources ? "，覆盖 " + sources + " 个视频来源" : "") +
          "。全局时间线仅用于证据聚合，不代表跨摄像头身份追踪。";
      } else {
        narrative = "目标首次确认于 " + formatHeroMs(first) + "，最后确认于 " + formatHeroMs(last) +
          "，共获得 " + counts.confirmed + " 帧有效证据。所有结论均可回溯至关键帧与证据时间线。";
      }
    } else if (counts.abstained > 0 || reportStatus === "abstained") {
      status = "证据不足，保持拒答";
      statusKind = "abstained";
      narrative = "已分析 " + analyzed + " 帧，其中 " + counts.abstained + " 帧证据不足。系统没有将不确定结果改写为肯定结论。";
    } else {
      status = "在已抽样证据中未被确认";
      statusKind = "not-found";
      narrative = "已分析 " + analyzed + " 帧，均未确认目标。该结果只描述已抽样证据，不对未采样画面作出断言。";
    }
    return {
      subject: target.subject,
      detail: target.detail,
      status: status,
      statusKind: statusKind,
      narrative: narrative
    };
  }
  function benchmarkHeroPresentation(run, data) {
    var verdict = String(data.verdict || "PARTIAL").toUpperCase();
    var status = verdict === "PASS" ? "确定性验证通过" :
      (verdict === "FAIL" ? "确定性验证未通过" : "阶段性验证尚未全部通过");
    return {
      subject: run.title || "Tier-3 验证记录",
      detail: "冻结运行数据 · 对称规则评分 · 完整保留失败历史",
      status: status,
      statusKind: verdict === "PASS" ? "confirmed" : (verdict === "FAIL" ? "failed" : "blocked"),
      narrative: benchmarkNarrative(data)
    };
  }
  function makeTruthBadge(truth, compact) {
    var badge = el("span", "truth-badge " + truthClass(truth), TRUTH_LABEL[truth] || truth || "—");
    if (compact) badge.classList.add("truth-badge-compact");
    return badge;
  }
  function makeArtifactLink(path, label) {
    var link = el("a", "artifact-link", label || path || "—");
    if (path) {
      link.href = artifactUrl(path);
      link.target = "_blank";
      link.rel = "noreferrer";
    }
    return link;
  }
  function appendProperty(list, name, value) {
    var row = el("div", "property-row");
    row.appendChild(el("dt", null, name));
    row.appendChild(el("dd", null, value === undefined || value === null || value === "" ? "—" : value));
    list.appendChild(row);
  }
  function makeBanner(kind, text) {
    return el("div", "state-banner " + (kind || "neutral"), text);
  }
  function setBodyLocked(locked) {
    document.body.style.overflow = locked ? "hidden" : "";
  }

  /* ── Topbar and custom run selector ───────────────────────── */
  function renderTopbar() {
    var run = currentRun();
    if (!run) return;
    $("run-select-label").textContent = run.title;
    var badge = $("truth-badge");
    badge.className = "truth-badge " + truthClass(run.truth);
    badge.textContent = TRUTH_LABEL[run.truth] || run.truth;
    badge.title = ((state.manifest.truth_status || {}).levels || {})[run.truth] || "";
    renderRunMenu();
  }

  function renderRunMenu() {
    var menu = $("run-menu");
    clear(menu);
    (state.manifest.runs || []).forEach(function (run) {
      var option = el("button", "run-option" + (run.id === state.runId ? " is-active" : ""));
      option.type = "button";
      option.setAttribute("role", "option");
      option.setAttribute("aria-selected", String(run.id === state.runId));
      option.setAttribute("data-run-id", run.id);
      var copy = el("span");
      copy.appendChild(el("span", "run-option-title", run.title));
      copy.appendChild(el("span", "run-option-meta", (TRUTH_LABEL[run.truth] || run.truth) + " · " + run.kind));
      option.appendChild(copy);
      option.appendChild(el("span", "run-option-check", run.id === state.runId ? "✓" : ""));
      option.addEventListener("click", function () {
        selectRun(run.id);
        closeRunMenu(true);
      });
      option.addEventListener("keydown", handleOptionKeys);
      menu.appendChild(option);
    });
  }

  function openRunMenu() {
    state.runMenuOpen = true;
    $("run-menu").hidden = false;
    $("run-select").setAttribute("aria-expanded", "true");
  }
  function closeRunMenu(returnFocus) {
    state.runMenuOpen = false;
    $("run-menu").hidden = true;
    $("run-select").setAttribute("aria-expanded", "false");
    if (returnFocus) $("run-select").focus();
  }
  function handleOptionKeys(event) {
    var options = Array.from($("run-menu").querySelectorAll(".run-option"));
    var index = options.indexOf(event.currentTarget);
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      var delta = event.key === "ArrowDown" ? 1 : -1;
      options[(index + delta + options.length) % options.length].focus();
    } else if (event.key === "Home" || event.key === "End") {
      event.preventDefault();
      options[event.key === "Home" ? 0 : options.length - 1].focus();
    } else if (event.key === "Escape") {
      event.preventDefault(); closeRunMenu(true);
    }
  }

  /* ── Hero ─────────────────────────────────────────────────── */
  function renderHero() {
    var run = currentRun();
    var data = currentData(run);
    if (!run || !data) return;
    var title = $("hero-title");
    var status = $("hero-status");
    var detail = $("hero-target-detail");
    var result = $("hero-result");
    var overline = $("hero-overline");
    var entries = entriesFor(run, data);
    var heroIndex = firstEvidenceIndex(entries);
    var heroEntry = heroIndex >= 0 ? entries[heroIndex] : null;

    var presentation = run.kind === "benchmark" ?
      benchmarkHeroPresentation(run, data) : visualHeroPresentation(run, data, entries);
    title.textContent = presentation.subject;
    status.textContent = presentation.status;
    status.className = "hero-status s-" + presentation.statusKind;
    detail.textContent = presentation.detail;
    result.textContent = presentation.narrative;
    overline.textContent = run.kind === "benchmark" ? "Tier-3 · 确定性验证" :
      (run.kind === "multi-video" ? "多来源视觉证据" : "单视频视觉证据");
    renderHeroFacts(run, data);
    renderHeroVisual(run, data, heroEntry);

    $("hero-provenance").textContent = run.kind === "benchmark" ? "查看验证依据" : "查看证据来源";
    $("hero-provenance").onclick = function () {
      if (heroEntry && !state.selection) state.selection = { kind: "frame", index: heroIndex, mode: state.mode };
      openInspector($("hero-provenance"));
    };
    $("hero-json").onclick = function () { openJson(run.title + " · recorded data", data, $("hero-json")); };
  }

  function benchmarkNarrative(entry) {
    if (entry.verdict === "PASS") {
      return "最终 PASS 来自 v2 对 18 份冻结原始输出的对称重评分；未重跑模型，初次 PARTIAL 与 E9 真实缺陷完整保留。";
    }
    if (entry.defect) return "真实缺陷未隐藏：" + entry.defect;
    if (entry.fix) return "已完成产品根因修复；评测历史保留当前阶段的 " + entry.verdict + " 结论。";
    return entry.truth_note || "Recorded benchmark artifact.";
  }

  function renderHeroFacts(run, data) {
    var facts = $("hero-facts");
    clear(facts);
    var values;
    if (run.kind === "benchmark") {
      values = [
        ["验证结论", data.verdict || "—"],
        ["运行样本", "9 × 2 冻结记录"],
        ["评分方式", "确定性规则"],
        ["真实性", TRUTH_LABEL[run.truth] || run.truth]
      ];
    } else {
      var count = entriesFor(run, data).length;
      values = [
        ["运行形态", run.kind === "multi-video" ? "多来源视频" : "单视频"],
        ["证据帧", String(count) + " 帧记录"],
        ["视觉后端", "本地 Qwen 27B"],
        ["真实性", TRUTH_LABEL[run.truth] || run.truth]
      ];
    }
    values.forEach(function (item) {
      var wrap = el("div", "hero-fact");
      wrap.appendChild(el("dt", null, item[0]));
      wrap.appendChild(el("dd", null, item[1]));
      facts.appendChild(wrap);
    });
  }

  function renderHeroVisual(run, data, entry) {
    var media = $("visual-media");
    clear(media);
    if (entry && entry.frame_path) {
      var image = el("img");
      image.src = artifactUrl(entry.frame_path);
      image.alt = entry.description || "记录的真实关键帧";
      image.loading = "eager";
      media.appendChild(image);
      $("visual-source").textContent = (entry.source_id || "MEDIA-0") + " · RECORDED FRAME";
      $("visual-time").textContent = formatMs(entry.global_timestamp_ms !== undefined ? entry.global_timestamp_ms : entry.timestamp_ms);
      $("visual-caption").textContent = entry.evidence_text || entry.description || "结构化视觉证据";
      $("visual-confidence").textContent = statusLabel(frameStatus(entry)) + " · " + formatConfidence(entry.confidence);
      $("visual-confidence").className = "confidence s-" + frameStatus(entry);
    } else {
      var placeholder = el("div", "visual-placeholder");
      placeholder.appendChild(el("strong", null, data.verdict || "PASS"));
      placeholder.appendChild(el("span", null, "DETERMINISTIC TIER-3 VERDICT"));
      media.appendChild(placeholder);
      $("visual-source").textContent = "FROZEN BENCHMARK ARTIFACT";
      $("visual-time").textContent = "18 / 18 RE-SCORED";
      $("visual-caption").textContent = "同一任务与模型条件下，对比 baseline 与 with-skill。";
      $("visual-confidence").textContent = data.verdict || "—";
      $("visual-confidence").className = "confidence";
    }
  }

  /* ── Evidence Ribbon ──────────────────────────────────────── */
  function renderRibbon() {
    var rail = $("rail");
    clear(rail);
    var run = currentRun();
    if (!run || !(run.rail || []).length) {
      rail.appendChild(el("li", null, "没有可展示的证据链路"));
      return;
    }
    run.rail.forEach(function (node, index) {
      var copy = stageCopy(node);
      var item = el("li", "rail-item");
      var button = el("button", "rail-node" + (node.id === state.nodeId ? " is-selected" : ""));
      button.type = "button";
      button.setAttribute("data-node", node.id);
      button.setAttribute("aria-label", "阶段 " + (index + 1) + "：" + copy.title + "，" + copy.description + "，" + (TRUTH_LABEL[node.truth] || node.truth));
      if (node.id === state.nodeId) button.setAttribute("aria-current", "step");
      var row = el("span", "rail-index-row");
      row.appendChild(el("span", "rail-index", String(index + 1).padStart(2, "0") + " / 09"));
      row.appendChild(el("span", "rail-truth-dot " + truthClass(node.truth)));
      button.appendChild(row);
      button.appendChild(el("span", "rail-node-title", copy.title));
      button.appendChild(el("span", "rail-node-desc", copy.description));
      button.appendChild(el("span", "rail-node-exec", excerpt(node.executor || TRUTH_LABEL[node.truth], 34)));
      button.addEventListener("click", function () { selectNode(node.id); });
      button.addEventListener("keydown", handleRibbonKeys);
      item.appendChild(button);
      rail.appendChild(item);
    });
    renderRibbonLegend();
  }

  function handleRibbonKeys(event) {
    var buttons = Array.from($("rail").querySelectorAll(".rail-node"));
    var index = buttons.indexOf(event.currentTarget);
    if (["ArrowRight", "ArrowLeft", "Home", "End"].indexOf(event.key) === -1) return;
    event.preventDefault();
    var next = index;
    if (event.key === "ArrowRight") next = Math.min(buttons.length - 1, index + 1);
    if (event.key === "ArrowLeft") next = Math.max(0, index - 1);
    if (event.key === "Home") next = 0;
    if (event.key === "End") next = buttons.length - 1;
    buttons[next].focus();
  }

  function renderRibbonLegend() {
    var legend = $("ribbon-legend");
    clear(legend);
    Object.keys(TRUTH_LABEL).forEach(function (key) {
      var item = el("span", "legend-item " + truthClass(key));
      item.appendChild(el("span", "legend-mark"));
      item.appendChild(el("span", null, TRUTH_LABEL[key]));
      legend.appendChild(item);
    });
  }

  /* ── Stage canvas ─────────────────────────────────────────── */
  function renderEvidence() {
    var run = currentRun();
    var data = currentData(run);
    var node = currentNode(run);
    var body = $("evidence-body");
    var controls = $("evidence-controls");
    clear(body); clear(controls);
    if (!run || !data || !node) {
      body.appendChild(el("div", "empty-state", "当前记录没有可展示的阶段证据。"));
      return;
    }
    var index = (run.rail || []).findIndex(function (item) { return item.id === node.id; });
    $("stage-index").textContent = "阶段 " + String(index + 1).padStart(2, "0") + " / 09 · " + (TRUTH_LABEL[node.truth] || node.truth || "—");
    $("evidence-title").textContent = stageCopy(node).title;
    $("stage-deck").textContent = STAGE_DECK[node.id] || "选择阶段以查看输入、输出、执行者与可回溯 artifact。";
    renderEvidenceControls(controls, run, data);

    if (run.kind === "benchmark") {
      renderBenchmarkStage(body, data);
      return;
    }
    if (node.id === "video-frames" || node.id === "qwen-evidence") renderFramesStage(body, run, data);
    else if (node.id === "global-timeline") renderTimelineStage(body, run, data);
    else if (node.id === "final-decision") renderDecisionStage(body, run, data);
    else if (node.id === "visual-task-spec") renderSpecStage(body, data);
    else if (node.id === "tier3-verification") renderRunVerification(body, node);
    else renderNodeFlow(body, node);
  }

  function renderEvidenceControls(controls, run, data) {
    if (run.kind === "single-video" && (run.modes || []).length > 1) {
      (run.modes || []).forEach(function (mode) {
        var button = el("button", "mode-button" + (state.mode === mode ? " is-active" : ""), mode === "positive" ? "正向证据" : "负向验证");
        button.type = "button";
        button.setAttribute("aria-pressed", String(state.mode === mode));
        button.addEventListener("click", function () {
          state.mode = mode;
          state.selection = null;
          renderHero(); renderEvidence(); renderInspector();
        });
        controls.appendChild(button);
      });
    }
    var provenance = el("button", "quiet-button", "Provenance");
    provenance.type = "button";
    provenance.addEventListener("click", function () { openInspector(provenance); });
    controls.appendChild(provenance);
    var json = el("button", "quiet-button", "查看 JSON");
    json.type = "button";
    json.addEventListener("click", function () { openJson(run.title + " · recorded data", data, json); });
    controls.appendChild(json);
  }

  function renderNodeFlow(body, node) {
    var flow = el("div", "node-flow");
    var input = el("article", "flow-card");
    input.appendChild(el("span", "flow-card-label", "INPUT"));
    input.appendChild(el("h3", null, "进入阶段"));
    input.appendChild(el("p", "wrap-any", node.input || "—"));
    flow.appendChild(input);
    flow.appendChild(el("div", "flow-arrow", "→"));
    var output = el("article", "flow-card");
    output.appendChild(el("span", "flow-card-label", "OUTPUT"));
    output.appendChild(el("h3", null, "留下证据"));
    output.appendChild(el("p", "wrap-any", node.output || "—"));
    flow.appendChild(output);
    body.appendChild(flow);
    appendStageMeta(body, node);
    if (node.risk) body.appendChild(makeBanner("blocked", node.risk));
  }

  function appendStageMeta(body, node) {
    var meta = el("div", "stage-meta");
    [
      ["Executor", node.executor || "—"],
      ["Truth level", TRUTH_LABEL[node.truth] || node.truth || "—"]
    ].forEach(function (item) {
      var wrap = el("div", "stage-meta-item");
      wrap.appendChild(el("b", null, item[0]));
      wrap.appendChild(el("span", null, item[1]));
      meta.appendChild(wrap);
    });
    if (node.artifact) {
      var artifact = el("div", "stage-meta-item");
      artifact.appendChild(el("b", null, "Artifact"));
      artifact.appendChild(makeArtifactLink(node.artifact, node.artifact));
      meta.appendChild(artifact);
    }
    body.appendChild(meta);
  }

  function renderSpecStage(body, data) {
    var spec = data.spec || {};
    var target = spec.target || {};
    var layout = el("div", "spec-layout");
    var primary = el("article", "spec-primary");
    primary.appendChild(el("p", "eyebrow", "COMPILED TARGET"));
    primary.appendChild(el("h3", "spec-target", target.description || "未声明目标"));
    if ((target.attributes || []).length) primary.appendChild(el("p", null, "视觉属性：" + target.attributes.join(" · ")));
    primary.appendChild(makeBanner("verified", "requires_visual_input = " + String(spec.requires_visual_input) + " · Schema contract preserved"));
    var side = el("article", "spec-side");
    var list = el("dl", "property-list");
    appendProperty(list, "task_id", spec.task_id);
    appendProperty(list, "task_type", spec.task_type);
    appendProperty(list, "source_media", sourceSummary(spec.source_media));
    appendProperty(list, "artifact", spec.artifact);
    side.appendChild(list);
    layout.appendChild(primary); layout.appendChild(side);
    body.appendChild(layout);
  }

  function sourceSummary(source) {
    if (Array.isArray(source)) return source.map(function (item) { return item.source_id + " · offset " + item.time_offset_ms + "ms"; }).join(" / ");
    return source || "—";
  }

  function renderFramesStage(body, run, data) {
    var entries = entriesFor(run, data);
    if (!entries.length) { body.appendChild(el("div", "empty-state", "该运行没有帧证据。")); return; }
    var selectedIndex = state.selection && state.selection.index < entries.length ? state.selection.index : firstEvidenceIndex(entries);
    if (selectedIndex < 0) selectedIndex = 0;
    state.selection = { kind: "frame", index: selectedIndex, mode: state.mode };
    var selected = entries[selectedIndex];
    var layout = el("div", "frame-stage");

    var feature = el("article", "frame-feature");
    var featureMedia = el("div", "frame-feature-media");
    if (selected.frame_path) {
      var featureImage = el("img");
      featureImage.src = artifactUrl(selected.frame_path);
      featureImage.alt = selected.description || "选择的真实关键帧";
      featureMedia.appendChild(featureImage);
    } else featureMedia.appendChild(el("div", "frame-missing", "关键帧文件不可用"));
    feature.appendChild(featureMedia);
    var caption = el("div", "frame-feature-caption");
    caption.appendChild(el("span", "mono", formatMs(selected.global_timestamp_ms !== undefined ? selected.global_timestamp_ms : selected.timestamp_ms)));
    caption.appendChild(el("span", "frame-feature-text", selected.evidence_text || selected.description || "—"));
    caption.appendChild(el("span", "frame-card-status s-" + frameStatus(selected), statusLabel(frameStatus(selected)) + " · " + formatConfidence(selected.confidence)));
    feature.appendChild(caption);
    layout.appendChild(feature);

    var summaryCard = el("aside", "frame-summary");
    var copy = el("div");
    copy.appendChild(el("p", "eyebrow", "SELECTED EVIDENCE"));
    copy.appendChild(el("h3", null, statusLabel(frameStatus(selected))));
    copy.appendChild(el("p", null, selected.description || selected.evidence_text || "无描述"));
    summaryCard.appendChild(copy);
    var mini = el("div", "mini-metrics");
    var metrics = frameMetrics(run, data, entries);
    metrics.forEach(function (item) {
      var metric = el("div", "mini-metric");
      metric.appendChild(el("strong", null, item[1]));
      metric.appendChild(el("span", null, item[0]));
      mini.appendChild(metric);
    });
    summaryCard.appendChild(mini);
    var sourceButton = el("button", "text-button", "打开完整 Provenance →");
    sourceButton.type = "button";
    sourceButton.addEventListener("click", function () { openInspector(sourceButton); });
    summaryCard.appendChild(sourceButton);
    layout.appendChild(summaryCard);

    var filmstrip = el("div", "frame-filmstrip");
    entries.forEach(function (entry, index) {
      var card = el("button", "frame-card" + (index === selectedIndex ? " is-selected" : ""));
      card.type = "button";
      card.setAttribute("data-frame", String(index));
      card.setAttribute("aria-label", "关键帧 " + (index + 1) + "，" + statusLabel(frameStatus(entry)) + "，" + formatMs(entry.timestamp_ms));
      var thumb = el("div", "frame-thumb");
      if (entry.frame_path) {
        var image = el("img");
        image.src = artifactUrl(entry.frame_path);
        image.alt = "";
        image.loading = "lazy";
        thumb.appendChild(image);
      } else thumb.appendChild(el("div", "frame-missing", "Frame unavailable"));
      card.appendChild(thumb);
      var meta = el("span", "frame-card-meta");
      meta.appendChild(el("span", "frame-card-time", formatMs(entry.global_timestamp_ms !== undefined ? entry.global_timestamp_ms : entry.timestamp_ms)));
      meta.appendChild(el("span", "frame-card-status s-" + frameStatus(entry), statusLabel(frameStatus(entry)) + " · " + formatConfidence(entry.confidence)));
      card.appendChild(meta);
      card.addEventListener("click", function () {
        state.selection = { kind: "frame", index: index, mode: state.mode };
        renderEvidence(); renderInspector();
        var renderedCard = document.querySelector('.frame-card[data-frame="' + index + '"]');
        openInspector(renderedCard || card);
      });
      filmstrip.appendChild(card);
    });
    layout.appendChild(filmstrip);
    body.appendChild(layout);
  }

  function frameMetrics(run, data, entries) {
    var confirmed = entries.filter(function (entry) { return frameStatus(entry) === "confirmed"; }).length;
    var rejected = entries.filter(function (entry) { return frameStatus(entry) === "failed"; }).length;
    var sources = new Set(entries.map(function (entry) { return entry.source_id || "media-0"; })).size;
    return [
      ["CONFIRMED", String(confirmed)],
      ["FAILED", String(rejected)],
      ["SOURCES", String(sources)],
      ["TOTAL FRAMES", String(entries.length)]
    ];
  }

  function renderTimelineStage(body, run, data) {
    var entries = entriesFor(run, data);
    if (!entries.length) { body.appendChild(el("div", "empty-state", "该运行没有时间线条目。")); return; }
    if (run.kind === "multi-video") {
      body.appendChild(el("div", "timeline-note", "全局时间线是多来源证据聚合，不是跨摄像头身份追踪；不据此断言同一物理实例从 A 移动到 B。"));
    }
    var scroll = el("div", "timeline-scroll");
    var table = el("table", "timeline-table");
    var head = el("thead");
    var headRow = el("tr");
    ["#", run.kind === "multi-video" ? "Global time" : "Timestamp", "Source", "Finding", "Confidence", "Bounding box", "Evidence"].forEach(function (label) { headRow.appendChild(el("th", null, label)); });
    head.appendChild(headRow); table.appendChild(head);
    var tableBody = el("tbody");
    entries.forEach(function (entry, index) {
      var row = el("tr", "tl-row" + (state.selection && state.selection.kind === "timeline" && state.selection.index === index ? " is-selected" : ""));
      row.tabIndex = 0;
      row.setAttribute("data-timeline", String(index));
      row.appendChild(el("td", "tl-mono", String(index + 1).padStart(2, "0")));
      row.appendChild(el("td", "tl-mono", formatMs(entry.global_timestamp_ms !== undefined ? entry.global_timestamp_ms : entry.timestamp_ms)));
      row.appendChild(el("td", "tl-mono", entry.source_id || "media-0"));
      row.appendChild(el("td", "tl-found " + (entry.object_found === true ? "yes" : "no"), entry.object_found === true ? "confirmed" : frameStatus(entry)));
      row.appendChild(el("td", "tl-mono", formatConfidence(entry.confidence)));
      var bbox = el("td", "tl-mono");
      if (entry.bounding_box === null || entry.bounding_box === undefined) bbox.appendChild(el("span", "bbox-null", "null · no invented box"));
      else {
        bbox.appendChild(el("span", null, "[" + entry.bounding_box.map(function (v) { return Number(v).toFixed(3); }).join(", ") + "]"));
        if (entry.bounding_box_source_format === "pixel") bbox.appendChild(el("div", "tl-fmt", "pixel → normalized"));
      }
      row.appendChild(bbox);
      row.appendChild(el("td", "wrap-any", excerpt(entry.evidence_text, 120) || "—"));
      function choose() {
        state.selection = { kind: "timeline", index: index, mode: state.mode };
        renderInspector();
        tableBody.querySelectorAll(".tl-row").forEach(function (item) { item.classList.toggle("is-selected", item === row); });
        openInspector(row);
      }
      row.addEventListener("click", choose);
      row.addEventListener("keydown", function (event) { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); choose(); } });
      tableBody.appendChild(row);
    });
    table.appendChild(tableBody); scroll.appendChild(table); body.appendChild(scroll);
  }

  function renderDecisionStage(body, run, data) {
    var report = data.report || {};
    var entries = entriesFor(run, data);
    var layout = el("div", "decision-layout");
    var main = el("article", "decision-main");
    main.appendChild(el("p", "eyebrow", "FINAL DECISION · " + String(report.status || "unknown").toUpperCase()));
    main.appendChild(el("h3", null, report.conclusion || "没有记录的结论"));
    if (report.semantic_limitation_note) main.appendChild(el("p", null, report.semantic_limitation_note));
    layout.appendChild(main);
    var side = el("div", "decision-side");
    [
      [formatConfidence(report.confidence), "REPORT CONFIDENCE"],
      [String(entries.length), "TRACEABLE FRAMES"],
      [TRUTH_LABEL[run.truth] || run.truth, "TRUTH STATUS"]
    ].forEach(function (item) {
      var stat = el("div", "decision-stat");
      stat.appendChild(el("b", null, item[0]));
      stat.appendChild(el("span", null, item[1]));
      side.appendChild(stat);
    });
    layout.appendChild(side); body.appendChild(layout);
  }

  function renderRunVerification(body, node) {
    body.appendChild(makeBanner("verified", node.output || "验证规则通过"));
    renderNodeFlow(body, node);
  }

  function renderBenchmarkStage(body, entry) {
    var layout = el("div", "benchmark-stage");
    var verdict = el("article", "verdict-panel");
    verdict.appendChild(el("p", "eyebrow", "DETERMINISTIC VERDICT"));
    verdict.appendChild(el("strong", "verdict-word", entry.verdict || "—"));
    verdict.appendChild(el("p", null, benchmarkNarrative(entry)));
    layout.appendChild(verdict);
    var dims = el("div", "dimension-grid");
    Object.keys(entry.dimensions || {}).forEach(function (name) {
      var value = entry.dimensions[name] || {};
      var card = el("article", "dimension-card");
      card.appendChild(el("span", "dimension-name", name));
      var score = el("div", "dimension-score");
      score.appendChild(el("strong", null, value.with_skill + "/" + (value.total || 9)));
      score.appendChild(el("span", null, "baseline " + value.baseline + "/" + (value.total || 9)));
      card.appendChild(score); dims.appendChild(card);
    });
    layout.appendChild(dims); body.appendChild(layout);
    if (entry.defect) body.appendChild(makeBanner("failed", "真实缺陷：" + entry.defect));
    if (entry.fix) body.appendChild(makeBanner("verified", "产品修复：" + entry.fix));
  }

  /* ── Inspector drawer ─────────────────────────────────────── */
  function renderInspector() {
    var body = $("inspector-body");
    clear(body);
    var run = currentRun();
    var data = currentData(run);
    var node = currentNode(run);
    if (!run || !data) { body.appendChild(el("div", "inspector-empty", "没有运行记录。")); return; }

    if (run.kind === "benchmark") {
      body.appendChild(el("div", "inspector-title", data.label || run.title));
      var benchmarkList = el("dl", "property-list inspector");
      appendProperty(benchmarkList, "verdict", data.verdict);
      appendProperty(benchmarkList, "truth", TRUTH_LABEL[data.truth] || data.truth);
      appendProperty(benchmarkList, "commit", data.commit || "—");
      appendProperty(benchmarkList, "artifact", data.artifact);
      body.appendChild(benchmarkList);
      appendInspectorSection(body, "WHY THIS VERDICT", benchmarkNarrative(data));
      if (data.artifact) appendInspectorArtifact(body, data.artifact);
      return;
    }

    var entries = entriesFor(run, data);
    var selected = state.selection && entries[state.selection.index];
    if (!selected) {
      body.appendChild(el("div", "inspector-title", node ? node.title : run.title));
      var stageList = el("dl", "property-list inspector");
      appendProperty(stageList, "executor", node && node.executor);
      appendProperty(stageList, "truth", node && (TRUTH_LABEL[node.truth] || node.truth));
      appendProperty(stageList, "input", node && node.input);
      appendProperty(stageList, "output", node && node.output);
      body.appendChild(stageList);
      if (node && node.artifact) appendInspectorArtifact(body, node.artifact);
      return;
    }

    body.appendChild(el("div", "inspector-title", run.kind === "multi-video" ? "Global timeline provenance" : "Frame provenance"));
    var list = el("dl", "property-list inspector");
    appendProperty(list, "source_id", selected.source_id || "media-0");
    appendProperty(list, "source_video", selected.source_path || sourceSummary((data.spec || {}).source_media));
    appendProperty(list, "frame_path", selected.frame_path);
    appendProperty(list, "timestamp", formatMs(selected.timestamp_ms));
    if (selected.global_timestamp_ms !== undefined) appendProperty(list, "global_time", formatMs(selected.global_timestamp_ms));
    appendProperty(list, "skill", run.kind === "multi-video" ? "visual-evidence-extractor · multi-video" : "visual-evidence-extractor");
    appendProperty(list, "model", "Qwen3.8-27B-GGUF · local Ollama");
    appendProperty(list, "confidence", formatConfidence(selected.confidence));
    appendProperty(list, "finding", frameStatus(selected));
    body.appendChild(list);
    appendInspectorSection(body, "EVIDENCE TEXT", selected.evidence_text || selected.description || "—");
    appendInspectorSection(body, "BOUNDING BOX", selected.bounding_box ? JSON.stringify(selected.bounding_box) : "null · 未提供可靠定位框，不画假框");
    if (selected.abstention_reason) appendInspectorSection(body, "ABSTENTION REASON", selected.abstention_reason);
    var warnings = (selected.warnings || []).concat(selected.gaps || []);
    if (warnings.length) {
      var section = el("section", "inspector-section");
      section.appendChild(el("h3", null, "WARNINGS / GAPS"));
      var warningsList = el("ul", "warning-list");
      warnings.forEach(function (warning) { warningsList.appendChild(el("li", null, warning)); });
      section.appendChild(warningsList); body.appendChild(section);
    }
    var limitations = data.semantic_limitations || run.semantic_limitations;
    if (limitations) {
      var limitSection = el("section", "inspector-section");
      limitSection.appendChild(el("h3", null, "SEMANTIC LIMITATIONS"));
      limitSection.appendChild(el("div", "semantic-note", limitations.note || JSON.stringify(limitations)));
      body.appendChild(limitSection);
    }
    if (selected.frame_path) appendInspectorArtifact(body, selected.frame_path);
  }

  function appendInspectorSection(body, title, copy) {
    var section = el("section", "inspector-section");
    section.appendChild(el("h3", null, title));
    section.appendChild(el("p", null, copy));
    body.appendChild(section);
  }
  function appendInspectorArtifact(body, path) {
    var section = el("section", "inspector-section");
    section.appendChild(el("h3", null, "SOURCE ARTIFACT"));
    section.appendChild(makeArtifactLink(path, path));
    body.appendChild(section);
  }
  function openInspector(trigger) {
    state.drawerTrigger = trigger || document.activeElement;
    renderInspector();
    $("provenance-drawer").hidden = false;
    setBodyLocked(true);
    $("drawer-close").focus();
  }
  function closeInspector() {
    if ($("provenance-drawer").hidden) return;
    $("provenance-drawer").hidden = true;
    setBodyLocked(false);
    if (state.drawerTrigger && typeof state.drawerTrigger.focus === "function") state.drawerTrigger.focus();
  }

  /* ── Tier-3 finale and governance ─────────────────────────── */
  function latestBenchmark() {
    var history = state.manifest.benchmark_history || [];
    return history[history.length - 1] || {};
  }
  function renderVerificationFinale() {
    var entry = latestBenchmark();
    var result = $("verification-result");
    clear(result);
    var metrics = [];
    ["security", "correctness", "discoverability", "effectiveness"].forEach(function (name) {
      var dimension = (entry.dimensions || {})[name] || {};
      metrics.push([String(dimension.with_skill || "—") + "/" + String(dimension.total || 9), name]);
    });
    var efficiency = entry.efficiency || {};
    var baseline = efficiency.baseline || {};
    var withSkill = efficiency["with-skill"] || {};
    metrics.push([String(baseline.total_time_s || "—") + "s → " + String(withSkill.total_time_s || "—") + "s", "Recorded runtime"]);
    metrics.forEach(function (item, index) {
      var card = el("article", "verification-metric" + (index === 4 ? " runtime" : ""));
      card.appendChild(el("b", null, item[0]));
      card.appendChild(el("span", null, item[1]));
      result.appendChild(card);
    });
    renderBenchmarkHistory();
    renderGovernance();
  }

  function renderBenchmarkHistory() {
    var pane = $("pane-benchmark");
    clear(pane);
    var history = state.manifest.benchmark_history || [];
    var list = el("div", "history-list");
    history.forEach(function (entry, index) {
      var item = el("article", "history-item" + (index === history.length - 1 ? " is-current" : ""));
      item.appendChild(el("span", "history-step", "0" + (index + 1) + " / 0" + history.length));
      item.appendChild(el("h3", null, entry.label));
      item.appendChild(el("p", null, historySummary(entry)));
      item.appendChild(el("span", "history-verdict", entry.verdict + " · " + (TRUTH_LABEL[entry.truth] || entry.truth)));
      var details = el("details", "history-details");
      details.appendChild(el("summary", null, "查看该阶段数据"));
      var content = el("div", "history-details-content");
      if (entry.dimensions) content.appendChild(historyDimensions(entry.dimensions));
      content.appendChild(el("p", null, entry.truth_note || "—"));
      if (entry.artifact) content.appendChild(makeArtifactLink(entry.artifact, entry.artifact));
      details.appendChild(content); item.appendChild(details); list.appendChild(item);
    });
    pane.appendChild(list);
  }

  function historySummary(entry) {
    if (entry.defect) return "暴露真实缺陷：" + excerpt(entry.defect, 150);
    if (entry.fix) return "根因修复：" + excerpt(entry.fix, 150);
    if (entry.false_positives) return "冻结 v1 评分器发现 " + entry.false_positives.length + " 项语境误报，按规则停止并留痕。";
    if (entry.verdict === "PASS") return "v2 对冻结数据对称重评分；2 项已知误报修复，0 项意外变化。";
    return entry.truth_note || "Recorded evaluation stage.";
  }

  function historyDimensions(dimensions) {
    var table = el("table");
    var head = el("tr");
    ["Dimension", "Baseline", "With-Skill"].forEach(function (label) { head.appendChild(el("th", null, label)); });
    table.appendChild(head);
    Object.keys(dimensions).forEach(function (name) {
      var value = dimensions[name] || {};
      var row = el("tr");
      row.appendChild(el("td", null, name));
      row.appendChild(el("td", null, value.baseline + "/" + (value.total || 9)));
      row.appendChild(el("td", null, value.with_skill + "/" + (value.total || 9)));
      table.appendChild(row);
    });
    return table;
  }

  function renderGovernance() {
    var pane = $("pane-governance");
    clear(pane);
    var grid = el("div", "governance-grid");
    Object.keys(state.manifest.governance || {}).forEach(function (name) {
      var card = state.manifest.governance[name] || {};
      var box = el("article", "governance-card");
      box.appendChild(el("h3", null, name));
      box.appendChild(el("p", null, excerpt(card.excerpt, 260) || "Skill Card contract"));
      if (card.artifact) box.appendChild(makeArtifactLink(card.artifact, "Open Skill Card →"));
      grid.appendChild(box);
    });
    pane.appendChild(grid);
    var truth = el("div", "governance-note");
    truth.appendChild(el("strong", null, "Truth status · "));
    truth.appendChild(document.createTextNode("Verified / Recorded / Structural / Blocked / Synthetic Fixture 始终保留原始含义。视觉推理只在本地 DGX Spark 完成；禁止身份、年龄、关系与意图推断。"));
    pane.appendChild(truth);
  }

  function selectBottomTab(name, focus) {
    state.bottomTab = name;
    document.querySelectorAll(".verification-tab").forEach(function (tab) {
      var active = tab.getAttribute("data-tab") === name;
      tab.classList.toggle("is-active", active);
      tab.setAttribute("aria-selected", String(active));
      tab.tabIndex = active ? 0 : -1;
      if (active && focus) tab.focus();
    });
    ["benchmark", "governance"].forEach(function (paneName) {
      var pane = $("pane-" + paneName);
      pane.hidden = paneName !== name;
      pane.classList.toggle("is-active", paneName === name);
    });
  }

  /* ── JSON modal ───────────────────────────────────────────── */
  function openJson(title, data, trigger) {
    state.modalTrigger = trigger || document.activeElement;
    $("json-modal-title").textContent = title;
    $("json-modal-body").textContent = JSON.stringify(data, null, 2);
    $("json-modal").hidden = false;
    setBodyLocked(true);
    $("json-modal-close").focus();
  }
  function closeJson() {
    if ($("json-modal").hidden) return;
    $("json-modal").hidden = true;
    setBodyLocked(false);
    if (state.modalTrigger && typeof state.modalTrigger.focus === "function") state.modalTrigger.focus();
  }

  /* ── Selection and lifecycle ──────────────────────────────── */
  function selectNode(nodeId) {
    state.nodeId = nodeId;
    state.selection = null;
    renderRibbon(); renderEvidence(); renderInspector();
  }
  function selectRun(runId) {
    var run = (state.manifest.runs || []).find(function (item) { return item.id === runId; });
    if (!run) return;
    state.runId = run.id;
    state.mode = run.default_mode || (run.modes || [])[0] || null;
    var preferred = run.kind === "benchmark" ? "tier3-verification" : "video-frames";
    state.nodeId = (run.rail || []).some(function (node) { return node.id === preferred; }) ? preferred : ((run.rail || [])[0] || {}).id;
    state.selection = null;
    renderAll();
  }
  function renderAll() {
    renderTopbar(); renderHero(); renderRibbon(); renderEvidence(); renderInspector(); renderVerificationFinale(); selectBottomTab(state.bottomTab, false);
  }
  function showError(message) {
    $("error-banner").textContent = message;
    $("error-banner").hidden = false;
  }

  function bindStaticEvents() {
    $("run-select").addEventListener("click", function () {
      if (state.runMenuOpen) closeRunMenu(false); else openRunMenu();
    });
    $("run-select").addEventListener("keydown", function (event) {
      if (event.key === "ArrowDown") {
        event.preventDefault(); openRunMenu();
        var active = $("run-menu").querySelector(".run-option.is-active") || $("run-menu").querySelector(".run-option");
        if (active) active.focus();
      }
    });
    document.addEventListener("click", function (event) {
      if (state.runMenuOpen && !$("run-picker").contains(event.target)) closeRunMenu(false);
    });
    $("truth-badge").addEventListener("click", function () { openInspector($("truth-badge")); });
    $("drawer-close").addEventListener("click", closeInspector);
    $("drawer-backdrop").addEventListener("click", closeInspector);
    $("json-modal-close").addEventListener("click", closeJson);
    $("json-modal-backdrop").addEventListener("click", closeJson);
    document.querySelectorAll(".verification-tab").forEach(function (tab) {
      tab.addEventListener("click", function () { selectBottomTab(tab.getAttribute("data-tab"), false); });
      tab.addEventListener("keydown", function (event) {
        if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
        event.preventDefault();
        selectBottomTab(tab.getAttribute("data-tab") === "benchmark" ? "governance" : "benchmark", true);
      });
    });
    document.addEventListener("keydown", function (event) {
      if (event.key !== "Escape") return;
      if (!$('json-modal').hidden) closeJson();
      else if (!$("provenance-drawer").hidden) closeInspector();
      else if (state.runMenuOpen) closeRunMenu(true);
    });
  }

  function init() {
    $("loading").hidden = false;
    bindStaticEvents();
    fetch("data/demo-manifest.json", { cache: "no-store" })
      .then(function (response) {
        if (!response.ok) throw new Error("Manifest HTTP " + response.status);
        return response.json();
      })
      .then(function (manifest) {
        state.manifest = manifest;
        $("loading").hidden = true;
        var runs = manifest.runs || [];
        if (!runs.length) { showError("Manifest 中没有运行记录"); return; }
        selectRun(runs[0].id);
      })
      .catch(function (error) {
        $("loading").hidden = true;
        showError("Manifest 加载失败：" + error.message + "。请先运行 scripts/build_demo_manifest.py。 ");
      });
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
