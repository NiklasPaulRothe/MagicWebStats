/* ════════════════════════════════════════════════════════════════════════
   sidebar.js — progressive enhancement for the app-shell sidebar
   ------------------------------------------------------------------------
   The sidebar works with no JS: a hidden #nav-toggle checkbox opens the
   mobile drawer, and <label>s (hamburger + backdrop) flip it. This script
   layers nicer behavior on top WITHOUT breaking the no-JS baseline:

     • Drives the drawer via an `.is-open` class on .app-shell (and keeps the
       checkbox in sync) so state is consistent either way.
     • Esc closes the drawer; focus returns to the hamburger.
     • Clicking the backdrop or any nav link closes the drawer (mobile).
     • Desktop: a collapse toggle shrinks the rail to icons; the choice is
       remembered in localStorage and re-applied on load.
     • Keeps aria-expanded on the hamburger in sync for screen readers.

   All lookups are null-guarded so a missing element never throws.
   ════════════════════════════════════════════════════════════════════════ */
(function () {
    'use strict';

    var MOBILE_QUERY = '(max-width: 1023.98px)';
    var COLLAPSE_KEY = 'mtgstats.sidebar.collapsed';

    var shell = document.getElementById('app-shell');
    if (!shell) { return; }

    var toggle = document.getElementById('nav-toggle');      // checkbox
    var openBtn = document.getElementById('nav-open');        // hamburger label
    var backdrop = document.getElementById('nav-close');      // backdrop label
    var sidebar = document.getElementById('sidebar');
    var mql = window.matchMedia(MOBILE_QUERY);

    /* ── Mobile drawer ───────────────────────────────────────────────────── */
    function isMobile() { return mql.matches; }

    function setOpen(open) {
        shell.classList.toggle('is-open', open);
        if (toggle) { toggle.checked = open; }
        if (openBtn) { openBtn.setAttribute('aria-expanded', open ? 'true' : 'false'); }
    }

    function openDrawer() { setOpen(true); }

    function closeDrawer(returnFocus) {
        setOpen(false);
        if (returnFocus && openBtn && typeof openBtn.focus === 'function') {
            openBtn.focus();
        }
    }

    // Intercept the hamburger so we own the state (preventDefault stops the
    // label from also toggling the checkbox, which would double-flip it).
    if (openBtn) {
        openBtn.addEventListener('click', function (e) {
            e.preventDefault();
            if (shell.classList.contains('is-open')) {
                closeDrawer(false);
            } else {
                openDrawer();
            }
        });
        // Space/Enter on the label (it's role=button) should also toggle.
        openBtn.addEventListener('keydown', function (e) {
            if (e.key === 'Enter' || e.key === ' ' || e.key === 'Spacebar') {
                e.preventDefault();
                openBtn.click();
            }
        });
    }

    if (backdrop) {
        backdrop.addEventListener('click', function (e) {
            e.preventDefault();
            closeDrawer(true);
        });
    }

    // Esc closes the drawer when open (mobile only).
    document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape' && shell.classList.contains('is-open')) {
            closeDrawer(true);
        }
    });

    // Close the drawer after following a nav link on mobile (the new page
    // would reset it anyway, but this avoids a flash of the open drawer and
    // handles same-page anchor links).
    if (sidebar) {
        sidebar.addEventListener('click', function (e) {
            var link = e.target.closest('a.nav-link, a.account__action, a.account__login');
            if (link && isMobile()) {
                closeDrawer(false);
            }
        });
    }

    // If the viewport grows past the breakpoint while the drawer is open,
    // drop the mobile state so the desktop rail shows cleanly.
    function handleBreakpointChange() {
        if (!isMobile()) { setOpen(false); }
    }
    if (typeof mql.addEventListener === 'function') {
        mql.addEventListener('change', handleBreakpointChange);
    } else if (typeof mql.addListener === 'function') {
        mql.addListener(handleBreakpointChange); // Safari < 14
    }

    /* ── Desktop collapse (icon-only rail), remembered ───────────────────── */
    function applyCollapsed(collapsed) {
        shell.classList.toggle('is-collapsed', collapsed);
        var btn = document.getElementById('nav-collapse');
        if (btn) { btn.setAttribute('aria-pressed', collapsed ? 'true' : 'false'); }
    }

    // Re-apply the saved preference on load.
    try {
        if (localStorage.getItem(COLLAPSE_KEY) === '1') {
            applyCollapsed(true);
        }
    } catch (err) { /* localStorage may be blocked; ignore */ }

    // Collapse control: the #nav-collapse button toggles the icon-only rail.
    var collapseBtn = document.getElementById('nav-collapse');
    if (collapseBtn) {
        collapseBtn.addEventListener('click', function (e) {
            e.preventDefault();
            var next = !shell.classList.contains('is-collapsed');
            applyCollapsed(next);
            try { localStorage.setItem(COLLAPSE_KEY, next ? '1' : '0'); } catch (err) { /* ignore */ }
        });
    }
})();
