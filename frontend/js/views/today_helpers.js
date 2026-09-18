/**
 * 📱 «Σήμερα» — pure helpers (χωρίς DOM/API), ώστε να ελέγχονται με node --test.
 *
 * Browser: global TodayHelpers. Node: module.exports για τα tests. No build step.
 */
const TodayHelpers = {
    DAYS: ['Δευτέρα', 'Τρίτη', 'Τετάρτη', 'Πέμπτη', 'Παρασκευή', 'Σάββατο', 'Κυριακή'],

    /** JS Date → μέρα EDS (0=Δευτέρα … 6=Κυριακή). */
    edsDay(date) {
        return (date.getDay() + 6) % 7;
    },

    /** «H:MM»/«HH:MM» → λεπτά από τα μεσάνυχτα (για σωστή σύγκριση). */
    minutes(hhmm) {
        const [h, m] = String(hhmm || '0:0').split(':').map(Number);
        return (h || 0) * 60 + (m || 0);
    },

    nowHHMM(date) {
        return `${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`;
    },

    /** Επιλογές φίλτρου: καθηγητές και αίθουσες που εμφανίζονται στο πρόγραμμα. */
    filterOptions(slots) {
        const collator = new Intl.Collator('el');
        const uniq = (key) => [...new Set((slots || []).filter(s => !s.is_unplaced && s[key]).map(s => s[key]))]
            .sort(collator.compare);
        return { teachers: uniq('teacher_name'), rooms: uniq('classroom_name') };
    },

    /** filter: '' (όλα) | 't:<καθηγητής>' | 'r:<αίθουσα>' */
    matches(slot, filter) {
        if (!filter) return true;
        const value = filter.slice(2);
        return filter.startsWith('t:') ? slot.teacher_name === value : slot.classroom_name === value;
    },

    /**
     * Ομαδοποίηση μιας μέρας σε «Τώρα / Ακολουθεί / Αργότερα».
     * now = «HH:MM» για σήμερα, ή null για άλλη μέρα (όλα στο «Αργότερα»).
     */
    buildDay(slots, periods, day, now, filter = '') {
        const byPeriod = new Map((periods || []).map(p => [p.id, p]));
        const groups = new Map();
        (slots || []).forEach(s => {
            const p = byPeriod.get(s.period_id);
            if (s.is_unplaced || s.day_of_week !== day || !p || !TodayHelpers.matches(s, filter)) return;
            if (!groups.has(p.id)) groups.set(p.id, { period: p, items: [] });
            groups.get(p.id).items.push(s);
        });
        const collator = new Intl.Collator('el');
        const ordered = [...groups.values()]
            .sort((a, b) => TodayHelpers.minutes(a.period.start_time) - TodayHelpers.minutes(b.period.start_time));
        ordered.forEach(g => g.items.sort((a, b) =>
            collator.compare(a.classroom_name || '', b.classroom_name || '')));

        const result = { current: null, next: null, later: [], done: 0, empty: ordered.length === 0 };
        if (now === null || now === undefined) {
            result.later = ordered;
            return result;
        }
        const t = TodayHelpers.minutes(now);
        ordered.forEach(g => {
            const start = TodayHelpers.minutes(g.period.start_time);
            const end = TodayHelpers.minutes(g.period.end_time);
            if (end <= t) result.done += 1;
            else if (start <= t) result.current = g;
            else if (!result.next) result.next = g;
            else result.later.push(g);
        });
        return result;
    },

    _esc(s) {
        return String(s == null ? '' : s)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    },

    groupHtml(group, title, cls) {
        const esc = TodayHelpers._esc;
        const p = group.period;
        const items = group.items.map(s => `
            <div class="today-item">
                <div class="today-room">${esc(s.classroom_name || '—')}</div>
                <div class="today-what"><b>${esc(s.subject_name || 'Μάθημα')}</b>
                    <small>${esc(s.class_name || '')}</small></div>
                <div class="today-who">👤 ${esc(s.teacher_name || '—')}</div>
            </div>`).join('');
        return `<section class="today-group ${cls}">
                    <h3>${title ? `${title} · ` : ''}${esc(p.start_time)}–${esc(p.end_time)}</h3>${items}
                </section>`;
    },

    buildHtml(day) {
        if (day.empty) return '<p class="text-muted today-empty">Κανένα μάθημα αυτή τη μέρα.</p>';
        const parts = [];
        if (day.current) parts.push(TodayHelpers.groupHtml(day.current, '🟢 Τώρα', 'is-now'));
        if (day.next) parts.push(TodayHelpers.groupHtml(day.next, '⏭ Ακολουθεί', 'is-next'));
        if (!day.current && !day.next && day.done && !day.later.length) {
            parts.push('<p class="text-muted today-empty">✅ Τα μαθήματα της μέρας τελείωσαν.</p>');
        }
        day.later.forEach(g => parts.push(TodayHelpers.groupHtml(g, '', '')));
        if (day.done) parts.push(`<p class="text-muted" style="font-size:0.8rem">${day.done} ώρες έχουν ήδη ολοκληρωθεί.</p>`);
        return parts.join('');
    },
};

if (typeof module !== 'undefined' && module.exports) {
    module.exports = TodayHelpers;
}
