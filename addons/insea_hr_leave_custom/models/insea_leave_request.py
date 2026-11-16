from datetime import datetime, time, timedelta

from dateutil.relativedelta import relativedelta
from markupsafe import Markup

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import format_date
from odoo.tools.float_utils import float_compare

GROUP_HR = 'insea_hr_leave_custom.group_leave_hr'

# ----------------------------------------------------------------------
# Règles de gestion (section 2 du cahier des charges)
# ----------------------------------------------------------------------
EXIT_MAX_HOURS = 4.0            # une autorisation de sortie : ½ journée max
EXIT_MONTHLY_MAX_COUNT = 3      # au plus 3 autorisations par mois calendaire…
EXIT_MONTHLY_MAX_HOURS = 8.0    # … ou 8 heures cumulées
NOTICE_MIN_DAYS = 7             # délai de prévenance (jours calendaires)
NOTICE_THRESHOLD_DAYS = 3       # … pour les congés payés de plus de 3 jours

ACTIVE_STATES = ('submitted', 'manager_approved', 'approved')
PENDING_STATES = ('submitted', 'manager_approved')
TODO_ACTIVITY = 'mail.mail_activity_data_todo'


class InseaLeaveRequest(models.Model):
    """Demande d'autorisation de sortie ou de congé.

    Cycle de vie (champ state) :
        draft → submitted → (manager_approved →) approved
                    └──────────────┴──→ refused → draft
    """

    _name = 'insea.leave.request'
    _description = "Demande d'absence / de congé"
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date_from desc, id desc'

    # ------------------------------------------------------------------
    # Identification
    # ------------------------------------------------------------------
    name = fields.Char(
        string='Référence', required=True, readonly=True, copy=False, default='/',
    )
    employee_id = fields.Many2one(
        'hr.employee', string='Employé', required=True, index=True, tracking=True,
        default=lambda self: self.env.user.employee_id,
    )
    user_id = fields.Many2one(
        related='employee_id.user_id', string='Utilisateur', store=True, index=True,
    )
    manager_id = fields.Many2one(
        related='employee_id.parent_id', string='Manager N+1', store=True, index=True,
    )
    department_id = fields.Many2one(
        related='employee_id.department_id', string='Département', store=True,
    )
    company_id = fields.Many2one(
        'res.company', string='Société', required=True, default=lambda self: self.env.company,
    )

    # ------------------------------------------------------------------
    # Type et motif
    # ------------------------------------------------------------------
    leave_type_id = fields.Many2one(
        'insea.leave.type', string='Type', required=True, tracking=True,
    )
    category = fields.Selection(related='leave_type_id.category', store=True)
    reason_id = fields.Many2one(
        'insea.leave.reason', string='Motif',
        domain="[('leave_type_id', '=', leave_type_id)]",
    )
    description = fields.Text(string='Commentaire')

    # ------------------------------------------------------------------
    # Période
    # ------------------------------------------------------------------
    date_from = fields.Datetime(string='Début', required=True, tracking=True)
    date_to = fields.Datetime(string='Fin', required=True, tracking=True)
    duration_hours = fields.Float(
        string='Durée (heures)', compute='_compute_duration', store=True,
    )
    duration_days = fields.Float(
        string='Durée (jours ouvrés)', compute='_compute_duration', store=True,
    )

    # ------------------------------------------------------------------
    # Justificatif et workflow
    # ------------------------------------------------------------------
    attachment_ids = fields.Many2many(
        'ir.attachment', 'insea_leave_request_attachment_rel', 'request_id', 'attachment_id',
        string='Justificatifs',
    )
    attachment_required = fields.Boolean(
        string='Justificatif requis', compute='_compute_attachment_required',
    )
    state = fields.Selection(
        selection=[
            ('draft', 'Brouillon'),
            ('submitted', 'Soumis'),
            ('manager_approved', 'Validé manager'),
            ('approved', 'Approuvé'),
            ('refused', 'Refusé'),
        ],
        string='État', required=True, default='draft', copy=False, tracking=True, index=True,
    )
    submit_date = fields.Datetime(string='Soumis le', readonly=True, copy=False)
    manager_validator_id = fields.Many2one(
        'res.users', string='Validé par (manager)', readonly=True, copy=False,
    )
    hr_validator_id = fields.Many2one(
        'res.users', string='Validé par (RH)', readonly=True, copy=False,
    )
    refuse_reason = fields.Text(string='Motif de refus', readonly=True, copy=False, tracking=True)

    # ------------------------------------------------------------------
    # Informations d'affichage (solde, droits de l'utilisateur courant)
    # ------------------------------------------------------------------
    employee_leave_balance = fields.Float(
        related='employee_id.leave_balance', string='Solde disponible (j)',
    )
    is_owner = fields.Boolean(compute='_compute_user_rights')
    is_hr_user = fields.Boolean(compute='_compute_user_rights')
    can_manager_approve = fields.Boolean(compute='_compute_user_rights')
    can_hr_approve = fields.Boolean(compute='_compute_user_rights')
    can_refuse = fields.Boolean(compute='_compute_user_rights')

    # ------------------------------------------------------------------
    # Contraintes SQL
    # ------------------------------------------------------------------
    _date_check = models.Constraint(
        'CHECK (date_to > date_from)',
        "La date de fin doit être postérieure à la date de début.",
    )

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', '/') == '/':
                vals['name'] = self.env['ir.sequence'].next_by_code('insea.leave.request') or '/'
        requests = super().create(vals_list)
        requests._link_attachments()
        return requests

    def write(self, vals):
        result = super().write(vals)
        if 'attachment_ids' in vals:
            self._link_attachments()
        return result

    def _link_attachments(self):
        """Rattache les justificatifs à la demande (res_model / res_id).

        Un fichier téléversé reste sinon privé à son auteur : le manager et le RH
        ne pourraient pas le consulter, ni donc valider la demande.
        Les droits d'accès au fichier suivent alors ceux de la demande.
        """
        for request in self:
            orphans = request.sudo().attachment_ids.filtered(
                lambda a: a.res_model != self._name or a.res_id != request.id
            )
            if orphans:
                orphans.write({'res_model': self._name, 'res_id': request.id})

    def unlink(self):
        if any(request.state != 'draft' for request in self):
            raise UserError(_("Seules les demandes en brouillon peuvent être supprimées."))
        return super().unlink()

    # ------------------------------------------------------------------
    # Champs calculés
    # ------------------------------------------------------------------
    @api.depends('date_from', 'date_to', 'leave_type_id.category')
    def _compute_duration(self):
        """Une seule unité par catégorie, pour des totaux cohérents :

        * autorisation de sortie : durée en heures (jours = 0) ;
        * congé : nombre de jours ouvrés, du lundi au vendredi, bornes incluses (heures = 0).
        """
        for request in self:
            request.duration_hours = 0.0
            request.duration_days = 0.0
            if not request.date_from or not request.date_to or request.date_to <= request.date_from:
                continue
            if request.category == 'exit_permission':
                delta = request.date_to - request.date_from
                request.duration_hours = round(delta.total_seconds() / 3600.0, 2)
                continue
            day = request.date_from.date()
            last_day = request.date_to.date()
            working_days = 0
            while day <= last_day:
                if day.weekday() < 5:
                    working_days += 1
                day += timedelta(days=1)
            request.duration_days = working_days

    @api.depends('name', 'employee_id.name', 'leave_type_id.name')
    def _compute_display_name(self):
        for request in self:
            reference = request.name if request.name and request.name != '/' else _("Nouvelle demande")
            if request.employee_id and request.leave_type_id:
                request.display_name = "%s – %s (%s)" % (
                    reference, request.employee_id.name, request.leave_type_id.name)
            else:
                request.display_name = reference

    @api.depends_context('uid')
    @api.depends('state', 'user_id', 'manager_id.user_id')
    def _compute_user_rights(self):
        user = self.env.user
        is_hr = user.has_group(GROUP_HR)
        for request in self:
            is_manager = request.manager_id.user_id == user
            request.is_owner = request.user_id == user
            request.is_hr_user = is_hr
            request.can_manager_approve = request.state == 'submitted' and (is_manager or is_hr)
            request.can_hr_approve = request.state == 'manager_approved' and is_hr
            request.can_refuse = (
                (request.state == 'submitted' and (is_manager or is_hr))
                or (request.state == 'manager_approved' and is_hr)
            )

    @api.depends('leave_type_id.requires_attachment', 'reason_id.requires_attachment')
    def _compute_attachment_required(self):
        for request in self:
            request.attachment_required = (
                request.leave_type_id.requires_attachment or request.reason_id.requires_attachment
            )

    # ------------------------------------------------------------------
    # Onchange (confort de saisie)
    # ------------------------------------------------------------------
    @api.onchange('leave_type_id')
    def _onchange_leave_type_id(self):
        if self.reason_id and self.reason_id.leave_type_id != self.leave_type_id:
            self.reason_id = False

    # ------------------------------------------------------------------
    # Contraintes de cohérence (vérifiées à chaque enregistrement)
    # ------------------------------------------------------------------
    @api.constrains('reason_id', 'leave_type_id')
    def _check_reason_matches_type(self):
        for request in self:
            if request.reason_id and request.reason_id.leave_type_id != request.leave_type_id:
                raise ValidationError(_("Le motif choisi ne correspond pas au type de demande."))

    @api.constrains('date_from', 'date_to', 'leave_type_id')
    def _check_exit_duration(self):
        """Autorisation de sortie : une seule journée, 4 heures au maximum."""
        for request in self.filtered(lambda r: r.category == 'exit_permission'):
            if request.date_from.date() != request.date_to.date():
                raise ValidationError(_(
                    "Une autorisation de sortie doit commencer et se terminer le même jour."
                ))
            if float_compare(request.duration_hours, EXIT_MAX_HOURS, precision_digits=2) > 0:
                raise ValidationError(_(
                    "Une autorisation de sortie ne peut pas dépasser %(max)s heures "
                    "(demandé : %(hours)s h).",
                    max=int(EXIT_MAX_HOURS), hours=request.duration_hours,
                ))

    @api.constrains('date_from', 'date_to', 'leave_type_id')
    def _check_max_days(self):
        """Congés exceptionnels : durée maximale par événement (mariage 4 j, naissance 3 j…)."""
        for request in self:
            max_days = request.leave_type_id.max_days
            if max_days and float_compare(request.duration_days, max_days, precision_digits=2) > 0:
                raise ValidationError(_(
                    "« %(type)s » est limité à %(max)s jour(s) ouvré(s) (demandé : %(days)s).",
                    type=request.leave_type_id.name, max=max_days, days=request.duration_days,
                ))

    @api.constrains('date_from', 'date_to', 'employee_id', 'state')
    def _check_overlap(self):
        """Interdit tout chevauchement avec une demande soumise, en validation ou approuvée."""
        for request in self.filtered(lambda r: r.state != 'refused'):
            overlapping = self.sudo().search([
                ('id', '!=', request.id),
                ('employee_id', '=', request.employee_id.id),
                ('state', 'in', ACTIVE_STATES),
                ('date_from', '<', request.date_to),
                ('date_to', '>', request.date_from),
            ], limit=1)
            if overlapping:
                raise ValidationError(_(
                    "Cette période chevauche la demande %(other)s (%(state)s) du %(start)s au %(end)s.",
                    other=overlapping.name,
                    state=dict(self._fields['state'].selection)[overlapping.state],
                    start=format_date(self.env, overlapping.date_from),
                    end=format_date(self.env, overlapping.date_to),
                ))

    # ------------------------------------------------------------------
    # Contraintes vérifiées à la soumission (passage à l'état « Soumis »)
    # ------------------------------------------------------------------
    @api.constrains('state')
    def _check_monthly_exit_limit(self):
        """Autorisations de sortie : 3 par mois calendaire ou 8 heures cumulées au maximum."""
        for request in self.filtered(lambda r: r.state == 'submitted' and r.category == 'exit_permission'):
            month_start = datetime.combine(request.date_from.date().replace(day=1), time.min)
            month_end = month_start + relativedelta(months=1)
            others = self.sudo().search([
                ('id', '!=', request.id),
                ('employee_id', '=', request.employee_id.id),
                ('category', '=', 'exit_permission'),
                ('state', 'in', ACTIVE_STATES),
                ('date_from', '>=', month_start),
                ('date_from', '<', month_end),
            ])
            count = len(others) + 1
            hours = sum(others.mapped('duration_hours')) + request.duration_hours
            if count > EXIT_MONTHLY_MAX_COUNT:
                raise ValidationError(_(
                    "Plafond mensuel atteint : %(max)s autorisations de sortie par mois au maximum "
                    "(déjà %(done)s ce mois-ci).",
                    max=EXIT_MONTHLY_MAX_COUNT, done=len(others),
                ))
            if float_compare(hours, EXIT_MONTHLY_MAX_HOURS, precision_digits=2) > 0:
                raise ValidationError(_(
                    "Plafond mensuel atteint : %(max)s heures de sortie cumulées par mois au maximum "
                    "(déjà %(done)s h, demandé %(asked)s h).",
                    max=int(EXIT_MONTHLY_MAX_HOURS),
                    done=round(hours - request.duration_hours, 2),
                    asked=request.duration_hours,
                ))

    @api.constrains('state')
    def _check_balance(self):
        """Congé payé : le solde disponible doit couvrir la durée demandée.

        Le solde disponible tient compte des autres congés payés déjà en attente
        de validation, afin de ne pas « réserver » deux fois les mêmes jours.
        """
        for request in self.filtered(lambda r: r.state in PENDING_STATES and r.leave_type_id.affects_balance):
            pending = self.sudo().search([
                ('id', '!=', request.id),
                ('employee_id', '=', request.employee_id.id),
                ('leave_type_id.affects_balance', '=', True),
                ('state', 'in', PENDING_STATES),
            ])
            available = request.employee_id.sudo().leave_balance - sum(pending.mapped('duration_days'))
            if float_compare(available, request.duration_days, precision_digits=2) < 0:
                raise ValidationError(_(
                    "Solde de congés insuffisant : %(available)s jour(s) disponible(s), "
                    "%(asked)s jour(s) demandé(s).",
                    available=round(available, 2), asked=request.duration_days,
                ))

    @api.constrains('state')
    def _check_notice_period(self):
        """Congé payé de plus de 3 jours : soumis au moins 7 jours calendaires à l'avance."""
        today = fields.Date.context_today(self)
        for request in self.filtered(
            lambda r: r.state == 'submitted' and r.category == 'paid'
            and r.duration_days > NOTICE_THRESHOLD_DAYS
        ):
            notice = (request.date_from.date() - today).days
            if notice < NOTICE_MIN_DAYS:
                raise ValidationError(_(
                    "Un congé payé de plus de %(threshold)s jours doit être demandé au moins "
                    "%(min)s jours à l'avance (début dans %(notice)s jour(s)).",
                    threshold=NOTICE_THRESHOLD_DAYS, min=NOTICE_MIN_DAYS, notice=max(notice, 0),
                ))

    # ------------------------------------------------------------------
    # Workflow
    # ------------------------------------------------------------------
    def _is_hr(self):
        return self.env.user.has_group(GROUP_HR)

    def _check_state(self, allowed_states):
        for request in self:
            if request.state not in allowed_states:
                raise UserError(_(
                    "Action impossible : la demande %(name)s est à l'état « %(state)s ».",
                    name=request.name,
                    state=dict(self._fields['state'].selection)[request.state],
                ))

    def _get_hr_users(self):
        """Responsables RH à solliciter pour la validation.

        Le compte administrateur technique n'est sollicité qu'en l'absence
        d'un véritable Responsable RH.
        """
        users = self.env.ref(GROUP_HR).sudo().user_ids.filtered(
            lambda u: not u.share and u.active and u != self.env.ref('base.user_root')
        )
        admin = self.env.ref('base.user_admin', raise_if_not_found=False)
        return users - admin if admin and users - admin else users

    def _notify_employee(self, body, subject):
        """Message dans le chatter, notifié à l'employé (boîte de réception / e-mail)."""
        for request in self:
            partner = request.user_id.partner_id
            request.message_post(
                body=body,
                subject=subject,
                partner_ids=partner.ids,
                subtype_xmlid='mail.mt_comment',
            )

    def action_submit(self):
        """Brouillon → Soumis (par l'employé lui-même ou un RH).

        Le passage à l'état « Soumis » déclenche les contraintes de soumission :
        plafond mensuel, solde, délai de prévenance, chevauchement.
        """
        self._check_state(['draft'])
        for request in self:
            if request.user_id != self.env.user and not self._is_hr():
                raise UserError(_("Vous ne pouvez soumettre que vos propres demandes."))
        self.write({'state': 'submitted', 'submit_date': fields.Datetime.now()})
        for request in self:
            approver = request.manager_id.user_id
            if approver:
                request.activity_schedule(
                    TODO_ACTIVITY, user_id=approver.id,
                    summary=_("Demande à approuver"),
                )
            else:
                for hr_user in request._get_hr_users():
                    request.activity_schedule(
                        TODO_ACTIVITY, user_id=hr_user.id,
                        summary=_("Demande à approuver (employé sans manager)"),
                    )
            request.message_post(body=_("Demande soumise pour validation."))

    def action_manager_approve(self):
        """Soumis → Approuvé (sortie) ou Validé manager (congé). Réservé au manager N+1."""
        self._check_state(['submitted'])
        for request in self:
            if request.manager_id.user_id != self.env.user and not self._is_hr():
                raise UserError(_("Seul le manager N+1 de l'employé peut approuver cette demande."))
            final = not request.leave_type_id.requires_hr_validation
            request.write({
                'state': 'approved' if final else 'manager_approved',
                'manager_validator_id': self.env.user.id,
            })
            request.activity_unlink([TODO_ACTIVITY], only_automated=False)
            if final:
                request._notify_employee(
                    Markup(_("Votre demande <b>%s</b> a été approuvée.")) % request.display_name,
                    subject=_("✅ Demande approuvée : %s", request.name),
                )
            else:
                for hr_user in request._get_hr_users():
                    request.activity_schedule(
                        TODO_ACTIVITY, user_id=hr_user.id,
                        summary=_("Validation RH requise"),
                    )
                request.message_post(body=_("Approuvée par le manager, en attente de la validation RH."))

    def action_hr_approve(self):
        """Validé manager → Approuvé. Réservé au Responsable RH.

        Vérifie le justificatif puis impute définitivement le solde (congé payé).
        """
        self._check_state(['manager_approved'])
        if not self._is_hr():
            raise UserError(_("Seul le Responsable RH peut effectuer la validation finale."))
        for request in self:
            if request.attachment_required and not request.sudo().attachment_ids:
                raise UserError(_(
                    "La demande %s requiert un justificatif avant la validation finale.",
                    request.name,
                ))
        self.write({'state': 'approved', 'hr_validator_id': self.env.user.id})
        for request in self:
            request.activity_unlink([TODO_ACTIVITY], only_automated=False)
            message = Markup(_("Votre demande <b>%s</b> a été validée par les Ressources Humaines.")) % request.display_name
            if request.leave_type_id.affects_balance:
                message += Markup("<br/>") + _(
                    "%(days)s jour(s) déduit(s) de votre solde (nouveau solde : %(balance)s j).",
                    days=request.duration_days, balance=request.employee_id.sudo().leave_balance,
                )
            request._notify_employee(message, subject=_("✅ Demande approuvée : %s", request.name))

    def action_refuse(self):
        """Ouvre l'assistant de refus (motif obligatoire)."""
        self.ensure_one()
        self._check_state(['submitted', 'manager_approved'])
        return {
            'type': 'ir.actions.act_window',
            'name': _('Refuser la demande'),
            'res_model': 'insea.leave.refuse.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_request_id': self.id},
        }

    def _do_refuse(self, reason):
        """Passage à l'état Refusé (appelé par l'assistant après contrôle des droits)."""
        self.write({'state': 'refused', 'refuse_reason': reason})
        for request in self:
            request.activity_unlink([TODO_ACTIVITY], only_automated=False)
            request._notify_employee(
                Markup(_("Votre demande <b>%(name)s</b> a été refusée.<br/>Motif : %(reason)s"))
                % {'name': request.display_name, 'reason': reason},
                subject=_("❌ Demande refusée : %s", request.name),
            )

    def action_reset_draft(self):
        """Refusé → Brouillon, pour corriger et resoumettre."""
        self._check_state(['refused'])
        for request in self:
            if request.user_id != self.env.user and not self._is_hr():
                raise UserError(_("Seul l'auteur de la demande peut la remettre en brouillon."))
        self.write({
            'state': 'draft',
            'refuse_reason': False,
            'manager_validator_id': False,
            'hr_validator_id': False,
            'submit_date': False,
        })
