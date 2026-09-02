/** @odoo-module **/

import {
    Component,
    onWillUnmount,
    useEffect,
    useRef,
    useState,
} from "@odoo/owl";
import { registry } from "@web/core/registry";
import { user } from "@web/core/user";
import { _t } from "@web/core/l10n/translation";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

import { loadExcalidraw } from "../excalidraw_loader";

const SCENE_UPDATE_DELAY = 600; // ms — debounce before writing scene JSON to the record
const PREVIEW_UPDATE_DELAY = 2500; // ms — idle delay before regenerating the PNG preview
const PREVIEW_MAX_WIDTH = 512; // px — preview thumbnail width

/** Map an Odoo user lang to the closest Excalidraw locale code. */
function excalidrawLang(odooLang) {
    const fallbacks = {
        es: "es-ES",
        pt: "pt-BR",
        en: "en",
        fr: "fr-FR",
        de: "de-DE",
        it: "it-IT",
        zh: "zh-CN",
    };
    const normalized = (odooLang || "en").replace("_", "-");
    const [base] = normalized.split("-");
    return fallbacks[base] || normalized;
}

/** Detect the Odoo webclient color scheme ("light" | "dark").
 * Odoo 19 exposes the --o-webclient-color-scheme custom property on the
 * webclient root (body.o_web_client), with values "bright" | "dark". */
function webclientTheme() {
    const webclient = document.querySelector(
        "body.o_web_client, .o_webclient"
    );
    if (webclient) {
        const scheme = getComputedStyle(webclient)
            .getPropertyValue("--o-webclient-color-scheme")
            .trim();
        if (scheme) {
            return scheme === "dark" ? "dark" : "light";
        }
    }
    if (window.matchMedia?.("(prefers-color-scheme: dark)").matches) {
        return "dark";
    }
    return "light";
}

/** Downscale a PNG blob to a JPEG data URL (white background) for previews. */
async function previewDataUrl(blob, maxWidth) {
    try {
        const bitmap = await createImageBitmap(blob);
        const scale = Math.min(1, maxWidth / bitmap.width);
        const canvas = document.createElement("canvas");
        canvas.width = Math.max(1, Math.round(bitmap.width * scale));
        canvas.height = Math.max(1, Math.round(bitmap.height * scale));
        const ctx = canvas.getContext("2d");
        ctx.fillStyle = "#ffffff";
        ctx.fillRect(0, 0, canvas.width, canvas.height);
        ctx.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
        bitmap.close?.();
        return canvas.toDataURL("image/jpeg", 0.85);
    } catch {
        return null;
    }
}

export class ExcalidrawCanvasField extends Component {
    static template = "excalidraw_for_odoo.ExcalidrawCanvasField";
    static props = { ...standardFieldProps };

    setup() {
        this.containerRef = useRef("excalidraw_container");

        this.state = useState({ loading: false, error: "" });
        this.lib = null;
        this.reactRoot = null;
        this.excalidrawAPI = null;
        this.mountToken = 0;

        // Editor theme: null = follow the webclient color scheme, otherwise
        // a manual "light" | "dark" choice kept until the widget unmounts.
        this.manualTheme = null;
        this.reactProps = null;
        this._schemeObserver = null;

        this._sceneTimer = null;
        this._previewTimer = null;
        this._latestElements = null;
        this._latestAppState = null;
        this._lastSerializedScene = this.props.record.data.scene_data || "";

        // (Re)mount the React editor whenever the edited record or the
        // readonly flag changes. Cleanup runs before each re-mount, which
        // also covers unmounting on record switch.
        useEffect(
            () => {
                const el = this.containerRef.el;
                if (!this.props.readonly && el) {
                    this.mountEditor(el);
                }
                return () => this.destroyEditor();
            },
            () => [this.props.record.resId, this.props.readonly],
        );

        onWillUnmount(() => this.destroyEditor());

        // Follow webclient dark-mode switches while no manual choice was made.
        this._schemeObserver = new MutationObserver(() => {
            if (this.manualTheme === null) {
                this.applyEditorTheme();
            }
        });
        this._schemeObserver.observe(document.documentElement, {
            attributes: true,
            attributeFilter: ["class", "style", "data-color-mode"],
        });
        this._schemeObserver.observe(document.body, {
            attributes: true,
            attributeFilter: ["class", "style"],
        });
    }

    get previewSrc() {
        const data = this.props.record.data.preview_image;
        return data ? `data:image/jpeg;base64,${data}` : false;
    }

    get effectiveTheme() {
        return this.manualTheme ?? webclientTheme();
    }

    get themeTooltip() {
        return this.effectiveTheme === "dark"
            ? _t("Switch to light theme")
            : _t("Switch to dark theme");
    }

    toggleTheme() {
        this.manualTheme = this.effectiveTheme === "dark" ? "light" : "dark";
        this.applyEditorTheme();
    }

    /** Re-render the React root with the current theme, preserving the scene
     * (initialData only applies on mount, so React reconciliation keeps the
     * internal editor state intact). */
    applyEditorTheme() {
        if (this.reactProps && this.reactRoot && this.lib) {
            this.reactProps.theme = this.effectiveTheme;
            this.reactRoot.render(
                this.lib.React.createElement(this.lib.Excalidraw, this.reactProps)
            );
        }
    }

    // ------------------------------------------------------------------
    // Editor lifecycle
    // ------------------------------------------------------------------

    async mountEditor(el) {
        const token = ++this.mountToken;
        this.state.loading = true;
        this.state.error = "";
        try {
            const lib = await loadExcalidraw();
            if (token !== this.mountToken || !this.containerRef.el) {
                return; // stale mount
            }
            this.lib = lib;
            this._lastSerializedScene = this.props.record.data.scene_data || "";
            this.reactRoot = lib.ReactDOMClient.createRoot(el);
            this.reactProps = {
                initialData: this.buildInitialData(),
                onChange: (elements, appState) =>
                    this.scheduleSceneUpdate(elements, appState),
                excalidrawAPI: (api) => {
                    if (token === this.mountToken) {
                        this.excalidrawAPI = api;
                    }
                },
                lang: excalidrawLang(user.lang),
                theme: this.effectiveTheme,
                name: this.props.record.data.name || "drawing",
                gridMode: null,
            };
            this.reactRoot.render(
                lib.React.createElement(lib.Excalidraw, this.reactProps),
            );
        } catch (error) {
            if (token === this.mountToken) {
                this.state.error = `${_t("Could not load the Excalidraw editor")}: ${error?.message || error}`;
            }
        } finally {
            if (token === this.mountToken) {
                this.state.loading = false;
            }
        }
    }

    destroyEditor() {
        // Flush pending scene edits so the last strokes are never lost.
        if (this._sceneTimer) {
            clearTimeout(this._sceneTimer);
            this._sceneTimer = null;
            this.flushSceneNow();
        }
        if (this._previewTimer) {
            clearTimeout(this._previewTimer);
            this._previewTimer = null;
        }
            this.mountToken++;
            this._latestElements = null;
            this._latestAppState = null;
            this.reactProps = null;
            if (this._schemeObserver) {
                this._schemeObserver.disconnect();
                this._schemeObserver = null;
            }
        if (this.reactRoot) {
            try {
                this.reactRoot.unmount();
            } catch {
                // React root may already be gone with its container.
            }
            this.reactRoot = null;
        }
        this.excalidrawAPI = null;
    }

    // ------------------------------------------------------------------
    // Scene serialization / persistence
    // ------------------------------------------------------------------

    buildInitialData() {
        const raw = this.props.record.data.scene_data;
        if (raw) {
            try {
                const parsed = JSON.parse(raw);
                if (Array.isArray(parsed.elements)) {
                    return {
                        elements: parsed.elements,
                        appState: {
                            viewBackgroundColor:
                                parsed.appState?.viewBackgroundColor ||
                                "#ffffff",
                        },
                        files: parsed.files || {},
                    };
                }
            } catch {
                // Fall back to a fresh scene when stored data is invalid.
            }
        }
        return {
            appState: { viewBackgroundColor: "#ffffff" },
            elements: [],
            files: {},
        };
    }

    serializeScene(elements, appState) {
        const files = {};
        for (const [fileId, file] of Object.entries(
            this.excalidrawAPI?.getFiles() || {},
        )) {
            files[fileId] = {
                dataURL: file.dataURL,
                mimeType: file.mimeType,
                created: file.created,
            };
        }
        return JSON.stringify({
            type: "excalidraw",
            version: 2,
            source: "excalidraw_for_odoo",
            elements,
            appState: {
                viewBackgroundColor: appState?.viewBackgroundColor || "#ffffff",
            },
            files,
        });
    }

    scheduleSceneUpdate(elements, appState) {
        if (this.props.readonly) {
            return;
        }
        this._latestElements = elements;
        this._latestAppState = appState;
        clearTimeout(this._sceneTimer);
        this._sceneTimer = setTimeout(
            () => this.flushSceneNow(),
            SCENE_UPDATE_DELAY,
        );
        clearTimeout(this._previewTimer);
        this._previewTimer = setTimeout(
            () => this.updatePreview(),
            PREVIEW_UPDATE_DELAY,
        );
    }

    flushSceneNow() {
        this._sceneTimer = null;
        if (!this._latestElements) {
            return;
        }
        const json = this.serializeScene(
            this._latestElements,
            this._latestAppState,
        );
        if (json !== this._lastSerializedScene) {
            this._lastSerializedScene = json;
            this.props.record.update({ scene_data: json });
        }
    }

    async updatePreview() {
        this._previewTimer = null;
        const api = this.excalidrawAPI;
        if (!api || !this.lib || !this._latestElements?.length) {
            return;
        }
        try {
            const blob = await this.lib.exportToBlob({
                elements: this._latestElements,
                appState: this._latestAppState,
                files: api.getFiles(),
                mimeType: "image/png",
            });
            const dataUrl = await previewDataUrl(blob, PREVIEW_MAX_WIDTH);
            if (dataUrl && !this.props.readonly) {
                this.props.record.update({
                    preview_image: dataUrl.split(",")[1],
                });
            }
        } catch (error) {
            // Preview generation is best-effort: never block drawing on it.
            console.error(
                "excalidraw_for_odoo: preview generation failed",
                error,
            );
        }
    }
}

export const excalidrawCanvasField = {
    component: ExcalidrawCanvasField,
    displayName: _t("Excalidraw canvas"),
    supportedTypes: ["text"],
};

registry.category("fields").add("excalidraw_canvas", excalidrawCanvasField);
