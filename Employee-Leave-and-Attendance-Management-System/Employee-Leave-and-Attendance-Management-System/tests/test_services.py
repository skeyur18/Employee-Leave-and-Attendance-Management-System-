import os
import sys
import unittest
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from elams import auth, services as s
from elams.db import get_conn


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.c = get_conn(":memory:")
        self.mgr = s.add_employee(self.c, "Ravi", "ravi@x.com", "secret1", "HR", role="manager")
        self.mgr2 = s.add_employee(self.c, "Priya", "priya@x.com", "secret1", "Ops", role="manager")
        self.emp = s.add_employee(self.c, "Asha", "asha@x.com", "secret1", "IT")

    # employees & auth
    def test_add_employee_validation(self):
        with self.assertRaises(ValueError):
            s.add_employee(self.c, "", "a@b.com", "secret1", "IT")
        with self.assertRaises(ValueError):
            s.add_employee(self.c, "X", "not-an-email", "secret1", "IT")
        with self.assertRaises(ValueError):
            s.add_employee(self.c, "X", "x@x.com", "123", "IT")
        with self.assertRaises(ValueError):
            s.add_employee(self.c, "X", "asha@x.com", "secret1", "IT")  # duplicate

    def test_login_and_sessions(self):
        token, user = auth.login(self.c, "ASHA@x.com", "secret1")
        self.assertEqual(user["name"], "Asha")
        self.assertEqual(auth.user_for_token(self.c, token)["id"], self.emp)
        auth.logout(self.c, token)
        self.assertIsNone(auth.user_for_token(self.c, token))
        with self.assertRaises(auth.AuthError):
            auth.login(self.c, "asha@x.com", "wrong")

    def test_passwords_are_hashed(self):
        stored = s.get_employee(self.c, self.emp)["password_hash"]
        self.assertNotIn("secret1", stored)
        self.assertTrue(auth.verify_password("secret1", stored))

    def test_deactivated_user_cannot_login(self):
        s.update_employee(self.c, self.mgr, self.emp, {"active": False})
        with self.assertRaises(auth.AuthError):
            auth.login(self.c, "asha@x.com", "secret1")

    def test_cannot_change_own_role(self):
        with self.assertRaises(ValueError):
            s.update_employee(self.c, self.mgr, self.mgr, {"role": "employee"})

    def test_change_password(self):
        with self.assertRaises(ValueError):
            s.change_password(self.c, self.emp, "bad", "newpass1")
        s.change_password(self.c, self.emp, "secret1", "newpass1")
        auth.login(self.c, "asha@x.com", "newpass1")

    # attendance
    def test_check_in_out(self):
        t = datetime(2026, 11, 18, 9, 0, 0)
        s.check_in(self.c, self.emp, t)
        with self.assertRaises(ValueError):
            s.check_in(self.c, self.emp, t)
        s.check_out(self.c, self.emp, datetime(2026, 11, 18, 17, 30, 0))
        rows = s.list_attendance(self.c, self.emp, "2026-11")
        self.assertEqual(rows[0]["hours"], 8.5)
        self.assertEqual(s.today_status(self.c, self.emp, t)["state"], "done")

    def test_check_out_needs_check_in(self):
        with self.assertRaises(ValueError):
            s.check_out(self.c, self.emp)

    def test_cannot_check_in_on_approved_leave(self):
        lid = s.apply_leave(self.c, self.emp, "Casual", "2026-11-18", "2026-11-19")
        s.decide_leave(self.c, self.mgr, lid, True)
        with self.assertRaises(ValueError):
            s.check_in(self.c, self.emp, datetime(2026, 11, 18, 9, 0, 0))

    # leave
    def test_leave_flow_and_balance(self):
        lid = s.apply_leave(self.c, self.emp, "Casual", "2026-12-01", "2026-12-03", "Trip")
        s.decide_leave(self.c, self.mgr, lid, True, "Enjoy")
        self.assertEqual(s.get_employee(self.c, self.emp)["leave_balance"], 17)
        row = s.list_leaves(self.c, "mine", self.emp)[0]
        self.assertEqual((row["status"], row["comment"], row["decided_by_name"]), ("APPROVED", "Enjoy", "Ravi"))
        with self.assertRaises(ValueError):
            s.decide_leave(self.c, self.mgr, lid, False)  # already decided

    def test_rejection_keeps_balance(self):
        lid = s.apply_leave(self.c, self.emp, "Sick", "2026-12-01", "2026-12-02")
        s.decide_leave(self.c, self.mgr, lid, False)
        self.assertEqual(s.get_employee(self.c, self.emp)["leave_balance"], 20)

    def test_unpaid_leave_keeps_balance(self):
        lid = s.apply_leave(self.c, self.emp, "Unpaid", "2026-12-01", "2026-12-05")
        s.decide_leave(self.c, self.mgr, lid, True)
        self.assertEqual(s.get_employee(self.c, self.emp)["leave_balance"], 20)

    def test_permissions(self):
        lid = s.apply_leave(self.c, self.emp, "Casual", "2026-12-01", "2026-12-02")
        with self.assertRaises(PermissionError):
            s.decide_leave(self.c, self.emp, lid, True)
        mlid = s.apply_leave(self.c, self.mgr, "Casual", "2026-12-10", "2026-12-11")
        with self.assertRaises(PermissionError):
            s.decide_leave(self.c, self.mgr, mlid, True)  # own request
        s.decide_leave(self.c, self.mgr2, mlid, True)     # other manager is fine

    def test_leave_validation(self):
        bad = [("Casual", "2026-12-05", "2026-12-01"), ("Casual", "2026-01-01", "2026-03-01"),
               ("Casual", "2026-12-01", "2026-12-25"), ("Holiday", "2026-12-01", "2026-12-02"),
               ("Casual", "bad", "date")]
        for args in bad:
            with self.assertRaises(ValueError, msg=args):
                s.apply_leave(self.c, self.emp, *args)
        s.apply_leave(self.c, self.emp, "Casual", "2026-12-01", "2026-12-03")
        with self.assertRaises(ValueError):
            s.apply_leave(self.c, self.emp, "Casual", "2026-12-03", "2026-12-04")  # overlap

    def test_pending_list_excludes_own(self):
        s.apply_leave(self.c, self.emp, "Casual", "2026-12-01", "2026-12-02")
        s.apply_leave(self.c, self.mgr, "Casual", "2026-12-10", "2026-12-11")
        names = [l["name"] for l in s.list_leaves(self.c, "pending", self.mgr)]
        self.assertEqual(names, ["Asha"])

    # dashboard & reports
    def test_dashboard_and_report(self):
        today = date(2026, 11, 18)
        s.check_in(self.c, self.emp, datetime(2026, 11, 16, 9, 0, 0))
        s.check_out(self.c, self.emp, datetime(2026, 11, 16, 17, 0, 0))
        lid = s.apply_leave(self.c, self.emp, "Casual", "2026-11-17", "2026-11-17")
        s.decide_leave(self.c, self.mgr, lid, True)
        d = s.dashboard(self.c, s.get_employee(self.c, self.mgr), datetime(2026, 11, 18, 10, 0, 0))
        self.assertEqual(d["team"]["employees"], 3)
        rep = s.monthly_report(self.c, "2026-11", today)
        self.assertEqual(rep["working_days"], 13)  # 1-18 Nov 2026, Mon-Fri
        asha = next(r for r in rep["rows"] if r["name"] == "Asha")
        self.assertEqual((asha["present"], asha["hours"], asha["leave_days"]), (1, 8.0, 1))
        self.assertTrue(s.report_csv(rep).startswith("Employee,Department"))

    def test_seed_demo(self):
        c = get_conn(":memory:")
        self.assertTrue(s.seed_demo(c, date(2026, 11, 18)))
        self.assertFalse(s.seed_demo(c))
        self.assertEqual(len(s.list_employees(c)), 6)
        auth.login(c, "ravi@company.com", "manager123")


if __name__ == "__main__":
    unittest.main()
