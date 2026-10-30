"use strict";

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const safe = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[char]));

async function api(url, options = {}) {
  const response = await fetch(url, {headers: {"Content-Type": "application/json", ...(options.headers || {})}, ...options});
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || "Something went wrong. Please try again.");
  return data;
}

function toast(message, type = "") {
  const region = $("#toast-region");
  const item = document.createElement("div");
  item.className = `toast ${type}`;
  item.setAttribute("role", "status");
  item.textContent = message;
  region.append(item);
  window.setTimeout(() => item.remove(), 3600);
}

function setBusy(button, busy, label) {
  if (!button) return;
  if (busy) {
    button.dataset.originalText = button.innerHTML;
    button.disabled = true;
    button.innerHTML = `<span class="spinner"></span>${safe(label || "Working…")}`;
  } else {
    button.disabled = false;
    button.innerHTML = button.dataset.originalText || button.innerHTML;
  }
}

function renderText(text) {
  const lines = String(text || "").split(/\r?\n/);
  let html = "", listOpen = false;
  const closeList = () => { if (listOpen) { html += "</ul>"; listOpen = false; } };
  for (const raw of lines) {
    const line = raw.trim();
    if (!line) { closeList(); continue; }
    if (/^#{1,3}\s/.test(line)) {
      closeList();
      const level = line.match(/^#+/)[0].length;
      html += `<h${level}>${safe(line.replace(/^#+\s*/, ""))}</h${level}>`;
    } else if (/^[-*•]\s/.test(line)) {
      if (!listOpen) { html += "<ul>"; listOpen = true; }
      html += `<li>${safe(line.replace(/^[-*•]\s*/, ""))}</li>`;
    } else {
      closeList(); html += `<p>${safe(line)}</p>`;
    }
  }
  closeList();
  return html;
}

function dateLabel(value) {
  if (!value) return "Just now";
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? value : date.toLocaleDateString(undefined, {month:"short", day:"numeric", year:"numeric"});
}

let modalAction = null;
function confirmDialog(message, action, title = "Are you sure?", confirmText = "Delete") {
  $("#modal-title").textContent = title;
  $("#modal-message").textContent = message;
  $("#modal-confirm").textContent = confirmText;
  modalAction = action;
  $("#modal-backdrop").classList.remove("hidden");
  $("#modal-confirm").focus();
}

function closeConfirm() { $("#modal-backdrop").classList.add("hidden"); modalAction = null; }

async function updateTheme(theme, persist = true) {
  document.body.classList.toggle("dark", theme === "dark");
  localStorage.setItem("studymate-theme", theme);
  const toggle = $("#theme-toggle");
  if (toggle) { toggle.textContent = theme === "dark" ? "☀" : "☾"; toggle.setAttribute("aria-label", theme === "dark" ? "Switch to light theme" : "Switch to dark theme"); }
  $$("[data-theme-choice]").forEach((button) => button.classList.toggle("selected", button.dataset.themeChoice === theme));
  if (persist) {
    try { await api("/api/settings", {method:"PUT", body:JSON.stringify({theme})}); } catch (_) { /* local theme remains available offline */ }
  }
}

function initShell() {
  const date = $("#today-label");
  if (date) date.textContent = new Date().toLocaleDateString(undefined, {weekday:"short", month:"short", day:"numeric"});
  updateTheme(localStorage.getItem("studymate-theme") || "light", false);
  $("#theme-toggle")?.addEventListener("click", () => updateTheme(document.body.classList.contains("dark") ? "light" : "dark"));
  $("#menu-toggle")?.addEventListener("click", () => { $("#sidebar").classList.add("open"); $("#mobile-scrim").classList.add("show"); });
  $("#mobile-scrim")?.addEventListener("click", () => { $("#sidebar").classList.remove("open"); $("#mobile-scrim").classList.remove("show"); });
  $("#modal-cancel")?.addEventListener("click", closeConfirm);
  $("#modal-backdrop")?.addEventListener("click", (event) => { if (event.target.id === "modal-backdrop") closeConfirm(); });
  $("#modal-confirm")?.addEventListener("click", async () => { const action = modalAction; closeConfirm(); if (action) await action(); });
  document.addEventListener("keydown", (event) => { if (event.key === "Escape") { closeConfirm(); $("#detail-backdrop")?.classList.add("hidden"); } });
  document.body.insertAdjacentHTML("beforeend", '<style>.spinner{width:12px;height:12px;border:2px solid #ffffff80;border-top-color:#fff;border-radius:50%;display:inline-block;animation:spin .7s linear infinite}@keyframes spin{to{transform:rotate(360deg)}}</style>');
  const page = document.body.dataset.page;
  if (page === "dashboard") initDashboard();
  if (page === "summarizer") initSummarizer();
  if (page === "quiz") initQuiz();
  if (page === "flashcards") initFlashcards();
  if (page === "history") initHistory();
  if (page === "settings") initSettings();
}

async function initDashboard() {
  try {
    const data = await api("/api/stats");
    $("#stat-sessions").textContent = data.sessions;
    $("#stat-summaries").textContent = data.summaries;
    $("#stat-quizzes").textContent = data.quizzes;
    $("#stat-score").textContent = data.average_score;
    const list = $("#recent-activity");
    if (!data.recent.length) {
      list.innerHTML = '<div class="empty-inline">No activity yet. Choose a quick action above to begin.</div>';
      $("#dashboard-empty").classList.remove("hidden");
    } else {
      list.innerHTML = data.recent.map((item) => {
        const icon = item.type === "summary" ? "✎" : item.type === "quiz" ? "☷" : "▱";
        const title = item.type === "summary" ? "Summary saved" : item.type === "quiz" ? "Quiz completed" : "Flashcards created";
        const detail = item.type === "quiz" ? `${item.score} / ${item.total} · ${item.title}` : `${item.subject} · ${dateLabel(item.created_at)}`;
        return `<div class="activity-row"><span class="activity-symbol">${icon}</span><div class="activity-copy"><strong>${title}</strong><span>${safe(detail)}</span></div>${item.type === "quiz" ? `<span class="activity-score">${Math.round(item.score / item.total * 100)}%</span>` : ""}</div>`;
      }).join("");
    }
    const chart = $("#weekly-chart");
    if (data.weekly.length) {
      const counts = new Map(data.weekly.map((r) => [r.day, Number(r.count)]));
      const days = Array.from({length:7}, (_, i) => { const d = new Date(); d.setDate(d.getDate() - (6-i)); return d; });
      const values = days.map((d) => counts.get(d.toISOString().slice(0,10)) || 0);
      const max = Math.max(...values, 1);
      chart.innerHTML = `<div class="chart-bars">${days.map((d,i) => `<div class="bar-column"><div class="bar ${values[i] ? "active" : ""}" title="${values[i]} quiz attempt${values[i]===1?"":"s"}" style="height:${Math.max(5,values[i]/max*100)}%"></div><span class="bar-label">${d.toLocaleDateString(undefined,{weekday:"narrow"})}</span></div>`).join("")}</div>`;
    }
  } catch (err) { toast(err.message, "error"); }
}

async function initSummarizer() {
  const form = $("#summary-form"), notes = $("#summary-notes"), output = $("#summary-result");
  let currentSummary = "";
  notes.addEventListener("input", () => { $("#summary-char-count").textContent = `${notes.value.length.toLocaleString()} / 20,000`; });
  $("#summary-clear").addEventListener("click", () => { form.reset(); $("#summary-char-count").textContent = "0 / 20,000"; output.classList.add("hidden"); $("#summary-placeholder").classList.remove("hidden"); $("#summary-saved").classList.add("hidden"); currentSummary = ""; });
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = $("#summary-submit"); setBusy(button, true, "Summarizing…");
    try {
      const data = await api("/api/summarize", {method:"POST",body:JSON.stringify({notes:notes.value,subject:$("#summary-subject").value,length:$("#summary-length").value,language:$("#summary-language").value})});
      currentSummary = data.summary;
      $("#summary-result-title").textContent = $("#summary-subject").value.trim() || "Your summary";
      $("#summary-content").innerHTML = renderText(currentSummary);
      $("#summary-placeholder").classList.add("hidden"); output.classList.remove("hidden"); $("#summary-saved").classList.add("hidden");
      toast(data.demo ? "Demo example ready. Add an API key for genuine AI summaries." : "Your summary is ready.", "success");
    } catch (err) { toast(err.message, "error"); } finally { setBusy(button, false); }
  });
  $("#summary-copy").addEventListener("click", async () => { try { await navigator.clipboard.writeText(currentSummary); toast("Summary copied to clipboard.", "success"); } catch (_) { toast("Clipboard access is unavailable in this browser.", "error"); } });
  $("#summary-save").addEventListener("click", async (event) => {
    const button = event.currentTarget; setBusy(button, true, "Saving…");
    try { await api("/api/history/summary", {method:"POST",body:JSON.stringify({content:currentSummary,notes:notes.value,subject:$("#summary-subject").value || "General study"})}); $("#summary-saved").classList.remove("hidden"); toast("Summary saved to your history.", "success"); }
    catch (err) { toast(err.message, "error"); } finally { setBusy(button, false); }
  });
}

async function initQuiz() {
  let quiz = null, answers = [], index = 0, submitted = null;
  const stage = $("#quiz-active");
  function drawQuestion() {
    if (!quiz) return;
    const q = quiz.questions[index], letters = ["A","B","C","D"];
    stage.innerHTML = `<div class="quiz-active-header"><div><span class="result-kicker">${safe($("#quiz-subject").value || "YOUR QUIZ")}</span><h2>${submitted ? "Quiz review" : "Question " + (index+1)}</h2></div><span class="question-progress">${index+1} of ${quiz.questions.length}</span></div><div class="progress-track"><div class="progress-fill" style="width:${(index+1)/quiz.questions.length*100}%"></div></div><p class="question-text">${safe(q.question)}</p><div class="options-list">${q.options.map((option,i) => { let cls = answers[index] === i ? "selected" : ""; let mark = ""; if (submitted) { cls = i === submitted.review[index].answer_index ? "review-correct" : answers[index] === i ? "review-wrong" : "review-dim"; mark = i === submitted.review[index].answer_index ? "✓" : answers[index] === i ? "×" : ""; } return `<button type="button" class="answer-option ${cls}" data-answer="${i}" ${submitted?"disabled":""}><span class="option-letter">${letters[i]}</span><span>${safe(option)}</span>${mark?`<span class="answer-mark">${mark}</span>`:""}</button>`; }).join("")}</div>${submitted ? `<div class="explanation"><strong>Explanation:</strong> ${safe(submitted.review[index].explanation)}</div>` : ""}<div class="quiz-controls"><button type="button" class="button button-quiet" id="quiz-prev" ${index===0?"disabled":""}>← Previous</button>${submitted ? (index === quiz.questions.length-1 ? '<button class="button button-primary" id="quiz-retake">↻ Retake quiz</button>' : '<button class="button button-primary" id="quiz-next">Next →</button>') : (index === quiz.questions.length-1 ? '<button class="button button-primary" id="quiz-submit">Submit quiz</button>' : '<button class="button button-primary" id="quiz-next">Next →</button>')}</div>${submitted && index===0 ? `<div class="score-banner"><div class="score-circle">${submitted.percentage}%</div><div><strong>${submitted.percentage>=80?"Excellent work!":submitted.percentage>=60?"Nice progress!":"Keep practicing!"}</strong><span>You got ${submitted.score} of ${submitted.total} questions correct.</span></div></div>` : ""}`;
    stage.querySelectorAll("[data-answer]").forEach((button) => button.addEventListener("click", () => { answers[index] = Number(button.dataset.answer); drawQuestion(); }));
    $("#quiz-prev", stage)?.addEventListener("click", () => { index--; drawQuestion(); });
    $("#quiz-next", stage)?.addEventListener("click", () => { index++; drawQuestion(); });
    $("#quiz-submit", stage)?.addEventListener("click", submitQuiz);
    $("#quiz-retake", stage)?.addEventListener("click", () => { answers = Array(quiz.questions.length).fill(null); submitted = null; index = 0; drawQuestion(); });
  }
  async function submitQuiz() {
    if (answers.some((answer) => answer === null || answer === undefined)) { toast("Please answer every question before submitting.", "error"); return; }
    const button = $("#quiz-submit", stage); setBusy(button, true, "Scoring…");
    try { submitted = await api("/api/quiz/submit", {method:"POST",body:JSON.stringify({quiz_id:quiz.quiz_id,answers})}); index = 0; drawQuestion(); toast("Quiz scored and saved to your history.", "success"); }
    catch (err) { toast(err.message, "error"); if (button) setBusy(button, false); }
  }
  $("#quiz-form").addEventListener("submit", async (event) => {
    event.preventDefault(); const button = $("#quiz-generate"); setBusy(button, true, "Building quiz…");
    try {
      quiz = await api("/api/quiz/generate", {method:"POST",body:JSON.stringify({notes:$("#quiz-notes").value,subject:$("#quiz-subject").value,topic:$("#quiz-topic").value,count:Number($("#quiz-count").value),difficulty:$("#quiz-difficulty").value})});
      answers = Array(quiz.questions.length).fill(null); submitted = null; index = 0; $("#quiz-placeholder").classList.add("hidden"); stage.classList.remove("hidden"); stage.classList.add("quiz-review"); drawQuestion(); toast(quiz.demo ? "Demo quiz ready. Add an API key for genuine AI questions." : "Your quiz is ready.", "success");
    } catch (err) { toast(err.message, "error"); } finally { setBusy(button, false); }
  });
}

async function initFlashcards() {
  let cards = [], order = [], index = 0, known = new Set(), needsPractice = new Set();
  const active = $("#flash-active");
  function renderCard() {
    const card = cards[order[index]];
    active.innerHTML = `<div class="flash-progress"><span>${safe($("#flash-subject").value || "STUDY DECK")}</span><span class="flash-topic-pill">Card ${index+1} of ${cards.length}${known.has(order[index])?" · Known":needsPractice.has(order[index])?" · Needs practice":""}</span></div><div class="flashcard-scene" id="flashcard-scene" role="button" tabindex="0" aria-label="Flip flashcard"><div class="flashcard" id="flashcard"><span class="flashcard-label">${card.flipped ? "ANSWER" : "QUESTION"}</span><div class="flashcard-text">${safe(card.flipped ? card.answer : card.question)}</div><span class="flashcard-hint">Click or press Enter to flip</span></div></div><div class="flash-controls"><button class="button button-quiet" id="flash-prev" ${index===0?"disabled":""}>← Previous</button><div class="flash-controls-center"><button class="button flash-known ${known.has(order[index])?"marked":""}" id="flash-known">✓ Known</button><button class="button flash-practice ${needsPractice.has(order[index])?"marked":""}" id="flash-practice">↻ Practice</button></div><button class="button button-quiet" id="flash-next" ${index===cards.length-1?"disabled":""}>Next →</button></div><div style="text-align:center;padding-top:9px"><button class="shuffle-button" id="flash-shuffle">⤨ Shuffle cards</button></div>`;
    const flip = () => { card.flipped = !card.flipped; renderCard(); };
    $("#flashcard-scene", active).addEventListener("click", flip);
    $("#flashcard-scene", active).addEventListener("keydown", (event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); flip(); } });
    $("#flash-prev", active).addEventListener("click", () => { index--; renderCard(); });
    $("#flash-next", active).addEventListener("click", () => { index++; renderCard(); });
    $("#flash-known", active).addEventListener("click", () => { known.add(order[index]); needsPractice.delete(order[index]); toast("Marked as known.", "success"); renderCard(); });
    $("#flash-practice", active).addEventListener("click", () => { known.delete(order[index]); needsPractice.add(order[index]); toast("Added to your practice list."); renderCard(); });
    $("#flash-shuffle", active).addEventListener("click", () => { for (let i=order.length-1;i>0;i--) { const j=Math.floor(Math.random()*(i+1)); [order[i],order[j]]=[order[j],order[i]]; } index=0; renderCard(); toast("Deck shuffled.", "success"); });
  }
  function loadCards(items, subject) { cards = items.map((c) => ({...c,flipped:false})); order = cards.map((_,i)=>i); index=0; known.clear(); needsPractice.clear(); $("#flash-subject").value=subject || ""; $("#flash-placeholder").classList.add("hidden"); active.classList.remove("hidden"); renderCard(); }
  $("#flash-form").addEventListener("submit", async (event) => {
    event.preventDefault(); const button = $("#flash-generate"); setBusy(button,true,"Creating cards…");
    try { const data = await api("/api/flashcards/generate",{method:"POST",body:JSON.stringify({notes:$("#flash-notes").value,subject:$("#flash-subject").value,topic:$("#flash-topic").value})}); loadCards(data.cards,$("#flash-subject").value); await loadDeckList(); toast(data.demo?"Demo flashcards created and saved. Add an API key for genuine AI content.":"Flashcards created and saved.","success"); }
    catch(err){toast(err.message,"error");}finally{setBusy(button,false);}
  });
  async function loadDeckList() {
    try { const {items} = await api("/api/history"); const decks = items.filter((x)=>x.type==="flashcards").slice(0,4); const host=$("#saved-decks");
      host.innerHTML=decks.length?decks.map((d)=>`<button class="deck-card" data-deck="${d.id}"><strong>${safe(d.title || d.subject)}</strong><span>${safe(d.subject)} · ${dateLabel(d.created_at)}</span></button>`).join(""):'<div class="empty-inline">Your saved flashcard decks will show up here.</div>';
      host.querySelectorAll("[data-deck]").forEach((button)=>button.addEventListener("click",async()=>{try{const d=await api(`/api/history/${button.dataset.deck}?type=flashcards`);loadCards(d.cards,d.subject);$("#flash-topic").value=d.topic||"";toast("Saved deck opened.","success");}catch(err){toast(err.message,"error");}}));
    }catch(err){toast(err.message,"error");}
  }
  await loadDeckList();
}

async function initHistory() {
  let items = [], filter = new URLSearchParams(location.search).get("filter") || "all";
  const list = $("#history-items");
  function draw() {
    const query = $("#history-search").value.trim().toLowerCase();
    const filtered = items.filter((item) => (filter === "all" || item.type === filter) && `${item.subject} ${item.title}`.toLowerCase().includes(query));
    $("#history-count").textContent = `${filtered.length} item${filtered.length===1?"":"s"}`;
    $("#history-empty").classList.toggle("hidden", items.length > 0);
    list.classList.toggle("hidden", !filtered.length);
    if (items.length && !filtered.length) { list.innerHTML='<div class="empty-inline">No items match your search.</div>'; list.classList.remove("hidden"); }
    else list.innerHTML = filtered.map((item) => { const icon=item.type==="summary"?"✎":item.type==="quiz"?"☷":"▱"; const label=item.type==="summary"?"Summary":item.type==="quiz"?"Quiz result":"Flashcard set"; return `<article class="history-item"><span class="history-type-icon ${item.type}">${icon}</span><div class="history-meta"><strong>${safe(item.title || label)}</strong><span>${safe(item.subject)} · ${label} · ${dateLabel(item.created_at)}</span></div>${item.type==="quiz"?`<span class="history-score">${item.score}/${item.total} · ${Math.round(item.score/item.total*100)}%</span>`:""}<div class="history-actions"><button class="small-action" aria-label="View item" title="View" data-view="${item.type}:${item.id}">↗</button><button class="small-action delete" aria-label="Delete item" title="Delete" data-delete="${item.type}:${item.id}">×</button></div></article>`; }).join("");
    list.querySelectorAll("[data-view]").forEach((button)=>button.addEventListener("click",()=>viewItem(button.dataset.view)));
    list.querySelectorAll("[data-delete]").forEach((button)=>button.addEventListener("click",()=>deleteItem(button.dataset.delete)));
  }
  async function viewItem(key) {
    const [type,id]=key.split(":");
    try { const item=await api(`/api/history/${id}?type=${type}`); $("#detail-type").textContent=type.toUpperCase(); $("#detail-title").textContent=item.topic || item.subject || "Saved study item";
      if(type==="summary") $("#detail-content").innerHTML=renderText(item.content);
      else if(type==="quiz") $("#detail-content").innerHTML=`<p><strong>Score:</strong> ${item.score} / ${item.total}</p><p><strong>Completed:</strong> ${dateLabel(item.created_at)}</p>${item.review.map((q,i)=>`<h3>${i+1}. ${safe(q.question)} ${q.correct?"✓":"×"}</h3><ul>${q.options.map((option,j)=>`<li>${safe(option)}${j===q.answer_index?" · Correct answer":""}${j===q.selected_index&&!q.correct?" · Your answer":""}</li>`).join("")}</ul><p>${safe(q.explanation)}</p>`).join("")}`;
      else $("#detail-content").innerHTML=item.cards.map((card,i)=>`<h3>Card ${i+1}: ${safe(card.question)}</h3><p>${safe(card.answer)}</p>`).join("");
      $("#detail-backdrop").classList.remove("hidden");
    }catch(err){toast(err.message,"error");}
  }
  async function deleteItem(key) { const [type,id]=key.split(":"); confirmDialog("This saved item will be permanently removed from your history.",async()=>{try{await api(`/api/history/${id}?type=${type}`,{method:"DELETE"});items=items.filter((item)=>!(item.type===type&&String(item.id)===id));draw();toast("Item deleted.","success");}catch(err){toast(err.message,"error");}},"Delete saved item"); }
  $("#history-search").addEventListener("input",draw);
  $$(".filter-chip").forEach((button)=>button.addEventListener("click",()=>{filter=button.dataset.filter;$$(".filter-chip").forEach((b)=>b.classList.toggle("active",b===button));draw();}));
  $$(".filter-chip").forEach((button)=>button.classList.toggle("active",button.dataset.filter===filter));
  $("#detail-close").addEventListener("click",()=>$("#detail-backdrop").classList.add("hidden"));
  $("#detail-backdrop").addEventListener("click",(event)=>{if(event.target.id==="detail-backdrop")event.currentTarget.classList.add("hidden");});
  try { ({items}=await api("/api/history")); draw(); } catch(err){toast(err.message,"error");}
}

async function initSettings() {
  try {
    const data=await api("/api/settings");
    $("#settings-language").value=data.language;
    $("#provider-name").textContent=data.provider;
    $("#model-name").textContent=data.model;
    $("#connection-status").textContent=data.ai_status;
    $("#connection-detail").textContent=data.ai_status==="Not configured"?"Add AI_API_KEY to your local .env file to enable genuine AI generation.":data.ai_status==="Demo mode"?"Sample content is used and is labeled as demo output.":"Your configured AI provider is ready for requests.";
    $("#connection-indicator").classList.add(data.ai_status==="Connected"?"ok":"off");
    await updateTheme(data.theme,false);
  } catch(err){toast(err.message,"error");}
  $$("[data-theme-choice]").forEach((button)=>button.addEventListener("click",()=>updateTheme(button.dataset.themeChoice)));
  $("#settings-save").addEventListener("click",async()=>{try{await api("/api/settings",{method:"PUT",body:JSON.stringify({theme:document.body.classList.contains("dark")?"dark":"light",language:$("#settings-language").value})});$("#settings-status").textContent="Preferences saved";toast("Preferences saved.","success");setTimeout(()=>$("#settings-status").textContent="",2500);}catch(err){toast(err.message,"error");}});
  $("#clear-history").addEventListener("click",()=>confirmDialog("This permanently deletes all summaries, quiz attempts, and flashcard sets from this device.",async()=>{try{await api("/api/history",{method:"DELETE"});toast("Study history cleared.","success");}catch(err){toast(err.message,"error");}},"Clear all study history","Delete all"));
}

document.addEventListener("DOMContentLoaded", initShell);
