/** @odoo-module **/

// Odoo 20 / OWL 3 port of the chatter extension:
// - Chatter moved to @mail/chatter/web_portal_project/chatter and its
//   threadId/threadModel props are propComputed (call them: this.threadId()).
// - onWillUpdateProps is gone: useOnChange tracks the threadId change that
//   happens when a record is saved while its chatter stays open.
// - useState is gone: visibility is a signal.
// - check_access_rights (call_kw) is gone in 20: the user service exposes
//   checkAccessRight(model, operation), backed by has_access() and cached.
import { patch } from "@web/core/utils/patch";
import { useService } from "@web/core/utils/hooks";
import { user } from "@web/core/user";
import { _t } from "@web/core/l10n/translation";
import { Chatter } from "@mail/chatter/web_portal_project/chatter";
import { signal, useOnChange } from "@odoo/owl";

import { ExcalidrawPickerDialog } from "./excalidraw_dialogs";

// Session-level caches (design §3.1): the group check runs once per session
// (the user service caches hasGroup anyway) and the model-level write-ACL
// check runs once per distinct host model per session.
const excalidrawCaches = {
    groupCheckDone: false,
    groupCheckResult: false,
    modelWriteAccess: new Map(), // Map<modelName, Boolean>
};

async function isExcalidrawGroupUser() {
    if (!excalidrawCaches.groupCheckDone) {
        excalidrawCaches.groupCheckResult = await user.hasGroup(
            "excalidraw_for_odoo.group_excalidraw_user",
        );
        excalidrawCaches.groupCheckDone = true;
    }
    return excalidrawCaches.groupCheckResult;
}

/** Model-level write ACL signal (O1): cached per model; any failure
 * degrades to `true` (visible button + friendly controller error on save) —
 * the spec-sanctioned degradation, the controller stays the source of truth
 * (FR-ACCESS-1). Record-rule denials are intentionally not detected here. */
async function modelWriteAccess(model) {
    if (!excalidrawCaches.modelWriteAccess.has(model)) {
        let access = true;
        try {
            access = await user.checkAccessRight(model, "write");
        } catch (error) {
            console.error(
                "excalidraw_for_odoo: write access check failed",
                error,
            );
            access = true;
        }
        excalidrawCaches.modelWriteAccess.set(model, access);
    }
    return excalidrawCaches.modelWriteAccess.get(model);
}

patch(Chatter.prototype, {
    setup() {
        super.setup(...arguments);
        this.dialog = useService("dialog");

        // Reactive visibility (OWL 3 signal): default hidden so the button
        // never flashes while the async checks resolve (and never renders at
        // all for non-members or unsaved records — FR-ENTRY-1).
        this.excalidrawVisible = signal(false);
        this.excalidrawButtonTitle = _t("Add or edit an Excalidraw drawing");

        this.resolveExcalidrawVisibility();
        useOnChange(
            () => this.threadId(),
            (threadId) => {
                if (threadId) {
                    // threadId became truthy after a change: the record was
                    // just saved (falsy → truthy) while the chatter stayed
                    // open — re-run the visibility checks. A direct record
                    // switch re-resolving is harmless (cached checks).
                    this.resolveExcalidrawVisibility();
                }
            },
            { initialRun: false },
        );
    },

    async resolveExcalidrawVisibility() {
        if (!this.threadId()) {
            // Unsaved record: hidden, zero RPCs (FR-ENTRY-1).
            this.excalidrawVisible.set(false);
            return;
        }
        if (!(await isExcalidrawGroupUser())) {
            this.excalidrawVisible.set(false);
            return;
        }
        this.excalidrawVisible.set(
            await modelWriteAccess(this.threadModel()),
        );
    },

    openExcalidraw() {
        this.dialog.add(ExcalidrawPickerDialog, {
            resModel: this.threadModel(),
            resId: this.threadId(),
            onSaved: async () => {
                await this.refreshAttachments();
            },
        });
    },

    /** Chatter refresh (FR-SAVE-1). Odoo 20: the 19-era chain
     * (attachmentList.load → reloadAttachments → props.onSave) is gone with
     * the old Chatter; the 20 chatter itself listens for MAIL:RELOAD-THREAD
     * and refetches thread data (messages + attachments) for the matching
     * model/id — exactly the "attachment created server-side" case this
     * module needs. */
    async refreshAttachments() {
        try {
            this.env.bus.trigger("MAIL:RELOAD-THREAD", {
                model: this.threadModel(),
                id: this.threadId(),
            });
        } catch (error) {
            console.error(
                "excalidraw_for_odoo: could not refresh attachments",
                error,
            );
        }
    },
});
