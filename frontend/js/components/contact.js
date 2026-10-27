/**
 * Τηλέφωνα ως σύνδεσμοι: κλήση, SMS, Viber — ίδιοι κανόνες με το CRM
 * (frontend/src/lib/contact.ts). Αριθμός που δεν διαβάζεται με σιγουριά δεν
 * δίνει κουμπί — ποτέ λάθος αριθμό (π.χ. «+6912345678» θα πήγαινε Μικρονησία).
 *
 * Browser: global Contact. Node: module.exports για τα tests.
 */
const Contact = {
    GREEK: /^(?:2\d{9}|69\d{8})$/,
    GREEK_TAIL: /(?:2\d{9}|69\d{8})$/,

    _international(d) {
        if (/^30/.test(d)) return Contact.GREEK.test(d.slice(2)) ? `+${d}` : null;
        if (d.startsWith('0') || Contact.GREEK_TAIL.test(d) || !/^\d{8,15}$/.test(d)) return null;
        return `+${d}`;
    },

    _one(part) {
        const t = String(part || '').trim();
        const d = t.replace(/\D/g, '');
        if (!d) return null;
        if (t.startsWith('+')) return Contact._international(d);
        if (d.startsWith('00')) return Contact._international(d.slice(2));
        if (Contact.GREEK.test(d)) return `+30${d}`;
        if (/^30/.test(d) && Contact.GREEK.test(d.slice(2))) return `+${d}`;
        return null;
    },

    /** Όλοι οι αριθμοί ενός πεδίου: [{ intl, display, mobile }]. */
    phoneNumbers(raw) {
        const out = [];
        const seen = new Set();
        const add = (intl) => {
            if (seen.has(intl)) return;
            seen.add(intl);
            const display = intl.startsWith('+30')
                ? `${intl.slice(3, 6)} ${intl.slice(6, 9)} ${intl.slice(9)}` : intl;
            out.push({ intl, display, mobile: /^\+3069/.test(intl) || !intl.startsWith('+30') });
        };
        for (const part of String(raw || '').split(/[/,;|]|\s+(?:ή|και|or|-)\s+/i)) {
            const single = Contact._one(part);
            if (single) { add(single); continue; }
            if (part.includes('+')) continue;
            let acc = '';
            for (const group of part.trim().split(/\s+/)) {
                acc += group.replace(/\D/g, '');
                if (acc.length < 10) continue;
                if (acc.length > 10) break;
                if (Contact.GREEK.test(acc)) add(`+30${acc}`);
                acc = '';
            }
        }
        return out;
    },

    /** Σύνδεσμοι για έναν αριθμό· μηνύματα μόνο σε κινητά. text → προσυμπληρωμένο SMS. */
    links(p, text) {
        const body = text ? encodeURIComponent(text) : '';
        return {
            call: `tel:${p.intl}`,
            sms: p.mobile ? `sms:${p.intl}${body ? `?body=${body}` : ''}` : null,
            viber: p.mobile ? `viber://chat?number=${encodeURIComponent(p.intl)}` : null,
        };
    },
};

if (typeof module !== 'undefined' && module.exports) {
    module.exports = Contact;
}
