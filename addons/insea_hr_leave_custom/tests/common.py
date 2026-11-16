from datetime import date, datetime, time, timedelta

from odoo import Command, fields
from odoo.tests.common import TransactionCase, new_test_user


class InseaLeaveCommon(TransactionCase):
    """Jeu de données commun : un RH, un manager, deux employés de son équipe, un employé externe.

    Les dates sont calculées par rapport à aujourd'hui (toujours un jour ouvré),
    pour que les tests restent valides quelle que soit la date d'exécution.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True, mail_notrack=True))
        grp = 'insea_hr_leave_custom.group_leave_%s'

        cls.user_hr = new_test_user(cls.env, login='t_rh', groups=grp % 'hr', name='Responsable RH')
        cls.user_manager = new_test_user(cls.env, login='t_manager', groups=grp % 'manager', name='Manager')
        cls.user_employee = new_test_user(cls.env, login='t_employe', groups=grp % 'employee', name='Employé')
        cls.user_colleague = new_test_user(cls.env, login='t_collegue', groups=grp % 'employee', name='Collègue')
        cls.user_outsider = new_test_user(cls.env, login='t_externe', groups=grp % 'employee', name='Externe')

        Employee = cls.env['hr.employee']
        cls.emp_hr = Employee.create({'name': 'Responsable RH', 'user_id': cls.user_hr.id})
        cls.emp_manager = Employee.create({'name': 'Manager', 'user_id': cls.user_manager.id})
        cls.emp_employee = Employee.create({
            'name': 'Employé', 'user_id': cls.user_employee.id, 'parent_id': cls.emp_manager.id,
        })
        cls.emp_colleague = Employee.create({
            'name': 'Collègue', 'user_id': cls.user_colleague.id, 'parent_id': cls.emp_manager.id,
        })
        cls.emp_outsider = Employee.create({'name': 'Externe', 'user_id': cls.user_outsider.id})

        ref = cls.env.ref
        cls.type_exit = ref('insea_hr_leave_custom.leave_type_exit')
        cls.type_paid = ref('insea_hr_leave_custom.leave_type_paid')
        cls.type_marriage = ref('insea_hr_leave_custom.leave_type_marriage')
        cls.type_sick = ref('insea_hr_leave_custom.leave_type_sick')
        cls.reason_admin = ref('insea_hr_leave_custom.leave_reason_admin')
        cls.reason_medical = ref('insea_hr_leave_custom.leave_reason_medical')

        # Solde initial confortable pour l'employé : 10 jours
        cls.env['insea.leave.accrual'].create({
            'employee_id': cls.emp_employee.id, 'days': 10, 'type': 'manual_adjustment',
        })

    # ------------------------------------------------------------------
    # Outils de dates
    # ------------------------------------------------------------------
    @staticmethod
    def next_weekday(start, weekday=0):
        """Prochain jour de la semaine `weekday` (0 = lundi) à partir de `start` inclus."""
        return start + timedelta(days=(weekday - start.weekday()) % 7)

    @classmethod
    def monday_in(cls, days):
        """Lundi situé au moins `days` jours après aujourd'hui."""
        return cls.next_weekday(fields.Date.today() + timedelta(days=days))

    @staticmethod
    def at(day, hour):
        return datetime.combine(day, time(hour=hour))

    # ------------------------------------------------------------------
    # Fabriques de demandes
    # ------------------------------------------------------------------
    def create_exit(self, day, start_hour=9, hours=2, user=None, employee=None, reason=None):
        user = user or self.user_employee
        return self.env['insea.leave.request'].with_user(user).create({
            'employee_id': (employee or self.emp_employee).id,
            'leave_type_id': self.type_exit.id,
            'reason_id': (reason or self.reason_admin).id,
            'date_from': self.at(day, start_hour),
            'date_to': self.at(day, start_hour) + timedelta(hours=hours),
        })

    def create_leave(self, leave_type, first_day, nb_days, user=None, employee=None):
        """Congé de `nb_days` jours ouvrés consécutifs à partir d'un lundi."""
        user = user or self.user_employee
        last_day = first_day + timedelta(days=nb_days - 1)
        return self.env['insea.leave.request'].with_user(user).create({
            'employee_id': (employee or self.emp_employee).id,
            'leave_type_id': leave_type.id,
            'date_from': self.at(first_day, 8),
            'date_to': self.at(last_day, 17),
        })

    def attach_file(self, request, user=None):
        attachment = self.env['ir.attachment'].with_user(user or self.user_employee).create({
            'name': 'justificatif.pdf', 'raw': b'%PDF-1.4 test',
        })
        request.with_user(user or self.user_employee).attachment_ids = [Command.link(attachment.id)]
