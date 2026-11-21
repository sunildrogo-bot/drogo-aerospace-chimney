import io
import os
import secrets
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from sqlalchemy.engine import make_url
from werkzeug.security import generate_password_hash

with patch.dict(os.environ, {'CHIMNEY_SCHEMA_READY': '1'}):
    from app import create_app

from models import ChimneyProject, Division, Module, Project, Role, User, db
from chimney_upload_jobs import append_chunk, claim_queued, get_job, jobs_root, new_job
from chimney_upload_worker import process_job


class ReleaseChecks(unittest.TestCase):
    def setUp(self):
        with redirect_stdout(io.StringIO()):
            self.app = create_app('sqlite:///:memory:')
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()
        self.password = secrets.token_urlsafe(18)
        self.context = self.app.app_context()
        self.context.push()
        self.addCleanup(self.context.pop)
        survey = Module(name='Land Survey')
        admin, client = Role(name='Admin'), Role(name='Client User')
        self.visible = Project(name='Assigned survey', module=survey.name)
        self.other = Project(name='Separate survey', module=survey.name)
        self.inspection = ChimneyProject(asset_name='Inspection', latitude=17, longitude=80)
        self.division = Division(project=self.visible, name='Division', latitude=17, longitude=80)
        self.account = User(username='Release Checker', email='checker@example.invalid', status='Active',
                            password_hash=generate_password_hash(self.password), roles=[admin, client],
                            modules=[survey], allowed_projects=[self.visible])
        db.session.add_all([self.account, self.visible, self.other, self.inspection, self.division])
        db.session.commit()

    def login(self, role):
        response = self.client.post('/api/auth/login', json={
            'email': self.account.email, 'password': self.password, 'login_as': role,
        })
        self.assertEqual(response.status_code, 200)

    def test_assigned_client_projects_and_reports(self):
        self.login('Client User')
        for path in ('/api/projects', '/api/projects?module=Land%20Survey'):
            rows = self.client.get(path).get_json()['projects']
            self.assertEqual([p['name'] for p in rows], [self.visible.name])
        self.assertEqual(self.client.get(f'/api/projects/{self.visible.id}/divisions').status_code, 200)
        self.assertEqual(self.client.get(f'/api/divisions/{self.division.id}/lines').status_code, 200)
        self.assertEqual(self.client.get('/api/dashboard/client-summary').get_json()['projects']['total'], 1)
        self.assertNotIn(b'openAddProjectModal()', self.client.get('/land-survey').data)
        self.assertEqual(self.client.get('/api/assistant/central-report.pdf').status_code, 403)
        self.account.modules = []
        db.session.commit()
        self.assertEqual(self.client.get('/api/projects').get_json()['projects'], [])
        self.assertEqual(self.client.get('/api/assistant/central-report.pdf').status_code, 403)

    def test_admin_can_create_and_session_tracks_account_changes(self):
        self.login('Admin')
        result = self.client.post('/api/projects', data={'module': 'Land Survey', 'name': 'New survey'})
        self.assertEqual(result.status_code, 201)
        report = self.client.get('/api/assistant/central-report.pdf')
        self.assertEqual(report.status_code, 200)
        self.assertEqual(report.mimetype, 'application/pdf')
        self.assertTrue(report.data.startswith(b'%PDF-'))
        self.assertTrue(report.cache_control.no_store)
        self.assertEqual(self.client.post('/api/auth/switch-role', json={'role': 'Client User'}).status_code, 200)
        self.assertEqual(self.client.post('/api/projects').status_code, 403)
        self.account.status = 'Inactive'
        db.session.commit()
        self.assertIsNone(self.client.get('/api/auth/me').get_json()['user'])

    def test_bootstrap_is_idempotent_and_demo_is_opt_in(self):
        import seed_db
        with patch.object(seed_db, 'app', self.app), redirect_stdout(io.StringIO()):
            seed_db.seed()
            self.assertEqual(User.query.count(), 1)
            with patch.object(seed_db, 'getpass', return_value=self.password) as prompt:
                seed_db.seed(admin_email='first@example.invalid')
                seed_db.seed(admin_email='first@example.invalid')
                self.assertEqual(prompt.call_count, 1)
        self.assertEqual(User.query.count(), 2)
        self.assertEqual(Project.query.count(), 2)

    def test_worker_completes_a_real_queued_upload(self):
        with tempfile.TemporaryDirectory() as directory:
            self.app.static_folder = directory
            body = b'{"asset":{"version":"1.0"},"geometricError":0,"root":{}}'
            job = new_job(directory, self.inspection.id, 'tileset.json', len(body))
            append_chunk(directory, self.inspection.id, job['id'], 0, body)
            process_job(self.app, claim_queued(directory))
            status = get_job(directory, self.inspection.id, job['id'])
            self.assertEqual(status['state'], 'completed', status.get('error'))
            self.assertFalse(status['model_activated'])
            self.assertFalse((jobs_root(directory) / str(self.inspection.id) / job['id'] / 'upload.part').exists())
            retry = append_chunk(directory, self.inspection.id, job['id'], 0, body)
            self.assertEqual(retry['state'], 'completed')

    def test_a_later_upload_preserves_the_active_model(self):
        self.assertTrue(ChimneyProject.activate_first_model(self.inspection.id, 'first/tileset.json'))
        self.assertFalse(ChimneyProject.activate_first_model(self.inspection.id, 'second/tileset.json'))
        self.assertEqual(self.inspection.tileset_path, 'first/tileset.json')


@unittest.skipUnless(os.getenv('CHIMNEY_TEST_POSTGRES_URL'), 'requires a disposable PostgreSQL service')
class PostgresUpgrade(unittest.TestCase):
    def test_upgrade_preserves_rows_and_can_be_repeated(self):
        from sqlalchemy import create_engine, inspect, text
        from migrate_add_defect_columns import ensure_defect_columns
        base = make_url(os.environ['CHIMNEY_TEST_POSTGRES_URL'])
        schema = 'chimney_test_' + secrets.token_hex(8)
        engine = create_engine(base)
        with engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA {schema}'))
        try:
            url = base.update_query_dict({'options': f'-csearch_path={schema}'})
            app = create_app(url.render_as_string(hide_password=False), initialize_schema=False)
            with app.app_context():
                db.create_all()
                with db.engine.begin() as connection:
                    connection.execute(text("INSERT INTO users (username,email,password_hash) VALUES ('QA','qa@example.invalid','fixture')"))
                    connection.execute(text('ALTER TABLE users DROP COLUMN last_login_at'))
                    connection.execute(text('ALTER TABLE chimney_defects DROP COLUMN closed_at'))
                for _ in range(2):
                    self.assertTrue(ensure_defect_columns(app, verbose=False))
                with db.engine.connect() as connection:
                    self.assertEqual(connection.scalar(text("SELECT username FROM users")), 'QA')
                    for table, name in [('users', 'last_login_at'), ('chimney_defects', 'closed_at')]:
                        columns = {c['name']: c['type'] for c in inspect(connection).get_columns(table)}
                        self.assertEqual(str(columns[name]), 'TIMESTAMP')
                db.session.remove()
                db.engine.dispose()
        finally:
            with engine.begin() as connection:
                connection.execute(text(f'DROP SCHEMA {schema} CASCADE'))
            engine.dispose()
