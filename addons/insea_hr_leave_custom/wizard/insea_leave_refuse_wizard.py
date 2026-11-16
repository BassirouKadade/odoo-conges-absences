from odoo import _, fields, models
from odoo.exceptions import UserError


class InseaLeaveRefuseWizard(models.TransientModel):
    """Assistant de refus : impose la saisie d'un motif."""

    _name = 'insea.leave.refuse.wizard'
    _description = "Assistant de refus d'une demande"

    request_id = fields.Many2one('insea.leave.request', string='Demande', required=True)
    reason = fields.Text(string='Motif du refus', required=True)

    def action_confirm_refuse(self):
        self.ensure_one()
        request = self.request_id
        request._check_state(['submitted', 'manager_approved'])
        if not self.reason or not self.reason.strip():
            raise UserError(_("Le motif du refus est obligatoire."))
        is_manager = request.manager_id.user_id == self.env.user
        if request.state == 'submitted' and not (is_manager or request._is_hr()):
            raise UserError(_("Seul le manager N+1 ou le RH peut refuser cette demande."))
        if request.state == 'manager_approved' and not request._is_hr():
            raise UserError(_("Seul le Responsable RH peut refuser à ce stade."))
        request._do_refuse(self.reason.strip())
        return {'type': 'ir.actions.act_window_close'}
