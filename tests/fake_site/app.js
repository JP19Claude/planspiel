// Mini-Nachbau einer Börsenspiel-Seite für Tests (Zustand in localStorage).
const SECURITIES = [
  {name: "SAP SE", wkn: "716460", isin: "DE0007164600", price: 240.0},
  {name: "Siemens AG", wkn: "723610", isin: "DE0007236101", price: 210.0},
  {name: "Siemens Energy AG", wkn: "ENER6Y", isin: "DE000ENER6Y0", price: 95.0},
];
const S = {
  get(k, d) { try { return JSON.parse(localStorage.getItem(k)) ?? d; } catch (_) { return d; } },
  set(k, v) { localStorage.setItem(k, JSON.stringify(v)); },
};
const de = (n) => n.toLocaleString("de-DE", {minimumFractionDigits: 2, maximumFractionDigits: 2});
const loggedIn = () => S.get("loggedIn", false);
function header() {
  const h = document.getElementById("hdr");
  if (h) h.innerHTML = loggedIn() ? '<a id="logout" href="login.html" onclick="localStorage.clear()">Abmelden</a>' : "<span>Bitte einloggen</span>";
}
function cash() {
  let c = 50000;
  for (const o of S.get("orders", [])) if (o.status === "ausgeführt") c += (o.side === "Kauf" ? -1 : 1) * o.qty * o.price;
  return c;
}
function positions() {
  const pos = {};
  for (const o of S.get("orders", [])) {
    if (o.status !== "ausgeführt") continue;
    pos[o.name] = pos[o.name] || {name: o.name, qty: 0, price: o.price};
    pos[o.name].qty += o.side === "Kauf" ? o.qty : -o.qty;
  }
  return Object.values(pos).filter(p => p.qty !== 0);
}
function renderDepot() {
  if (!loggedIn()) return;
  document.getElementById("cash").textContent = de(cash()) + " €";
  const pos = positions();
  const total = cash() + pos.reduce((s, p) => s + p.qty * p.price, 0);
  document.getElementById("total").textContent = de(total) + " €";
  const tb = document.querySelector("#positions tbody");
  tb.innerHTML = pos.length ? pos.map(p => `<tr><td>${p.name}</td><td>${p.qty}</td><td>${de(p.price)}</td><td>${de(p.qty * p.price)}</td></tr>`).join("")
                            : '<tr><td colspan="4">Keine Positionen</td></tr>';
}
function renderOrders() {
  if (!loggedIn()) return;
  const orders = S.get("orders", []);
  const row = (o) => `<tr><td>${o.name}</td><td>${o.side}</td><td>${o.qty}</td><td>${o.limit ? de(o.limit) : "-"}</td><td>${o.status}</td><td>${o.time}</td></tr>`;
  document.querySelector("#open-orders tbody").innerHTML = orders.filter(o => o.status === "offen").map(row).join("");
  document.querySelector("#history tbody").innerHTML = orders.filter(o => o.status !== "offen").map(row).join("");
}
let chosen = null, side = null, type = "market";
function initOrder() {
  if (!loggedIn()) return;
  const input = document.getElementById("search");
  input.addEventListener("input", () => {
    const q = input.value.trim().toLowerCase();
    const res = q ? SECURITIES.filter(s => (s.name + " " + s.wkn + " " + s.isin).toLowerCase().includes(q)) : [];
    document.getElementById("results").innerHTML = res.map((s, i) => `<li class="result" data-i="${SECURITIES.indexOf(s)}">${s.name} · ${s.wkn} · ${s.isin}</li>`).join("");
    document.querySelectorAll("li.result").forEach(li => li.addEventListener("click", () => {
      chosen = SECURITIES[+li.dataset.i];
      document.getElementById("identity").textContent = `${chosen.name} | WKN ${chosen.wkn} | ISIN ${chosen.isin}`;
      document.getElementById("order-form").style.display = "block";
    }));
  });
  document.getElementById("side-buy").onclick = () => { side = "Kauf"; };
  document.getElementById("side-sell").onclick = () => { side = "Verkauf"; };
  document.getElementById("type-market").onclick = () => { type = "market"; document.getElementById("limit").style.display = "none"; };
  document.getElementById("type-limit").onclick = () => { type = "limit"; document.getElementById("limit").style.display = "inline"; };
  document.getElementById("submit").onclick = () => {
    const qty = parseInt(document.getElementById("qty").value, 10);
    const limit = type === "limit" ? parseFloat(document.getElementById("limit").value.replace(".", "").replace(",", ".")) : null;
    const err = document.getElementById("error"), ok = document.getElementById("success");
    err.style.display = ok.style.display = "none";
    if (!chosen || !side || !(qty > 0)) { err.textContent = "Bitte alle Felder ausfüllen"; err.style.display = "block"; return; }
    if (side === "Kauf" && qty * chosen.price > cash()) { err.textContent = "Nicht genügend Liquidität"; err.style.display = "block"; return; }
    const orders = S.get("orders", []);
    orders.push({name: chosen.name, side, qty, limit, price: chosen.price,
                 status: type === "limit" ? "offen" : "ausgeführt", time: new Date().toISOString()});
    S.set("orders", orders);
    ok.textContent = "Ihre Order wurde erteilt"; ok.style.display = "block";
  };
}
function initLogin() {
  document.getElementById("login-btn").onclick = (e) => {
    e.preventDefault();
    const u = document.getElementById("user").value;
    if (u === "captcha") { document.getElementById("captcha").style.display = "block"; return; }
    if (document.getElementById("pass").value !== "geheim") { document.getElementById("login-error").style.display = "block"; return; }
    S.set("loggedIn", true);
    location.href = "depot.html";
  };
}
