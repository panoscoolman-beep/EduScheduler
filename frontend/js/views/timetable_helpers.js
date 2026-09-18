/**
 * Pure data helpers for the Timetable view (no DOM, no globals).
 *
 * Extracted from timetable.js so the data-shaping logic — unique-value
 * extraction, the student label maps, teacher-id lookup, export-param
 * resolution, locked-slot counting — can be unit-tested with Node's built-in
 * test runner (`node --test`) without a browser/DOM.
 *
 * Dual-mode: in the browser it's a classic script that defines the global
 * `TimetableHelpers` (timetable.js reads it, like it reads API/App); under
 * Node it also exports via module.exports for the tests. No build step.
 */
const TimetableHelpers = {
    /** Distinct truthy values of `key` across slots, preserving first-seen order. */
    uniqueValues(slots, key) {
        return [...new Set((slots || []).map(s => s[key]).filter(Boolean))];
    },

    /**
     * Build the student dropdown maps from the students list:
     *   classIdsByLabel: "Last First" -> Set(class_ids)   (for slot filtering)
     *   idByLabel:       "Last First" -> student id        (for export params)
     *   sortedNames:     labels sorted with Greek collation
     */
    buildStudentLabelMaps(students) {
        const classIdsByLabel = new Map();
        const idByLabel = new Map();
        for (const st of students || []) {
            const label = `${st.last_name} ${st.first_name}`.trim();
            classIdsByLabel.set(label, new Set(st.class_ids || []));
            idByLabel.set(label, st.id);
        }
        const sortedNames = Array.from(classIdsByLabel.keys()).sort((a, b) =>
            a.localeCompare(b, 'el')
        );
        return { classIdsByLabel, idByLabel, sortedNames };
    },

    /** teacher_name -> teacher_id, for the per-teacher export buttons. */
    teacherIdByName(slots) {
        const map = new Map();
        for (const s of slots || []) {
            if (s.teacher_name && s.teacher_id) map.set(s.teacher_name, s.teacher_id);
        }
        return map;
    },

    /**
     * Resolve the current view/filter to an export query string, or null when
     * the selection isn't a single teacher/student (so print falls back to
     * window.print() and ICS is disabled).
     */
    resolveExportParams(viewType, filterValue, solutionId, teacherIdByName, studentIdByLabel) {
        if (filterValue === 'all') return null;
        if (viewType === 'teacher' && teacherIdByName.has(filterValue)) {
            return `solution_id=${solutionId}&teacher_id=${teacherIdByName.get(filterValue)}`;
        }
        if (viewType === 'student' && studentIdByLabel.has(filterValue)) {
            return `solution_id=${solutionId}&student_id=${studentIdByLabel.get(filterValue)}`;
        }
        return null;
    },

    /**
     * Προτίμηση «Τμήμα ως» για τις εκτυπώσεις καθηγητών (full|short|both),
     * όπως τη θυμάται η σελίδα εκτύπωσης στο localStorage. Pure — το storage
     * περνιέται ως όρισμα (default το window.localStorage αν υπάρχει).
     */
    printClassLabelPref(storage) {
        const st = storage !== undefined ? storage
            : (typeof localStorage !== 'undefined' ? localStorage : null);
        let v = null;
        try { v = st && st.getItem('eds-print-class-label'); } catch (e) { v = null; }
        return ['full', 'short', 'both'].includes(v) ? v : 'full';
    },

    /** Πρόσθεσε class_label στα params εκτύπωσης (μόνο για καθηγητές). Pure. */
    withPrintClassLabel(params, pref) {
        if (!params || !/(^|&)(teacher_id=|all=teachers)/.test(params)) return params;
        return `${params}&class_label=${pref}`;
    },

    /** Number of placed (non-parking-lot) slots the user has locked. */
    countLockedSlots(slots) {
        return (slots || []).filter(s => s.is_locked && !s.is_unplaced).length;
    },

    /** Minimal HTML-escape for values interpolated into template strings. */
    esc(s) {
        return String(s ?? '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;');
    },

    /**
     * Build the compare-modal results HTML (side-by-side metrics table with
     * the winner per row starred/highlighted), or an empty-state line when
     * the API returned no metrics. Pure: data in, HTML string out.
     */
    buildCompareResultHtml(result) {
        if (!result.metrics?.length) {
            return '<p class="text-muted">Δεν επιστράφηκαν metrics.</p>';
        }

        const metricLabels = {
            score:               'Σκορ (penalty)',
            placed_count:        '✅ Τοποθετήθηκαν',
            unplaced_count:      '🅿️ Στο parking',
            teacher_gap_total:   'Παράθυρα καθηγητών (σύνολο)',
            workload_stddev:     'Ανισορροπία ωρών (σ)',
            avg_days_per_class:  'Μέσος όρος ημερών/τμήμα',
            max_days_per_class:  'Max ημέρες σε τμήμα',
            late_periods_used:   'Αργές ώρες (μετά τη μέση)',
        };

        const metricKeys = Object.keys(metricLabels);
        const winners = result.winners || {};

        const headerCells = result.metrics.map(m =>
            `<th>${TimetableHelpers.esc(m.name)}</th>`
        ).join('');

        const rows = metricKeys.map(key => {
            const cells = result.metrics.map(m => {
                const value = m[key];
                const isWinner = winners[key] === m.solution_id;
                const display = value === null || value === undefined
                    ? '—'
                    : (typeof value === 'number' ? value : String(value));
                return `<td style="${isWinner ? 'background:#D1FAE5; font-weight:600;' : ''}">
                    ${display}${isWinner ? ' ⭐' : ''}
                </td>`;
            }).join('');
            return `<tr><td><strong>${metricLabels[key]}</strong></td>${cells}</tr>`;
        }).join('');

        return `
            <p class="text-muted" style="font-size:0.85em; margin-bottom:0.5rem;">
                ⭐ = καλύτερη τιμή για κάθε metric (lower is better, εκτός από Τοποθετήθηκαν).
            </p>
            <table class="data-table" style="font-size:0.9em;">
                <thead>
                    <tr><th>Metric</th>${headerCells}</tr>
                </thead>
                <tbody>${rows}</tbody>
            </table>
        `;
    },

    /**
     * Build the substitute-modal results HTML: a card per affected slot with
     * candidate substitutes + reschedule options, or an empty-state line when
     * the teacher has no lessons that day. Pure: data in, HTML string out.
     */
    buildSubstituteResultHtml(data, dayLabel) {
        if (!data.affected_slots.length) {
            return `
                <p class="text-muted">
                    Ο καθηγητής δεν έχει προγραμματισμένα μαθήματα την ${dayLabel}.
                    Δεν χρειάζεται αντικατάσταση.
                </p>
            `;
        }

        const cards = data.affected_slots.map(slot => {
            const candidatesHtml = slot.candidates.length
                ? `<ul style="margin:0.4em 0 0 1.4em; padding:0;">
                       ${slot.candidates.slice(0, 5).map(c => `
                           <li style="margin-bottom:0.3em;">
                               <strong>${TimetableHelpers.esc(c.name)}</strong>
                               <span class="text-muted" style="font-size:0.85em;">
                                 (score ${c.score})
                               </span>
                               <div style="font-size:0.85em; color:var(--text-muted);">
                                 ${TimetableHelpers.esc(c.reasons.join(', '))}
                               </div>
                           </li>
                       `).join('')}
                   </ul>`
                : '<p class="text-muted" style="font-size:0.9em; margin:0.3em 0;">Κανείς διαθέσιμος αυτή την ώρα.</p>';

            const rescheduleHtml = slot.reschedule_options.length
                ? `<ul style="margin:0.4em 0 0 1.4em; padding:0; max-height:120px; overflow:auto;">
                       ${slot.reschedule_options.slice(0, 8).map(opt => {
                           const dayName = ['Δευ','Τρι','Τετ','Πεμ','Παρ','Σαβ','Κυρ'][opt.day_of_week];
                           return `<li>${dayName} • ${TimetableHelpers.esc(opt.period_name || '?')}</li>`;
                       }).join('')}
                   </ul>`
                : '<p class="text-muted" style="font-size:0.9em; margin:0.3em 0;">Καμία ελεύθερη ώρα στην εβδομάδα.</p>';

            return `
                <div class="card" style="margin-bottom:1rem; padding:0.8rem 1rem;">
                    <div style="font-weight:600; margin-bottom:0.5rem;">
                        ${TimetableHelpers.esc(slot.subject_name || '?')} —
                        ${TimetableHelpers.esc(slot.class_name || '?')} •
                        ${TimetableHelpers.esc(slot.period_name || '?')} •
                        ${TimetableHelpers.esc(slot.classroom_name || '?')}
                    </div>
                    <div style="display:grid; grid-template-columns:1fr 1fr; gap:1rem;">
                        <div>
                            <strong style="font-size:0.9em;">Αντικαταστάτες:</strong>
                            ${candidatesHtml}
                        </div>
                        <div>
                            <strong style="font-size:0.9em;">Εναλλακτικές ώρες ίδιας εβδομάδας:</strong>
                            ${rescheduleHtml}
                        </div>
                    </div>
                </div>
            `;
        }).join('');

        return `
            <div style="margin-bottom:1rem; padding:0.6rem 0.8rem;
                        background:var(--bg-secondary, #F3F4F6); border-radius:6px;">
                <strong>Σύνολο μαθημάτων που επηρεάζονται:</strong>
                ${data.stats.affected_count}
                — ${data.stats.with_candidates} με διαθέσιμους αντικαταστάτες
            </div>
            ${cards}
        `;
    },

    /** Μικρό table CSS που συνοδεύει τα builder HTML (grid + modals). */
    _tableCss() {
        return `<style>
              .fr-table { border-collapse: collapse; width: 100%; }
              .fr-table th, .fr-table td { border: 1px solid var(--border-color, #ccc);
                  padding: 6px 8px; font-size: 0.85rem; text-align: center; vertical-align: top; }
              .fr-time { white-space: nowrap; }
              .fr-count { font-weight: 700; margin-bottom: 2px; }
              td.fr-none { opacity: 0.55; }
              td.fr-free { background: rgba(16, 185, 129, 0.14); }
              td.fr-busy { background: rgba(239, 68, 68, 0.10); }
              .fr-free-mark { font-weight: 700; color: #059669; }
              .fr-busy-what { font-size: 0.78rem; opacity: 0.85; }
              .fr-summary { margin: 0 0 0.5rem; font-size: 0.9rem; }
              .fr-controls { display: flex; align-items: center; gap: 6px;
                  flex-wrap: wrap; margin-bottom: 0.5rem; font-size: 0.85rem; }
              .fr-controls select { padding: 2px 6px; }
              .fr-all-free { color: #059669; font-weight: 600; }
            </style>`;
    },

    /** "HH:MM" → λεπτά από τα μεσάνυχτα, ή null. Pure. */
    /**
     * Ωράριο λειτουργίας: ποιες διδακτικές ώρες φαίνονται στο πλέγμα. Μέσα
     * είναι όσες ΞΕΚΙΝΟΥΝ στο [from, to)· χωρίς ωράριο ή με άγνωστη ώρα → όλες.
     * Ώρα με ΤΟΠΟΘΕΤΗΜΕΝΟ μάθημα δεν κρύβεται ποτέ — επιστρέφεται στο
     * `outside` για σήμανση. Ίδιος κανόνας με backend/services/operating_hours.py.
     */
    visiblePeriods(periods, window, slots) {
        const w = window || {};
        const lo = TimetableHelpers.timeToMinutes(w.from);
        const hi = TimetableHelpers.timeToMinutes(w.to);
        const used = new Set((slots || [])
            .filter(s => !s.is_unplaced && s.period_id != null)
            .map(s => s.period_id));
        const outside = new Set();
        const visible = (periods || []).filter(p => {
            const start = TimetableHelpers.timeToMinutes(p.start_time);
            const inside = start == null
                || ((lo == null || start >= lo) && (hi == null || start < hi));
            if (inside) return true;
            if (used.has(p.id)) { outside.add(p.id); return true; }
            return false;
        });
        return { periods: visible, outside };
    },

    /**
     * Προβολή μίας αίθουσας: το id της, ώστε το drop σε κελί να σημαίνει «ΑΥΤΗ
     * η αίθουσα» (ρητή επιλογή). Αλλιώς null → ο server κρατά/διαλέγει αίθουσα.
     */
    roomIdForFilter(slots, viewType, filterValue) {
        if (viewType !== 'room' || !filterValue || filterValue === 'all') return null;
        const hit = (slots || []).find(s => s.classroom_name === filterValue && s.classroom_id != null);
        return hit ? hit.classroom_id : null;
    },

    timeToMinutes(hhmm) {
        const m = /^(\d{1,2}):(\d{2})/.exec(String(hhmm ?? '').trim());
        if (!m) return null;
        return Number(m[1]) * 60 + Number(m[2]);
    },

    /**
     * Οι διδακτικές ώρες που πέφτουν μέσα στο παράθυρο [from, to] ("HH:MM").
     * Κρατά μια ώρα όταν ΞΕΚΙΝΑ >= from ΚΑΙ ΤΕΛΕΙΩΝΕΙ <= to. Κενό/άκυρο
     * παράθυρο = όλες οι διδακτικές ώρες. Pure.
     */
    filterPeriodsByWindow(periods, from, to) {
        const teaching = (periods || []).filter(p => !p.is_break);
        const lo = this.timeToMinutes(from);
        const hi = this.timeToMinutes(to);
        if (lo === null && hi === null) return teaching;
        return teaching.filter(p => {
            const start = this.timeToMinutes(p.start_time);
            const end = this.timeToMinutes(p.end_time);
            if (start === null || end === null) return true;   // άγνωστη ώρα: μη την κρύψεις
            if (lo !== null && start < lo) return false;
            if (hi !== null && end > hi) return false;
            return true;
        });
    },

    /** Οι δύο επιλογείς «Ώρες: Από – Έως» πάνω από το grid. Pure. */
    buildFreeRoomsControlsHtml(periods, from, to) {
        const esc = this.esc.bind(this);
        const teaching = (periods || []).filter(p => !p.is_break);
        // Οι επιλογές είναι τα πραγματικά όρια των διδακτικών ωρών· αν το
        // τρέχον παράθυρο δεν πέφτει πάνω σε όριο (π.χ. αποθηκευμένο 14:00
        // ενώ οι ώρες ξεκινούν 13:00/16:00), πρόσθεσέ το ΩΣΤΕ ο επιλογέας
        // να δείχνει την αλήθεια αντί για το πρώτο option.
        const sorted = (values) => [...new Set(values.filter(Boolean))]
            .sort((a, b) => (this.timeToMinutes(a) ?? 0) - (this.timeToMinutes(b) ?? 0));
        const starts = sorted([...teaching.map(p => p.start_time), from]);
        const ends = sorted([...teaching.map(p => p.end_time), to]);
        const opts = (values, current) => values
            .map(v => `<option value="${esc(v)}"${v === current ? ' selected' : ''}>${esc(v)}</option>`)
            .join('');
        return `
            <div class="fr-controls">
              <span>🕒 Ώρες:</span>
              <select id="fr-from" onchange="TimetableView.setFreeRoomsWindow(this.value, document.getElementById('fr-to').value)">
                ${opts(starts, from)}
              </select>
              <span>–</span>
              <select id="fr-to" onchange="TimetableView.setFreeRoomsWindow(document.getElementById('fr-from').value, this.value)">
                ${opts(ends, to)}
              </select>
              <button class="btn btn-secondary btn-sm" onclick="TimetableView.setFreeRoomsWindow('', '')">Όλες οι ώρες</button>
            </div>`;
    },

    /**
     * «Ελεύθερες Αίθουσες»: grid Ώρα × Ημέρα.
     *
     * Χωρίς φίλτρο (roomFilter κενό/'all'): κάθε κελί δείχνει ΠΟΙΕΣ αίθουσες
     * δεν έχουν μάθημα εκείνη τη στιγμή (μετρητής ελεύθερες/σύνολο).
     * Με φίλτρο αίθουσας: κάθε κελί λέει αν ΑΥΤΗ η αίθουσα είναι ελεύθερη
     * («✅ Ελεύθερη») ή ποιο μάθημα την κρατά («❌ ΑΛΓΕΒΡΑ · Β2 · Νικολάου»),
     * με σύνοψη ελεύθερων ωρών από πάνω.
     *
     * Pure: slots της λύσης + περίοδοι + ΟΛΕΣ οι αίθουσες μέσα, HTML έξω.
     */
    buildFreeRoomsHtml(slots, periods, daysCount, allRooms, roomFilter, timeWindow) {
        const esc = this.esc.bind(this);
        const dayNames = ['Δευτέρα', 'Τρίτη', 'Τετάρτη', 'Πέμπτη', 'Παρασκευή', 'Σάββατο', 'Κυριακή'];
        const days = [...Array(Math.min(daysCount, 7)).keys()];
        const win = timeWindow || {};
        const teaching = this.filterPeriodsByWindow(periods, win.from, win.to);
        const roomNames = (allRooms || []).map(r => r.name);
        const single = roomFilter && roomFilter !== 'all' && roomNames.includes(roomFilter)
            ? roomFilter : null;

        // (day, period_id) → Set κατειλημμένων αιθουσών· και ποιο μάθημα
        // κρατά κάθε αίθουσα (για το φίλτρο μίας αίθουσας).
        const busy = new Map();
        const occupant = new Map();
        for (const s of slots || []) {
            if (s.is_unplaced || s.day_of_week === null || s.day_of_week === undefined) continue;
            if (!s.classroom_name) continue;
            const key = `${s.day_of_week}|${s.period_id}`;
            if (!busy.has(key)) busy.set(key, new Set());
            busy.get(key).add(s.classroom_name);
            occupant.set(`${key}|${s.classroom_name}`, s);
        }

        const header = days.map(d => `<th>${dayNames[d]}</th>`).join('');
        let freeCount = 0;
        const rows = teaching.map(p => {
            const cells = days.map(d => {
                const key = `${d}|${p.id}`;
                const taken = busy.get(key) || new Set();
                if (single) {
                    const isFree = !taken.has(single);
                    if (isFree) freeCount += 1;
                    if (isFree) {
                        return '<td class="fr-free"><span class="fr-free-mark">✅ Ελεύθερη</span></td>';
                    }
                    const s = occupant.get(`${key}|${single}`) || {};
                    const what = [s.subject_name, s.class_name, s.teacher_name]
                        .filter(Boolean).map(esc).join(' · ');
                    return `<td class="fr-busy">❌<div class="fr-busy-what">${what || 'κατειλημμένη'}</div></td>`;
                }
                const free = roomNames.filter(n => !taken.has(n));
                const badgeClass = free.length === 0 ? 'fr-none' : 'fr-some';
                let list;
                if (!free.length) {
                    list = '<em>Καμία ελεύθερη</em>';
                } else if (taken.size === 0) {
                    // Κανένα μάθημα εκείνη την ώρα — μην τυπώνεις όλη τη λίστα.
                    list = `<span class="fr-all-free">Όλες ελεύθερες</span>`;
                } else {
                    list = free.map(esc).join('<br>');
                }
                return `<td class="${badgeClass}"><div class="fr-count">${free.length}/${roomNames.length}</div>${list}</td>`;
            }).join('');
            return `<tr><th class="fr-time">${esc(p.start_time)}–${esc(p.end_time)}</th>${cells}</tr>`;
        }).join('');

        const total = teaching.length * days.length;
        const summary = single
            ? `<p class="fr-summary">🏫 <b>${esc(single)}</b> — ελεύθερη <b>${freeCount}</b> από ${total} ώρες${
                win.from || win.to ? ` (${esc(win.from || '…')}–${esc(win.to || '…')})` : ' της εβδομάδας'}.</p>`
            : '';
        const controls = this.buildFreeRoomsControlsHtml(periods, win.from, win.to);
        const empty = teaching.length
            ? ''
            : '<p class="fr-summary">Καμία διδακτική ώρα σε αυτό το χρονικό παράθυρο.</p>';

        return `
            ${this._tableCss()}
            ${controls}
            ${summary}
            ${empty}
            <table class="fr-table">
              <thead><tr><th class="fr-time">Ώρα</th>${header}</tr></thead>
              <tbody>${rows}</tbody>
            </table>`;
    },

    /**
     * HTML αποτελεσμάτων του diff δύο λύσεων («τι άλλαξε;»). Pure.
     * `diff` = το JSON του GET /api/solver/diff.
     */
    buildDiffResultHtml(diff) {
        const esc = this.esc.bind(this);
        const posLabel = (p) => `${esc(p.day_name)} ${esc(p.period_name)}`
            + (p.room ? ` · 🏫 ${esc(p.room)}` : '');

        const section = (title, items, line) => items.length
            ? `<h4 style="margin:0.75rem 0 0.25rem">${title} (${items.length})</h4>
               <ul style="margin:0; padding-left:1.2rem">${items.map(line).join('')}</ul>`
            : '';

        const moved = section('🔀 Μετακινήθηκαν', diff.moved, m =>
            `<li><b>${esc(m.lesson)}</b> — ${posLabel(m.from)} → ${posLabel(m.to)}</li>`);
        const added = section('➕ Προστέθηκαν', diff.added, a =>
            `<li><b>${esc(a.lesson)}</b> — ${posLabel(a.at)}</li>`);
        const removed = section('➖ Αφαιρέθηκαν', diff.removed, r =>
            `<li><b>${esc(r.lesson)}</b> — ${posLabel(r.at)}</li>`);

        const changedLoads = diff.teacher_load.filter(t => t.delta !== 0);
        const loads = changedLoads.length
            ? `<h4 style="margin:0.75rem 0 0.25rem">👤 Μεταβολή φόρτου</h4>
               <table class="fr-table"><thead><tr><th>Καθηγητής</th><th>${esc(diff.base.name)}</th><th>${esc(diff.other.name)}</th><th>Δ</th></tr></thead>
               <tbody>${changedLoads.map(t =>
                   `<tr><td>${esc(t.teacher)}</td><td>${t.base_hours}</td><td>${t.other_hours}</td><td>${t.delta > 0 ? '+' : ''}${t.delta}</td></tr>`
               ).join('')}</tbody></table>`
            : '';

        const nothing = !diff.moved.length && !diff.added.length && !diff.removed.length;
        return `
            ${this._tableCss()}
            <div style="font-size:0.9rem; color:var(--text-secondary,#666)">
                ${esc(diff.base.name)} → ${esc(diff.other.name)} ·
                ${diff.unchanged_count} ώρες έμειναν ως είχαν
            </div>
            ${nothing ? '<p>✅ Καμία διαφορά στις τοποθετήσεις.</p>' : moved + added + removed}
            ${loads}`;
    },

    /**
     * HTML της αναφοράς παραβιάσεων soft constraints («γιατί αυτό το score;»).
     * Pure. `rep` = το JSON του GET /api/solver/solutions/{id}/violations.
     */
    buildViolationsHtml(rep) {
        const esc = this.esc.bind(this);
        const s = rep.summary;
        const badges = `
            <div style="display:flex; gap:0.5rem; margin-bottom:0.75rem; flex-wrap:wrap">
                <span class="constraint-badge ${s.gap_total ? 'hard' : 'soft'}">Κενά καθηγητών: ${s.gap_total}</span>
                <span class="constraint-badge ${s.late_total ? 'hard' : 'soft'}">Αργές ώρες: ${s.late_total}</span>
                <span class="constraint-badge soft">σ φόρτου: ${s.workload_stddev}</span>
            </div>`;

        const gaps = rep.teacher_gaps.length
            ? `<h4 style="margin:0.5rem 0 0.25rem">🕳️ Κενά καθηγητών</h4>
               <ul style="margin:0; padding-left:1.2rem">${rep.teacher_gaps.map(g =>
                   `<li><b>${esc(g.teacher)}</b> — ${esc(g.day_name)}: κενό στη ${g.gap_periods.map(esc).join(', ')}</li>`
               ).join('')}</ul>`
            : '';

        const late = rep.late_slots.length
            ? `<h4 style="margin:0.75rem 0 0.25rem">🌙 Αργές ώρες</h4>
               <ul style="margin:0; padding-left:1.2rem">${rep.late_slots.map(l =>
                   `<li><b>${esc(l.subject)}</b> (${esc(l.class_name)}, ${esc(l.teacher)}) — ${esc(l.day_name)} ${esc(l.period_name)} ${esc(l.time)}</li>`
               ).join('')}</ul>`
            : '';

        const work = rep.workload.length
            ? `<h4 style="margin:0.75rem 0 0.25rem">⚖️ Φόρτος ανά καθηγητή</h4>
               <table class="fr-table"><thead><tr><th>Καθηγητής</th><th>Ώρες</th></tr></thead>
               <tbody>${rep.workload.map(w =>
                   `<tr><td>${esc(w.teacher)}</td><td>${w.hours}</td></tr>`).join('')}</tbody></table>`
            : '';

        const clean = !rep.teacher_gaps.length && !rep.late_slots.length;
        return this._tableCss() + badges
            + (clean ? '<p>✅ Καμία παραβίαση soft constraint — καθαρή λύση.</p>' : gaps + late)
            + work;
    },

    /**
     * HTML αναφοράς εφικτότητας — «γιατί δεν βγαίνει;». Pure.
     * `report` = το JSON του GET /api/solver/feasibility-check
     * (feasible, errors, warnings, suggestions, stats).
     */
    buildFeasibilityHtml(report) {
        const esc = this.esc.bind(this);
        const stats = report.stats || {};
        const verdict = report.feasible
            ? '<span style="color:var(--success,#10B981)">✅ Εφικτό</span>'
            : '<span style="color:var(--danger,#EF4444)">❌ Δεν βγαίνει με τα τρέχοντα δεδομένα</span>';
        const loadPct = stats.load_factor != null ? Math.round(stats.load_factor * 100) : '—';

        const list = (title, items, color) => items && items.length
            ? `<div style="margin-top:0.5rem"><b>${title} (${items.length}):</b>
                 <ul style="margin:0.3em 0 0 1.4em; color:${color}">
                   ${items.map(x => `<li>${esc(x)}</li>`).join('')}</ul></div>`
            : '';

        const suggestions = report.suggestions && report.suggestions.length
            ? `<div style="margin-top:0.6rem; padding:0.5rem 0.75rem; background:var(--surface-2,#f4f6fb); border-radius:6px">
                 <b>💡 Τι να κάνεις:</b>
                 <ul style="margin:0.3em 0 0 1.4em">${report.suggestions.map(s => `<li>${esc(s)}</li>`).join('')}</ul></div>`
            : '';

        return `
            <div class="card" style="padding:0.75rem">
                <div style="font-size:1.1em; margin-bottom:0.4rem">${verdict}</div>
                <div style="font-size:0.9em; color:var(--text-muted,#6B7280)">
                    Φόρτος: <b>${stats.total_periods_needed ?? '—'} / ${stats.total_slots_available ?? '—'}</b> slots
                    (${loadPct}%) · ${stats.total_lessons ?? 0} μαθήματα, ${stats.total_teachers ?? 0} καθηγητές, ${stats.total_classes ?? 0} τάξεις
                </div>
                ${list('Σίγουρα προβλήματα', report.errors, 'var(--danger,#EF4444)')}
                ${list('Πιθανά προβλήματα', report.warnings, 'var(--warning,#F59E0B)')}
                ${suggestions}
                ${report.feasible && !(report.warnings || []).length
                    ? '<p style="color:var(--success,#10B981); margin-top:0.5rem">Όλα τα checks πέρασαν — μπορείς να τρέξεις τον solver.</p>' : ''}
            </div>`;
    },

    /** Convert a #RRGGBB hex colour to an rgba() string at the given alpha. */
    hexToRgba(hex, alpha = 1) {
        const r = parseInt(hex.slice(1, 3), 16);
        const g = parseInt(hex.slice(3, 5), 16);
        const b = parseInt(hex.slice(5, 7), 16);
        return `rgba(${r}, ${g}, ${b}, ${alpha})`;
    },

    /**
     * Group a solution's slots by lesson into palette entries — the data
     * behind the «Παλέτα Μαθημάτων». Pure: slots + lessons in, entries out.
     *
     * Per entry:
     *   placed    — slots on the grid
     *   remaining — unplaced (parking) slots, i.e. draggable hours
     *   missing   — hours the lesson SHOULD have (periods_per_week) but has
     *               no slot row at all (solutions older than the parking-lot
     *               sync) — fixable via the sync-slots endpoint
     *   drag_slot — the first unplaced slot (the card the user drags next)
     *
     * The `lessons` list drives ppw/missing and surfaces lessons with ZERO
     * slots in this solution; slots provide names/colors. Either input may
     * be empty.
     */
    buildLessonPalette(slots, lessons) {
        const byLesson = new Map();
        const entryFor = (lessonId) => {
            let e = byLesson.get(lessonId);
            if (!e) {
                e = {
                    lesson_id: lessonId, total: 0, placed: 0, remaining: 0,
                    missing: 0, drag_slot: null, subject_name: null,
                    subject_color: null, class_name: null, teacher_name: null,
                };
                byLesson.set(lessonId, e);
            }
            return e;
        };

        for (const l of lessons || []) {
            const e = entryFor(l.id);
            e.total = l.periods_per_week || 0;
            e.subject_name = l.subject_name || null;
            e.class_name = l.class_name || null;
            e.teacher_name = l.teacher_name || null;
        }
        for (const s of slots || []) {
            if (s.lesson_id == null) continue;
            const e = entryFor(s.lesson_id);
            // Slots are the richer source (colors, short names) — fill gaps.
            if (!e.subject_name) e.subject_name = s.subject_name || s.subject_short || null;
            if (!e.class_name) e.class_name = s.class_name || s.class_short || null;
            if (!e.teacher_name) e.teacher_name = s.teacher_name || null;
            if (!e.subject_color && s.subject_color) e.subject_color = s.subject_color;
            if (s.is_unplaced) {
                e.remaining += 1;
                if (!e.drag_slot) e.drag_slot = s;
            } else {
                e.placed += 1;
            }
        }

        const entries = [...byLesson.values()];
        for (const e of entries) {
            const known = e.placed + e.remaining;
            // A lesson deleted from the catalog can still have slots — treat
            // the slots we see as the whole truth (total=known, missing=0).
            if (e.total < known) e.total = known;
            e.missing = Math.max(0, e.total - known);
        }

        // Draggable work first, then fixable deficits, fully-placed last.
        const rank = (e) => (e.remaining > 0 ? 0 : (e.missing > 0 ? 1 : 2));
        entries.sort((a, b) =>
            rank(a) - rank(b)
            || String(a.class_name || '').localeCompare(String(b.class_name || ''), 'el')
            || String(a.subject_name || '').localeCompare(String(b.subject_name || ''), 'el'));

        const totals = { hours_total: 0, hours_placed: 0, hours_remaining: 0, hours_missing: 0 };
        for (const e of entries) {
            totals.hours_total += e.total;
            totals.hours_placed += e.placed;
            totals.hours_remaining += e.remaining;
            totals.hours_missing += e.missing;
        }
        return { entries, totals };
    },

    /**
     * Build the swap-confirmation modal body: the two cards side by side
     * with their current positions and the ⇄ direction. Pure.
     */
    buildSwapConfirmHtml(slotA, slotB, periods) {
        const esc = TimetableHelpers.esc;
        const DAY_NAMES = ['Δευτέρα', 'Τρίτη', 'Τετάρτη', 'Πέμπτη', 'Παρασκευή', 'Σάββατο', 'Κυριακή'];
        const periodById = new Map((periods || []).map(p => [p.id, p]));
        const posLabel = (s) => {
            const day = DAY_NAMES[s.day_of_week] || `Ημέρα ${(s.day_of_week ?? 0) + 1}`;
            const p = periodById.get(s.period_id);
            return p ? `${day} ${p.short_name} (${p.start_time})` : day;
        };
        const card = (s) => {
            const color = s.subject_color || '#9CA3AF';
            const sub = [esc(s.class_name || s.class_short || ''),
                         esc(s.teacher_name || '')].filter(Boolean).join(' • ');
            return `
                <div class="swap-confirm-card" style="border-left: 4px solid ${color};">
                    <div style="font-weight:600; color:${color};">${esc(s.subject_name || '?')}</div>
                    <div class="text-muted" style="font-size:0.85em;">${sub}</div>
                    <div style="margin-top:4px;">📅 ${esc(posLabel(s))}</div>
                    ${s.classroom_name ? `<div class="text-muted" style="font-size:0.85em;">🚪 ${esc(s.classroom_name)}</div>` : ''}
                </div>`;
        };
        return `
            <p class="text-muted" style="margin-bottom:0.75rem;">
                Οι δύο κάρτες θα ανταλλάξουν μέρα/ώρα. Οι αίθουσες διατηρούνται
                όπου χωράνε, αλλιώς επιλέγεται αυτόματα άλλη ελεύθερη — όλοι οι
                έλεγχοι (κωλύματα, κοινοί μαθητές κ.λπ.) τρέχουν πριν την αλλαγή.
            </p>
            <div class="swap-confirm-row">
                ${card(slotA)}
                <div class="swap-confirm-arrow">⇄</div>
                ${card(slotB)}
            </div>`;
    },

    /**
     * Index a placement-map cell list by "day:period_id" for O(1) lookup
     * while shading the grid during a drag. Pure.
     */
    indexPlacementMap(cells) {
        const idx = new Map();
        for (const c of cells || []) {
            idx.set(`${c.day}:${c.period_id}`, {
                ok: !!c.ok,
                reason: c.reason || null,
                short: c.short || null,
                code: c.code || null,
                blocking_slot_id: c.blocking_slot_id ?? null,
            });
        }
        return idx;
    },

    /**
     * Build the «Βρες μου θέση» modal body: every OK cell of a placement
     * map as clickable chips grouped by day (sorted by period order) PLUS a
     * collapsible «Γιατί όχι αλλού» list with the named reason of every
     * blocked cell. Pure: map + periods in, HTML out ('' only when the map
     * has no cells at all — with zero legal cells the reasons still show).
     */
    buildPlacementChoicesHtml(map, periods) {
        const DAY_NAMES = ['Δευτέρα', 'Τρίτη', 'Τετάρτη', 'Πέμπτη', 'Παρασκευή', 'Σάββατο', 'Κυριακή'];
        const esc = TimetableHelpers.esc;
        const cells = (map && map.cells) || [];
        if (!cells.length) return '';

        const periodById = new Map((periods || []).map(p => [p.id, p]));
        const sortOrder = (c) => { const p = periodById.get(c.period_id); return p ? p.sort_order : 0; };
        const periodLabel = (c) => {
            const p = periodById.get(c.period_id);
            return p ? `${esc(p.short_name)} (${esc(p.start_time)})` : `#${c.period_id}`;
        };
        const dayName = (day) => DAY_NAMES[day] || `Ημέρα ${day + 1}`;
        const groupByDay = (list) => {
            const byDay = new Map();
            for (const c of list) {
                if (!byDay.has(c.day)) byDay.set(c.day, []);
                byDay.get(c.day).push(c);
            }
            return [...byDay.keys()].sort((a, b) => a - b)
                .map(day => [day, byDay.get(day).slice().sort((a, b) => sortOrder(a) - sortOrder(b))]);
        };

        const okCells = cells.filter(c => c.ok);
        const blocked = cells.filter(c => !c.ok);

        const rows = groupByDay(okCells).map(([day, list]) => {
            const chips = list.map(c => `<button class="btn btn-secondary btn-sm placement-chip"
                                onclick="TimetableView.placeAt(${map.slot_id}, ${c.day}, ${c.period_id})">
                                ${periodLabel(c)}
                            </button>`).join('');
            return `
                <div class="placement-day-row">
                    <strong>${dayName(day)}</strong>
                    <div class="placement-chips">${chips}</div>
                </div>`;
        }).join('');

        // Συγχώνευση διαδοχικών ωρών με την ΙΔΙΑ αιτία: «1η (08:00) – 8η (15:00)
        // — Κώλυμα καθηγητή Χ» αντί για οκτώ ίδιες γραμμές.
        const runsOf = (list) => {
            const runs = [];
            for (const c of list) {
                const reason = c.reason || 'μη διαθέσιμο';
                const last = runs[runs.length - 1];
                if (last && last.reason === reason) last.cells.push(c);
                else runs.push({ reason, cells: [c] });
            }
            return runs;
        };
        const runLabel = (run) => run.cells.length === 1
            ? periodLabel(run.cells[0])
            : `${periodLabel(run.cells[0])} – ${periodLabel(run.cells[run.cells.length - 1])}`;
        const blockedRows = groupByDay(blocked).map(([day, list]) => `
                    <li><strong>${dayName(day)}:</strong> ${
                        runsOf(list).map(r => `${runLabel(r)} — ${esc(r.reason)}`).join(' · ')
                    }</li>`).join('');
        const blockedHtml = blocked.length ? `
            <details class="placement-blocked"${okCells.length ? '' : ' open'}>
                <summary>⛔ Γιατί όχι αλλού — ${blocked.length} μπλοκαρισμένες θέσεις</summary>
                <ul>${blockedRows}</ul>
            </details>` : '';

        const intro = okCells.length
            ? `<p class="text-muted" style="margin-bottom:0.75rem;">
                ${okCells.length} νόμιμες θέσεις — διάλεξε μία και η ώρα τοποθετείται
                αμέσως (η αίθουσα επιλέγεται αυτόματα).
            </p>`
            : `<p class="text-muted" style="margin-bottom:0.75rem;">
                <b>Καμία νόμιμη θέση</b> αυτή τη στιγμή — παρακάτω φαίνεται τι μπλοκάρει κάθε ώρα.
            </p>`;

        return intro + rows + blockedHtml;
    },

    /**
     * Κουμπί «Τι επηρεάζει;» — κοινό σε όλες τις κάρτες της Παλέτας. Ανοίγει
     * τον έλεγχο ΠΡΙΝ από καθάρισμα/διαγραφή ωρών (LessonImpactModal).
     */
    _paletteInspectBtnHtml(lessonId) {
        return `<button class="palette-inspect-btn"
                        onmousedown="event.stopPropagation();"
                        ondragstart="event.stopPropagation(); event.preventDefault();"
                        onclick="event.stopPropagation(); TimetableView.inspectLesson(${lessonId})"
                        title="Τι επηρεάζει; — έλεγχος πριν σβήσεις ώρες">🔍</button>`;
    },

    /**
     * Options του επιλογέα προγράμματος. Τα αρχειοθετημένα μπαίνουν σε δική
     * τους ομάδα στο τέλος, ώστε να φαίνονται μόνο όταν τα ψάχνεις (και να
     * μπορείς να τα επαναφέρεις).
     */
    buildSolutionOptionsHtml(solutions, currentId) {
        const esc = TimetableHelpers.esc;
        const opt = (s) =>
            `<option value="${s.id}"${s.id === currentId ? ' selected' : ''}>${esc(s.name)}</option>`;
        const list = solutions || [];
        const active = list.filter(s => !s.archived);
        const archived = list.filter(s => s.archived);
        let html = active.map(opt).join('');
        if (archived.length) {
            html += `<optgroup label="📦 Αρχειοθετημένα (${archived.length})">`
                + archived.map(opt).join('') + '</optgroup>';
        }
        return html;
    },

    /** Ποιο πρόγραμμα ανοίγει: το επιλεγμένο αν είναι ενεργό, αλλιώς το νεότερο ενεργό. */
    defaultSolutionId(solutions, preferredId) {
        const list = solutions || [];
        const preferred = list.find(s => s.id === preferredId);
        if (preferred && !preferred.archived) return preferred.id;
        return ((list.find(s => !s.archived) || preferred || list[0]) || {}).id;
    },

    /** Εικονίδιο/επεξήγηση του κουμπιού αρχειοθέτησης για το επιλεγμένο πρόγραμμα. */
    archiveButtonState(solutions, currentId) {
        const current = (solutions || []).find(s => s.id === currentId);
        const archived = Boolean(current && current.archived);
        return {
            archived,
            icon: archived ? '♻️' : '📦',
            title: archived
                ? 'Επαναφορά του προγράμματος στη λίστα'
                : 'Αρχειοθέτηση — βγαίνει από τη λίστα και σταματά να κρατά ώρες στην Παλέτα (αναστρέψιμο)',
        };
    },

    /** One palette card. Split out of buildLessonPaletteHtml for readability. */
    _paletteCardHtml(e) {
        const esc = TimetableHelpers.esc;
        const color = e.subject_color || '#9CA3AF';
        const bgLight = TimetableHelpers.hexToRgba(color, 0.15);
        const subject = esc(e.subject_name || '?');
        const sub = [esc(e.class_name || ''), esc(e.teacher_name || '')]
            .filter(Boolean).join(' • ');
        const filterAttrs = `data-fclass="${esc(e.class_name || '')}"
                     data-fteacher="${esc(e.teacher_name || '')}"
                     data-fsubject="${esc(e.subject_name || '')}"
                     data-search="${esc([e.subject_name, e.class_name, e.teacher_name]
                         .filter(Boolean).join(' ').toLowerCase())}"`;

        if (e.remaining > 0) {
            const slotJson = JSON.stringify(e.drag_slot).replace(/'/g, '&#39;');
            return `
                <div class="lesson-card parking-card palette-card"
                     data-slot-id="${e.drag_slot.id}" data-lesson-id="${e.lesson_id}"
                     ${filterAttrs}
                     draggable="true"
                     ondragstart="TimetableGrid.handleDragStart(event, ${e.drag_slot.id})"
                     ondragend="TimetableGrid.handleDragEnd(event)"
                     onclick="TimetableGrid.showDetails(this)"
                     data-json='${slotJson}'
                     style="background:${bgLight}; border-left: 4px solid ${color};"
                     title="Σύρε στο πρόγραμμα — απομένουν ${e.remaining} από ${e.total} ώρες${
                         e.drag_slot.unplaced_reason
                             ? ' · Γιατί έμεινε εκτός: ' + esc(e.drag_slot.unplaced_reason).replace(/"/g, '&quot;')
                             : ''}">
                    <div class="palette-card-title" style="color:${color};">${subject}</div>
                    <div class="palette-card-sub">${sub}</div>
                    <span class="palette-badge">×${e.remaining}</span>
                    <button class="palette-find-btn"
                            onmousedown="event.stopPropagation();"
                            ondragstart="event.stopPropagation(); event.preventDefault();"
                            onclick="event.stopPropagation(); TimetableView.findPlacement(${e.lesson_id})"
                            title="Βρες μου θέση — δείξε όλες τις νόμιμες θέσεις">🎯</button>
                    ${TimetableHelpers._paletteInspectBtnHtml(e.lesson_id)}
                </div>`;
        }
        if (e.missing > 0) {
            return `
                <div class="lesson-card palette-card palette-missing"
                     data-lesson-id="${e.lesson_id}" ${filterAttrs}
                     style="border-left: 4px solid ${color};"
                     title="Η λύση δεν έχει slots για ${e.missing} ώρες αυτού του μαθήματος">
                    <div class="palette-card-title">${subject}</div>
                    <div class="palette-card-sub">${sub}</div>
                    <button class="btn btn-secondary btn-sm palette-sync-btn"
                            onclick="TimetableView.syncLessonSlots(${e.lesson_id})">
                        ➕ Λείπουν ${e.missing} ώρες
                    </button>
                    ${TimetableHelpers._paletteInspectBtnHtml(e.lesson_id)}
                </div>`;
        }
        return `
            <div class="lesson-card palette-card palette-done"
                 data-lesson-id="${e.lesson_id}" ${filterAttrs}
                 style="border-left: 4px solid ${color};"
                 title="Όλες οι ώρες είναι στο πρόγραμμα">
                <div class="palette-card-title">${subject}</div>
                <div class="palette-card-sub">${sub}</div>
                <span class="palette-badge palette-badge-done">✓ ${e.placed}/${e.total}</span>
                ${TimetableHelpers._paletteInspectBtnHtml(e.lesson_id)}
            </div>`;
    },

    /**
     * Build the «Παλέτα Μαθημάτων» panel HTML. Pure: palette data (from
     * buildLessonPalette) + ui state in, HTML string out. The view mounts
     * it, wires the control events, and re-applies filters.
     *
     * ui: {collapsed, search, fClass, fTeacher, fSubject} — restored on
     * re-render so a drop doesn't reset the user's filters.
     */
    buildLessonPaletteHtml(palette, ui = {}) {
        const esc = TimetableHelpers.esc;
        const { entries, totals } = palette;
        if (!entries.length) return '';

        const opt = (values, selected) => values.map(v =>
            `<option value="${esc(v)}" ${v === selected ? 'selected' : ''}>${esc(v)}</option>`
        ).join('');
        const classes = [...new Set(entries.map(e => e.class_name).filter(Boolean))]
            .sort((a, b) => a.localeCompare(b, 'el'));
        const teachers = [...new Set(entries.map(e => e.teacher_name).filter(Boolean))]
            .sort((a, b) => a.localeCompare(b, 'el'));
        const subjects = [...new Set(entries.map(e => e.subject_name).filter(Boolean))]
            .sort((a, b) => a.localeCompare(b, 'el'));

        const cards = entries.map(e => TimetableHelpers._paletteCardHtml(e)).join('');
        const done = totals.hours_remaining === 0 && totals.hours_missing === 0;

        return `
            <div class="card mt-lg lesson-palette" style="border-left: 4px solid ${done ? 'var(--success, #10B981)' : 'var(--primary, #3B82F6)'};">
                <div class="card-header" style="cursor:pointer;" onclick="TimetableView.togglePalette()">
                    <h2 class="card-title">🎨 Παλέτα Μαθημάτων — ${totals.hours_placed}/${totals.hours_total} ώρες τοποθετημένες${done ? ' ✅' : ''}</h2>
                    <button class="btn btn-secondary btn-sm" id="palette-toggle"
                            onclick="event.stopPropagation(); TimetableView.togglePalette()">
                        ${ui.collapsed ? '▸ Εμφάνιση' : '▾ Απόκρυψη'}
                    </button>
                </div>
                <div id="palette-body" style="${ui.collapsed ? 'display:none;' : ''}">
                    <p class="text-muted" style="margin-bottom: 0.75rem;">
                        Όλα τα μαθήματα του σεναρίου. Σύρε μια κάρτα στο πρόγραμμα για να τοποθετήσεις μία ώρα —
                        οι έλεγχοι τρέχουν στο drop, και αν η αίθουσα είναι πιασμένη επιλέγεται αυτόματα άλλη ελεύθερη.
                    </p>
                    <div class="palette-controls">
                        <input type="text" class="form-input" id="palette-search"
                               placeholder="🔍 Αναζήτηση..." value="${esc(ui.search || '')}">
                        <select class="form-select" id="palette-f-class">
                            <option value="">Όλα τα τμήματα</option>${opt(classes, ui.fClass)}
                        </select>
                        <select class="form-select" id="palette-f-teacher">
                            <option value="">Όλοι οι καθηγητές</option>${opt(teachers, ui.fTeacher)}
                        </select>
                        <select class="form-select" id="palette-f-subject">
                            <option value="">Όλα τα μαθήματα</option>${opt(subjects, ui.fSubject)}
                        </select>
                    </div>
                    <div class="palette-cards">${cards}</div>
                    <p class="text-muted palette-empty-msg" style="display:none; margin-top:0.5rem;">
                        Κανένα μάθημα δεν ταιριάζει στα φίλτρα.
                    </p>
                </div>
            </div>
        `;
    },
};

if (typeof module !== 'undefined' && module.exports) {
    module.exports = TimetableHelpers;
}
