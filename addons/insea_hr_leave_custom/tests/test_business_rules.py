from datetime import timedelta

from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests import tagged

from .common import InseaLeaveCommon


@tagged('post_install', '-at_install', 'insea_leave')
class TestBusinessRules(InseaLeaveCommon):
    """Règles de gestion de la section 2 du cahier des charges."""

    # ------------------------------------------------------------------
    # Durées calculées
    # ------------------------------------------------------------------
    def test_duration_computation(self):
        monday = self.monday_in(14)
        exit_request = self.create_exit(monday, hours=3)
        self.assertEqual(exit_request.duration_hours, 3.0)
        # Du lundi au lundi suivant : 6 jours ouvrés (week-end exclu)
        leave = self.create_leave(self.type_paid, monday, 8)
        self.assertEqual(leave.duration_days, 6)

    # ------------------------------------------------------------------
    # Autorisation de sortie
    # ------------------------------------------------------------------
    def test_exit_max_four_hours(self):
        monday = self.monday_in(14)
        self.create_exit(monday, hours=4)  # 4 h : autorisé
        with self.assertRaisesRegex(ValidationError, "ne peut pas dépasser 4 heures"):
            self.create_exit(monday + timedelta(days=1), hours=5)

    def test_exit_same_day(self):
        monday = self.monday_in(14)
        with self.assertRaisesRegex(ValidationError, "même jour"):
            self.create_exit(monday, start_hour=22, hours=3)

    def test_exit_monthly_count_limit(self):
        """3 autorisations par mois au maximum : la 4e est refusée à la soumission."""
        first = self.next_weekday(self.monday_in(30).replace(day=1))
        for offset in range(3):
            self.create_exit(first + timedelta(days=offset), hours=1).action_submit()
        fourth = self.create_exit(first + timedelta(days=3), hours=1)
        with self.assertRaisesRegex(ValidationError, "3 autorisations de sortie par mois"):
            fourth.action_submit()

    def test_exit_monthly_hours_limit(self):
        """8 heures cumulées par mois au maximum."""
        first = self.next_weekday(self.monday_in(30).replace(day=1))
        self.create_exit(first, hours=4).action_submit()
        self.create_exit(first + timedelta(days=1), hours=3).action_submit()
        third = self.create_exit(first + timedelta(days=2), hours=2)  # 4 + 3 + 2 = 9 h
        with self.assertRaisesRegex(ValidationError, "8 heures de sortie cumulées"):
            third.action_submit()

    def test_exit_limit_ignores_refused_and_other_months(self):
        first = self.next_weekday(self.monday_in(30).replace(day=1))
        refused = self.create_exit(first, hours=4)
        refused.action_submit()
        refused.with_user(self.user_manager)._do_refuse("Non")
        self.create_exit(first + timedelta(days=1), hours=4).action_submit()
        self.create_exit(first + timedelta(days=2), hours=4).action_submit()  # 8 h : OK

    def test_exit_does_not_affect_balance(self):
        balance = self.emp_employee.leave_balance
        request = self.create_exit(self.monday_in(14), hours=2)
        request.action_submit()
        request.with_user(self.user_manager).action_manager_approve()
        self.assertEqual(request.state, 'approved')
        self.assertEqual(self.emp_employee.leave_balance, balance)

    # ------------------------------------------------------------------
    # Non-chevauchement
    # ------------------------------------------------------------------
    def test_overlap_with_submitted_request(self):
        monday = self.monday_in(14)
        self.create_leave(self.type_paid, monday, 3).action_submit()
        with self.assertRaisesRegex(ValidationError, "chevauche"):
            self.create_exit(monday + timedelta(days=1), hours=2)

    def test_overlap_ignores_drafts_and_refused(self):
        monday = self.monday_in(14)
        self.create_leave(self.type_paid, monday, 3)  # brouillon : ne bloque pas
        refused = self.create_leave(self.type_paid, monday + timedelta(days=7), 3)
        refused.action_submit()
        refused.with_user(self.user_manager)._do_refuse("Période chargée")
        self.create_leave(self.type_paid, monday, 2).action_submit()
        self.create_leave(self.type_paid, monday + timedelta(days=7), 2).action_submit()

    def test_overlap_other_employee_allowed(self):
        monday = self.monday_in(14)
        self.create_leave(self.type_paid, monday, 3).action_submit()
        self.env['insea.leave.accrual'].create({'employee_id': self.emp_colleague.id, 'days': 5})
        self.create_leave(self.type_paid, monday, 3, user=self.user_colleague,
                          employee=self.emp_colleague).action_submit()

    def test_adjacent_requests_allowed(self):
        monday = self.monday_in(14)
        self.create_exit(monday, start_hour=9, hours=2).action_submit()
        self.create_exit(monday, start_hour=11, hours=2).action_submit()  # commence à la fin de l'autre

    # ------------------------------------------------------------------
    # Solde de congés payés
    # ------------------------------------------------------------------
    def test_balance_insufficient(self):
        request = self.create_leave(self.type_paid, self.monday_in(21), 15)  # 11 jours ouvrés
        self.assertEqual(request.duration_days, 11)
        with self.assertRaisesRegex(ValidationError, "Solde de congés insuffisant"):
            request.action_submit()

    def test_balance_exactly_enough(self):
        request = self.create_leave(self.type_paid, self.monday_in(21), 12)  # 10 jours ouvrés
        self.assertEqual(request.duration_days, 10)
        request.action_submit()
        self.assertEqual(request.state, 'submitted')

    def test_balance_reserves_pending_requests(self):
        """Deux demandes en attente ne peuvent pas consommer les mêmes jours."""
        self.create_leave(self.type_paid, self.monday_in(21), 5).action_submit()      # 5 j réservés
        second = self.create_leave(self.type_paid, self.monday_in(35), 12)           # 10 j
        with self.assertRaisesRegex(ValidationError, "5.0 jour"):
            second.action_submit()

    def test_balance_deducted_after_hr_approval(self):
        request = self.create_leave(self.type_paid, self.monday_in(21), 3)
        request.action_submit()
        request.with_user(self.user_manager).action_manager_approve()
        self.assertEqual(self.emp_employee.leave_balance, 10, "Pas de déduction avant la validation RH")
        request.with_user(self.user_hr).action_hr_approve()
        self.assertEqual(self.emp_employee.leave_taken, 3)
        self.assertEqual(self.emp_employee.leave_balance, 7)

    def test_sick_leave_does_not_affect_balance(self):
        request = self.create_leave(self.type_sick, self.monday_in(14), 3)
        request.action_submit()
        request.with_user(self.user_manager).action_manager_approve()
        self.attach_file(request)
        request.with_user(self.user_hr).action_hr_approve()
        self.assertEqual(self.emp_employee.leave_balance, 10)

    # ------------------------------------------------------------------
    # Délai de prévenance
    # ------------------------------------------------------------------
    def test_notice_period_too_short(self):
        """Congé payé de 5 jours ouvrés commençant dans 2 jours : refusé."""
        start = fields.Date.today() + timedelta(days=2)
        request = self.create_leave(self.type_paid, start, 7)  # 7 jours calendaires = 5 ouvrés
        self.assertEqual(request.duration_days, 5)
        with self.assertRaisesRegex(ValidationError, "au moins 7 jours à l'avance"):
            request.action_submit()

    def test_notice_period_respected(self):
        """Exactement 7 jours de prévenance : accepté."""
        start = fields.Date.today() + timedelta(days=7)
        request = self.create_leave(self.type_paid, start, 7)
        request.action_submit()
        self.assertEqual(request.state, 'submitted')

    def test_notice_period_not_required_for_short_leave(self):
        """Un congé payé de 3 jours ou moins peut être demandé à la dernière minute."""
        start = fields.Date.today() + timedelta(days=1)
        request = self.create_leave(self.type_paid, start, 3)
        self.assertLessEqual(request.duration_days, 3)
        request.action_submit()
        self.assertEqual(request.state, 'submitted')

    # ------------------------------------------------------------------
    # Congés exceptionnels
    # ------------------------------------------------------------------
    def test_exceptional_leave_max_days(self):
        self.create_leave(self.type_marriage, self.monday_in(14), 4)  # mariage : 4 j autorisés
        with self.assertRaisesRegex(ValidationError, "limité à 4"):
            self.create_leave(self.type_marriage, self.monday_in(28), 5)
