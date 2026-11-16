from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from .common import InseaLeaveCommon


@tagged('post_install', '-at_install', 'insea_leave')
class TestSecurity(InseaLeaveCommon):
    """Droits d'accès et règles d'enregistrement (Record Rules)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.request_employee = cls.create_leave_cls(cls.emp_employee, cls.user_employee)
        cls.request_colleague = cls.create_leave_cls(cls.emp_colleague, cls.user_colleague)
        cls.request_outsider = cls.create_leave_cls(cls.emp_outsider, cls.user_outsider)

    @classmethod
    def create_leave_cls(cls, employee, user):
        day = cls.monday_in(14)
        return cls.env['insea.leave.request'].with_user(user).create({
            'employee_id': employee.id,
            'leave_type_id': cls.type_exit.id,
            'reason_id': cls.reason_admin.id,
            'date_from': cls.at(day, 9),
            'date_to': cls.at(day, 10),
        })

    def visible(self, user):
        return self.env['insea.leave.request'].with_user(user).search([])

    def test_employee_sees_only_own_requests(self):
        self.assertEqual(self.visible(self.user_employee), self.request_employee)
        self.assertEqual(self.visible(self.user_outsider), self.request_outsider)

    def test_manager_sees_own_team(self):
        visible = self.visible(self.user_manager)
        self.assertIn(self.request_employee, visible)
        self.assertIn(self.request_colleague, visible)
        self.assertNotIn(self.request_outsider, visible)

    def test_hr_sees_everything(self):
        visible = self.visible(self.user_hr)
        for request in (self.request_employee, self.request_colleague, self.request_outsider):
            self.assertIn(request, visible)

    def test_employee_cannot_read_other_request(self):
        with self.assertRaises(AccessError):
            self.request_colleague.with_user(self.user_employee).read(['name'])

    def test_employee_cannot_create_for_someone_else(self):
        with self.assertRaises(AccessError):
            self.create_leave_cls(self.emp_colleague, self.user_employee)

    def test_only_direct_manager_can_approve(self):
        self.request_outsider.with_user(self.user_outsider).action_submit()
        # Le manager n'est pas le N+1 de l'employé externe : la demande lui est invisible
        with self.assertRaises(AccessError):
            self.request_outsider.with_user(self.user_manager).action_manager_approve()
        # Un collègue ne voit pas (et ne peut donc pas approuver) la demande d'un autre membre
        self.request_employee.with_user(self.user_employee).action_submit()
        with self.assertRaises(AccessError):
            self.request_employee.with_user(self.user_colleague).action_manager_approve()

    def test_employee_cannot_approve_own_request(self):
        self.request_employee.with_user(self.user_employee).action_submit()
        with self.assertRaisesRegex(UserError, "manager N\\+1"):
            self.request_employee.with_user(self.user_employee).action_manager_approve()

    def test_manager_cannot_do_hr_validation(self):
        request = self.create_leave(self.type_paid, self.monday_in(21), 2)
        request.action_submit()
        request.with_user(self.user_manager).action_manager_approve()
        with self.assertRaisesRegex(UserError, "Responsable RH"):
            request.with_user(self.user_manager).action_hr_approve()

    def test_configuration_reserved_to_hr(self):
        with self.assertRaises(AccessError):
            self.type_paid.with_user(self.user_manager).write({'max_days': 99})
        with self.assertRaises(AccessError):
            self.env['insea.leave.accrual'].with_user(self.user_employee).create({
                'employee_id': self.emp_employee.id, 'days': 30,
            })
        self.type_paid.with_user(self.user_hr).write({'sequence': 11})

    def test_ui_buttons_follow_roles(self):
        self.request_employee.with_user(self.user_employee).action_submit()
        as_employee = self.request_employee.with_user(self.user_employee)
        as_manager = self.request_employee.with_user(self.user_manager)
        self.assertTrue(as_employee.is_owner)
        self.assertFalse(as_employee.can_manager_approve)
        self.assertFalse(as_employee.can_refuse)
        self.assertTrue(as_manager.can_manager_approve)
        self.assertTrue(as_manager.can_refuse)
        self.assertFalse(as_manager.can_hr_approve)
