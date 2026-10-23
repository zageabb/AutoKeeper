/* AutoKeeper browser UI. API and URL prefix are configured by the host. */
"use strict";
(function () {
  const base = window.AUTO_BASE || "";
  const rowsElement = document.getElementById("vehicle-rows");
  const dialog = document.getElementById("vehicle-dialog");
  const form = document.getElementById("vehicle-form");
  const notice = document.getElementById("notice");
  let records = [];
  let editing = null;

  function byId(id) { return document.getElementById(id); }
  function escapeHTML(s) {
    return String(s === null || s === undefined ? "" : s).replace(/[&<>"']/g, function (c) {
      return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c];
    });
  }
  async function api(path, options) {
    const opts = Object.assign({headers: {}}, options || {});
    if (opts.method && opts.method.toUpperCase() !== "GET") {
      opts.headers["X-AutoKeeper-Request"] = "same-origin";
    }
    const response = await fetch(base + path, opts);
    if (!response.ok) {
      let reason = "Request failed (HTTP " + response.status + ")";
      try {
        const data = await response.json();
        if (data.detail) reason = typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail);
      } catch (_) { /* preserve HTTP error */ }
      throw new Error(reason);
    }
    return response.json();
  }
  function jsonOptions(method, body) {
    return {method: method, headers: {"Content-Type":"application/json"}, body: JSON.stringify(body)};
  }
  function message(text, isError) {
    notice.hidden = false;
    notice.textContent = text;
    notice.className = "notice" + (isError ? " error" : "");
  }
  function setText(id, value) { byId(id).textContent = String(value); }
  function formatDate(input) {
    if (!input) return "Not available";
    const d = new Date(input + "T00:00:00");
    return isNaN(d.getTime()) ? "Not available" : d.toLocaleDateString("en-GB", {day:"2-digit",month:"short",year:"numeric"});
  }
  function statusText(data) {
    if (!data || data.state === "unknown") return "No data";
    if (data.state === "sorn") return "SORN";
    if (data.state === "overdue") return "Overdue";
    if (data.state === "due") return data.days === 0 ? "Due today" : "Due soon";
    return "Up to date";
  }
  function dueCell(data, dateText) {
    const value = data || {state:"unknown"};
    const state = ["ok","due","overdue","sorn"].includes(value.state) ? value.state : "unknown";
    return '<span class="date-cell"><span class="pill pill-' + state + '">' +
      escapeHTML(statusText(value)) + '</span><span class="date-text">' +
      escapeHTML(formatDate(dateText)) + '</span></span>';
  }
  function showRows() {
    const q = byId("search").value.trim().toLowerCase();
    const filter = byId("filter").value;
    const filtered = records.filter(function (r) {
      if (q && ![r.registration,r.owner,r.company,r.make,r.model,r.email]
        .some(function (v) { return String(v || "").toLowerCase().includes(q); })) return false;
      if (filter === "attention" && !["due","overdue"].includes(r.mot.state) &&
          !["due","overdue"].includes(r.tax.state)) return false;
      if (filter === "unchecked" && r.last_checked_at) return false;
      if (filter === "missing-email" && r.email) return false;
      return true;
    });
    if (!filtered.length) {
      rowsElement.innerHTML = '<tr><td colspan="7" class="empty">No matching vehicles. Add a vehicle or change the filter.</td></tr>';
    } else {
      rowsElement.innerHTML = filtered.map(function (v) {
        const car = escapeHTML([v.make,v.model].filter(Boolean).join(" ") || "Vehicle details pending");
        const driver = escapeHTML(v.owner || "Not assigned");
        return '<tr>' +
          '<td><div class="vehicle-name"><span class="reg-plate">' + escapeHTML(v.registration) +
          '</span><div class="vehicle-caption">' + car + '</div></div></td>' +
          '<td><div class="primary-cell">' + driver + '</div><div class="secondary-cell">' +
            escapeHTML(v.company || "—") + '</div></td>' +
          '<td>' + dueCell(v.mot, v.mot_expiry_date) + '</td>' +
          '<td>' + dueCell(v.tax, v.tax_due_date) + '</td>' +
          '<td><span class="email-cell">' + escapeHTML(v.email || "Not set") + '</span></td>' +
          '<td><div class="secondary-cell">' + escapeHTML(
            v.last_checked_at ? v.last_checked_at.slice(0,10) : "Never") +
            '</div>' + (v.last_error ? '<div class="error-small">' + escapeHTML(v.last_error) + '</div>' : '') + '</td>' +
          '<td class="row-actions"><button class="small-button" data-action="edit" data-id="' + v.id +
          '" type="button">Edit</button><button class="icon-button" data-action="check" data-id="' + v.id +
          '" type="button" title="Check with DVLA" aria-label="Refresh ' + escapeHTML(v.registration) +
          '">↻</button><button class="icon-button delete" data-action="delete" data-id="' + v.id +
          '" type="button" title="Remove" aria-label="Delete ' + escapeHTML(v.registration) + '">×</button></td>' +
          '</tr>';
      }).join("");
    }
    setText("record-count", filtered.length + " of " + records.length + " vehicles");
  }
  async function load() {
    const data = await api("/api/dashboard", {method:"GET"});
    records = data.vehicles;
    const stats = data.stats;
    setText("stat-total", stats.total);
    setText("stat-mot", stats.mot_due);
    setText("stat-tax", stats.tax_due);
    setText("stat-attention", stats.attention);
    setText("stat-mot-meta", stats.mot_overdue ? stats.mot_overdue + " already overdue" : "Upcoming renewals");
    setText("stat-tax-meta", stats.tax_overdue ? stats.tax_overdue + " already overdue" : "Within the next 30 days");
    setText("unchecked-count", stats.unchecked);
    setText("email-count", stats.missing_email);
    setText("dvla-status", data.dvla_configured ? "Configured" : "Needs API key");
    byId("dvla-status").className = "status-chip " + (data.dvla_configured ? "active" : "pending");
    setText("smtp-status", data.smtp_configured ? "Configured" : "Needs credentials");
    byId("smtp-status").className = "status-chip " + (data.smtp_configured ? "active" : "pending");
    const clear = stats.total - stats.attention;
    const pct = stats.total ? Math.round(100 * clear / stats.total) : 0;
    byId("health-ring").style.setProperty("--progress", String(pct) + "%");
    setText("health-number", stats.total ? pct + "%" : "—");
    setText("health-message", stats.total ? clear + " of " + stats.total + " without imminent expiry" : "No vehicles yet");
    setText("health-description", stats.total ? "Based on known MOT and tax expiry dates. Unknown data needs checking." : "Add a vehicle to see the health summary.");
    showRows();
  }
  function openDialog(row) {
    editing = row ? row.id : null;
    setText("dialog-title", row ? "Edit vehicle" : "Add a vehicle");
    form.reset();
    ["registration","owner","company","email","make","model","colour"].forEach(function (name) {
      byId("field-" + name).value = row ? row[name] || "" : "";
    });
    dialog.showModal();
  }
  async function guarded(fn) {
    try { await fn(); }
    catch (error) { message(error.message || "Something went wrong", true); }
  }
  byId("add-vehicle").addEventListener("click", function () { openDialog(null); });
  byId("close-dialog").addEventListener("click", function () { dialog.close(); });
  byId("cancel-dialog").addEventListener("click", function () { dialog.close(); });
  form.addEventListener("submit", function (event) {
    event.preventDefault();
    guarded(async function () {
      const body = Object.fromEntries(new FormData(form).entries());
      const method = editing === null ? "POST" : "PUT";
      const url = editing === null ? "/api/vehicles" : "/api/vehicles/" + editing;
      await api(url, jsonOptions(method, body));
      dialog.close();
      message("Vehicle saved successfully.");
      await load();
    });
  });
  rowsElement.addEventListener("click", function (event) {
    const button = event.target.closest("button[data-action]");
    if (!button) return;
    const id = Number(button.dataset.id);
    const record = records.find(function (v) { return v.id === id; });
    if (!record) return;
    guarded(async function () {
      if (button.dataset.action === "edit") openDialog(record);
      if (button.dataset.action === "check") {
        button.disabled = true;
        const result = await api("/api/vehicles/" + id + "/refresh", {method:"POST"});
        message(result.success ? "DVLA details updated for " + record.registration :
          "DVLA check failed: " + result.error, !result.success);
        await load();
      }
      if (button.dataset.action === "delete" &&
          window.confirm("Remove " + record.registration + " and its reminder history?")) {
        await api("/api/vehicles/" + id, {method:"DELETE"});
        message(record.registration + " removed.");
        await load();
      }
    });
  });
  byId("refresh-all").addEventListener("click", function () {
    const button = this;
    guarded(async function () {
      button.disabled = true;
      message("Running DVLA checks. This can take a while for larger fleets.");
      try {
        const result = await api("/api/refresh-all", {method:"POST"});
        message("DVLA checked " + result.total + " vehicles: " + result.success +
          " successful, " + result.failed + " failed.", result.failed > 0);
        await load();
      } finally { button.disabled = false; }
    });
  });
  byId("preview-reminders").addEventListener("click", function () {
    guarded(async function () {
      const r = await api("/api/reminders/preview", {method:"POST"});
      message("Reminder preview: " + r.would_send + " would be sent; " +
        r.already_sent + " already sent; " + r.missing_email + " missing email addresses.");
    });
  });
  byId("import-form").addEventListener("submit", function (event) {
    event.preventDefault();
    const selected = byId("import-file").files[0];
    if (!selected) { message("Choose a .xlsx or .csv file to import.", true); return; }
    guarded(async function () {
      const data = new FormData();
      data.append("file", selected);
      const result = await api("/api/import", {method:"POST", body:data});
      message("Import complete: " + result.created + " added, " + result.updated +
        " updated, " + result.skipped + " skipped." +
        (result.errors.length ? " Check source rows with invalid details." : ""), !!result.errors.length);
      byId("import-file").value = "";
      await load();
    });
  });
  byId("search").addEventListener("input", showRows);
  byId("filter").addEventListener("change", showRows);
  guarded(load);
}());
