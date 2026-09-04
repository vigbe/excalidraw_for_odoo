# Local dev environments do not ship the odoo package; the runtime imports
# are resolved inside the odoo:19 container. Same suppression pattern as the
# sibling `drawing` module manifest.
# pyright: reportMissingImports=false
from odoo import Command
from odoo.exceptions import AccessError, ValidationError
from odoo.tests import TransactionCase, tagged

VALID_SCENE = '{"type":"excalidraw","version":2,"source":"excalidraw_for_odoo","elements":[{"id":"e1","type":"rectangle"}],"appState":{"viewBackgroundColor":"#ffffff"},"files":{}}'
INVALID_JSON_SCENE = "this is not json"
MISSING_ELEMENTS_SCENE = '{"type":"excalidraw","version":2}'


@tagged("post_install", "-at_install")
class TestExcalidrawDrawing(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user_group = cls.env.ref("excalidraw_for_odoo.group_excalidraw_user")
        cls.manager_group = cls.env.ref("excalidraw_for_odoo.group_excalidraw_manager")
        cls.drawing_user = cls.env["res.users"].create(
            {
                "name": "Excalidraw User",
                "login": "excalidraw_user",
                "email": "excalidraw_user@example.com",
                # Odoo 19: res.users uses group_ids (groups_id was removed)
                "group_ids": [Command.link(cls.user_group.id)],
            }
        )
        cls.drawing_manager = cls.env["res.users"].create(
            {
                "name": "Excalidraw Manager",
                "login": "excalidraw_manager",
                "email": "excalidraw_manager@example.com",
                "group_ids": [Command.link(cls.manager_group.id)],
            }
        )

    def test_create_with_valid_scene(self):
        drawing = self.env["excalidraw.drawing"].create(
            {"name": "Flow", "scene_data": VALID_SCENE}
        )
        self.assertEqual(drawing.element_count, 1)
        self.assertTrue(drawing.active)

    def test_create_defaults_name(self):
        drawing = self.env["excalidraw.drawing"].create({})
        self.assertEqual(drawing.name, "Untitled drawing")

    def test_invalid_scene_json(self):
        with self.assertRaises(ValidationError):
            self.env["excalidraw.drawing"].create(
                {"name": "Bad", "scene_data": INVALID_JSON_SCENE}
            )

    def test_scene_without_elements(self):
        with self.assertRaises(ValidationError):
            self.env["excalidraw.drawing"].create(
                {"name": "Bad", "scene_data": MISSING_ELEMENTS_SCENE}
            )

    def test_archive(self):
        drawing = self.env["excalidraw.drawing"].create({"name": "To archive"})
        drawing.action_archive()
        self.assertFalse(drawing.active)
        self.assertFalse(
            self.env["excalidraw.drawing"].search([("name", "=", "To archive")])
        )
        drawing.action_unarchive()
        self.assertTrue(drawing.active)

    def test_user_can_edit_but_not_delete(self):
        drawing = self.env["excalidraw.drawing"].create(
            {"name": "Shared", "scene_data": VALID_SCENE}
        )
        drawing = drawing.with_user(self.drawing_user)
        drawing.write({"name": "Renamed"})
        self.assertEqual(drawing.name, "Renamed")
        with self.assertRaises(AccessError):
            drawing.unlink()

    def test_manager_can_delete(self):
        drawing = self.env["excalidraw.drawing"].create({"name": "Doomed"})
        drawing.with_user(self.drawing_manager).unlink()
        self.assertFalse(
            self.env["excalidraw.drawing"].search([("name", "=", "Doomed")])
        )

    def test_chatter_message(self):
        drawing = self.env["excalidraw.drawing"].create({"name": "With chatter"})
        drawing.message_post(body="First comment")
        # Note: create() also logs a tracking/system message in the chatter,
        # and bodies are stored as markup (<p>First comment</p>).
        posted = drawing.message_ids.filtered(
            lambda m: "First comment" in (m.body or "")
        )
        self.assertEqual(len(posted), 1)
