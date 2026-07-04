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
            </style>`;
    },

    /**
     * «Ελεύθερες Αίθουσες»: grid Ώρα × Ημέρα όπου κάθε κελί δείχνει ποιες
     * αίθουσες ΔΕΝ έχουν μάθημα εκείνη τη στιγμή. Pure: slots της λύσης +
     * περίοδοι + ΟΛΕΣ οι αίθουσες μέσα, HTML string έξω.
     */
    buildFreeRoomsHtml(slots, periods, daysCount, allRooms) {
        const esc = this.esc.bind(this);
        const dayNames = ['Δευτέρα', 'Τρίτη', 'Τετάρτη', 'Πέμπτη', 'Παρασκευή', 'Σάββατο', 'Κυριακή'];
        const days = [...Array(Math.min(daysCount, 7)).keys()];
        const teaching = periods.filter(p => !p.is_break);
        const roomNames = allRooms.map(r => r.name);

        // (day, period_id) → Set κατειλημμένων αιθουσών
        const busy = new Map();
        for (const s of slots) {
            if (s.is_unplaced || s.day_of_week === null || s.day_of_week === undefined) continue;
            if (!s.classroom_name) continue;
            const key = `${s.day_of_week}|${s.period_id}`;
            if (!busy.has(key)) busy.set(key, new Set());
            busy.get(key).add(s.classroom_name);
        }

        const header = days.map(d => `<th>${dayNames[d]}</th>`).join('');
        const rows = teaching.map(p => {
            const cells = days.map(d => {
                const taken = busy.get(`${d}|${p.id}`) || new Set();
                const free = roomNames.filter(n => !taken.has(n));
                const badgeClass = free.length === 0 ? 'fr-none' : 'fr-some';
                const list = free.length
                    ? free.map(esc).join('<br>')
                    : '<em>Καμία ελεύθερη</em>';
                return `<td class="${badgeClass}"><div class="fr-count">${free.length}/${roomNames.length}</div>${list}</td>`;
            }).join('');
            return `<tr><th class="fr-time">${esc(p.start_time)}–${esc(p.end_time)}</th>${cells}</tr>`;
        }).join('');

        return `
            ${this._tableCss()}
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

    /** Convert a #RRGGBB hex colour to an rgba() string at the given alpha. */
    hexToRgba(hex, alpha = 1) {
        const r = parseInt(hex.slice(1, 3), 16);
        const g = parseInt(hex.slice(3, 5), 16);
        const b = parseInt(hex.slice(5, 7), 16);
        return `rgba(${r}, ${g}, ${b}, ${alpha})`;
    },

    /**
     * Build the parking-lot panel HTML (draggable cards for the slots the
     * solver couldn't place). Pure: a NON-empty list of unplaced slots in,
     * HTML string out. The caller handles the empty case + the DOM mount.
     */
    buildParkingLotHtml(unplaced) {
        const cards = unplaced.map(slot => {
            const bgColor = slot.subject_color || '#9CA3AF';
            const bgLight = TimetableHelpers.hexToRgba(bgColor, 0.15);
            const reasonText = slot.unplaced_reason
                ? ` <span class="text-muted" style="font-size:0.8em">— ${slot.unplaced_reason}</span>`
                : '';
            return `
                <div class="lesson-card parking-card"
                     data-slot-id="${slot.id}"
                     draggable="true"
                     ondragstart="TimetableGrid.handleDragStart(event, ${slot.id})"
                     ondragend="TimetableGrid.handleDragEnd(event)"
                     onclick="TimetableGrid.showDetails(this)"
                     data-json='${JSON.stringify(slot).replace(/'/g, "&#39;")}'
                     style="background:${bgLight}; cursor: grab; padding: 10px 14px;
                            border-left: 4px solid ${bgColor}; margin-bottom: 6px;
                            border-radius: 6px;"
                     title="Σύρε στο πρόγραμμα για να τοποθετηθεί">
                    <div style="font-weight: 600; color: ${bgColor};">
                        ${slot.subject_name || slot.subject_short || '?'}
                    </div>
                    <div style="font-size: 0.9em; color: var(--text-muted);">
                        ${slot.class_name || slot.class_short || ''}
                        ${slot.teacher_name ? ' • ' + slot.teacher_name : ''}
                    </div>
                    ${reasonText ? `<div style="font-size:0.8em; color:var(--text-muted); margin-top:4px;">${slot.unplaced_reason || ''}</div>` : ''}
                </div>
            `;
        }).join('');

        return `
            <div class="card mt-lg parking-lot" style="border-left: 4px solid var(--warning, #F59E0B);">
                <div class="card-header">
                    <h2 class="card-title">🅿️ Parking Lot — ${unplaced.length}
                        ${unplaced.length === 1 ? 'ώρα δεν τοποθετήθηκε' : 'ώρες δεν τοποθετήθηκαν'}
                    </h2>
                </div>
                <p class="text-muted" style="margin-bottom: 1rem;">
                    Σύρε ένα μάθημα στο πρόγραμμα για να το τοποθετήσεις χειροκίνητα.
                    Οι περιορισμοί επικυρώνονται κατά το drop — αν συγκρούεται με κάτι, θα δεις σφάλμα.
                </p>
                ${cards}
            </div>
        `;
    },
};

if (typeof module !== 'undefined' && module.exports) {
    module.exports = TimetableHelpers;
}
