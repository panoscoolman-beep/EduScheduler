/**
 * Timetable interaction services (extracted from views/timetable.js).
 *
 * Async flows that aren't pure data-shaping. Currently `pollSolve`, used by the
 * Lock & Regenerate flow to wait for a background solve to finish. Dual-mode:
 * a classic-script global `TimetableInteractions` in the browser, module.exports
 * under Node for tests. Depends on the global API.
 */
const TimetableInteractions = {
    /**
     * Poll /solver/status until the run leaves 'generating' (or a deadline of
     * maxTimeSeconds + 60s elapses). Returns the final status object, or an
     * error-shaped object on timeout. Transient status errors are swallowed —
     * the run keeps going server-side.
     */
    async pollSolve(solutionId, maxTimeSeconds) {
        const deadline = Date.now() + (maxTimeSeconds + 60) * 1000;
        while (Date.now() < deadline) {
            await new Promise(r => setTimeout(r, 3000));
            try {
                const status = await API.solver.status(solutionId);
                if (status.status !== 'generating') return status;
            } catch (e) {
                // transient hiccup — keep polling, the run continues server-side
            }
        }
        return { status: 'error', message: 'Η αναδημιουργία αργεί — δες τη λίστα λύσεων σε λίγο.' };
    },
};

if (typeof module !== 'undefined' && module.exports) {
    module.exports = TimetableInteractions;
}
