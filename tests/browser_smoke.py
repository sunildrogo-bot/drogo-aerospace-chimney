"""CI browser journeys against the locally built image and its disposable database."""
import os
import secrets
import sys
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlparse

from playwright.sync_api import expect, sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    if not os.environ.get('DATABASE_URL') or os.environ['DATABASE_URL'] != os.environ.get('CHIMNEY_TEST_POSTGRES_URL'):
        raise SystemExit('Run against the disposable release-test database.')
    from seed_db import seed

    email = f'browser-{secrets.token_hex(5)}@example.invalid'
    password = secrets.token_urlsafe(24)
    with patch('seed_db.getpass', return_value=password):
        seed(admin_email=email)
    origin = 'http://127.0.0.1:8000'
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        for role, path, title in [('Admin', '/admin', 'Admin Dashboard'), ('Client', '/dashboard', 'Dashboard')]:
            context = browser.new_context()
            context.route('**/*', lambda route: route.continue_() if urlparse(route.request.url).hostname == '127.0.0.1' else route.abort())
            page = context.new_page()
            page.goto(origin + '/login')
            if role == 'Admin':
                page.locator('label', has_text='Admin').click()
            page.locator('input[type=email]').fill(email)
            page.locator('input[type=password]').fill(password)
            page.get_by_role('button', name='Sign In').click()
            expect(page).to_have_url(origin + path)
            expect(page).to_have_title(title + ' — DROGO AEROSPACE')
            page.reload()
            expect(page).to_have_title(title + ' — DROGO AEROSPACE')
            actual_role = context.request.get(origin + '/api/auth/me').json()['user']['role']
            assert actual_role == ('Admin' if role == 'Admin' else 'Client User')
            context.close()
            print(f'{role} login and dashboard refresh passed')
        browser.close()


if __name__ == '__main__':
    main()
