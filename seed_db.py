"""Initialize reference data, optionally creating a first administrator or demo fixtures."""
import argparse
from getpass import getpass

from app import app
from models import db, Module, User
from users import _get_or_create_role, _get_or_create_module, ROLES, MODULES, MODULE_ROUTES
from werkzeug.security import generate_password_hash

SEED_USERS = [
    {
        'username': 'Sunil Kumar',
        'email':    'sunil@drogodrones.com',
        'contact':  '+91 98765 43210',
        'roles':    ['Admin', 'Client User'],
        'modules':  ['Transmission Line', 'Land Survey', '3D Inspection'],
        'status':   'Active',
    },
    {
        'username': 'Ramesh Patel',
        'email':    'ramesh@drogodrones.com',
        'contact':  '+91 91234 56780',
        'roles':    ['Client User'],
        'modules':  ['Transmission Line'],
        'status':   'Active',
    },
    {
        'username': 'Anjali Sharma',
        'email':    'anjali@drogodrones.com',
        'contact':  '+91 99887 76655',
        'roles':    ['Client User'],
        'modules':  ['Land Survey'],
        'status':   'Pending',
    },
    {
        'username': 'Vikram Singh',
        'email':    'vikram@drogodrones.com',
        'contact':  '+91 90909 12121',
        'roles':    ['Client User'],
        'modules':  ['3D Inspection', 'Land Survey'],
        'status':   'Active',
    },
    {
        'username': 'Meena Rao',
        'email':    'meena@drogodrones.com',
        'contact':  '+91 98001 22334',
        'roles':    ['Admin'],
        'modules':  ['Transmission Line', 'Land Survey', '3D Inspection'],
        'status':   'Inactive',
    },
]


def seed(*, admin_email=None, demo=False):
    with app.app_context():
        # ── Seed lookup tables ────────────────────────────────────────────────
        for r in ROLES:
            _get_or_create_role(r)
        for m in MODULES:
            mod = Module.query.filter_by(name=m).first()
            if not mod:
                db.session.add(Module(name=m, route=MODULE_ROUTES.get(m, '')))
            elif mod.route != MODULE_ROUTES.get(m, ''):
                # Keeps existing rows in sync if MODULE_ROUTES changes later
                # (e.g. Chimney Inspection used to point at the 'mpptcl' placeholder).
                mod.route = MODULE_ROUTES.get(m, '')
        db.session.commit()
        print("✓ Roles and modules seeded")

        if admin_email:
            email = admin_email.strip().lower()
            if '@' not in email or any(char.isspace() for char in email):
                raise SystemExit('Enter a valid administrator email address.')
            existing = User.query.filter_by(email=email).first()
            if existing:
                if 'Admin' not in existing.role_names():
                    raise SystemExit('An account with that email already exists without the Admin role.')
                print('The administrator account already exists.')
                return
            accounts = [dict(username='Administrator', email=email, contact='', status='Active',
                             roles=['Admin', 'Client User'], modules=MODULES)]
        elif demo:
            accounts = SEED_USERS
        else:
            return

        missing = [account for account in accounts if not User.query.filter_by(email=account['email']).first()]
        if missing:
            password = getpass('New password for the account(s) being created: ')
            if len(password) < 12:
                raise SystemExit('Use a password of at least 12 characters.')
        created = 0
        for data in missing:

            user = User(
                username      = data['username'],
                email         = data['email'],
                password_hash = generate_password_hash(password),
                contact       = data['contact'],
                status        = data['status'],
            )
            db.session.add(user)
            for role_name in data['roles']:
                user.roles.append(_get_or_create_role(role_name))
            for mod_name in data['modules']:
                user.modules.append(_get_or_create_module(mod_name))

            created += 1

        db.session.commit()
        print(f"Created {created} user(s).")
        if not demo:
            return

        # ── Seed demo Transmission Line projects ────────────────────────────────
        from models import Project, Division, Line

        if not Project.query.filter_by(name='Damodar Valley Corporation').first():
            db.session.add(Project(
                module='Transmission Line',
                name='Damodar Valley Corporation',
                contact_no='+91 90000 00001',
                email='owner@dvc.example.com',
                country='India', state='West Bengal / Jharkhand',
                logo_path='images/logos/dvc-logo.png',
                legacy_route='dvc',
                legacy_banner='https://images.pexels.com/photos/32599646/pexels-photo-32599646.jpeg?auto=compress&cs=tinysrgb&w=800',
            ))

        mpptcl = Project.query.filter_by(name='Madhya Pradesh Power Transmission').first()
        if not mpptcl:
            mpptcl = Project(
                module='Transmission Line',
                name='Madhya Pradesh Power Transmission',
                contact_no='+91 90000 00002',
                email='owner@mpptcl.example.com',
                country='India', state='Madhya Pradesh',
                logo_path='images/logos/mpptcl-logo.png',
            )
            db.session.add(mpptcl)
            db.session.flush()
            division = Division(project_id=mpptcl.id, name='Bhopal Division', latitude=23.2599, longitude=77.4126)
            db.session.add(division)
            db.session.flush()
            db.session.add(Line(
                division_id=division.id, name='Bhopal–Indore 400kV',
                start_lat=23.2599, start_lng=77.4126, end_lat=22.7196, end_lng=75.8577,
                length_km=190.5, tower_count=420,
            ))

        if not Project.query.filter_by(name='Kothegudam').first():
            db.session.add(Project(
                module='Land Survey',
                name='Kothegudam',
                contact_no='+91 90000 00003',
                email='owner@kothegudam.example.com',
                country='India', state='Telangana',
                legacy_route='land-survey/kothegudam',
                legacy_banner='/static/images/landsurvey_Cover.png',
            ))

        db.session.commit()
        print("✓ Demo projects seeded (DVC legacy, MPPTCL dynamic, Kothegudam legacy)")



if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--admin-email', help='Create a first administrator, prompting for a password.')
    mode.add_argument('--demo', action='store_true', help='Add sample accounts and projects to a development database.')
    seed(**vars(parser.parse_args()))
