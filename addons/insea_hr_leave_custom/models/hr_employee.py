import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

MONTHLY_ACCRUAL_DAYS = 1.5      # 1,5 jour de congé payé acquis par mois de travail


class HrEmployee(models.Model):
    """Extension de hr.employee : solde de congés payés."""

    _inherit = 'hr.employee'

    leave_request_ids = fields.One2many(
        'insea.leave.request', 'employee_id', string="Demandes d'absence",
    )
    accrual_ids = fields.One2many(
        'insea.leave.accrual', 'employee_id', string='Acquisitions de congés',
    )
    leave_allocated = fields.Float(
        string='Congés acquis (j)', compute='_compute_leave_balance', compute_sudo=True,
    )
    leave_taken = fields.Float(
        string='Congés pris (j)', compute='_compute_leave_balance', compute_sudo=True,
    )
    leave_balance = fields.Float(
        string='Solde de congés (j)', compute='_compute_leave_balance', compute_sudo=True,
    )

    @api.depends(
        'accrual_ids.days',
        'leave_request_ids.state',
        'leave_request_ids.duration_days',
        'leave_request_ids.leave_type_id.affects_balance',
    )
    def _compute_leave_balance(self):
        for employee in self:
            allocated = sum(employee.accrual_ids.mapped('days'))
            taken = sum(
                employee.leave_request_ids.filtered(
                    lambda r: r.state == 'approved' and r.leave_type_id.affects_balance
                ).mapped('duration_days')
            )
            employee.leave_allocated = allocated
            employee.leave_taken = taken
            employee.leave_balance = allocated - taken

    @api.model
    def _cron_monthly_accrual(self, date=None):
        """Tâche planifiée : crédite 1,5 jour à chaque employé actif, une fois par mois.

        La ligne est datée du 1er du mois : relancer la tâche dans le même mois
        ne crédite jamais deux fois (contrôle applicatif + index unique en base).

        :param date: date de référence (aujourd'hui par défaut), utile pour les tests
        :return: les lignes d'acquisition créées
        """
        reference = date or fields.Date.context_today(self)
        month_start = reference.replace(day=1)
        Accrual = self.env['insea.leave.accrual'].sudo()
        employees = self.sudo().search([('active', '=', True)])
        already_credited = Accrual.search([
            ('type', '=', 'monthly'),
            ('date', '=', month_start),
            ('employee_id', 'in', employees.ids),
        ]).employee_id
        to_credit = employees - already_credited
        accruals = Accrual.create([{
            'employee_id': employee.id,
            'date': month_start,
            'days': MONTHLY_ACCRUAL_DAYS,
            'type': 'monthly',
            'note': "Acquisition mensuelle %s" % month_start.strftime('%m/%Y'),
        } for employee in to_credit])
        _logger.info(
            "Acquisition mensuelle des congés (%s) : %d employé(s) crédité(s), %d déjà à jour.",
            month_start.strftime('%m/%Y'), len(accruals), len(already_credited),
        )
        return accruals
