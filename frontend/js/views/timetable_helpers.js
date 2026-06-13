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
};

if (typeof module !== 'undefined' && module.exports) {
    module.exports = TimetableHelpers;
}
