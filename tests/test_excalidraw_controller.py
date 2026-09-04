# Local dev environments do not ship the odoo package; the runtime imports
# are resolved inside the odoo:19 container. Same suppression pattern as the
# sibling `drawing` module manifest.
# pyright: reportMissingImports=false
"""Strict-TDD controller suite for the Excalidraw chatter tool.

Written BEFORE ``controllers/main.py`` exists (RED), then made green by the
controller implementation. Covers IR-ROUTE-1 (``/excalidraw/chatter/save``),
IR-ROUTE-2 (``/excalidraw/chatter/scene``), FR-PAIR-1, FR-ACCESS-1,
FR-NAME-1, BR-SCENE-1, BR-CONC-1, DR-ATT-1 per design §7.

Host model notes (verified against this build):
- ``res.users`` has no ``message_post`` in Odoo 19 → not chatter-capable; the
  write-denial path uses ``project.task`` (model ACL: read=t / write=f for
  ``base.group_user``).
- The scene read-denial path uses ``crm.lead`` (no ACL at all for plain
  internal users → host read denied through the attachment ORM read).
"""

import base64
import json

from odoo import Command
from odoo.tests import HttpCase, TransactionCase, tagged

SAVE_URL = "/excalidraw/chatter/save"
SCENE_URL = "/excalidraw/chatter/scene"

# Valid scene documents (DR-SCENE-1 envelope; server-side contract is the
# looser "JSON dict containing an elements key" per BR-SCENE-1).
SCENE_V1 = json.dumps(
    {
        "type": "excalidraw",
        "version": 2,
        "source": "excalidraw_for_odoo",
        "elements": [{"id": "e1", "type": "rectangle"}],
        "appState": {"viewBackgroundColor": "#ffffff"},
        "files": {},
    }
)
SCENE_V2 = json.dumps(
    {
        "type": "excalidraw",
        "version": 2,
        "source": "excalidraw_for_odoo",
        "elements": [
            {"id": "e1", "type": "rectangle"},
            {"id": "e2", "type": "text"},
        ],
        "appState": {"viewBackgroundColor": "#ffffff"},
        "files": {},
    }
)
EMPTY_ELEMENTS_SCENE = json.dumps(
    {
        "type": "excalidraw",
        "version": 2,
        "source": "excalidraw_for_odoo",
        "elements": [],
        "appState": {"viewBackgroundColor": "#ffffff"},
        "files": {},
    }
)

# 1x1 transparent PNG.
PNG_A_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8AA"
    "AwAB/wF/idjixAAAAABJRU5ErkJggg=="
)
# 1x1 red PNG (PIL-generated; different bytes than PNG_A for
# content-change assertions). Replaces a hand-crafted constant that was
# structurally corrupt and blew up PIL inside ir.attachment writes.
PNG_B_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4"
    "nGP4z8DwHwAFAAH/iZk9HQAAAABJRU5ErkJggg=="
)


@tagged("post_install", "-at_install")
class TestExcalidrawChatterController(HttpCase):
    """Route-level contract tests dispatched through the real HTTP stack."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.exc_group = cls.env.ref("excalidraw_for_odoo.group_excalidraw_user")
        cls.excalidraw_user = cls.env["res.users"].create(
            {
                "name": "Excalidraw Full Access",
                "login": "exc_full",
                "email": "exc_full@example.com",
                "password": "exc_full",
                "group_ids": [
                    Command.link(cls.exc_group.id),
                    Command.link(cls.env.ref("base.group_system").id),
                ],
            }
        )
        cls.plain_user = cls.env["res.users"].create(
            {
                "name": "Excalidraw Plain User",
                "login": "exc_plain",
                "email": "exc_plain@example.com",
                "password": "exc_plain",
                "group_ids": [
                    Command.link(cls.exc_group.id),
                    Command.link(cls.env.ref("base.group_user").id),
                ],
            }
        )
        cls.outsider = cls.env["res.users"].create(
            {
                "name": "Excalidraw Outsider",
                "login": "exc_outsider",
                "email": "exc_outsider@example.com",
                "password": "exc_outsider",
                "group_ids": [Command.link(cls.env.ref("base.group_user").id)],
            }
        )
        # Happy-path host: chatter-capable and writable by excalidraw_user.
        cls.host = cls.env["res.partner"].create({"name": "Excalidraw Host"})

        # Write-denial host: project.task is readable but NOT writable by
        # plain internal users (model ACL write=f for base.group_user).
        cls.deny_task = None
        if "project.task" in cls.env:
            project = cls.env["project.project"].create({"name": "Exc Deny"})
            cls.deny_task = cls.env["project.task"].create(
                {"name": "No Write Task", "project_id": project.id}
            )

        # Read-denial host: plain internal users have no crm.lead ACL at all,
        # so the ORM read of a lead-linked attachment raises AccessError.
        cls.read_denied_attachment_id = None
        if "crm.lead" in cls.env:
            lead = cls.env["crm.lead"].create(
                {"name": "Exc Read Denial", "type": "lead"}
            )
            read_denied = cls.env["ir.attachment"].create(
                {
                    "name": "Secret.excalidraw",
                    "mimetype": "application/json",
                    "raw": SCENE_V1.encode("utf-8"),
                    "res_model": "crm.lead",
                    "res_id": lead.id,
                    "res_field": False,
                    "public": False,
                    "url": False,
                }
            )
            cls.read_denied_attachment_id = read_denied.id

        # A non-.excalidraw attachment on the happy-path host (wrong-type
        # payload for the scene route).
        cls.png_only_attachment = cls.env["ir.attachment"].create(
            {
                "name": "photo.png",
                "mimetype": "image/png",
                "raw": base64.b64decode(PNG_A_B64),
                "res_model": "res.partner",
                "res_id": cls.host.id,
                "res_field": False,
                "public": False,
                "url": False,
            }
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _json_rpc(self, path, params, login, password):
        """Dispatch a JSON-RPC style POST as ``login`` and return the result."""
        self.authenticate(login, password)
        response = self.url_open(
            path,
            data=json.dumps({"jsonrpc": "2.0", "method": "call", "params": params}),
            headers={"Content-Type": "application/json"},
        )
        return response.json()["result"]

    def _save(self, login, password, **params):
        return self._json_rpc(SAVE_URL, params, login, password)

    def _scene(self, login, password, attachment_id):
        return self._json_rpc(
            SCENE_URL, {"attachment_id": attachment_id}, login, password
        )

    def _new_host(self, name="Fresh Host"):
        return self.env["res.partner"].create({"name": name})

    def _host_attachments(self, host):
        return self.env["ir.attachment"].search(
            [
                ("res_model", "=", host._name),
                ("res_id", "=", host.id),
                ("res_field", "=", False),
            ]
        )

    # ------------------------------------------------------------------
    # IR-ROUTE-1 / FR-PAIR-1 / DR-ATT-1
    # ------------------------------------------------------------------

    def test_save_pair_completeness(self):
        """A first non-empty save creates exactly the attachment pair."""
        host = self._new_host("Pair Host")
        result = self._save(
            "exc_full",
            "exc_full",
            res_model="res.partner",
            res_id=host.id,
            name="Cover",
            scene=SCENE_V1,
            png=PNG_A_B64,
        )
        self.assertNotIn("error", result)
        self.assertTrue(result.get("ok"))
        self.assertTrue(result.get("scene_id"))
        self.assertTrue(result.get("png_id"))
        attachments = self._host_attachments(host)
        self.assertEqual(len(attachments), 2)
        scene = attachments.filtered(lambda a: a.name == "Cover.excalidraw")
        png = attachments.filtered(lambda a: a.name == "Cover.png")
        self.assertEqual(len(scene), 1)
        self.assertEqual(len(png), 1)
        self.assertEqual(result["scene_id"], scene.id)
        self.assertEqual(result["png_id"], png.id)
        self.assertEqual(scene.mimetype, "application/json")
        self.assertEqual(png.mimetype, "image/png")
        for att in attachments:
            self.assertEqual(att.res_model, "res.partner")
            self.assertEqual(att.res_id, host.id)
            self.assertFalse(att.res_field)
            self.assertFalse(att.public)
            self.assertFalse(att.url)
        self.assertEqual(scene.raw, SCENE_V1.encode("utf-8"))
        self.assertEqual(png.raw, base64.b64decode(PNG_A_B64))

    def test_save_upsert_no_duplicate(self):
        """Re-saving the same drawing updates in place, never duplicates."""
        host = self._new_host("Upsert Host")
        first = self._save(
            "exc_full",
            "exc_full",
            res_model="res.partner",
            res_id=host.id,
            name="Sketch",
            scene=SCENE_V1,
            png=PNG_A_B64,
        )
        self.assertNotIn("error", first)
        scene_row = self.env["ir.attachment"].browse(first["scene_id"])
        first_write_date = scene_row.write_date
        second = self._save(
            "exc_full",
            "exc_full",
            res_model="res.partner",
            res_id=host.id,
            name="Sketch",
            scene=SCENE_V2,
            png=PNG_B_B64,
        )
        self.assertNotIn("error", second)
        self.assertEqual(second["scene_id"], first["scene_id"])
        self.assertEqual(second["png_id"], first["png_id"])
        self.assertEqual(len(self._host_attachments(host)), 2)
        scene_row = self.env["ir.attachment"].browse(first["scene_id"])
        self.assertEqual(scene_row.raw, SCENE_V2.encode("utf-8"))
        self.assertGreaterEqual(scene_row.write_date, first_write_date)

    def test_save_last_write_wins(self):
        """Sequential conflicting saves end with the last content (BR-CONC-1)."""
        host = self._new_host("Concurrent Host")
        first = self._save(
            "exc_full",
            "exc_full",
            res_model="res.partner",
            res_id=host.id,
            name="Race",
            scene=SCENE_V1,
            png=PNG_A_B64,
        )
        second = self._save(
            "exc_full",
            "exc_full",
            res_model="res.partner",
            res_id=host.id,
            name="Race",
            scene=SCENE_V2,
            png=PNG_B_B64,
        )
        self.assertNotIn("error", first)
        self.assertNotIn("error", second)
        self.assertEqual(len(self._host_attachments(host)), 2)
        scene_row = self.env["ir.attachment"].browse(second["scene_id"])
        self.assertEqual(scene_row.raw, SCENE_V2.encode("utf-8"))

    def test_save_png_twin_recreated(self):
        """A deleted PNG twin is regenerated by the next PNG-carrying save."""
        host = self._new_host("Twin Host")
        first = self._save(
            "exc_full",
            "exc_full",
            res_model="res.partner",
            res_id=host.id,
            name="Twin",
            scene=SCENE_V1,
            png=PNG_A_B64,
        )
        self.env["ir.attachment"].browse(first["png_id"]).unlink()
        self.assertEqual(len(self._host_attachments(host)), 1)
        second = self._save(
            "exc_full",
            "exc_full",
            res_model="res.partner",
            res_id=host.id,
            name="Twin",
            scene=SCENE_V2,
            png=PNG_B_B64,
        )
        self.assertNotIn("error", second)
        self.assertEqual(second["scene_id"], first["scene_id"])
        attachments = self._host_attachments(host)
        self.assertEqual(len(attachments), 2)
        png = attachments.filtered(lambda a: a.name == "Twin.png")
        self.assertEqual(len(png), 1)
        self.assertEqual(png.raw, base64.b64decode(PNG_B_B64))

    # ------------------------------------------------------------------
    # BR-SCENE-1 / robustness / IR-ROUTE-1 param contract
    # ------------------------------------------------------------------

    def test_save_corrupt_scene_rejected(self):
        """Invalid scene documents are rejected with zero attachment rows."""
        host = self._new_host("Corrupt Host")
        for scene in ("not json", "[1, 2]", '{"foo": 1}'):
            result = self._save(
                "exc_full",
                "exc_full",
                res_model="res.partner",
                res_id=host.id,
                name="Bad",
                scene=scene,
                png=None,
            )
            self.assertIn("error", result, scene)
            self.assertEqual(len(self._host_attachments(host)), 0)

    def test_save_invalid_png_rejected(self):
        """Non-base64 PNG payloads are rejected with zero attachment rows."""
        host = self._new_host("BadPng Host")
        result = self._save(
            "exc_full",
            "exc_full",
            res_model="res.partner",
            res_id=host.id,
            name="BadPng",
            scene=SCENE_V1,
            png="@@not-base64@@",
        )
        self.assertIn("error", result)
        self.assertEqual(len(self._host_attachments(host)), 0)

    def test_save_empty_elements_scene_only(self):
        """An element-less scene persists the scene file only (BR-EMPTY-1)."""
        host = self._new_host("Empty Host")
        result = self._save(
            "exc_full",
            "exc_full",
            res_model="res.partner",
            res_id=host.id,
            name="Blank",
            scene=EMPTY_ELEMENTS_SCENE,
            png=None,
        )
        self.assertNotIn("error", result)
        self.assertTrue(result.get("ok"))
        self.assertIsNone(result.get("png_id"))
        attachments = self._host_attachments(host)
        self.assertEqual(len(attachments), 1)
        self.assertEqual(attachments.name, "Blank.excalidraw")

    def test_save_missing_params_refused(self):
        """Missing or unresolvable params are refused with zero writes."""
        host = self._new_host("Missing Host")
        full = {
            "res_model": "res.partner",
            "res_id": host.id,
            "name": "X",
            "scene": SCENE_V1,
            "png": None,
        }
        variants = []
        for key in ("res_model", "res_id", "scene"):
            variants.append({k: v for k, v in full.items() if k != key})
        variants.append({**full, "res_id": 0})
        variants.append({**full, "res_id": "not-a-number"})
        for params in variants:
            result = self._save("exc_full", "exc_full", **params)
            self.assertIn("error", result, params)
        self.assertEqual(len(self._host_attachments(host)), 0)

    def test_save_empty_name_fallback(self):
        """An empty name falls back to a server timestamp name (FR-NAME-1)."""
        host = self._new_host("Fallback Host")
        result = self._save(
            "exc_full",
            "exc_full",
            res_model="res.partner",
            res_id=host.id,
            name="",
            scene=SCENE_V1,
            png=PNG_A_B64,
        )
        self.assertNotIn("error", result)
        attachments = self._host_attachments(host)
        self.assertEqual(len(attachments), 2)
        scene = attachments.filtered(lambda a: a.name.endswith(".excalidraw"))
        png = attachments.filtered(lambda a: a.name.endswith(".png"))
        self.assertEqual(len(scene), 1)
        self.assertEqual(len(png), 1)
        basename = scene.name[: -len(".excalidraw")]
        self.assertRegex(basename, r"^Drawing \d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")
        self.assertEqual(png.name, f"{basename}.png")

    # ------------------------------------------------------------------
    # FR-ACCESS-1 (server-side enforcement)
    # ------------------------------------------------------------------

    def test_save_group_denied(self):
        """A non-group user who can write the host is refused."""
        host = self._new_host("Group Host")
        result = self._save(
            "exc_outsider",
            "exc_outsider",
            res_model="res.partner",
            res_id=host.id,
            name="Nope",
            scene=SCENE_V1,
            png=None,
        )
        self.assertIn("error", result)
        self.assertEqual(len(self._host_attachments(host)), 0)

    def test_save_no_write_denied(self):
        """A group user without model write access is refused."""
        if self.deny_task is None:
            self.skipTest("project.task not available")
            return
        result = self._save(
            "exc_plain",
            "exc_plain",
            res_model="project.task",
            res_id=self.deny_task.id,
            name="Denied",
            scene=SCENE_V1,
            png=None,
        )
        self.assertIn("error", result)
        self.assertEqual(len(self._host_attachments(self.deny_task)), 0)

    def test_save_unknown_or_nonchatter_model_generic(self):
        """Unknown and chatter-less models share one generic error message."""
        host = self._new_host("Generic Host")
        unknown = self._save(
            "exc_full",
            "exc_full",
            res_model="no.such.model",
            res_id=1,
            name="X",
            scene=SCENE_V1,
            png=None,
        )
        nonchatter = self._save(
            "exc_full",
            "exc_full",
            res_model="res.company",
            res_id=1,
            name="X",
            scene=SCENE_V1,
            png=None,
        )
        self.assertIn("error", unknown)
        self.assertIn("error", nonchatter)
        self.assertEqual(unknown["error"], nonchatter["error"])
        self.assertEqual(len(self._host_attachments(host)), 0)

    # ------------------------------------------------------------------
    # IR-ROUTE-2 (scene fetch)
    # ------------------------------------------------------------------

    def test_scene_fetch_by_id(self):
        """A group member fetches the exact stored scene text."""
        host = self._new_host("Fetch Host")
        saved = self._save(
            "exc_full",
            "exc_full",
            res_model="res.partner",
            res_id=host.id,
            name="Fetch",
            scene=SCENE_V1,
            png=None,
        )
        fetched = self._scene("exc_full", "exc_full", saved["scene_id"])
        self.assertNotIn("error", fetched)
        self.assertEqual(fetched.get("scene"), SCENE_V1)
        # A non-.excalidraw attachment id is refused.
        wrong = self._scene("exc_full", "exc_full", self.png_only_attachment.id)
        self.assertIn("error", wrong)

    def test_scene_fetch_denied(self):
        """Outsiders and read-denied users get an error, never a scene."""
        host = self._new_host("FetchDenied Host")
        saved = self._save(
            "exc_full",
            "exc_full",
            res_model="res.partner",
            res_id=host.id,
            name="Denied Fetch",
            scene=SCENE_V1,
            png=None,
        )
        outsider = self._scene("exc_outsider", "exc_outsider", saved["scene_id"])
        self.assertIn("error", outsider)
        self.assertNotIn("scene", outsider)
        if self.read_denied_attachment_id:
            denied = self._scene(
                "exc_plain", "exc_plain", self.read_denied_attachment_id
            )
            self.assertIn("error", denied)
            self.assertNotIn("scene", denied)

    # ------------------------------------------------------------------
    # FR-REMOVE-1 (intentionally RED until the Slice 3 removal lands)
    # ------------------------------------------------------------------

    def test_removal_app_gone_groups_kept(self):
        """The standalone app is gone while groups and privilege survive."""
        self.assertNotIn("excalidraw.drawing", self.env)
        menus = self.env["ir.ui.menu"].search([("name", "ilike", "excalidraw")])
        self.assertFalse(menus)
        user_group = self.env.ref(
            "excalidraw_for_odoo.group_excalidraw_user", raise_if_not_found=False
        )
        manager_group = self.env.ref(
            "excalidraw_for_odoo.group_excalidraw_manager", raise_if_not_found=False
        )
        privilege = self.env.ref(
            "excalidraw_for_odoo.excalidraw_for_odoo_privilege",
            raise_if_not_found=False,
        )
        self.assertTrue(user_group)
        self.assertTrue(manager_group)
        self.assertTrue(privilege)


@tagged("post_install", "-at_install")
class TestExcalidrawAttachmentVisibility(TransactionCase):
    """Pure-ORM visibility of the stored pair (FR-ACCESS-1 reader path)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.reader = cls.env["res.users"].create(
            {
                "name": "Excalidraw Reader",
                "login": "exc_reader",
                "email": "exc_reader@example.com",
                "password": "exc_reader",
                "group_ids": [Command.link(cls.env.ref("base.group_user").id)],
            }
        )
        cls.host = cls.env["res.partner"].create({"name": "Reader Host"})

    def test_reader_sees_png(self):
        """A read-only user reads the pair through the ORM (A4, FR-ACCESS-1)."""
        scene = self.env["ir.attachment"].create(
            {
                "name": "Reader.excalidraw",
                "mimetype": "application/json",
                "raw": SCENE_V1.encode("utf-8"),
                "res_model": "res.partner",
                "res_id": self.host.id,
                "res_field": False,
                "public": False,
                "url": False,
            }
        )
        png = self.env["ir.attachment"].create(
            {
                "name": "Reader.png",
                "mimetype": "image/png",
                "raw": base64.b64decode(PNG_A_B64),
                "res_model": "res.partner",
                "res_id": self.host.id,
                "res_field": False,
                "public": False,
                "url": False,
            }
        )
        for att in (scene, png):
            read = att.with_user(self.reader).read(["name", "datas"])
            self.assertEqual(read[0]["name"], att.name)
            self.assertEqual(read[0]["datas"], att.datas)
            self.assertFalse(att.public)
