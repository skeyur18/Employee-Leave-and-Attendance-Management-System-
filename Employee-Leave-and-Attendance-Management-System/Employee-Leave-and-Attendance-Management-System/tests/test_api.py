import http.client
import json
import os
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["ELAMS_QUIET"] = "1"

import server
from elams import db, services


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        cls.tmp.close()
        db.DB_PATH = cls.tmp.name
        conn = db.get_conn()
        services.seed_demo(conn)
        conn.close()
        cls.srv = server.make_server("127.0.0.1", 0)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        os.unlink(cls.tmp.name)

    def call(self, method, path, body=None, cookie=None, headers=None):
        h = {"Content-Type": "application/json"}
        if method != "GET":
            h["X-Requested-With"] = "fetch"
        if cookie:
            h["Cookie"] = cookie
        h.update(headers or {})
        c = http.client.HTTPConnection("127.0.0.1", self.port)
        c.request(method, path, json.dumps(body) if body is not None else None, h)
        r = c.getresponse()
        raw = r.read()
        try:
            data = json.loads(raw)
        except ValueError:
            data = raw
        return r.status, data, r

    def login(self, email, pw):
        st, data, r = self.call("POST", "/api/login", {"email": email, "password": pw})
        self.assertEqual(st, 200, data)
        return r.getheader("Set-Cookie").split(";")[0]

    def test_website_is_served(self):
        st, data, r = self.call("GET", "/")
        self.assertEqual(st, 200)
        self.assertIn("text/html", r.getheader("Content-Type"))
        self.assertEqual(self.call("GET", "/../server.py")[0], 404)

    def test_auth_required(self):
        self.assertEqual(self.call("GET", "/api/me")[0], 401)
        st, data, _ = self.call("POST", "/api/login", {"email": "ravi@company.com", "password": "nope"})
        self.assertEqual((st, data["error"]), (401, "Incorrect email or password."))

    def test_requires_fetch_header(self):
        st, _, _ = self.call("POST", "/api/login", {"email": "a", "password": "b"}, headers={"X-Requested-With": ""})
        self.assertEqual(st, 400)

    def test_employee_flow(self):
        ck = self.login("asha@company.com", "employee123")
        self.assertEqual(self.call("GET", "/api/me", cookie=ck)[1]["user"]["name"], "Asha Reddy")
        self.assertNotIn("password_hash", json.dumps(self.call("GET", "/api/me", cookie=ck)[1]))
        st, d, _ = self.call("POST", "/api/checkin", {}, ck)
        self.assertEqual(st, 200, d)
        self.assertEqual(self.call("POST", "/api/checkin", {}, ck)[0], 400)
        self.assertEqual(self.call("POST", "/api/checkout", {}, ck)[0], 200)
        dash = self.call("GET", "/api/dashboard", cookie=ck)[1]
        self.assertEqual(dash["today"]["state"], "done")
        self.assertNotIn("team", dash)
        st, d, _ = self.call("POST", "/api/leaves", {"type": "Casual", "start": "2030-01-10", "end": "2030-01-11", "reason": "x"}, ck)
        self.assertEqual(st, 201, d)
        # employee-only restrictions
        self.assertEqual(self.call("GET", "/api/employees", cookie=ck)[0], 403)
        self.assertEqual(self.call("GET", "/api/leaves?scope=pending", cookie=ck)[0], 403)
        self.assertEqual(self.call("GET", "/api/attendance?scope=all", cookie=ck)[0], 403)
        self.assertEqual(self.call("GET", "/api/report?month=2026-11", cookie=ck)[0], 403)

    def test_manager_flow(self):
        ck = self.login("ravi@company.com", "manager123")
        pending = self.call("GET", "/api/leaves?scope=pending", cookie=ck)[1]["leaves"]
        self.assertTrue(pending)
        st, d, _ = self.call("POST", f"/api/leaves/{pending[0]['id']}/approve", {"comment": "ok"}, ck)
        self.assertEqual(st, 200, d)
        st, d, _ = self.call("POST", "/api/employees", {"name": "New Hire", "email": "new@company.com",
                             "password": "welcome1", "department": "QA", "designation": "Tester"}, ck)
        self.assertEqual(st, 201, d)
        self.assertEqual(self.call("POST", "/api/employees", {"name": "Dup", "email": "new@company.com",
                         "password": "welcome1", "department": "QA"}, ck)[0], 400)
        self.call("POST", "/api/employees", {}, ck)  # invalid body should not crash
        st, rep, _ = self.call("GET", "/api/report?month=2026-11", cookie=ck)
        self.assertEqual(st, 200)
        st, csv_body, r = self.call("GET", "/api/report.csv?month=2026-11", cookie=ck)
        self.assertIn("text/csv", r.getheader("Content-Type"))
        self.assertTrue(csv_body.startswith(b"Employee,Department"))

    def test_logout_ends_session(self):
        ck = self.login("sneha@company.com", "employee123")
        self.call("POST", "/api/logout", {}, ck)
        self.assertEqual(self.call("GET", "/api/me", cookie=ck)[0], 401)


if __name__ == "__main__":
    unittest.main()
