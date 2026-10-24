/* AutoKeeper browser UI. API and URL prefix are configured by the host. */
"use strict";
(function () {
  // LOCAL_UBUNTU_PROXY_COMPAT: requests follow browser page path, not server root_path.
  const base = window.AUTO_BASE || "";
  const rowsElement = document.getElementById("vehicle-rows");
  const dialog = document.getElementById("vehicle-dialog");
  const form = document.getElementById("vehicle-form");
  const notice = document.getElementById("notice");
  let records = [];
  let companies = [];
  let fleetStats = null;
  let selectedCompany = "all";
  const collapsedCompanies = new Set();
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
    if (data.state === "disposed") return "Disposed";
    if (data.state === "overdue") return "Overdue";
    if (data.state === "due") return data.days === 0 ? "Due today" : "Due soon";
    return "Up to date";
  }
  function dueCell(data, dateText, reportedStatus) {
    const value = data || {state:"unknown"};
    const state = ["ok","due","overdue","sorn","disposed"].includes(value.state) ? value.state : "unknown";
    return '<span class="date-cell"><span class="pill pill-' + state + '">' +
      escapeHTML(statusText(value)) + '</span><span class="date-text">' +
      escapeHTML(formatDate(dateText)) + '</span>' +
      (reportedStatus ? '<span class="dvla-raw-status">DVLA: ' +
        escapeHTML(reportedStatus) + '</span>' : '') + '</span>';
  }
  function companyScopedVehicles() {
    return selectedCompany === "all" ? records :
      records.filter(function (v) { return "company:" + v.company_key === selectedCompany; });
  }
  function selectedCompanyRecord() {
    if (selectedCompany === "all") return null;
    return companies.find(function (c) { return "company:" + c.key === selectedCompany; }) || null;
  }
  function renderCompanySelector() {
    const select = byId("company-select");
    const choices = ['<option value="all">All companies</option>'].concat(
      companies.map(function (c) {
        return '<option value="' + escapeHTML("company:" + c.key) + '">' +
          escapeHTML(c.name) + ' (' + c.stats.total + ')</option>';
      })
    );
    select.innerHTML = choices.join("");
    const valid = selectedCompany === "all" ||
      companies.some(function (c) { return "company:" + c.key === selectedCompany; });
    if (!valid) selectedCompany = "all";
    select.value = selectedCompany;
    byId("company-suggestions").innerHTML = companies.filter(function (c) {
      return c.key !== "";
    }).map(function (c) {
      return '<option value="' + escapeHTML(c.name) + '"></option>';
    }).join("");
  }
  function updateCompanyStats() {
    const chosen = selectedCompanyRecord();
    const stats = chosen ? chosen.stats : fleetStats;
    if (!stats) return;
    const scope = chosen ? chosen.name : "All companies";
    setText("company-scope", scope + " · " + stats.active + " active / " + stats.disposed + " disposed" +
      (!chosen ? " across " + companies.length + " company groups" : ""));
    setText("stat-total", stats.total);
    setText("stat-vehicle-meta", stats.active + " active · " + stats.disposed + " disposed");
    setText("stat-mot", stats.mot_due);
    setText("stat-tax", stats.tax_due);
    setText("stat-attention", stats.attention);
    setText("stat-mot-meta", stats.mot_overdue ? stats.mot_overdue + " already overdue" : "Upcoming renewals");
    setText("stat-tax-meta", stats.tax_overdue ? stats.tax_overdue + " already overdue" : "Within the next 30 days");
    setText("unchecked-count", stats.unchecked);
    setText("email-count", stats.missing_email);
    const clear = stats.clear;
    const pct = stats.active ? Math.round(100 * clear / stats.active) : 0;
    byId("health-ring").style.setProperty("--progress", String(pct) + "%");
    setText("health-number", stats.active ? pct + "%" : "—");
    setText("health-message", stats.active ?
      clear + " of " + stats.active + " active vehicles without imminent expiry" : "No active vehicles");
    setText("health-description", stats.active ?
      stats.unknown + " active vehicles have missing expiry information; check DVLA before treating them as compliant." :
      "Disposed vehicles remain in the register for historical reference.");
  }
  function isDue(state) {
    return state === "due" || state === "overdue";
  }
  function vehicleRow(v) {
    const car = escapeHTML([v.make,v.model].filter(Boolean).join(" ") || "Vehicle details pending");
    const driver = escapeHTML(v.owner || "Not assigned");
    return '<tr>' +
      '<td><div class="vehicle-name"><span class="reg-plate">' + escapeHTML(v.registration) +
      '</span><div class="vehicle-caption">' + car + '</div></div></td>' +
      '<td><div class="primary-cell">' + driver + '</div><div class="secondary-cell">' +
        escapeHTML(v.company || "—") + '</div></td>' +
      '<td><span class="date-text">' + escapeHTML(formatDate(v.acquisition_date)) + '</span></td>' +
      '<td><span class="date-text">' + escapeHTML(formatDate(v.disposal_date)) + '</span>' +
        (v.lifecycle_state === "disposed" ? '<span class="pill pill-disposed">Disposed</span>' :
         v.lifecycle_state === "scheduled" ? '<span class="pill pill-due">Scheduled</span>' : '') + '</td>' +
      '<td>' + dueCell(v.mot, v.mot_expiry_date, v.lifecycle_state === "disposed" ? v.mot_status : "") + '</td>' +
      '<td>' + dueCell(v.tax, v.tax_due_date, v.lifecycle_state === "disposed" ? v.tax_status : "") + '</td>' +
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
  }
  function companyHeader(group, entries) {
    const collapsed = collapsedCompanies.has(group.key);
    const managed = entries.filter(function (v) { return v.lifecycle_state !== "disposed"; });
    const dueMOT = managed.filter(function (v) { return isDue(v.mot.state); }).length;
    const dueTax = managed.filter(function (v) { return isDue(v.tax.state); }).length;
    const attention = managed.filter(function (v) {
      return isDue(v.mot.state) || isDue(v.tax.state);
    }).length;
    const disposed = entries.filter(function (v) { return v.lifecycle_state === "disposed"; }).length;
    return '<tr class="company-group-row"><td colspan="9">' +
      '<button class="company-toggle" type="button" data-company-key="' +
      escapeHTML(group.key) + '" aria-expanded="' + (!collapsed) + '">' +
      '<span class="company-group-title"><span class="company-chevron" aria-hidden="true">' +
      (collapsed ? "▸" : "▾") + '</span><span>' + escapeHTML(group.name) + '</span></span>' +
      '<span class="company-group-metrics"><span>' + entries.length + ' vehicle' +
      (entries.length === 1 ? '' : 's') + '</span><span>Disposed: ' + disposed + '</span><span>MOT due / overdue: ' +
      dueMOT + '</span><span>Tax due / overdue: ' + dueTax +
      '</span><span class="company-attention">Attention: ' + attention +
      '</span></span></button></td></tr>';
  }
  function showRows() {
    const q = byId("search").value.trim().toLowerCase();
    const filter = byId("filter").value;
    const scoped = companyScopedVehicles();
    const filtered = scoped.filter(function (v) {
      if (q && ![v.registration,v.owner,v.company,v.make,v.model,v.email]
        .some(function (s) { return String(s || "").toLowerCase().includes(q); })) return false;
      if (filter === "active" && v.lifecycle_state === "disposed") return false;
      if (filter === "disposed" && v.lifecycle_state !== "disposed") return false;
      if (filter === "attention" && (v.lifecycle_state === "disposed" ||
          (!isDue(v.mot.state) && !isDue(v.tax.state)))) return false;
      if (filter === "unchecked" && v.last_checked_at) return false;
      if (filter === "missing-email" && v.email) return false;
      return true;
    });
    if (!filtered.length) {
      rowsElement.innerHTML = '<tr><td colspan="9" class="empty">No matching vehicles. Try another company or filter.</td></tr>';
    } else {
      const buckets = new Map();
      for (const v of filtered) {
        if (!buckets.has(v.company_key)) buckets.set(v.company_key, []);
        buckets.get(v.company_key).push(v);
      }
      rowsElement.innerHTML = companies.filter(function (g) {
        return buckets.has(g.key);
      }).map(function (g) {
        return companyHeader(g, buckets.get(g.key)) +
          (collapsedCompanies.has(g.key) ? "" : buckets.get(g.key).map(vehicleRow).join(""));
      }).join("");
    }
    setText("record-count", filtered.length + " matching of " + scoped.length +
      " vehicles" + (selectedCompany === "all" ? " (all companies)" : ""));
  }
  async function load() {
    const data = await api("/api/dashboard", {method:"GET"});
    records = data.vehicles;
    companies = data.companies || [];
    fleetStats = data.stats;
    renderCompanySelector();
    updateCompanyStats();
    setText("dvla-status", data.dvla_configured ? "Configured" : "Needs API key");
    byId("dvla-status").className = "status-chip " + (data.dvla_configured ? "active" : "pending");
    setText("smtp-status", data.smtp_configured ? "Configured" : "Needs credentials");
    byId("smtp-status").className = "status-chip " + (data.smtp_configured ? "active" : "pending");
    showRows();
  }
  function openDialog(row) {
    editing = row ? row.id : null;
    setText("dialog-title", row ? "Edit vehicle" : "Add a vehicle");
    form.reset();
    ["registration","owner","company","email","make","model","colour","acquisition_date","disposal_date"].forEach(function (name) {
      const selected = selectedCompanyRecord();
      byId("field-" + name).value = row ? row[name] || "" :
        (name === "company" && selected && selected.key !== "" ? selected.name : "");
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
    const toggle = event.target.closest("button[data-company-key]");
    if (toggle) {
      const key = toggle.dataset.companyKey;
      if (collapsedCompanies.has(key)) collapsedCompanies.delete(key);
      else collapsedCompanies.add(key);
      showRows();
      return;
    }
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
  async function manualRefresh(scope, button) {
    button.disabled = true;
    message(scope === "disposed" ? "Checking disposed vehicles with DVLA." :
      "Checking active vehicles with DVLA.");
    try {
      const result = await api("/api/refresh-all?scope=" + scope, {method:"POST"});
      message("DVLA checked " + result.total + " " + scope + " vehicles: " +
        result.success + " successful, " + result.failed + " failed." +
        (scope === "active" ? " " + result.skipped_disposed + " disposed vehicles skipped." : ""),
        result.failed > 0);
      await load();
    } finally { button.disabled = false; }
  }
  byId("refresh-all").addEventListener("click", function () {
    const button = this;
    guarded(function () { return manualRefresh("active", button); });
  });
  byId("refresh-disposed").addEventListener("click", function () {
    const button = this;
    guarded(function () { return manualRefresh("disposed", button); });
  });
  byId("preview-reminders").addEventListener("click", function () {
    guarded(async function () {
      const r = await api("/api/reminders/preview", {method:"POST"});
      message("Reminder preview: " + r.would_send + " would be sent; " +
        r.already_sent + " already sent; " + r.missing_email + " missing email addresses.");
    });
  });
  byId("send-reminders").addEventListener("click", function () {
    const button = this;
    guarded(async function () {
      button.disabled = true;
      try {
        const preview = await api("/api/reminders/preview", {method:"POST"});
        const details = preview.would_send + " reminder(s) eligible to send.\n" +
          preview.already_sent + " already sent (no duplicate).\n" +
          preview.missing_email + " missing email address(es).\n\n" +
          "SORN and disposed vehicles are excluded. Send eligible emails now?";
        if (!preview.would_send) {
          message("No new reminders to send. " + preview.already_sent +
            " already sent; " + preview.missing_email + " missing email address(es).");
          return;
        }
        if (!window.confirm(details)) return;
        const sent = await api("/api/reminders/send", {method:"POST"});
        const diagnostics = (sent.failures || []).map(function (item) {
          return item.registration + " (" + item.kind + "): " + item.reason;
        });
        message("Manual email run: " + sent.sent + " sent, " + sent.already_sent +
          " previously sent, " + sent.failed + " failed, " +
          sent.not_configured + " not configured, " +
          sent.missing_email + " missing email address(es)." +
          (diagnostics.length ? " Delivery errors: " + diagnostics.join(" | ") : ""),
          sent.failed > 0 || sent.not_configured > 0);
      } finally {
        button.disabled = false;
      }
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
  byId("company-select").addEventListener("change", function () {
    selectedCompany = byId("company-select").value;
    updateCompanyStats();
    showRows();
  });
  byId("search").addEventListener("input", showRows);
  byId("filter").addEventListener("change", showRows);
  window.addEventListener("autokeeper-records-changed", function () { guarded(load); });
  guarded(load);
}());
