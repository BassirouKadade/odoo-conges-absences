"""Jeu de données de démonstration : la société fictive « Lambda ».

Toutes les demandes sont créées puis validées **à travers le vrai workflow**
(soumission, approbation manager, validation RH, refus avec motif) avec
l'utilisateur concerné : l'historique du chatter, les activités et les e-mails
(capturés par Mailpit) sont donc authentiques.

Les dates sont calculées par rapport au jour du chargement.

Chargement :
  * automatiquement sur une base créée avec les données de démo (clé 'demo' du manifest) ;
  * à la demande sur une base existante :
        env['insea.leave.demo'].load()       (odoo shell)
"""
import base64
import logging
from datetime import datetime, time, timedelta

from odoo import Command, api, fields, models

_logger = logging.getLogger(__name__)

DEMO_PASSWORD = 'lambda2026'
DOMAIN = 'lambda.ma'

# Petit PDF valide servant de justificatif fictif
_FAKE_PDF = (
    b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
    b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 595 842]/Contents 4 0 R"
    b"/Resources<</Font<</F1 5 0 R>>>>>>endobj\n"
    b"4 0 obj<</Length 60>>stream\nBT /F1 18 Tf 72 760 Td (Justificatif - document fictif) Tj ET\n"
    b"endstream endobj\n5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj\n"
    b"trailer<</Root 1 0 R>>\n%%EOF\n"
)

# (clé, nom, poste, département, groupe, manager)
PEOPLE = [
    ('rachid', 'Rachid El Amrani', 'Directeur Général', 'direction', 'manager', None),
    ('salma', 'Salma Bennani', 'Responsable RH', 'rh', 'hr', 'rachid'),
    ('youssef', 'Youssef Alaoui', 'Responsable Informatique', 'it', 'manager', 'rachid'),
    ('nadia', 'Nadia Chraibi', 'Responsable Financière', 'finance', 'manager', 'rachid'),
    ('karim', 'Karim Idrissi', 'Développeur', 'it', 'employee', 'youssef'),
    ('imane', 'Imane Tazi', 'Administratrice Systèmes', 'it', 'employee', 'youssef'),
    ('omar', 'Omar Fassi', 'Analyste Données', 'it', 'employee', 'youssef'),
    ('hajar', 'Hajar Berrada', 'Comptable', 'finance', 'employee', 'nadia'),
    ('mehdi', 'Mehdi Lahlou', 'Contrôleur de Gestion', 'finance', 'employee', 'nadia'),
]

DEPARTMENTS = {
    'direction': 'Direction Générale',
    'rh': 'Ressources Humaines',
    'it': 'Informatique',
    'finance': 'Finance',
}


class InseaLeaveDemo(models.AbstractModel):
    _name = 'insea.leave.demo'
    _description = "Chargeur des données de démonstration Congés & Absences"

    # ------------------------------------------------------------------
    # Outils
    # ------------------------------------------------------------------
    @staticmethod
    def _workday(day, step=1):
        """Décale `day` jusqu'au prochain jour ouvré dans la direction `step` (±1)."""
        while day.weekday() >= 5:
            day += timedelta(days=step)
        return day

    def _day(self, offset):
        """Jour ouvré à environ `offset` jours d'aujourd'hui."""
        today = fields.Date.context_today(self)
        return self._workday(today + timedelta(days=offset), 1 if offset >= 0 else -1)

    def _monday(self, offset):
        """Lundi de la semaine située à `offset` jours d'aujourd'hui."""
        day = fields.Date.context_today(self) + timedelta(days=offset)
        return day - timedelta(days=day.weekday())

    @staticmethod
    def _at(day, hour, minute=0):
        return datetime.combine(day, time(hour, minute))

    # ------------------------------------------------------------------
    # Organisation : départements, utilisateurs, employés, soldes
    # ------------------------------------------------------------------
    def _ensure_company(self):
        company = self.env.company
        if company.name in ('My Company', 'YourCompany', 'Mon entreprise', 'Mon Entreprise'):
            company.name = 'Lambda'
        if not company.email:
            company.email = 'rh@%s' % DOMAIN
        return company

    def _ensure_people(self):
        Department = self.env['hr.department'].sudo()
        departments = {}
        for key, name in DEPARTMENTS.items():
            departments[key] = Department.search([('name', '=', name)], limit=1) or Department.create({'name': name})

        groups = {g: self.env.ref('insea_hr_leave_custom.group_leave_%s' % g) for g in ('employee', 'manager', 'hr')}
        Users = self.env['res.users'].sudo().with_context(no_reset_password=True)
        Employee = self.env['hr.employee'].sudo()
        lang = 'fr_FR' if self.env['res.lang']._lang_get('fr_FR') else self.env.lang
        people = {}
        for key, name, job, dept, group, _manager in PEOPLE:
            first, last = name.split(' ', 1)
            login = '%s.%s@%s' % (first.lower(), last.lower().replace(' ', ''), DOMAIN)
            user = Users.search([('login', '=', login)], limit=1)
            if not user:
                user = Users.create({
                    'name': name,
                    'login': login,
                    'email': login,
                    'password': DEMO_PASSWORD,
                    'group_ids': [Command.link(groups[group].id)],
                    'notification_type': 'email',
                    'tz': 'Africa/Casablanca',
                    'lang': lang,
                })
            employee = Employee.search([('user_id', '=', user.id)], limit=1) or Employee.create({
                'name': name, 'user_id': user.id, 'work_email': login,
            })
            employee.write({'job_title': job, 'department_id': departments[dept].id})
            people[key] = employee
        for key, _n, _j, dept, _g, manager in PEOPLE:
            if manager:
                people[key].parent_id = people[manager]
        for key, dept_key in (('rachid', 'direction'), ('salma', 'rh'), ('youssef', 'it'), ('nadia', 'finance')):
            departments[dept_key].manager_id = people[key]
        # Le Directeur Général est rattaché au groupe « manager » ; ses demandes sont validées par le RH.
        return people

    def _ensure_accruals(self, people):
        """Historique d'acquisition : 1,5 j au 1er de chaque mois depuis janvier."""
        Accrual = self.env['insea.leave.accrual'].sudo()
        today = fields.Date.context_today(self)
        for employee in people.values():
            for month in range(1, today.month + 1):
                month_start = today.replace(month=month, day=1)
                if not Accrual.search_count([('employee_id', '=', employee.id), ('type', '=', 'monthly'),
                                             ('date', '=', month_start)]):
                    Accrual.create({
                        'employee_id': employee.id, 'date': month_start, 'days': 1.5, 'type': 'monthly',
                        'note': 'Acquisition mensuelle %s' % month_start.strftime('%m/%Y'),
                    })
        # Report de l'année précédente pour deux collaborateurs
        for key, days in (('karim', 4.0), ('hajar', 2.5)):
            if not Accrual.search_count([('employee_id', '=', people[key].id), ('type', '=', 'manual_adjustment')]):
                Accrual.create({
                    'employee_id': people[key].id, 'date': today.replace(month=1, day=1),
                    'days': days, 'type': 'manual_adjustment', 'note': "Report de l'année précédente",
                })

    # ------------------------------------------------------------------
    # Demandes, déroulées dans le vrai workflow
    # ------------------------------------------------------------------
    def _new_request(self, employee, leave_type, date_from, date_to, reason=None, description=None,
                     attach=False):
        user = employee.user_id
        request = self.env['insea.leave.request'].with_user(user).create({
            'employee_id': employee.id,
            'leave_type_id': leave_type.id,
            'reason_id': reason.id if reason else False,
            'date_from': date_from,
            'date_to': date_to,
            'description': description,
        })
        if attach:
            attachment = self.env['ir.attachment'].with_user(user).create({
                'name': 'justificatif_%s.pdf' % request.name.replace('/', '-'),
                'datas': base64.b64encode(_FAKE_PDF),
                'mimetype': 'application/pdf',
            })
            request.with_user(user).attachment_ids = [Command.link(attachment.id)]
        return request

    def _approver(self, request, people):
        manager = request.manager_id.user_id
        return manager or people['salma'].user_id

    def _run(self, request, people, until, refuse_reason=None):
        """Fait avancer `request` dans le workflow jusqu'à l'état `until`."""
        if until == 'draft':
            return request
        request.with_user(request.user_id).action_submit()
        if until == 'submitted':
            return request
        hr_user = people['salma'].user_id
        if until == 'refused_manager':
            request.with_user(self._approver(request, people))._do_refuse(refuse_reason)
            return request
        request.with_user(self._approver(request, people)).action_manager_approve()
        if until in ('manager_approved', 'approved') and request.state == until:
            return request
        if until == 'refused_hr':
            request.with_user(hr_user)._do_refuse(refuse_reason)
            return request
        request.with_user(hr_user).action_hr_approve()
        return request

    def _create_requests(self, people):
        ref = self.env.ref
        t_exit = ref('insea_hr_leave_custom.leave_type_exit')
        t_paid = ref('insea_hr_leave_custom.leave_type_paid')
        t_marriage = ref('insea_hr_leave_custom.leave_type_marriage')
        t_birth = ref('insea_hr_leave_custom.leave_type_birth')
        t_sick = ref('insea_hr_leave_custom.leave_type_sick')
        r_medical = ref('insea_hr_leave_custom.leave_reason_medical')
        r_admin = ref('insea_hr_leave_custom.leave_reason_admin')
        r_urgent = ref('insea_hr_leave_custom.leave_reason_urgent')
        p = people

        def leave(emp, ltype, monday_offset, nb_days, **kw):
            first = self._monday(monday_offset)
            last = first + timedelta(days=nb_days - 1)
            return self._new_request(p[emp], ltype, self._at(first, 8, 30), self._at(last, 17, 30), **kw)

        def sortie(emp, day_offset, hour, hours, reason, **kw):
            day = self._day(day_offset)
            start = self._at(day, hour)
            return self._new_request(p[emp], t_exit, start, start + timedelta(hours=hours), reason=reason, **kw)

        scenarios = [
            # --- Passé : historique approuvé ---------------------------------
            (lambda: leave('karim', t_paid, -35, 3, description="Week-end prolongé en famille"), 'approved', None),
            (lambda: sortie('karim', -12, 10, 2, r_admin, description="Renouvellement de la CIN"), 'approved', None),
            (lambda: leave('imane', t_sick, -21, 2, attach=True, description="Grippe"), 'approved', None),
            (lambda: sortie('hajar', -8, 14, 3, r_medical, attach=True), 'approved', None),
            (lambda: leave('nadia', t_paid, -28, 2), 'approved', None),
            (lambda: sortie('mehdi', -5, 9, 2, r_urgent, description="Panne de voiture"), 'refused_manager',
             "Clôture mensuelle en cours : merci de reporter cette sortie."),
            # --- En cours de validation ---------------------------------------
            (lambda: leave('imane', t_paid, 21, 5, description="Vacances d'hiver"), 'submitted', None),
            (lambda: sortie('omar', 3, 15, 2, r_medical, attach=True, description="Rendez-vous chez le dentiste"),
             'submitted', None),
            (lambda: leave('hajar', t_marriage, 28, 4, attach=True, description="Mariage – félicitations !"),
             'manager_approved', None),
            (lambda: leave('karim', t_birth, 14, 3, attach=False, description="Naissance de mon fils"),
             'manager_approved', None),
            (lambda: leave('youssef', t_paid, 10, 3, description="Déplacement personnel"), 'submitted', None),
            # --- À venir, approuvé ------------------------------------------------
            (lambda: leave('omar', t_paid, 42, 5, description="Voyage à Agadir"), 'approved', None),
            (lambda: leave('rachid', t_paid, 49, 4, description="Congé annuel du Directeur"), 'approved', None),
            # --- Refusé par le RH -----------------------------------------------
            (lambda: leave('mehdi', t_paid, 35, 5, description="Congé de fin d'année"), 'refused_hr',
             "Période d'inventaire annuel : deux membres de l'équipe Finance sont déjà absents."),
            # --- Brouillons --------------------------------------------------------
            (lambda: leave('mehdi', t_paid, 63, 3, description="À confirmer"), 'draft', None),
            (lambda: sortie('imane', 7, 11, 1, r_admin), 'draft', None),
        ]
        created = self.env['insea.leave.request']
        for build, until, reason in scenarios:
            request = build()
            self._run(request, people, until, refuse_reason=reason)
            created |= request
        return created

    # ------------------------------------------------------------------
    # Remise à zéro (avant une nouvelle démonstration)
    # ------------------------------------------------------------------
    @api.model
    def reset(self):
        """Supprime les demandes et soldes de la société Lambda (employés et comptes conservés)."""
        employees = self.env['hr.employee'].sudo().search([('user_id.login', '=like', '%@' + DOMAIN)])
        requests = self.env['insea.leave.request'].sudo().search([('employee_id', 'in', employees.ids)])
        requests.activity_ids.unlink()
        self.env['mail.message'].sudo().search([
            ('model', '=', 'insea.leave.request'), ('res_id', 'in', requests.ids),
        ]).unlink()
        requests.attachment_ids.unlink()
        requests.write({'state': 'draft'})
        requests.unlink()
        self.env['insea.leave.accrual'].sudo().search([('employee_id', 'in', employees.ids)]).unlink()
        self.env['ir.config_parameter'].sudo().search([
            ('key', '=', 'insea_hr_leave_custom.demo_loaded'),
        ]).unlink()
        _logger.info("Démo Congés & Absences réinitialisée : %d demandes supprimées.", len(requests))
        return len(requests)

    # ------------------------------------------------------------------
    # Point d'entrée
    # ------------------------------------------------------------------
    @api.model
    def load(self):
        """Charge (une seule fois) l'organisation Lambda et ses demandes de démonstration."""
        marker = 'insea_hr_leave_custom.demo_loaded'
        params = self.env['ir.config_parameter'].sudo()
        if params.get_param(marker):
            _logger.info("Données de démonstration Congés & Absences déjà chargées : rien à faire.")
            return False
        self._ensure_company()
        people = self._ensure_people()
        self._ensure_accruals(people)
        requests = self._create_requests(people)
        params.set_param(marker, fields.Datetime.now())
        _logger.info("Démo Congés & Absences : %d employés, %d demandes.", len(people), len(requests))
        return True
