        const $ = (id) => document.getElementById(id);
        const esc = (s) => { const d = document.createElement("div"); d.textContent = s; return d.innerHTML; };
        const md = (text) => {
            if (!window.marked || !window.DOMPurify) return esc(text);
            return DOMPurify.sanitize(marked.parse(text));
        };

        const TOAST_OK = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>';
        const TOAST_ERR = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>';
        const flash = (msg, isError) => {
            const toast = document.createElement("div");
            toast.className = `toast ${isError ? "error" : "ok"}`;
            toast.innerHTML = `${isError ? TOAST_ERR : TOAST_OK}<span>${msg}</span>`;
            $("toasts").appendChild(toast);
            const remove = () => {
                toast.classList.add("leaving");
                toast.addEventListener("animationend", () => toast.remove(), {once: true});
            };
            setTimeout(remove, 4000);
            toast.addEventListener("click", remove);
        };
        const spin = (msg) => { $("result").innerHTML = `<div class="spinner">${msg}</div>`; };

        const ICON_MOON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>';
        const ICON_SUN = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/></svg>';
        const applyTheme = (theme) => {
            document.documentElement.setAttribute("data-theme", theme);
            $("theme-toggle").innerHTML = theme === "dark" ? ICON_SUN : ICON_MOON;
        };
        const savedTheme = localStorage.getItem("theme") ||
            (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
        applyTheme(savedTheme);
        $("theme-toggle").addEventListener("click", () => {
            const next = document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark";
            localStorage.setItem("theme", next);
            applyTheme(next);
            if ($("panel-dashboard").classList.contains("active")) loadDashboard();
        });

        const escAttr = (s) => esc(s).replace(/"/g, "&quot;");
        const scopeParams = () => {
            const v = $("document").value;
            if (v.startsWith("subject:")) return { subject: v.slice(8) };
            if (v.startsWith("doc:")) return { document: v.slice(4) };
            return {};
        };
        const scopeLabel = () => {
            const opt = $("document").selectedOptions[0];
            return opt && opt.value ? opt.textContent : "tout le corpus";
        };
        const scopeQuery = () => {
            const p = scopeParams();
            if (p.subject) return `?subject=${encodeURIComponent(p.subject)}`;
            if (p.document) return `?document=${encodeURIComponent(p.document)}`;
            return "";
        };

        $("export-csv-btn").addEventListener("click", () => {
            window.location.href = "/api/export/csv" + scopeQuery();
        });

        const buildScopeOptions = (documents, subjects) => {
            let html = '<option value="">Tout le corpus</option>';
            if (subjects.length) {
                html += '<optgroup label="Matières">' +
                    subjects.map(s => `<option value="subject:${escAttr(s)}">${esc(s)}</option>`).join("") +
                    '</optgroup>';
            }
            html += '<optgroup label="Documents">' +
                documents.map(d => `<option value="doc:${escAttr(d)}">${esc(d)}</option>`).join("") +
                '</optgroup>';
            return html;
        };

        const refreshDocuments = (documents, subjects, docSubjects) => {
            subjects = subjects || [];
            docSubjects = docSubjects || {};
            $("corpus").textContent = documents.length;
            const select = $("document");
            const current = select.value;
            select.innerHTML = buildScopeOptions(documents, subjects);
            select.value = current;
            $("doc-links").innerHTML = documents.map(d => {
                const tag = docSubjects[d] ? ` <span class="doc-subject">· ${esc(docSubjects[d])}</span>` : "";
                return `<li><a href="/docs/${encodeURIComponent(d)}" target="_blank" rel="noopener">${esc(d)}${tag}</a>` +
                    `<button class="doc-del" data-doc="${escAttr(d)}" title="Supprimer" aria-label="Supprimer">✕</button></li>`;
            }).join("");
        };

        const refreshStats = async () => {
            $("scope-label").textContent = scopeLabel();
            try {
                const res = await fetch("/api/stats", {
                    method: "POST", headers: {"Content-Type": "application/json"},
                    body: JSON.stringify({...scopeParams()})
                });
                const s = await res.json();
                $("stat-due").textContent = s.due;
                $("stat-learned").textContent = s.learned;
                $("stat-total").textContent = s.total;
                $("stat-docs").textContent = s.documents;
            } catch (err) { /* stats non bloquantes */ }
        };

        const EMPTY_ICON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>';
        const emptyState = (areaId, message, cta) => {
            const btn = cta ? `<button class="cta-empty">${cta.label}</button>` : "";
            $(areaId).innerHTML = `<div class="empty">${EMPTY_ICON}<p>${message}</p>${btn}</div>`;
            if (cta) $(areaId).querySelector(".cta-empty").addEventListener("click", cta.onClick);
        };
        const MARK_OK = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>';
        const MARK_KO = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>';
        const DOC_ICON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/></svg>';
        const sourceChip = (doc) => {
            const label = (!doc || doc === "corpus") ? "Tout le corpus" : doc;
            return `<div class="src-chip" title="Source de cette carte">${DOC_ICON}<span>${esc(label)}</span></div>`;
        };

        document.querySelectorAll(".tab").forEach(tab => {
            tab.addEventListener("click", () => {
                if (tab.disabled) return;
                document.querySelectorAll(".tab").forEach(t => t.classList.remove("active"));
                document.querySelectorAll(".panel").forEach(p => p.classList.remove("active"));
                tab.classList.add("active");
                $("panel-" + tab.dataset.mode).classList.add("active");
                $("result").innerHTML = "";
                if (tab.dataset.mode === "recall") loadNextCard();
                if (tab.dataset.mode === "quiz") startQuizSession();
                if (tab.dataset.mode === "flashcards") loadNextFlash();
                if (tab.dataset.mode === "exercises") reviewExercise();
                if (tab.dataset.mode === "dashboard") loadDashboard();
            });
        });

        $("ask-form").addEventListener("submit", async (e) => {
            e.preventDefault();
            const question = $("question").value.trim();
            if (!question) return;
            spin("Recherche en cours…");
            try {
                const res = await fetch("/api/ask", {
                    method: "POST",
                    headers: {"Content-Type": "application/json"},
                    body: JSON.stringify({question, ...scopeParams()})
                });
                const data = await res.json();
                if (!res.ok) { $("result").innerHTML = ""; flash(data.error, true); return; }
                const citations = data.citations || [];
                $("result").innerHTML =
                    `<div class="answer"><div class="qlabel">${question}</div>` +
                    linkCitations(md(data.answer), citations) +
                    citationBlock(citations) +
                    `</div>`;
            } catch (err) { $("result").innerHTML = ""; flash("Erreur réseau.", true); }
        });

        const linkCitations = (html, citations) => {
            const known = new Set(citations.map(c => c.id));
            return html.replace(/\[(\d+(?:\s*[,;]\s*\d+)*)\]/g, (whole, group) => {
                const numbers = group.split(/[,;]/).map(n => Number(n.trim()));
                if (!numbers.every(n => known.has(n))) return whole;
                return numbers.map(n =>
                    `<sup class="cite-ref"><a href="#cite-${n}" data-cite="${n}">${n}</a></sup>`
                ).join("");
            });
        };

        const citationBlock = (citations) => {
            if (!citations.length) return "";
            const items = citations.map(c =>
                `<details class="cite" id="cite-${c.id}">` +
                `<summary><span class="cite-num">${c.id}</span>${esc(c.label)}</summary>` +
                `<blockquote>${esc(c.text)}</blockquote></details>`
            ).join("");
            return `<div class="sources"><strong>Sources :</strong>${items}</div>`;
        };

        $("result").addEventListener("click", (e) => {
            const ref = e.target.closest(".cite-ref a");
            if (!ref) return;
            e.preventDefault();
            const target = $("cite-" + ref.dataset.cite);
            if (!target) return;
            target.open = true;
            target.scrollIntoView({behavior: "smooth", block: "center"});
            target.classList.remove("cite-flash");
            void target.offsetWidth;
            target.classList.add("cite-flash");
        });

        $("fiche-btn").addEventListener("click", async () => {
            const btn = $("fiche-btn");
            btn.disabled = true;
            spin("Génération de la fiche…");
            try {
                const res = await fetch("/api/fiche", {
                    method: "POST",
                    headers: {"Content-Type": "application/json"},
                    body: JSON.stringify({...scopeParams()})
                });
                const data = await res.json();
                if (!res.ok) { $("result").innerHTML = ""; flash(data.error, true); return; }
                $("result").innerHTML =
                    `<div class="answer"><div class="qlabel">Fiche — ${data.scope}</div>${md(data.fiche)}</div>`;
            } catch (err) { $("result").innerHTML = ""; flash("Erreur réseau.", true); }
            finally { btn.disabled = false; }
        });

        $("feynman-btn").addEventListener("click", async () => {
            const concept = $("feynman-concept").value.trim();
            const explanation = $("feynman-explanation").value.trim();
            if (!concept || !explanation) { flash("Indique un concept et ton explication.", true); return; }
            const btn = $("feynman-btn");
            btn.disabled = true;
            $("feynman-area").innerHTML = '<div class="spinner">Analyse de ton explication…</div>';
            try {
                const res = await fetch("/api/feynman", {
                    method: "POST", headers: {"Content-Type": "application/json"},
                    body: JSON.stringify({concept, explanation, ...scopeParams()})
                });
                const data = await res.json();
                if (!res.ok) { $("feynman-area").innerHTML = ""; flash(data.error, true); return; }
                const sources = (data.sources || []).map(s => `<span>${esc(s)}</span>`).join("");
                $("feynman-area").innerHTML =
                    `<div class="answer"><div class="qlabel">Retour sur « ${esc(concept)} »</div>${md(data.feedback)}` +
                    (sources ? `<div class="sources"><strong>Basé sur :</strong><br>${sources}</div>` : "") +
                    `<div class="hint">Complète ton explication ci-dessus et revalide pour creuser.</div>` +
                    `</div>`;
            } catch (err) { $("feynman-area").innerHTML = ""; flash("Erreur réseau.", true); }
            finally { btn.disabled = false; }
        });

        const showProgress = (p) => {
            $("recall-progress").textContent =
                `Questions — à réviser : ${p.due} · maîtrisées : ${p.learned} / ${p.total}`;
            refreshStats();
        };

        const generateCards = async () => {
            const btn = $("gen-cards-btn");
            btn.disabled = true;
            $("study-area").innerHTML = '<div class="spinner">Génération des questions…</div>';
            try {
                const res = await fetch("/api/cards/generate", {
                    method: "POST", headers: {"Content-Type": "application/json"},
                    body: JSON.stringify({...scopeParams(), count: 8})
                });
                const data = await res.json();
                if (!res.ok) { flash(data.error, true); $("study-area").innerHTML = ""; return; }
                flash(`${data.added} question(s) générée(s) pour « ${data.scope} ».`, false);
                await loadNextCard();
            } catch (err) { flash("Erreur réseau.", true); $("study-area").innerHTML = ""; }
            finally { btn.disabled = false; }
        };
        $("gen-cards-btn").addEventListener("click", generateCards);

        const renderCard = (card) => {
            $("study-area").innerHTML =
                `<div class="answer">${sourceChip(card.document)}<div class="card-question">${esc(card.question)}</div>` +
                `<textarea id="user-answer" placeholder="Ta réponse de mémoire…" autofocus></textarea>` +
                `<button id="submit-answer" data-id="${card.id}">Valider</button></div>`;
            $("submit-answer").addEventListener("click", submitAnswer);
        };

        const badgeClass = (s) => s >= 4 ? "good" : (s >= 3 ? "mid" : "bad");

        const loadNextCard = async () => {
            $("study-area").innerHTML = '<div class="spinner">Chargement…</div>';
            const res = await fetch("/api/study/next", {
                method: "POST", headers: {"Content-Type": "application/json"},
                body: JSON.stringify({...scopeParams()})
            });
            const data = await res.json();
            showProgress(data.progress);
            if (!data.card) {
                emptyState("study-area",
                    "Aucune question à réviser pour l'instant.",
                    {label: "Générer des questions", onClick: generateCards});
                return;
            }
            renderCard(data.card);
        };

        const submitAnswer = async (e) => {
            const cardId = Number(e.target.dataset.id);
            const answer = $("user-answer").value.trim();
            if (!answer) return;
            e.target.disabled = true;
            $("study-area").insertAdjacentHTML("beforeend", '<div class="spinner">Correction…</div>');
            const res = await fetch("/api/study/answer", {
                method: "POST", headers: {"Content-Type": "application/json"},
                body: JSON.stringify({card_id: cardId, answer, ...scopeParams()})
            });
            const data = await res.json();
            if (!res.ok) { flash(data.error, true); return; }
            showProgress(data.progress);
            $("study-area").innerHTML =
                `<div class="answer">` +
                `<span class="badge ${badgeClass(data.score)}">${data.score}/5</span>${esc(data.feedback)}` +
                `<div class="reference"><b>Réponse attendue :</b><br>${esc(data.reference)}</div>` +
                `<div class="hint">Prochaine révision dans ${data.next_due_in_days} jour(s).</div>` +
                `<button id="next-card" style="margin-top:.8rem">Question suivante</button></div>`;
            $("next-card").addEventListener("click", loadNextCard);
        };


        const showQuizProgress = (p) => {
            $("quiz-progress").textContent = `QCM — à réviser : ${p.due} · maîtrisées : ${p.learned} / ${p.total}`;
            refreshStats();
        };

        const generateQuiz = async () => {
            const btn = $("gen-quiz-btn");
            btn.disabled = true;
            $("quiz-area").innerHTML = '<div class="spinner">Génération du QCM…</div>';
            try {
                const res = await fetch("/api/quiz/generate", {
                    method: "POST", headers: {"Content-Type": "application/json"},
                    body: JSON.stringify({...scopeParams(), count: 8})
                });
                const data = await res.json();
                if (!res.ok) { flash(data.error, true); $("quiz-area").innerHTML = ""; return; }
                flash(`${data.added} question(s) générée(s) pour « ${data.scope} ».`, false);
                startQuizSession();
            } catch (err) { flash("Erreur réseau.", true); $("quiz-area").innerHTML = ""; }
            finally { btn.disabled = false; }
        };
        $("gen-quiz-btn").addEventListener("click", generateQuiz);

        let quizOptions = [];
        let quizTotal = null;

        const startQuizSession = () => { quizTotal = null; loadNextQuiz(); };

        const renderQuiz = (card, pos, total) => {
            quizOptions = card.options;
            const opts = card.options.map((o, i) =>
                `<label class="opt" data-i="${i}"><input type="checkbox" name="quiz-opt" value="${i}"> ${esc(o)}</label>`
            ).join("");
            const counter = total ? `<div class="q-counter">Question ${pos} / ${total}</div>` : "";
            $("quiz-area").innerHTML =
                `<div class="answer">${counter}${sourceChip(card.document)}<div class="card-question">${esc(card.question)}</div>` +
                `<div class="hint">Coche toutes les bonnes réponses (une ou plusieurs).</div>` +
                `<div class="options">${opts}</div>` +
                `<button id="submit-quiz" data-id="${card.id}">Valider</button></div>`;
            $("submit-quiz").addEventListener("click", submitQuiz);
        };

        const loadNextQuiz = async () => {
            $("quiz-area").innerHTML = '<div class="spinner">Chargement…</div>';
            const res = await fetch("/api/quiz/next", {
                method: "POST", headers: {"Content-Type": "application/json"},
                body: JSON.stringify({...scopeParams()})
            });
            const data = await res.json();
            showQuizProgress(data.progress);
            if (!data.card) {
                quizTotal = null;
                emptyState("quiz-area",
                    "Aucune question à réviser pour l'instant.",
                    {label: "Générer un QCM", onClick: generateQuiz});
                return;
            }
            if (quizTotal === null) quizTotal = data.progress.due;
            const pos = quizTotal - data.progress.due + 1;
            renderQuiz(data.card, pos, quizTotal);
        };

        const submitQuiz = async (e) => {
            const cardId = Number(e.target.dataset.id);
            const checked = Array.from(document.querySelectorAll('input[name="quiz-opt"]:checked'));
            if (checked.length === 0) return;
            const selected = checked.map(c => quizOptions[Number(c.value)]);
            e.target.disabled = true;
            const res = await fetch("/api/quiz/answer", {
                method: "POST", headers: {"Content-Type": "application/json"},
                body: JSON.stringify({card_id: cardId, selected, ...scopeParams()})
            });
            const data = await res.json();
            if (!res.ok) { flash(data.error, true); return; }
            showQuizProgress(data.progress);
            const answers = new Set(data.answers || []);
            const chosen = new Set(selected);
            document.querySelectorAll(".opt").forEach(el => {
                const value = quizOptions[Number(el.dataset.i)];
                const input = el.querySelector("input");
                if (input) input.disabled = true;
                let mark = "";
                if (answers.has(value)) { el.classList.add("correct"); mark = MARK_OK; }
                else if (chosen.has(value)) { el.classList.add("wrong"); mark = MARK_KO; }
                if (mark) el.insertAdjacentHTML("beforeend", `<span class="mark">${mark}</span>`);
            });
            const verdict = data.correct
                ? '<span class="badge good">Bonne réponse</span>'
                : '<span class="badge bad">Raté</span>';
            const answersLabel = (data.answers || []).join(" · ");
            $("quiz-area").insertAdjacentHTML("beforeend",
                `<div class="answer">${verdict}` +
                (data.correct ? "" : `<div class="reference"><b>Bonne(s) réponse(s) :</b> ${esc(answersLabel)}</div>`) +
                (data.explanation ? `<div class="reference"><b>Explication :</b> ${esc(data.explanation)}</div>` : "") +
                `<div class="hint">Prochaine révision dans ${data.next_due_in_days} jour(s).</div>` +
                `<button id="next-quiz" style="margin-top:.8rem">Question suivante</button></div>`);
            $("next-quiz").addEventListener("click", loadNextQuiz);
        };


        const showFlashProgress = (p) => {
            $("flash-progress").textContent = `Flashcards — à réviser : ${p.due} · maîtrisées : ${p.learned} / ${p.total}`;
            refreshStats();
        };

        let flashCard = null;

        const renderFlash = (card) => {
            flashCard = card;
            $("flash-area").innerHTML =
                `<div class="answer">${sourceChip(card.document)}<div class="card-question">${esc(card.question)}</div>` +
                `<button id="reveal-flash">Révéler la réponse</button>` +
                `<div id="flash-back"></div></div>`;
            $("reveal-flash").addEventListener("click", revealFlash);
        };

        const revealFlash = () => {
            $("reveal-flash").disabled = true;
            $("flash-back").innerHTML =
                `<div class="reference"><b>Réponse :</b><br>${md(flashCard.answer)}</div>` +
                `<div class="hint">Comment t'en es-tu souvenu ?</div>` +
                `<div class="recall-actions" style="margin-top:.5rem">` +
                `<button class="rate" data-q="1">Raté</button>` +
                `<button class="rate" data-q="3">Difficile</button>` +
                `<button class="rate" data-q="4">Bien</button>` +
                `<button class="rate" data-q="5">Facile</button></div>`;
            document.querySelectorAll(".rate").forEach(b =>
                b.addEventListener("click", () => rateFlash(Number(b.dataset.q))));
        };

        const rateFlash = async (quality) => {
            const res = await fetch("/api/flashcards/answer", {
                method: "POST", headers: {"Content-Type": "application/json"},
                body: JSON.stringify({card_id: flashCard.id, quality, ...scopeParams()})
            });
            const data = await res.json();
            if (!res.ok) { flash(data.error, true); return; }
            showFlashProgress(data.progress);
            loadNextFlash();
        };

        const loadNextFlash = async () => {
            $("flash-area").innerHTML = '<div class="spinner">Chargement…</div>';
            const res = await fetch("/api/flashcards/next", {
                method: "POST", headers: {"Content-Type": "application/json"},
                body: JSON.stringify({...scopeParams()})
            });
            const data = await res.json();
            showFlashProgress(data.progress);
            if (!data.card) {
                emptyState("flash-area",
                    "Aucune carte à réviser. Génère d'abord des questions dans « Interroge-moi ».");
                return;
            }
            renderFlash(data.card);
        };

        let dashCharts = [];
        const cssVar = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
        const shortDate = (iso) => { const [, m, d] = iso.split("-"); return `${d}/${m}`; };
        const heatLevel = (n) => n === 0 ? 0 : n <= 2 ? 1 : n <= 5 ? 2 : n <= 9 ? 3 : 4;

        const renderHeatmap = (calendar, overdue) => {
            $("dash-overdue").textContent = overdue;
            $("heatmap").innerHTML = calendar.map(c => {
                const t = `${shortDate(c.date)} — ${c.count} carte(s)`;
                return `<i data-l="${heatLevel(c.count)}" title="${t}"></i>`;
            }).join("");
        };

        const INSIGHT_ICON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="4"/><circle cx="12" cy="12" r="0.5" fill="currentColor"/></svg>';
        const DONE_ICON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>';

        const goReview = (doc, mode) => {
            $("document").value = (doc === "corpus" || !doc) ? "" : "doc:" + doc;
            document.querySelector(`.tab[data-mode="${mode}"]`).click();
        };

        const renderInsight = (data) => {
            const box = $("dash-insight");
            const docs = data.by_document;
            const totalDue = docs.reduce((s, d) => s + d.due, 0);
            const label = (d) => d === "corpus" ? "tout le corpus" : d;

            if (totalDue === 0) {
                box.style.display = "";
                box.innerHTML = `<div class="insight-ic">${DONE_ICON}</div>` +
                    `<div class="insight-text"><b>Tout est à jour.</b> Aucune carte à réviser pour l'instant — reviens plus tard ou génère de nouvelles cartes.</div>`;
                return;
            }

            const focus = docs.filter(d => d.due > 0).sort((a, b) => b.due - a.due)[0];
            const weak = docs.filter(d => d.reviewed >= 3 && d.success_rate !== null)
                             .sort((a, b) => a.success_rate - b.success_rate)[0];

            let txt = `Tu as <b>${totalDue} carte(s)</b> à réviser`;
            if (focus && focus.document !== "corpus") txt += `, surtout dans « <b>${esc(label(focus.document))}</b> »`;
            txt += ".";
            if (weak && weak.success_rate < 70) {
                txt += ` Ton point faible : « <b>${esc(label(weak.document))}</b> » (${weak.success_rate}% de réussite).`;
            }

            const mode = focus.due_quiz >= focus.due_open ? "quiz" : "recall";
            box.style.display = "";
            box.innerHTML = `<div class="insight-ic">${INSIGHT_ICON}</div>` +
                `<div class="insight-text">${txt}</div>` +
                `<button id="insight-cta">Réviser maintenant</button>`;
            $("insight-cta").addEventListener("click", () => goReview(focus.document, mode));
        };

        const renderDashboard = (data) => {
            renderInsight(data);
            const ink = cssVar("--ink"), muted = cssVar("--muted"), line = cssVar("--line");
            const accent = cssVar("--accent"), good = cssVar("--good"), bad = cssVar("--bad");
            Chart.defaults.color = muted;
            Chart.defaults.font.family = "system-ui, sans-serif";
            dashCharts.forEach(c => c.destroy());
            dashCharts = [];

            const m = data.maturity;
            dashCharts.push(new Chart($("chart-maturity"), {
                type: "doughnut",
                data: {
                    labels: ["Nouvelles", "En apprentissage", "Jeunes", "Mûres"],
                    datasets: [{ data: [m.new, m.learning, m.young, m.mature],
                        backgroundColor: [muted, accent, "#0ea5e9", good], borderWidth: 0 }]
                },
                options: { responsive: true, maintainAspectRatio: false,
                    plugins: { legend: { position: "right", labels: { boxWidth: 12, padding: 10 } } } }
            }));

            const hist = data.reviews_history;
            dashCharts.push(new Chart($("chart-activity"), {
                type: "line",
                data: { labels: hist.map(h => shortDate(h.date)),
                    datasets: [{ data: hist.map(h => h.count), label: "Cartes révisées",
                        borderColor: accent, backgroundColor: accent + "33", fill: true, tension: .35,
                        pointRadius: 2 }] },
                options: { responsive: true, maintainAspectRatio: false,
                    plugins: { legend: { display: false } },
                    scales: { x: { grid: { display: false } },
                        y: { beginAtZero: true, ticks: { precision: 0 }, grid: { color: line } } } }
            }));

            const docs = data.by_document.map(d => d.document === "corpus" ? "Tout le corpus" : d.document);
            dashCharts.push(new Chart($("chart-docs"), {
                type: "bar",
                data: { labels: docs, datasets: [
                    { label: "Maîtrisées", data: data.by_document.map(d => d.learned), backgroundColor: good },
                    { label: "À apprendre", data: data.by_document.map(d => d.total - d.learned), backgroundColor: accent } ] },
                options: { indexAxis: "y", responsive: true, maintainAspectRatio: false,
                    plugins: { legend: { position: "bottom", labels: { boxWidth: 12 } } },
                    scales: { x: { stacked: true, beginAtZero: true, ticks: { precision: 0 }, grid: { color: line } },
                        y: { stacked: true, grid: { display: false } } } }
            }));

            renderHeatmap(data.due_calendar, data.overdue);
        };

        const loadDashboard = async () => {
            if (!window.Chart) { flash("Graphiques indisponibles (Chart.js non chargé).", true); return; }
            let data;
            try {
                const res = await fetch("/api/dashboard", {
                    method: "POST", headers: {"Content-Type": "application/json"},
                    body: JSON.stringify({...scopeParams()})
                });
                data = await res.json();
            } catch (err) { flash("Erreur de chargement du tableau de bord.", true); return; }
            const m = data.maturity;
            const hasCards = (m.new + m.learning + m.young + m.mature) > 0;
            $("dash-grid").style.display = hasCards ? "" : "none";
            $("dash-toolbar").style.display = hasCards ? "" : "none";
            $("dash-empty").style.display = hasCards ? "none" : "";
            if (!hasCards) {
                $("dash-insight").style.display = "none";
                $("dash-empty").innerHTML = EMPTY_ICON + "<p>Aucune carte pour l'instant. Génère un QCM ou des questions pour voir tes statistiques.</p>";
                return;
            }
            renderDashboard(data);
        };

        let currentExo = null;

        const showExoProgress = (p) => {
            if (p) $("exo-progress").textContent =
                `Compétences — à réviser : ${p.due} · maîtrisées : ${p.learned} / ${p.total}`;
        };

        const renderExoResult = (data) => {
            const verdict = data.correct
                ? '<span class="badge good">Correct ✓</span>'
                : '<span class="badge bad">Incorrect ✗</span>';
            const steps = data.solution.map(s => `<li>${esc(s)}</li>`).join("");
            const dueLine = data.next_due_in_days != null
                ? `<div class="hint">Compétence revue dans ${data.next_due_in_days} jour(s).</div>` : "";
            showExoProgress(data.progress);
            $("exo-result").innerHTML =
                `${verdict}` +
                (data.correct ? "" : `<div class="reference"><b>Réponse attendue :</b> ${esc(String(data.answer))}</div>`) +
                `<details class="exo-solution" ${data.correct ? "" : "open"}>` +
                `<summary>Solution étape par étape</summary><ol>${steps}</ol></details>` +
                dueLine +
                `<button id="exo-next" style="margin-top:.8rem">Continuer</button>`;
            $("exo-next").addEventListener("click", reviewExercise);
        };

        const submitExo = async () => {
            let given;
            if (currentExo.format === "mcq") {
                const checked = document.querySelector('input[name="exo-opt"]:checked');
                if (!checked) return;
                given = checked.value;
            } else {
                given = $("exo-input").value.trim();
                if (given === "") return;
            }
            $("exo-submit").disabled = true;
            const res = await fetch("/api/exercise/grade", {
                method: "POST", headers: {"Content-Type": "application/json"},
                body: JSON.stringify({kind: currentExo.kind, params: currentExo.params, answer: given})
            });
            const data = await res.json();
            if (!res.ok) { flash(data.error, true); return; }
            renderExoResult(data);
        };

        const renderExo = (exo) => {
            currentExo = exo;
            let input;
            if (exo.format === "mcq") {
                input = `<div class="options">` + exo.options.map(o =>
                    `<label class="opt"><input type="radio" name="exo-opt" value="${o}"> ${esc(String(o))}</label>`
                ).join("") + `</div>`;
            } else {
                input = `<input type="text" id="exo-input" inputmode="numeric" autocomplete="off" placeholder="Ta réponse (un nombre)…" style="margin:.3rem 0 .8rem">`;
            }
            $("exo-area").innerHTML =
                `<div class="answer"><div class="exo-title">${esc(exo.title)}</div>` +
                `<div class="card-question">${esc(exo.statement)}</div>` +
                input +
                `<button id="exo-submit">Valider</button>` +
                `<div id="exo-result" style="margin-top:.6rem"></div></div>`;
            $("exo-submit").addEventListener("click", submitExo);
            const field = $("exo-input");
            if (field) field.addEventListener("keydown", (ev) => { if (ev.key === "Enter") submitExo(); });
        };

        const loadExercise = async () => {
            $("exo-area").innerHTML = '<div class="spinner">Génération…</div>';
            try {
                const res = await fetch("/api/exercise/new", {
                    method: "POST", headers: {"Content-Type": "application/json"},
                    body: JSON.stringify({kind: $("exo-kind").value})
                });
                renderExo(await res.json());
            } catch (err) { flash("Erreur réseau.", true); }
        };

        const reviewExercise = async () => {
            $("exo-area").innerHTML = '<div class="spinner">Chargement…</div>';
            try {
                const res = await fetch("/api/exercise/next", {
                    method: "POST", headers: {"Content-Type": "application/json"}, body: "{}"
                });
                const data = await res.json();
                showExoProgress(data.progress);
                if (!data.exercise) {
                    emptyState("exo-area",
                        "Toutes les compétences sont à jour. Tu peux t'entraîner librement ci-dessus.");
                    return;
                }
                renderExo(data.exercise);
            } catch (err) { flash("Erreur réseau.", true); }
        };

        $("exo-review-btn").addEventListener("click", reviewExercise);
        $("exo-new-btn").addEventListener("click", loadExercise);
        $("exo-kind").addEventListener("change", loadExercise);

        $("upload-form").addEventListener("submit", async (e) => {
            e.preventDefault();
            const fileInput = $("pdf");
            if (!fileInput.files.length) { flash("Aucun fichier sélectionné.", true); return; }
            const body = new FormData();
            body.append("pdf", fileInput.files[0]);
            flash("Indexation en cours…", false);
            try {
                const res = await fetch("/api/upload", {method: "POST", body});
                const data = await res.json();
                if (!res.ok) { flash(data.error, true); return; }
                refreshDocuments(data.documents, data.subjects, data.document_subjects);
                fileInput.value = "";
                $("subject").value = "";
                refreshStats();
                flash(data.message, false);
            } catch (err) { flash("Erreur réseau.", true); }
        });

        $("doc-links").addEventListener("click", async (e) => {
            const btn = e.target.closest(".doc-del");
            if (!btn) return;
            const doc = btn.dataset.doc;
            if (!confirm(`Supprimer « ${doc} » et ses cartes de révision ? Action irréversible.`)) return;
            try {
                const res = await fetch(`/api/documents/${encodeURIComponent(doc)}`, { method: "DELETE" });
                const data = await res.json();
                if (!res.ok) { flash(data.error, true); return; }
                if ($("document").value === "doc:" + doc) $("document").value = "";
                refreshDocuments(data.documents, data.subjects, data.document_subjects);
                refreshStats();
                if ($("panel-dashboard").classList.contains("active")) loadDashboard();
                flash(data.message, false);
            } catch (err) { flash("Erreur réseau.", true); }
        });

        $("document").addEventListener("change", () => {
            refreshStats();
            if ($("panel-dashboard").classList.contains("active")) loadDashboard();
        });
        refreshStats();
