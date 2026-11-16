from datetime import date

from odoo.tests import tagged

from .common import InseaLeaveCommon


@tagged('post_install', '-at_install', 'insea_leave')
class TestAccrual(InseaLeaveCommon):
    """Acquisition mensuelle du solde (1,5 jour par mois) et tâche planifiée."""

    def test_monthly_accrual_credits_each_active_employee(self):
        balance = self.emp_employee.leave_balance
        created = self.env['hr.employee']._cron_monthly_accrual(date=date(2027, 3, 15))
        self.assertIn(self.emp_employee, created.employee_id)
        line = created.filtered(lambda a: a.employee_id == self.emp_employee)
        self.assertEqual(line.days, 1.5)
        self.assertEqual(line.date, date(2027, 3, 1), "L'acquisition est datée du 1er du mois")
        self.assertEqual(line.type, 'monthly')
        self.assertEqual(self.emp_employee.leave_balance, balance + 1.5)

    def test_monthly_accrual_is_idempotent(self):
        Employee = self.env['hr.employee']
        Employee._cron_monthly_accrual(date=date(2027, 3, 1))
        second_run = Employee._cron_monthly_accrual(date=date(2027, 3, 28))
        self.assertFalse(second_run, "Relancer la tâche dans le même mois ne crédite rien")
        next_month = Employee._cron_monthly_accrual(date=date(2027, 4, 2))
        self.assertIn(self.emp_employee, next_month.employee_id)

    def test_archived_employee_not_credited(self):
        self.emp_outsider.active = False
        created = self.env['hr.employee']._cron_monthly_accrual(date=date(2027, 5, 1))
        self.assertNotIn(self.emp_outsider, created.employee_id)

    def test_twelve_months_give_eighteen_days(self):
        """Sur une année : 12 × 1,5 = 18 jours acquis."""
        employee = self.env['hr.employee'].create({'name': 'Nouvel arrivant'})
        for month in range(1, 13):
            self.env['hr.employee']._cron_monthly_accrual(date=date(2028, month, 1))
        self.assertEqual(employee.leave_allocated, 18.0)

    def test_hr_manual_adjustment(self):
        self.env['insea.leave.accrual'].with_user(self.user_hr).create({
            'employee_id': self.emp_employee.id, 'days': -2, 'note': 'Régularisation',
        })
        self.assertEqual(self.emp_employee.leave_balance, 8)

    def test_cron_record_is_configured(self):
        cron = self.env.ref('insea_hr_leave_custom.ir_cron_monthly_accrual')
        self.assertTrue(cron.active)
        self.assertEqual((cron.interval_number, cron.interval_type), (1, 'months'))
        self.assertEqual(cron.nextcall.day, 1)
