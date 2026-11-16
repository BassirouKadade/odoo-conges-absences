from odoo import fields, models


class InseaLeaveType(models.Model):
    """Type de demande : autorisation de sortie, congé payé, congé exceptionnel, maladie."""

    _name = 'insea.leave.type'
    _description = "Type d'absence / de congé"
    _order = 'sequence, name'

    name = fields.Char(string='Nom', required=True, translate=True)
    code = fields.Char(string='Code', required=True)
    sequence = fields.Integer(default=10)
    category = fields.Selection(
        selection=[
            ('exit_permission', 'Autorisation de sortie'),
            ('paid', 'Congé payé annuel'),
            ('exceptional', 'Congé exceptionnel (événement familial)'),
            ('sick', 'Congé maladie'),
        ],
        string='Catégorie',
        required=True,
    )
    affects_balance = fields.Boolean(
        string='Déduit du solde',
        help="Si coché, la durée approuvée est déduite du solde de congés payés.",
    )
    requires_attachment = fields.Boolean(
        string='Justificatif obligatoire',
        help="Bloque la validation finale tant qu'aucun fichier n'est joint.",
    )
    requires_hr_validation = fields.Boolean(
        string='Validation RH requise',
        default=True,
        help="Si décoché, l'approbation du manager N+1 est finale.",
    )
    max_days = fields.Float(
        string='Durée maximale (jours)',
        help="0 = pas de limite. Ex : mariage = 4, naissance = 3, décès = 3.",
    )
    reason_ids = fields.One2many('insea.leave.reason', 'leave_type_id', string='Motifs')
    active = fields.Boolean(default=True)

    _code_unique = models.Constraint(
        'UNIQUE (code)',
        "Le code du type de congé doit être unique.",
    )
    _max_days_positive = models.Constraint(
        'CHECK (max_days >= 0)',
        "La durée maximale ne peut pas être négative.",
    )
