from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged

from .common import InseaLeaveCommon


@tagged('post_install', '-at_install', 'insea_leave')
class TestWorkflow(InseaLeaveCommon):
    """Circuit de validation (section 3 du cahier des charges)."""

    def test_reference_sequence(self):
        request = self.create_exit(self.monday_in(14))
        self.assertTrue(request.name.startswith('DA/'), request.name)

    def test_exit_permission_manager_approval_is_final(self):
        request = self.create_exit(self.monday_in(14), hours=2)
        self.assertEqual(request.state, 'draft')
        request.action_submit()
        self.assertEqual(request.state, 'submitted')
        self.assertTrue(request.submit_date)
        request.with_user(self.user_manager).action_manager_approve()
        self.assertEqual(request.state, 'approved')
        self.assertEqual(request.manager_validator_id, self.user_manager)

    def test_paid_leave_requires_hr_validation(self):
        request = self.create_leave(self.type_paid, self.monday_in(21), 3)
        request.action_submit()
        request.with_user(self.user_manager).action_manager_approve()
        self.assertEqual(request.state, 'manager_approved')
        request.with_user(self.user_hr).action_hr_approve()
        self.assertEqual(request.state, 'approved')
        self.assertEqual(request.hr_validator_id, self.user_hr)

    def test_attachment_required_before_final_validation(self):
        request = self.create_leave(self.type_sick, self.monday_in(14), 2)
        self.assertTrue(request.attachment_required)
        request.action_submit()
        request.with_user(self.user_manager).action_manager_approve()
        with self.assertRaisesRegex(UserError, "justificatif"):
            request.with_user(self.user_hr).action_hr_approve()
        self.attach_file(request)
        request.with_user(self.user_hr).action_hr_approve()
        self.assertEqual(request.state, 'approved')

    def test_attachment_visible_to_validators(self):
        """Le justificatif téléversé par l'employé est lisible par son manager et le RH."""
        request = self.create_leave(self.type_sick, self.monday_in(14), 2)
        self.attach_file(request)
        attachment = request.attachment_ids
        self.assertEqual((attachment.res_model, attachment.res_id), (request._name, request.id))
        request.action_submit()
        self.assertEqual(request.with_user(self.user_manager).attachment_ids, attachment)
        self.assertEqual(request.with_user(self.user_hr).attachment_ids, attachment)
        attachment.with_user(self.user_hr).read(['name', 'datas'])

    def test_medical_exit_requires_attachment_flag(self):
        request = self.create_exit(self.monday_in(14), reason=self.reason_medical)
        self.assertTrue(request.attachment_required)
        admin_exit = self.create_exit(self.monday_in(21), reason=self.reason_admin)
        self.assertFalse(admin_exit.attachment_required)

    def test_refuse_requires_reason_and_notifies(self):
        request = self.create_leave(self.type_paid, self.monday_in(21), 2)
        request.action_submit()
        action = request.with_user(self.user_manager).action_refuse()
        Wizard = self.env[action['res_model']].with_user(self.user_manager).with_context(action['context'])
        with self.assertRaises(UserError):
            Wizard.create({'reason': '   '}).action_confirm_refuse()
        Wizard.create({'reason': 'Période de clôture comptable'}).action_confirm_refuse()
        self.assertEqual(request.state, 'refused')
        self.assertEqual(request.refuse_reason, 'Période de clôture comptable')
        notified = request.message_ids.filtered(lambda m: self.user_employee.partner_id in m.partner_ids)
        self.assertTrue(notified, "L'employé doit être notifié du refus")

    def test_hr_can_refuse_after_manager_approval(self):
        request = self.create_leave(self.type_paid, self.monday_in(21), 2)
        request.action_submit()
        request.with_user(self.user_manager).action_manager_approve()
        with self.assertRaisesRegex(UserError, "Responsable RH"):
            self.env['insea.leave.refuse.wizard'].with_user(self.user_manager).create({
                'request_id': request.id, 'reason': 'Non',
            }).action_confirm_refuse()
        self.env['insea.leave.refuse.wizard'].with_user(self.user_hr).create({
            'request_id': request.id, 'reason': 'Effectif insuffisant',
        }).action_confirm_refuse()
        self.assertEqual(request.state, 'refused')

    def test_reset_to_draft_and_resubmit(self):
        request = self.create_leave(self.type_paid, self.monday_in(21), 2)
        request.action_submit()
        request.with_user(self.user_manager)._do_refuse("Dates à revoir")
        request.action_reset_draft()
        self.assertEqual(request.state, 'draft')
        self.assertFalse(request.refuse_reason)
        request.action_submit()
        self.assertEqual(request.state, 'submitted')

    def test_invalid_transitions(self):
        request = self.create_exit(self.monday_in(14))
        with self.assertRaisesRegex(UserError, "Action impossible"):
            request.with_user(self.user_manager).action_manager_approve()
        with self.assertRaisesRegex(UserError, "Action impossible"):
            request.with_user(self.user_hr).action_hr_approve()
        with self.assertRaisesRegex(UserError, "Action impossible"):
            request.action_reset_draft()

    def test_only_drafts_can_be_deleted(self):
        draft = self.create_exit(self.monday_in(14))
        submitted = self.create_exit(self.monday_in(21))
        submitted.action_submit()
        with self.assertRaisesRegex(UserError, "brouillon"):
            submitted.unlink()
        draft.unlink()

    def test_activities_follow_the_workflow(self):
        """Une activité « à faire » est créée pour le prochain valideur, puis retirée."""
        request = self.create_leave(self.type_paid, self.monday_in(21), 2)
        request.action_submit()
        self.assertEqual(request.activity_ids.user_id, self.user_manager)
        request.with_user(self.user_manager).action_manager_approve()
        self.assertIn(self.user_hr, request.activity_ids.user_id)
        self.assertNotIn(self.user_manager, request.activity_ids.user_id)
        request.with_user(self.user_hr).action_hr_approve()
        self.assertFalse(request.activity_ids)

    def test_reason_must_match_type(self):
        with self.assertRaisesRegex(ValidationError, "motif"):
            self.env['insea.leave.request'].with_user(self.user_employee).create({
                'employee_id': self.emp_employee.id,
                'leave_type_id': self.type_paid.id,
                'reason_id': self.reason_admin.id,
                'date_from': self.at(self.monday_in(14), 8),
                'date_to': self.at(self.monday_in(14), 17),
            })
