/** @odoo-module **/

/**
 * Loader for the vendored Excalidraw bundle.
 *
 * The library (@excalidraw/excalidraw 0.18.1 + React 18 runtime) is bundled
 * with esbuild into `static/lib/excalidraw/` as a self-contained ESM module.
 * It is NOT registered in the Odoo asset bundles: it must be loaded through
 * a native dynamic import so that its own code-split chunks and its font
 * assets resolve relative to the module static URL.
 *
 * Fonts are fetched from `window.EXCALIDRAW_ASSET_PATH` (Excalidraw
 * runtime contract), which we point to the vendored fonts directory.
 */

const MODULE_BASE = "/excalidraw_for_odoo/static/lib/excalidraw";

let loadPromise = null;

export function ensureExcalidrawAssetPath() {
    let base = `${MODULE_BASE}/`;
    if (!base.endsWith("/")) {
        base += "/";
    }
    window.EXCALIDRAW_ASSET_PATH = base;
    return base;
}

export function loadExcalidraw() {
    if (!loadPromise) {
        ensureExcalidrawAssetPath();
        // Computed specifier: keeps the dynamic import opaque to any static
        // bundler/transpiler pass, so it stays a native runtime import().
        const specifier = ["/excalidraw_for_odoo", "/static/lib/excalidraw/excalidraw.vendor.js"].join("");
        loadPromise = import(/* webpackIgnore: true */ specifier).catch((error) => {
            // Allow a later retry instead of caching the failure forever.
            loadPromise = null;
            throw error;
        });
    }
    return loadPromise;
}
