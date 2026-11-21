// Injected into every page. Defines window.__ab once; every call returns plain data.
// Shared by all engines (macOS WebKit and Playwright).
if (!window.__ab) {
  window.__ab = (function () {
    var nextId = 1;
    var SKIP = { SCRIPT: 1, STYLE: 1, NOSCRIPT: 1, TEMPLATE: 1, SVG: 1, CANVAS: 1, HEAD: 1, META: 1, LINK: 1 };
    var BLOCK = /^(ADDRESS|ARTICLE|ASIDE|BLOCKQUOTE|DETAILS|DIALOG|DD|DIV|DL|DT|FIELDSET|FIGCAPTION|FIGURE|FOOTER|FORM|H[1-6]|HEADER|HR|LI|MAIN|NAV|OL|P|PRE|SECTION|TABLE|TR|UL|BR|SUMMARY)$/;
    var INTERACTIVE_ROLES = /^(button|link|checkbox|radio|tab|menuitem|menuitemcheckbox|menuitemradio|option|switch|combobox|textbox|searchbox|slider)$/;

    function visible(el) {
      if (!(el instanceof Element)) return true;
      var s = getComputedStyle(el);
      if (s.display === 'none' || s.visibility === 'hidden' || s.opacity === '0') return false;
      if (el.getAttribute('aria-hidden') === 'true') return false;
      var r = el.getBoundingClientRect();
      return r.width > 0 || r.height > 0 || s.position === 'fixed' || el.tagName === 'OPTION';
    }

    function isInteractive(el) {
      var t = el.tagName;
      if (t === 'A' && el.hasAttribute('href')) return true;
      if (t === 'BUTTON' || t === 'SELECT' || t === 'TEXTAREA' || t === 'SUMMARY') return true;
      if (t === 'INPUT') return el.type !== 'hidden';
      var role = el.getAttribute('role');
      if (role && INTERACTIVE_ROLES.test(role)) return true;
      if (el.isContentEditable && el.getAttribute('contenteditable') !== null) return true;
      if (el.hasAttribute('onclick') || el.getAttribute('tabindex') === '0') return true;
      return false;
    }

    function clean(s) { return (s || '').replace(/\s+/g, ' ').trim(); }
    function clip(s, n) { s = clean(s); return s.length > n ? s.slice(0, n - 1) + '…' : s; }

    function label(el) {
      var aria = el.getAttribute('aria-label');
      if (aria) return clean(aria);
      if (el.id) {
        var l = document.querySelector('label[for="' + CSS.escape(el.id) + '"]');
        if (l) return clean(l.innerText);
      }
      var wrap = el.closest('label');
      if (wrap) return clean(wrap.innerText);
      return clean(el.getAttribute('title') || el.getAttribute('placeholder') || '');
    }

    function idFor(el) {
      var id = el.getAttribute('data-ab-id');
      if (!id) { id = String(nextId++); el.setAttribute('data-ab-id', id); }
      return id;
    }

    function describe(el) {
      var t = el.tagName.toLowerCase();
      var id = idFor(el);
      var role = el.getAttribute('role');
      if (t === 'input') {
        var type = (el.type || 'text').toLowerCase();
        var parts = ['[' + id + ' input type=' + type];
        var name = label(el) || el.name;
        if (name) parts.push('"' + clip(name, 60) + '"');
        if (type === 'checkbox' || type === 'radio') parts.push(el.checked ? 'checked' : 'unchecked');
        else if (type === 'password') parts.push(el.value ? 'value=•••' : 'empty');
        else if (type === 'submit' || type === 'button') parts.push('"' + clip(el.value, 40) + '"');
        else if (el.value) parts.push('value="' + clip(el.value, 60) + '"');
        if (el.disabled) parts.push('disabled');
        return parts.join(' ') + ']';
      }
      if (t === 'select') {
        var opts = Array.prototype.slice.call(el.options, 0, 25).map(function (o) {
          return (o.selected ? '*' : '') + clip(o.text, 40);
        });
        return '[' + id + ' select "' + clip(label(el) || el.name, 50) + '" options: ' + opts.join(' | ') + ']';
      }
      if (t === 'textarea') {
        return '[' + id + ' textarea "' + clip(label(el) || el.name, 50) + '"' + (el.value ? ' value="' + clip(el.value, 80) + '"' : '') + ']';
      }
      var text = clip(el.innerText || el.getAttribute('aria-label') || el.getAttribute('title') || el.getAttribute('alt') || '', 100);
      if (!text) { var img = el.querySelector('img[alt]'); if (img) text = clip(img.alt, 80); }
      var kind = t === 'a' ? 'link' : (role || t);
      var extra = '';
      if (t === 'a') {
        var href = el.getAttribute('href') || '';
        if (href && href.indexOf('javascript:') !== 0 && href !== '#') extra = ' → ' + clip(href, 80);
      }
      if (el.disabled || el.getAttribute('aria-disabled') === 'true') extra += ' disabled';
      return '[' + id + ' ' + kind + '] ' + (text || '(no text)') + extra;
    }

    function snapshot(maxChars) {
      maxChars = maxChars || 12000;
      var out = [];
      var line = '';
      var size = 0;
      var full = false;

      function flush() {
        var l = clean(line);
        if (l) { out.push(l); size += l.length + 1; if (size > maxChars) full = true; }
        line = '';
      }

      function walk(node) {
        if (full) return;
        if (node.nodeType === 3) { line += ' ' + node.nodeValue; return; }
        if (node.nodeType !== 1) return;
        var el = node;
        if (SKIP[el.tagName]) return;
        if (!visible(el)) return;
        if (el.tagName === 'IFRAME') {
          flush();
          out.push('[iframe ' + clip(el.getAttribute('title') || el.src || '', 80) + ']');
          return;
        }
        if (el.tagName === 'IMG') {
          var alt = clean(el.alt);
          if (alt) line += ' [img: ' + clip(alt, 60) + ']';
          return;
        }
        if (isInteractive(el)) {
          line += ' ' + describe(el);
          if (el.tagName === 'A' || el.tagName === 'BUTTON' || el.getAttribute('role')) return;
          if (el.tagName === 'INPUT' || el.tagName === 'SELECT' || el.tagName === 'TEXTAREA') return;
        }
        var block = BLOCK.test(el.tagName);
        if (block) flush();
        var h = /^H([1-6])$/.exec(el.tagName);
        if (h) line += new Array(+h[1] + 1).join('#') + ' ';
        if (el.tagName === 'LI') line += '• ';
        if (el.shadowRoot) Array.prototype.forEach.call(el.shadowRoot.childNodes, walk);
        Array.prototype.forEach.call(el.childNodes, walk);
        if (block) flush();
      }

      walk(document.body || document.documentElement);
      flush();
      var text = out.join('\n');
      var truncated = text.length > maxChars;
      if (truncated) text = text.slice(0, maxChars);
      return {
        url: location.href,
        title: document.title,
        text: text,
        truncated: truncated,
        scroll: Math.round(window.scrollY) + '/' + Math.max(0, document.documentElement.scrollHeight - window.innerHeight),
        challenge: detectChallenge()
      };
    }

    function byId(id) { return document.querySelector('[data-ab-id="' + String(id).replace(/"/g, '') + '"]'); }

    function info(id) {
      var el = byId(id);
      if (!el) return null;
      var form = el.form || el.closest('form');
      return {
        tag: el.tagName.toLowerCase(),
        type: (el.getAttribute('type') || '').toLowerCase(),
        text: clip(el.innerText || el.value || el.getAttribute('aria-label') || el.getAttribute('title') || '', 120),
        autocomplete: (el.getAttribute('autocomplete') || '').toLowerCase(),
        name: (el.getAttribute('name') || '').toLowerCase(),
        in_form: !!form,
        form_action: form ? clip(form.getAttribute('action') || '', 120) : ''
      };
    }

    function click(id) {
      var el = byId(id);
      if (!el) return { ok: false, error: 'no element with id ' + id + ' (read the page again)' };
      el.scrollIntoView({ block: 'center' });
      el.focus && el.focus();
      el.click();
      return { ok: true };
    }

    function setValue(el, value) {
      var proto = el.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
      var setter = Object.getOwnPropertyDescriptor(proto, 'value');
      if (setter && setter.set) setter.set.call(el, value); else el.value = value;
      el.dispatchEvent(new Event('input', { bubbles: true }));
      el.dispatchEvent(new Event('change', { bubbles: true }));
    }

    function type(id, text, submit) {
      var el = byId(id);
      if (!el) return { ok: false, error: 'no element with id ' + id + ' (read the page again)' };
      var textual = el.tagName === 'TEXTAREA' || el.isContentEditable ||
        (el.tagName === 'INPUT' && !/^(button|submit|reset|checkbox|radio|file|image|hidden)$/i.test(el.type));
      if (!textual) return { ok: false, error: 'element ' + id + ' is not a text field; use browser_click for buttons, links and checkboxes' };
      el.scrollIntoView({ block: 'center' });
      el.focus();
      if (el.isContentEditable && el.tagName !== 'INPUT' && el.tagName !== 'TEXTAREA') {
        el.textContent = text;
        el.dispatchEvent(new InputEvent('input', { bubbles: true }));
      } else {
        setValue(el, text);
      }
      if (submit) {
        var opts = { key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true };
        el.dispatchEvent(new KeyboardEvent('keydown', opts));
        el.dispatchEvent(new KeyboardEvent('keypress', opts));
        el.dispatchEvent(new KeyboardEvent('keyup', opts));
        var form = el.form || el.closest('form');
        if (form) { if (form.requestSubmit) form.requestSubmit(); else form.submit(); }
      }
      return { ok: true };
    }

    function select(id, value) {
      var el = byId(id);
      if (!el || el.tagName !== 'SELECT') return { ok: false, error: 'element ' + id + ' is not a select' };
      var v = clean(value).toLowerCase();
      for (var i = 0; i < el.options.length; i++) {
        var o = el.options[i];
        if (clean(o.text).toLowerCase() === v || String(o.value).toLowerCase() === v) {
          el.selectedIndex = i;
          el.dispatchEvent(new Event('input', { bubbles: true }));
          el.dispatchEvent(new Event('change', { bubbles: true }));
          return { ok: true, selected: clean(o.text) };
        }
      }
      return { ok: false, error: 'no option "' + value + '"' };
    }

    function scroll(direction) {
      var h = window.innerHeight * 0.85;
      if (direction === 'up') window.scrollBy(0, -h);
      else if (direction === 'top') window.scrollTo(0, 0);
      else if (direction === 'bottom') window.scrollTo(0, document.documentElement.scrollHeight);
      else window.scrollBy(0, h);
      return { ok: true };
    }

    // Cookie banners: only ever choose the privacy-preserving option. Never "accept all".
    var REJECT = /^(reject( all)?|decline( all)?|refuse( all)?|deny( all)?|only (necessary|essential)( cookies)?|(use )?necessary (cookies )?only|continue without accepting|rifiuta( tutto| tutti)?|solo (necessari|essenziali)|continua senza accettare|rechazar( todo| todas)?|solo necesarias|refuser( tout)?|tout refuser|continuer sans accepter|ablehnen|alle ablehnen|nur notwendige( cookies)?|recusar( tudo)?|rejeitar( tudo)?|apenas necessários)$/i;
    var KNOWN = ['#onetrust-reject-all-handler', '#didomi-notice-disagree-button', '.iubenda-cs-reject-btn',
      '#CybotCookiebotDialogBodyButtonDecline', '.qc-cmp2-summary-buttons button[mode="secondary"]',
      '[data-testid="uc-deny-all-button"]', '.cmpboxbtnno', '#truste-consent-required', '.fc-cta-do-not-consent'];
    var BANNER = /cookie|consent|gdpr|cmp|privacy|onetrust|didomi|iubenda|cookiebot|usercentrics|truste/i;

    function dismissCookies() {
      for (var i = 0; i < KNOWN.length; i++) {
        var k = document.querySelector(KNOWN[i]);
        if (k && visible(k)) { k.click(); return { clicked: clean(k.innerText) || KNOWN[i] }; }
      }
      var buttons = document.querySelectorAll('button, [role=button], a[href="#"], input[type=button]');
      for (var j = 0; j < buttons.length; j++) {
        var b = buttons[j];
        var t = clean(b.innerText || b.value || '');
        if (!t || t.length > 40 || !REJECT.test(t) || !visible(b)) continue;
        var box = b.closest('[id],[class],[aria-label]');
        var ctx = '';
        for (var p = b; p && p !== document.body; p = p.parentElement) {
          ctx += ' ' + (p.id || '') + ' ' + (typeof p.className === 'string' ? p.className : '') + ' ' + (p.getAttribute('aria-label') || '');
        }
        if (BANNER.test(ctx) || box && /dialog|banner/.test(box.getAttribute('role') || '')) {
          b.click();
          return { clicked: t };
        }
      }
      return { clicked: null };
    }

    // Detects pages where a human check is waiting. We never try to solve these:
    // the person does it, then the agent continues.
    function detectChallenge() {
      var title = document.title || '';
      if (/^(just a moment|un momento|un instant|einen moment|um momento|attention required)/i.test(title)) return 'cloudflare';
      if (document.querySelector('#challenge-form, #challenge-running, #cf-challenge-running, .cf-turnstile, #turnstile-wrapper')) return 'cloudflare';
      var frames = document.querySelectorAll('iframe');
      for (var i = 0; i < frames.length; i++) {
        var f = frames[i];
        var src = f.src || '';
        if (!visible(f)) continue;
        var r = f.getBoundingClientRect();
        if (r.width < 40 || r.height < 40) continue;
        if (/challenges\.cloudflare\.com/.test(src)) return 'cloudflare';
        if (/(google\.com|recaptcha\.net)\/recaptcha/.test(src) && !/size=invisible/.test(src)) return 'recaptcha';
        if (/hcaptcha\.com/.test(src) && !/size=invisible/.test(src)) return 'hcaptcha';
        if (/arkoselabs|funcaptcha/.test(src)) return 'arkose';
      }
      if (document.querySelector('.g-recaptcha:not([data-size=invisible]) iframe, .h-captcha:not([data-size=invisible]) iframe')) return 'captcha';
      return null;
    }

    // Hand-off overlay, used by engines without a native banner (Playwright).
    function overlay(message, button) {
      if (document.getElementById('__ab_overlay')) return { ok: true };
      var host = document.createElement('div');
      host.id = '__ab_overlay';
      host.style.cssText = 'position:fixed;top:0;left:0;right:0;z-index:2147483647;';
      var root = host.attachShadow ? host.attachShadow({ mode: 'open' }) : host;
      root.innerHTML = '<div style="font:500 14px system-ui,sans-serif;background:#fff4e5;color:#3b2a10;border-bottom:2px solid #f0a020;padding:10px 14px;display:flex;gap:12px;align-items:center;box-shadow:0 2px 8px rgba(0,0,0,.15)">' +
        '<span style="flex:1"></span><button style="font:600 14px system-ui,sans-serif;padding:6px 16px;border-radius:6px;border:0;background:#f0a020;color:#fff;cursor:pointer"></button></div>';
      root.querySelector('span').textContent = message;
      var btn = root.querySelector('button');
      btn.textContent = button;
      btn.onclick = function () { window.__abHumanDone = true; host.remove(); };
      (document.body || document.documentElement).appendChild(host);
      return { ok: true };
    }

    function removeOverlay() {
      var o = document.getElementById('__ab_overlay');
      if (o) o.remove();
      return { ok: true };
    }

    return {
      snapshot: snapshot, info: info, click: click, type: type, select: select, scroll: scroll,
      dismissCookies: dismissCookies, detectChallenge: detectChallenge,
      overlay: overlay, removeOverlay: removeOverlay
    };
  })();
}
