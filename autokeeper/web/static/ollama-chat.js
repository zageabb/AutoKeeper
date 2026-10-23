/* AutoKeeper browser Ollama chat, Markdown knowledge, record-change review. */
"use strict";
(function () {
  const base = window.AUTO_BASE || "";
  const el = id => document.getElementById(id);
  const panel = el("ollama-panel"), toggle = el("ollama-toggle");
  const area = el("ollama-messages"), form = el("ollama-chat-form");
  const input = el("ollama-input"), model = el("ollama-model");
  const status = el("ollama-status"), send = el("ollama-send");
  const propose = el("ollama-propose"), stop = el("ollama-stop");
  const dialog = el("knowledge-dialog"), source = el("knowledge-source");
  const preview = el("knowledge-preview"), kbStatus = el("knowledge-status");
  let history = [], lastInstruction = "", controller = null, busy = false;
  let revision = "", savedSource = "", previewVersion = 0, previewTimer;

  async function request(path, options) {
    const opts = Object.assign({headers: {}}, options || {});
    if (opts.method && opts.method !== "GET") opts.headers["X-AutoKeeper-Request"] = "same-origin";
    const res = await fetch(base + path, opts);
    if (!res.ok) {
      let error = "HTTP " + res.status;
      try { const json = await res.json(); error = String(json.detail || error); }
      catch (_) { /* status fallback */ }
      throw new Error(error);
    }
    return res;
  }
  const jsonOptions = (method, payload) => ({
    method, headers: {"Content-Type":"application/json"}, body: JSON.stringify(payload)
  });
  async function json(path, opts) { return (await request(path, opts)).json(); }
  function announce(text, failure) {
    status.textContent = text;
    status.className = "ollama-status" + (failure ? " ollama-error" : "");
  }
  function scroll() { area.scrollTop = area.scrollHeight; }
  function buttons() {
    const ready = !!model.value;
    send.disabled = busy || !ready || !input.value.trim();
    propose.disabled = busy || !ready || !(input.value.trim() || lastInstruction);
    input.disabled = !ready;
    stop.hidden = !controller;
  }
  function addMessage(role, text) {
    const box = document.createElement("section");
    box.className = "ollama-message ollama-" + role;
    const name = document.createElement("strong");
    name.className = "ollama-speaker";
    name.textContent = role === "user" ? "You" : "Ollama";
    const body = document.createElement("div");
    body.className = "markdown-body ollama-answer";
    body.textContent = text;
    box.append(name, body);
    const placeholder = area.querySelector(".ollama-placeholder");
    if (placeholder) placeholder.remove();
    area.append(box);
    scroll();
    return body;
  }
  async function renderMarkdown(target, markdown) {
    try {
      const data = await json("/api/markdown/render",
        jsonOptions("POST", {content: markdown.slice(0, 120000)}));
      target.innerHTML = data.html; // Server-sanitised Markdown only.
    } catch (_) { target.textContent = markdown; }
  }
  async function refreshModels() {
    const prior = model.value;
    model.disabled = true;
    model.replaceChildren(new Option("Connecting…", ""));
    announce("Connecting to Ollama…");
    try {
      const data = await json("/api/ollama/models", {method:"GET"});
      model.replaceChildren();
      for (const m of data.models || []) {
        model.add(new Option(m.name + (m.parameter_size ? " · " + m.parameter_size : ""), m.name));
      }
      if (!(data.models || []).length) {
        model.add(new Option("No installed models", ""));
        announce("No Ollama models are installed.", true);
      } else {
        model.value = data.models.some(m => m.name === prior) ? prior : data.models[0].name;
        model.disabled = false;
        announce(data.models.length + " installed model(s).");
      }
    } catch (error) {
      model.replaceChildren(new Option("Ollama unavailable", ""));
      announce(error.message, true);
    }
    buttons();
  }
  toggle.addEventListener("click", async () => {
    const open = panel.hidden;
    panel.hidden = !open;
    toggle.setAttribute("aria-expanded", String(open));
    if (open) { await refreshModels(); input.focus(); }
  });
  el("ollama-close").addEventListener("click", () => {
    panel.hidden = true;
    toggle.setAttribute("aria-expanded", "false");
    toggle.focus();
  });
  el("ollama-refresh-models").addEventListener("click", refreshModels);
  model.addEventListener("change", buttons);
  el("ollama-new").addEventListener("click", () => {
    if (busy) { announce("Finish or stop the current task first.", true); return; }
    history = []; lastInstruction = "";
    area.innerHTML = '<p class="ollama-placeholder">New chat. You can query vehicle records or prepare proposed changes.</p>';
    announce("Chat history cleared.");
    buttons();
  });
  input.addEventListener("input", buttons);
  input.addEventListener("keydown", event => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      if (!send.disabled) form.requestSubmit();
    }
  });
  stop.addEventListener("click", () => { if (controller) controller.abort(); });

  async function streamChat() {
    const prompt = input.value.trim();
    if (!prompt || busy || !model.value) return;
    lastInstruction = prompt;
    // Include the follow-up without exceeding the server-side context limit.
    const conversation = [...history, {role:"user", content:prompt}].slice(-19);
    while (conversation.reduce((total, m) => total + m.content.length, 0) > 29000) {
      conversation.shift();
    }
    addMessage("user", prompt);
    input.value = "";
    const output = addMessage("assistant", "");
    let answer = "", done = false;
    busy = true;
    controller = new AbortController();
    buttons();
    announce("Ollama is generating…");
    try {
      const res = await request("/api/ollama/chat", {
        ...jsonOptions("POST", {model:model.value, messages:conversation}),
        signal:controller.signal
      });
      if (!res.body) throw new Error("Streaming not supported by browser");
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      function onLine(line) {
        if (!line.trim()) return;
        const event = JSON.parse(line);
        if (event.error) throw new Error(event.error);
        if (typeof event.delta === "string") {
          answer += event.delta;
          output.textContent = answer;
          scroll();
        }
        if (event.done) done = true;
      }
      // Ollama sends an explicit done event. Do not wait for proxy EOF:
      // a reverse proxy may hold the HTTP connection open indefinitely,
      // leaving busy=true and blocking all subsequent messages.
      try {
        while (!done) {
          const block = await reader.read();
          if (block.done) break;
          buffer += decoder.decode(block.value, {stream:true});
          let pos;
          while ((pos = buffer.indexOf("\n")) !== -1) {
            onLine(buffer.slice(0, pos));
            buffer = buffer.slice(pos + 1);
            if (done) break;
          }
        }
        if (!done) {
          buffer += decoder.decode();
          if (buffer.trim()) onLine(buffer);
        }
        if (!done) throw new Error("Ollama response was incomplete.");
      } finally {
        // Cancel remaining response consumption without blocking the UI
        // on a network stream that never sends EOF.
        reader.cancel().catch(() => {});
      }
      // Keep subsequent turns within the API's 20-message/30k-character
      // bounds. The oldest message is discarded only when necessary.
      history = [...conversation,
        {role:"assistant", content:answer.slice(0, 6000)}].slice(-18);
      while (history.reduce((total, m) => total + m.content.length, 0) > 24000) {
        history.shift();
      }
      await renderMarkdown(output, answer);
      announce("Complete · " + model.value);
    } catch (error) {
      const errorText = error.name === "AbortError" ? "Reply stopped." : error.message;
      output.textContent = (answer || "") + "\n\n[" + errorText + "]";
      announce(errorText, error.name !== "AbortError");
    } finally {
      busy = false; controller = null; buttons();
      // The composer must always be reusable after completion, failure or Stop.
      if (!panel.hidden) input.focus();
    }
  }
  form.addEventListener("submit", event => {
    event.preventDefault();
    streamChat();
  });

  function showProposalResult(data) {
    const outer = document.createElement("section");
    outer.className = "ollama-proposal-wrapper";
    const title = document.createElement("h4");
    title.textContent = "Review the proposed changes before applying";
    const explanation = document.createElement("p");
    explanation.textContent = data.explanation || "";
    outer.append(title, explanation);
    if (!data.proposals || !data.proposals.length) {
      const empty = document.createElement("p");
      empty.textContent = "No unambiguous updates could be prepared.";
      outer.append(empty);
    }
    for (const p of data.proposals || []) {
      const card = document.createElement("section");
      card.className = "ollama-proposal";
      const heading = document.createElement("strong");
      heading.textContent = p.registration;
      card.append(heading);
      const table = document.createElement("table");
      table.className = "ollama-diff";
      const hr = table.createTHead().insertRow();
      for (const label of ["Field", "Before", "After"]) {
        const th = document.createElement("th");
        th.textContent = label;
        hr.append(th);
      }
      const body = table.createTBody();
      for (const [field, after] of Object.entries(p.after)) {
        const tr = body.insertRow();
        const before = p.before[field];
        for (const value of [field, before, after]) {
          const cell = tr.insertCell();
          cell.textContent = value === null || value === undefined || value === "" ?
            "(empty)" : String(value);
        }
      }
      card.append(table);
      const approve = document.createElement("button");
      approve.type = "button";
      approve.className = "btn btn-primary";
      approve.textContent = "Apply these changes";
      const outcome = document.createElement("span");
      outcome.className = "ollama-proposal-result";
      approve.addEventListener("click", async () => {
        if (!confirm("Update " + p.registration + " with the displayed values?")) return;
        approve.disabled = true;
        try {
          const reply = await json("/api/ollama/apply", jsonOptions("POST", {id:p.id}));
          outcome.textContent = "Saved: " + reply.registration;
          window.dispatchEvent(new Event("autokeeper-records-changed"));
        } catch (error) {
          outcome.textContent = "Not saved: " + error.message;
          approve.disabled = false;
        }
      });
      card.append(approve, outcome);
      outer.append(card);
    }
    area.append(outer); scroll();
  }
  propose.addEventListener("click", async () => {
    if (busy || !model.value) return;
    const instruction = input.value.trim() || lastInstruction;
    if (!instruction) { announce("Type a requested change first.", true); return; }
    busy = true; buttons();
    announce("Preparing proposed record update — nothing is saved yet.");
    try {
      const result = await json("/api/ollama/propose",
        jsonOptions("POST", {model:model.value, instruction}));
      lastInstruction = instruction;
      showProposalResult(result);
      announce("Review each before/after value before clicking Apply.");
    } catch (error) { announce(error.message, true); }
    finally { busy = false; buttons(); }
  });

  async function openKnowledge() {
    try {
      const data = await json("/api/knowledge", {method:"GET"});
      revision = data.revision; savedSource = data.content; source.value = data.content;
      dialog.showModal();
      kbStatus.textContent = "Loaded · changes are saved privately on the server.";
      await renderKnowledge();
      source.focus();
    } catch (error) { announce(error.message, true); }
  }
  async function renderKnowledge() {
    const version = ++previewVersion;
    const content = source.value;
    el("knowledge-count").textContent = content.length.toLocaleString() + " characters";
    try {
      const result = await json("/api/markdown/render",
        jsonOptions("POST", {content}));
      if (version === previewVersion) preview.innerHTML = result.html;
    } catch (error) {
      if (version === previewVersion) preview.textContent = error.message;
    }
  }
  source.addEventListener("input", () => {
    kbStatus.textContent = source.value === savedSource ? "No changes" : "Unsaved changes";
    clearTimeout(previewTimer);
    previewTimer = setTimeout(renderKnowledge, 350);
  });
  source.addEventListener("keydown", event => {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") {
      event.preventDefault(); el("knowledge-save").click();
    }
    if (event.key === "Tab") {
      event.preventDefault();
      const start = source.selectionStart;
      source.setRangeText("  ", start, source.selectionEnd, "end");
      source.dispatchEvent(new Event("input"));
    }
  });
  el("ollama-knowledge").addEventListener("click", openKnowledge);
  el("knowledge-close").addEventListener("click", () => {
    if (source.value === savedSource ||
        confirm("Discard unsaved knowledge edits?")) dialog.close();
  });
  dialog.addEventListener("cancel", event => {
    if (source.value !== savedSource &&
        !confirm("Discard unsaved knowledge edits?")) event.preventDefault();
  });
  el("knowledge-reload").addEventListener("click", () => {
    if (source.value !== savedSource && !confirm("Discard unsaved edits?")) return;
    dialog.close(); openKnowledge();
  });
  el("knowledge-save").addEventListener("click", async () => {
    const button = el("knowledge-save");
    button.disabled = true; kbStatus.textContent = "Saving…";
    try {
      const saved = await json("/api/knowledge",
        jsonOptions("PUT", {content:source.value, revision}));
      revision = saved.revision; savedSource = saved.content;
      kbStatus.textContent = "Saved. Future Ollama prompts use the updated document.";
    } catch (error) { kbStatus.textContent = "Not saved: " + error.message; }
    finally { button.disabled = false; }
  });
  el("knowledge-download").addEventListener("click", () => {
    const url = URL.createObjectURL(
      new Blob([source.value], {type:"text/markdown;charset=utf-8"}));
    const link = document.createElement("a");
    link.href = url; link.download = "AutoKeeper_Knowledge.md"; link.click();
    URL.revokeObjectURL(url);
  });
  function wrap(before, after, fallback) {
    const start = source.selectionStart, end = source.selectionEnd;
    const selected = source.value.slice(start, end) || fallback || "";
    source.setRangeText(before + selected + after, start, end, "select");
    source.dispatchEvent(new Event("input")); source.focus();
  }
  const fence = String.fromCharCode(96).repeat(3);
  const commands = {
    heading: () => wrap("## ", "", "Heading"),
    bold: () => wrap("**", "**", "bold"),
    italic: () => wrap("*", "*", "italic"),
    link: () => wrap("[", "](https://example.com)", "link"),
    image: () => wrap("![", "](https://example.com/image.png)", "image"),
    code: () => wrap("\n" + fence + "text\n", "\n" + fence + "\n", "code"),
    table: () => wrap("\n| Field | Value |\n| --- | --- |\n| ",
                       " | Data |\n", "Example"),
    task: () => wrap("\n- [ ] ", "\n", "Task"),
    quote: () => wrap("\n> ", "\n", "Quote"),
    rule: () => wrap("\n\n---\n\n", "", ""),
  };
  dialog.querySelectorAll("[data-md]").forEach(button =>
    button.addEventListener("click", () => commands[button.dataset.md]()));
  buttons();
})();
