"use strict";
/* ELAMS front-end. All data comes from the Python API (/api/...). */
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const pad = (n) => String(n).padStart(2, "0");
const iso = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
const nice = (s) => new Date(s + "T00:00").toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
const hm = (t) => (t ? t.slice(0, 5) : "—");
const plural = (n, w) => `${n} ${w}${n === 1 ? "" : "s"}`;
let me = null, view = "dashboard", punchState = "not_in", tt;

function toast(msg, err) {
  const t = $("toast"); t.textContent = msg; t.className = "toast show" + (err ? " err" : "");
  clearTimeout(tt); tt = setTimeout(() => (t.className = "toast"), 3000);
}
async function api(path, method = "GET", body) {
  const r = await fetch("/api" + path, {
    method, credentials: "same-origin",
    headers: { "Content-Type": "application/json", "X-Requested-With": "fetch" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  let data = {}; try { data = await r.json(); } catch (e) {}
  if (r.status === 401 && me && path !== "/login") { me = null; screen("login"); toast("Your session ended. Please sign in again.", 1); }
  if (!r.ok) throw new Error(data.error || "Something went wrong. Please try again.");
  return data;
}
const safe = (fn) => async (...a) => { try { await fn(...a); } catch (e) { toast(e.message, 1); } };
const screen = (name) => { ["landing", "login", "app"].forEach((id) => ($(id).hidden = id !== name)); window.scrollTo(0, 0); };
const tag = (s) => `<span class="tag ${s}">${s[0] + s.slice(1).toLowerCase()}</span>`;
const empty = (t) => `<li class="empty">${t}</li>`;

/* ---------- navigation ---------- */
const TITLES = {
  dashboard: ["", ""], attendance: ["Attendance", "Your check-ins and check-outs"],
  leave: ["My leave", "Request time off and track it"], approvals: ["Approvals", "Leave requests waiting for you"],
  employees: ["Employees", "Add people and manage roles"], reports: ["Reports", "Monthly attendance and leave summary"],
  profile: ["My profile", "Your details and password"],
};
const LOAD = { dashboard: loadDashboard, attendance: loadAttendance, leave: loadLeave, approvals: loadApprovals, employees: loadEmployees, reports: loadReports, profile: loadProfile };

function enter(user) {
  me = user; screen("app");
  const mgr = user.role === "manager";
  document.querySelectorAll("[data-m]").forEach((el) => (el.hidden = !mgr));
  $("chip").innerHTML = `<b>${esc(user.name)}</b><small>${mgr ? "Manager" : "Employee"} · ${esc(user.department)}</small>`;
  go("dashboard");
}
const go = safe(async (v) => {
  const mgr = me.role === "manager";
  if (!mgr && ["approvals", "employees", "reports"].includes(v)) v = "dashboard";
  view = v;
  document.querySelectorAll(".view").forEach((s) => (s.hidden = s.id !== "v-" + v));
  document.querySelectorAll("#nav button").forEach((b) => b.classList.toggle("on", b.dataset.v === v));
  $("title").textContent = v === "dashboard" ? `Hello, ${me.name.split(" ")[0]}` : TITLES[v][0];
  $("sub").textContent = v === "dashboard" ? `${me.designation} · ${me.department}` : TITLES[v][1];
  await LOAD[v]();
  if (mgr) refreshBadge();
});
async function refreshBadge() {
  try {
    const n = (await api("/leaves?scope=pending")).leaves.length;
    $("badge").hidden = !n; $("badge").textContent = n;
  } catch (e) {}
}

/* ---------- dashboard ---------- */
async function loadDashboard() {
  const d = await api("/dashboard"), t = d.today;
  punchState = t.state;
  $("punch").className = "punch" + (t.state === "in" ? " out" : "");
  $("punch").disabled = t.state === "done";
  $("punchTxt").textContent = { not_in: "Check in", in: "Check out", done: "Day complete" }[t.state];
  $("status").textContent = t.state === "not_in" ? "You haven’t checked in yet." : t.state === "in" ? `Checked in at ${hm(t.check_in)}.` : `Worked ${t.hours.toFixed(1)} h today (${hm(t.check_in)} – ${hm(t.check_out)}).`;
  $("today").textContent = new Date().toLocaleDateString("en-IN", { weekday: "long", day: "numeric", month: "long", year: "numeric" });
  $("sBal").textContent = d.balance; $("sPres").textContent = d.present_month; $("sPend").textContent = d.pending_mine;
  $("teamStats").hidden = !d.team;
  if (d.team) { $("tEmp").textContent = d.team.employees; $("tPres").textContent = d.team.present_today; $("tLeave").textContent = d.team.on_leave_today; $("tPend").textContent = d.team.pending_approvals; }
  const byDate = Object.fromEntries(d.recent.map((r) => [r.date, r.hours]));
  $("bars").innerHTML = [6, 5, 4, 3, 2, 1, 0].map((i) => {
    const day = new Date(); day.setDate(day.getDate() - i);
    const h = byDate[iso(day)] || 0;
    return `<div class="bar"><span>${h ? h.toFixed(1) : ""}</span><i class="${h ? "" : "none"}" style="height:${Math.min(h / 10, 1) * 100}%"></i>${day.toLocaleDateString("en-IN", { weekday: "short" })}</div>`;
  }).join("");
  const mine = (await api("/leaves?scope=mine")).leaves;
  $("recent").innerHTML = mine.slice(0, 3).map(leaveRow).join("") || empty("No leave requests yet.");
}
const leaveRow = (l) => `<li><div><b>${nice(l.start_date)} → ${nice(l.end_date)}</b><small>${l.leave_type} · ${plural(l.days, "day")}${l.reason ? " · " + esc(l.reason) : ""}${l.comment ? "<br>Manager: " + esc(l.comment) : ""}</small></div>${tag(l.status)}</li>`;
$("punch").onclick = safe(async () => {
  const r = await api(punchState === "in" ? "/checkout" : "/checkin", "POST", {});
  toast((punchState === "in" ? "Checked out at " : "Checked in at ") + hm(r.time));
  await loadDashboard();
});

/* ---------- attendance ---------- */
async function loadAttendance() {
  const all = me.role === "manager" && $("aScope").value === "all";
  const rows = (await api(`/attendance?month=${$("aMonth").value}${all ? "&scope=all" : ""}`)).attendance;
  $("attHead").innerHTML = `<tr>${all ? "<th>Employee</th>" : ""}<th>Date</th><th>In</th><th>Out</th><th>Hours</th></tr>`;
  $("attBody").innerHTML = rows.map((r) => `<tr>${all ? `<td>${esc(r.name)}<small>${esc(r.department)}</small></td>` : ""}<td>${nice(r.date)}</td><td>${hm(r.check_in)}</td><td>${hm(r.check_out)}</td><td>${r.check_out ? r.hours.toFixed(1) + " h" : "In progress"}</td></tr>`).join("") || `<tr><td colspan="5">No attendance recorded for this month.</td></tr>`;
}
$("aMonth").onchange = $("aScope").onchange = safe(loadAttendance);

/* ---------- leave ---------- */
async function loadLeave() {
  if (!$("lType").options.length) $("lType").innerHTML = (await api("/meta")).leave_types.map((t) => `<option>${t}</option>`).join("");
  $("myLeaves").innerHTML = (await api("/leaves?scope=mine")).leaves.map(leaveRow).join("") || empty("Nothing here yet. Use the form to apply.");
}
$("leaveForm").onsubmit = safe(async (e) => {
  e.preventDefault();
  await api("/leaves", "POST", { type: $("lType").value, start: $("lFrom").value, end: $("lTo").value, reason: $("lWhy").value });
  e.target.reset(); toast("Leave request submitted"); await loadLeave();
});

/* ---------- approvals ---------- */
async function loadApprovals() {
  const rows = (await api("/leaves?scope=pending")).leaves;
  $("pending").innerHTML = rows.map((l) => `<li><div><b>${esc(l.name)}</b><small>${esc(l.department)} · ${l.leave_type} · ${nice(l.start_date)} → ${nice(l.end_date)} (${plural(l.days, "day")})${l.reason ? "<br>" + esc(l.reason) : ""}</small></div>
    <div class="acts"><input class="cmt" placeholder="Comment (optional)" maxlength="300"><button class="mini ok" data-id="${l.id}" data-act="approve">Approve</button><button class="mini no" data-id="${l.id}" data-act="reject">Reject</button></div></li>`).join("") || empty("All caught up. No pending requests.");
}
$("pending").onclick = safe(async (e) => {
  const b = e.target.closest("[data-act]"); if (!b) return;
  await api(`/leaves/${b.dataset.id}/${b.dataset.act}`, "POST", { comment: b.parentElement.querySelector(".cmt").value });
  toast(b.dataset.act === "approve" ? "Leave approved" : "Leave rejected"); await loadApprovals(); refreshBadge();
});

/* ---------- employees ---------- */
async function loadEmployees() {
  const rows = (await api("/employees")).employees;
  $("empBody").innerHTML = rows.map((e) => { const self = e.id === me.id; return `<tr style="${e.active ? "" : "opacity:.55"}">
    <td>${esc(e.name)}<small>${esc(e.email)}</small></td><td>${esc(e.department)}<small>${esc(e.designation)}</small></td>
    <td><input type="number" min="0" max="365" value="${e.leave_balance}" data-id="${e.id}" data-f="leave_balance" aria-label="Leave days for ${esc(e.name)}"></td>
    <td><select data-id="${e.id}" data-f="role" ${self ? "disabled" : ""}><option value="employee" ${e.role === "employee" ? "selected" : ""}>Employee</option><option value="manager" ${e.role === "manager" ? "selected" : ""}>Manager</option></select></td>
    <td>${self ? tag("APPROVED").replace("Approved", "You") : `<button class="mini ${e.active ? "no" : "ok"}" data-id="${e.id}" data-toggle="${e.active ? 0 : 1}">${e.active ? "Deactivate" : "Activate"}</button>`}</td></tr>`; }).join("");
}
$("empBody").onchange = safe(async (e) => {
  const f = e.target.dataset.f; if (!f) return;
  await api(`/employees/${e.target.dataset.id}`, "PUT", { [f]: f === "leave_balance" ? +e.target.value : e.target.value });
  toast("Saved");
});
$("empBody").onclick = safe(async (e) => {
  const b = e.target.closest("[data-toggle]"); if (!b) return;
  await api(`/employees/${b.dataset.id}`, "PUT", { active: b.dataset.toggle === "1" });
  toast(b.dataset.toggle === "1" ? "Employee activated" : "Employee deactivated"); await loadEmployees();
});
$("empForm").onsubmit = safe(async (e) => {
  e.preventDefault();
  await api("/employees", "POST", { name: $("eName").value, email: $("eEmail").value, password: $("ePass").value, department: $("eDept").value, designation: $("eDes").value, role: $("eRole").value });
  e.target.reset(); toast("Employee added"); await loadEmployees();
});

/* ---------- reports ---------- */
async function loadReports() {
  const m = $("rMonth").value, r = await api(`/report?month=${m}`);
  $("csvLink").href = `/api/report.csv?month=${m}`;
  $("rNote").textContent = `${plural(r.working_days, "working day")} so far this month (Mon–Fri).`;
  $("repBody").innerHTML = r.rows.map((x) => `<tr><td>${esc(x.name)}<small>${esc(x.department)}</small></td><td>${x.present}</td><td>${x.hours} h</td>
    <td><div class="pct" title="${x.attendance_pct}%"><i style="width:${x.attendance_pct}%"></i></div><small>${x.attendance_pct}%</small></td><td>${x.leave_days}</td><td>${x.pending}</td></tr>`).join("");
}
$("rMonth").onchange = safe(loadReports);

/* ---------- profile ---------- */
async function loadProfile() {
  const u = (await api("/me")).user;
  $("prof").innerHTML = [["Name", u.name], ["Email", u.email], ["Department", u.department], ["Designation", u.designation], ["Role", u.role === "manager" ? "Manager" : "Employee"], ["Joined", nice(u.joined)], ["Leave balance", plural(u.leave_balance, "day")]]
    .map(([k, v]) => `<div class="kv"><span>${k}</span><b>${esc(v)}</b></div>`).join("");
}
$("pwForm").onsubmit = safe(async (e) => {
  e.preventDefault();
  await api("/password", "POST", { old: $("pOld").value, new: $("pNew").value });
  e.target.reset(); toast("Password updated");
});

/* ---------- sign in / out, website, themes ---------- */
$("loginForm").onsubmit = async (e) => {
  e.preventDefault(); $("lErr").textContent = "";
  try { const r = await api("/login", "POST", { email: $("lEmail").value, password: $("lPass").value }); $("lPass").value = ""; enter(r.user); }
  catch (err) { $("lErr").textContent = err.message; }
};
document.querySelectorAll("[data-fill]").forEach((b) => (b.onclick = () => { const [a, p] = b.dataset.fill.split("|"); $("lEmail").value = a; $("lPass").value = p; }));
$("logout").onclick = safe(async () => { await api("/logout", "POST", {}); me = null; screen("landing"); toast("Signed out"); });
$("backSite").onclick = $("home").onclick = () => screen("landing");
document.querySelectorAll("[data-go]").forEach((b) => (b.onclick = () => (me ? enter(me) : screen("login"))));
$("nav").onclick = (e) => { const b = e.target.closest("button"); if (b) go(b.dataset.v); };

const THEMES = { indigo: "#2b3a8c", sunset: "#d9480f", ocean: "#0e7490", forest: "#2f855a", plum: "#7c3aed" };
function setTheme(t) { document.documentElement.dataset.theme = t; try { localStorage.setItem("elams-theme", t); } catch (e) {} }
try { setTheme(localStorage.getItem("elams-theme") || "indigo"); } catch (e) {}
document.querySelectorAll("[data-dots]").forEach((c) => {
  c.innerHTML = Object.entries(THEMES).map(([k, v]) => `<button class="dot" data-t="${k}" style="background:${v}" aria-label="${k} theme" title="${k}"></button>`).join("");
  c.onclick = (e) => { const b = e.target.closest("[data-t]"); if (b) setTheme(b.dataset.t); };
});

const thisMonth = iso(new Date()).slice(0, 7);
$("aMonth").value = $("rMonth").value = thisMonth;
$("lFrom").min = $("lTo").min = iso(new Date());
setInterval(() => ($("clock").textContent = new Date().toLocaleTimeString("en-GB")), 1000);
$("clock").textContent = new Date().toLocaleTimeString("en-GB");
(async () => { try { me = (await api("/me")).user; } catch (e) { me = null; } screen("landing"); })();
