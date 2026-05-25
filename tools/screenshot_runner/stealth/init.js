// ============================================================
// Chimera Stealth Init — v1.0
// Injecté avant tout JS de la page via add_init_script()
// ============================================================

// 1. navigator.webdriver → undefined (le plus détecté)
Object.defineProperty(navigator, 'webdriver', {
    get: () => undefined,
    configurable: true
});

// 2. Chrome runtime (attendu sur Chrome réel)
if (!window.chrome) {
    window.chrome = { runtime: {} };
}

// 3. navigator.languages (cohérent avec le profil UA)
Object.defineProperty(navigator, 'languages', {
    get: () => ['fr-FR', 'fr', 'en-US', 'en'],
    configurable: true
});

// 4. navigator.plugins (liste réaliste, pas vide)
Object.defineProperty(navigator, 'plugins', {
    get: () => [
        { name: 'PDF Viewer', filename: 'internal-pdf-viewer' },
        { name: 'Chrome PDF Viewer', filename: 'internal-pdf-viewer' },
        { name: 'Chromium PDF Viewer', filename: 'internal-pdf-viewer' },
    ],
    configurable: true
});

// 5. Canvas fingerprint — bruit cohérent par session (seed injecté runtime)
// __SESSION_SEED__ est remplacé par loader.py avant add_init_script()
const _sessionSeed = __SESSION_SEED__;
const _origToDataURL = HTMLCanvasElement.prototype.toDataURL;
HTMLCanvasElement.prototype.toDataURL = function(...args) {
    const ctx = this.getContext('2d');
    if (ctx) {
        ctx.fillStyle = `rgba(${_sessionSeed % 5},${_sessionSeed % 7},${_sessionSeed % 11},0.003)`;
        ctx.fillRect(0, 0, 1, 1);
    }
    return _origToDataURL.apply(this, args);
};

// 6. WebGL vendor/renderer — cohérents avec l'UA (WebGL1 + WebGL2)
const _origGetParameter = WebGLRenderingContext.prototype.getParameter;
WebGLRenderingContext.prototype.getParameter = function(parameter) {
    if (parameter === 37445) return 'Intel Inc.';        // UNMASKED_VENDOR_WEBGL
    if (parameter === 37446) return 'Intel Iris OpenGL Engine'; // UNMASKED_RENDERER_WEBGL
    return _origGetParameter.apply(this, [parameter]);
};
if (typeof WebGL2RenderingContext !== 'undefined') {
    const _origGetParameter2 = WebGL2RenderingContext.prototype.getParameter;
    WebGL2RenderingContext.prototype.getParameter = function(parameter) {
        if (parameter === 37445) return 'Intel Inc.';
        if (parameter === 37446) return 'Intel Iris OpenGL Engine';
        return _origGetParameter2.apply(this, [parameter]);
    };
}
