# Local dev environments do not ship the odoo package; the runtime imports
# are resolved inside the odoo:19 container. Same suppression pattern as the
# sibling `drawing` module manifest.
# pyright: reportMissingImports=false
import json

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class ExcalidrawDrawing(models.Model):
    """A persisted Excalidraw scene.

    The scene itself is stored as the Excalidraw scene JSON document
    (``{"type": "excalidraw", "version": 2, "elements": [...], ...}``) so it
    stays fully editable by the embedded editor and importable/exportable as
    a standard ``.excalidraw`` file. A PNG preview is generated client-side
    (browser canvas) and kept as an attachment for list thumbnails.
    """

    _name = "excalidraw.drawing"
    _description = "Excalidraw Drawing"
    _order = "write_date desc"

    name = fields.Char(string="Name", required=True)
    scene_data = fields.Text(
        string="Scene",
        help="Excalidraw scene JSON document (elements + editor state).",
        tracking=False,
    )
    preview_image = fields.Image(
        string="Preview",
        max_width=512,
        max_height=512,
        verify_resolution=False,
    )
    active = fields.Boolean(string="Active", default=True)
    element_count = fields.Integer(
        string="Elements",
        compute="_compute_element_count",
    )
    # Optional link to a business record (kept generic for future features).
    res_model = fields.Char(string="Linked Document Model", index=True)
    res_id = fields.Integer(string="Linked Document ID", index=True)

    @api.depends("scene_data")
    def _compute_element_count(self):
        for drawing in self:
            count = 0
            scene = drawing._parse_scene(raise_error=False)
            if scene:
                count = len(scene.get("elements") or [])
            drawing.element_count = count

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get("name"):
                vals["name"] = _("Untitled drawing")
        return super().create(vals_list)

    @api.constrains("scene_data")
    def _check_scene_data(self):
        for drawing in self:
            if drawing.scene_data:
                drawing._parse_scene(raise_error=True)

    def _parse_scene(self, raise_error=False):
        """Parse and validate ``scene_data`` as an Excalidraw scene document.

        :param bool raise_error: raise ``ValidationError`` on invalid data
        :return: parsed scene dict, or ``None``/``False`` when absent
        """
        self.ensure_one()
        if not self.scene_data:
            return None
        try:
            scene = json.loads(self.scene_data)
        except (TypeError, ValueError):
            scene = None
        if not isinstance(scene, dict) or "elements" not in scene:
            scene = None
        if scene is None:
            if raise_error:
                raise ValidationError(
                    _(
                        "The scene is not a valid Excalidraw document: "
                        "it must be a JSON object with an 'elements' key."
                    )
                )
            return False
        return scene
