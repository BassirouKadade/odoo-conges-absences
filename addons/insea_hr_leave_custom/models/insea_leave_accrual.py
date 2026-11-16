from odoo import fields, models


class InseaLeaveAccrual(models.Model):
    """Ligne d'acquisition du solde de congés payés.

    Une ligne « monthly » est créée chaque mois par la tâche planifiée (1,5 jour) ;
    le Responsable RH peut ajouter des lignes « manual_adjustment » (positives ou négatives).
    """

    _name = 'insea.leave.accrual'
    _description = "Acquisition de congés payés"
    _order = 'date desc, id desc'

    employee_id = fields.Many2one(
        'hr.employee', string='Employé', required=True, ondelete='cascade', index=True,
    )
    date = fields.Date(string='Date', required=True, default=fields.Date.context_today)
    days = fields.Float(string='Jours', required=True, default=1.5)
    type = fields.Selection(
        selection=[
            ('monthly', 'Acquisition mensuelle'),
            ('manual_adjustment', 'Ajustement RH'),
        ],
        string='Type',
        required=True,
        default='manual_adjustment',
    )
    note = fields.Char(string='Commentaire')

    # Index unique partiel : empêche le cron de créditer deux fois le même mois
    _monthly_unique = models.UniqueIndex(
        "(employee_id, date) WHERE type = 'monthly'",
        "Une seule acquisition mensuelle par employé et par date.",
    )
