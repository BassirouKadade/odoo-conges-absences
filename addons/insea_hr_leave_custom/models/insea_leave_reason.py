from odoo import fields, models


class InseaLeaveReason(models.Model):
    """Motif d'une demande (ex : consultation médicale, démarche administrative)."""

    _name = 'insea.leave.reason'
    _description = "Motif d'absence"
    _order = 'leave_type_id, sequence, name'

    name = fields.Char(string='Motif', required=True, translate=True)
    sequence = fields.Integer(default=10)
    leave_type_id = fields.Many2one(
        'insea.leave.type', string='Type', required=True, ondelete='cascade',
    )
    requires_attachment = fields.Boolean(
        string='Justificatif obligatoire',
        help="Ex : une sortie pour consultation médicale exige un justificatif.",
    )
    active = fields.Boolean(default=True)
