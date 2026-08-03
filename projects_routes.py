"""
projects_routes.py — Blueprint for Project / Division / Line data.

This is the Project-B (Chimney + Land Survey) build, split out from the
combined codebase. Land Survey uses this generic Project -> Division ->
Line CRUD system (same shared creation modal/API as Transmission Line
used to), but — confirmed by tracing static/js/projects.js — a Land
Survey project always opens at /projects/<id>/info, a plain metadata
page with no tower/KML/defect content at all. Every TRANS-specific
route (the full map, KML tower parsing, tower photos, defects, reports,
pilot assignment, inspection-status) lived only behind
/projects/<id>/map, which Land Survey never navigates to — so none of
that machinery is needed here and has been removed rather than carried
along unused. See projects_routes.py.orig in this same folder for the
original combined version, kept for reference during the split.

Register in app.py with: app.register_blueprint(projects_bp)
"""
import os
import math
from flask import Blueprint, render_template, request, jsonify, session, redirect, url_for, current_app
from werkzeug.utils import secure_filename
from models import db, Project, Division, Line, ActivityLog, User
import settings as app_settings

projects_bp = Blueprint('projects_bp', __name__)

LOGO_EXTS = {'jpg', 'jpeg', 'png'}
KML_EXTS  = {'kml', 'kmz'}

UPLOAD_BASE = os.path.join('static', 'uploads')


def _login_guard():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    return None


def _admin_guard():
    guard = _login_guard()
    if guard:
        return guard
    if session.get('role') != 'Admin':
        return jsonify({'error': 'Your account has view-only access to this module.'}), 403
    return None


def _visible_project_ids(module_name):
    """None means "no restriction, show every project in this module" —
    Admin sessions always get this, and so does a Client User who hasn't
    had any specific projects assigned for this module (the
    backward-compatible default). Otherwise, the set of project IDs this
    Client User is actually allowed to see."""
    if session.get('role') == 'Admin':
        return None
    user = User.query.get(session.get('user_id'))
    if not user:
        return set()  # no valid session user — show nothing rather than guess
    return user.restricted_project_ids_for_module(module_name)


def _project_access_guard(project):
    """For direct-URL access to a project's info page — the list endpoint
    filtering above only helps if someone actually goes through the
    list; this closes the gap for anyone who has (or guesses) a direct
    link to a project they're not allowed to see."""
    allowed_ids = _visible_project_ids(project.module)
    if allowed_ids is not None and project.id not in allowed_ids:
        return jsonify({'error': "You don't have access to this project."}), 403
    return None


def _ext_ok(filename, allowed):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in allowed


def _save_upload(file_storage, subfolder, allowed_exts):
    """Save an uploaded file under static/uploads/<subfolder>/ and return the
    path relative to /static (or '' if no valid file was supplied)."""
    if not file_storage or not file_storage.filename:
        return ''
    if not _ext_ok(file_storage.filename, allowed_exts):
        return None  # signals an invalid file type to the caller
    base_dir = current_app.root_path if hasattr(current_app, 'root_path') else '.'
    folder_fs = os.path.join(base_dir, UPLOAD_BASE, subfolder)
    os.makedirs(folder_fs, exist_ok=True)
    safe_name = secure_filename(file_storage.filename)
    name_root, name_ext = os.path.splitext(safe_name)
    final_name = safe_name
    i = 1
    while os.path.exists(os.path.join(folder_fs, final_name)):
        final_name = f"{name_root}_{i}{name_ext}"
        i += 1
    file_storage.save(os.path.join(folder_fs, final_name))
    return f"uploads/{subfolder}/{final_name}"


def _haversine_km(lat1, lng1, lat2, lng2):
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


# ── Projects ────────────────────────────────────────────────────────────────

@projects_bp.route('/api/projects', methods=['GET'])
def api_list_projects():
    guard = _login_guard()
    if guard:
        return guard
    module = request.args.get('module', '')
    q = Project.query
    if module:
        q = q.filter_by(module=module)
    projects = q.order_by(Project.created_at.asc()).all()

    if module:
        allowed_ids = _visible_project_ids(module)
        if allowed_ids is not None:
            projects = [p for p in projects if p.id in allowed_ids]

    return jsonify({'projects': [p.to_dict() for p in projects]})


@projects_bp.route('/api/projects', methods=['POST'])
def api_create_project():
    guard = _login_guard()
    if guard:
        return guard

    form = request.form
    name = (form.get('name') or '').strip()
    module = (form.get('module') or '').strip()
    email = (form.get('email') or '').strip()

    if not name:
        return jsonify({'error': 'Project name is required.'}), 400
    if not module:
        return jsonify({'error': 'Module is required.'}), 400
    if email and '@' not in email:
        return jsonify({'error': 'Invalid email address.'}), 400

    logo_path = ''
    logo_file = request.files.get('logo')
    if logo_file and logo_file.filename:
        saved = _save_upload(logo_file, 'logos', LOGO_EXTS)
        if saved is None:
            return jsonify({'error': 'Company logo must be a .jpg or .png file.'}), 400
        logo_path = saved

    def _int_or_none(raw):
        raw = (raw or '').strip()
        if not raw:
            return None
        try:
            return int(raw)
        except ValueError:
            return None

    project = Project(
        module=module,
        name=name,
        contact_no=(form.get('contact_no') or '').strip(),
        email=email,
        country=(form.get('country') or '').strip(),
        state=(form.get('state') or '').strip(),
        logo_path=logo_path,
        client_name=(form.get('client_name') or '').strip(),
        planned_divisions=_int_or_none(form.get('planned_divisions')),
        planned_towers=_int_or_none(form.get('planned_towers')),
        timeline=(form.get('timeline') or '').strip(),
        created_by=session.get('user_id'),
    )
    db.session.add(project)
    db.session.commit()
    return jsonify(project.to_dict()), 201


@projects_bp.route('/api/projects/<int:project_id>', methods=['GET'])
def api_get_project(project_id):
    guard = _login_guard()
    if guard:
        return guard
    project = Project.query.get_or_404(project_id)
    data = project.to_dict()
    data['divisions'] = [d.to_dict() for d in project.divisions]
    return jsonify(data)


@projects_bp.route('/api/projects/<int:project_id>', methods=['DELETE'])
def api_delete_project(project_id):
    guard = _login_guard()
    if guard:
        return guard
    project = Project.query.get_or_404(project_id)

    data = request.get_json(force=True, silent=True) or {}
    password = (data.get('password') or request.args.get('password') or '').strip()
    if not app_settings.verify_delete_password(password):
        return jsonify({'error': 'Incorrect delete password.'}), 403

    name, module = project.name, project.module
    db.session.delete(project)
    ActivityLog.log(action='delete', entity_type='Project', entity_name=name,
                     module=module, performed_by=session.get('user_name', ''))
    db.session.commit()
    return jsonify({'deleted': project_id})


@projects_bp.route('/projects/<int:project_id>/info')
def project_info(project_id):
    guard = _login_guard()
    if guard:
        return guard
    project = Project.query.get_or_404(project_id)
    guard = _project_access_guard(project)
    if guard:
        return guard
    return render_template('project_info.html', project=project, user_name=session.get('user_name', ''))


# ── Divisions ──────────────────────────────────────────────────────────────

@projects_bp.route('/api/projects/<int:project_id>/divisions', methods=['GET'])
def api_list_divisions(project_id):
    guard = _login_guard()
    if guard:
        return guard
    Project.query.get_or_404(project_id)
    divisions = Division.query.filter_by(project_id=project_id).order_by(Division.created_at.asc()).all()
    return jsonify({'divisions': [d.to_dict() for d in divisions]})


@projects_bp.route('/api/projects/<int:project_id>/divisions', methods=['POST'])
def api_create_division(project_id):
    guard = _login_guard()
    if guard:
        return guard
    Project.query.get_or_404(project_id)

    data = request.get_json(force=True, silent=True) or request.form
    name = (data.get('name') or '').strip()
    try:
        lat = float(data.get('latitude'))
        lng = float(data.get('longitude'))
    except (TypeError, ValueError):
        return jsonify({'error': 'Latitude and longitude must be valid numbers.'}), 400

    if not name:
        return jsonify({'error': 'Division name is required.'}), 400
    if not (-90 <= lat <= 90) or not (-180 <= lng <= 180):
        return jsonify({'error': 'Latitude/longitude out of range.'}), 400

    planned_towers_raw = (data.get('planned_towers') or '').strip() if isinstance(data.get('planned_towers'), str) else data.get('planned_towers')
    planned_towers = None
    if planned_towers_raw not in (None, ''):
        try:
            planned_towers = int(planned_towers_raw)
        except (TypeError, ValueError):
            planned_towers = None

    division = Division(
        project_id=project_id, name=name, latitude=lat, longitude=lng,
        client_name=(data.get('client_name') or '').strip() if isinstance(data.get('client_name'), str) else '',
        state=(data.get('state') or '').strip() if isinstance(data.get('state'), str) else '',
        planned_towers=planned_towers,
    )
    db.session.add(division)
    db.session.commit()
    return jsonify(division.to_dict()), 201


@projects_bp.route('/api/divisions/<int:division_id>', methods=['DELETE'])
def api_delete_division(division_id):
    guard = _login_guard()
    if guard:
        return guard
    division = Division.query.get_or_404(division_id)
    db.session.delete(division)
    db.session.commit()
    return jsonify({'deleted': division_id})


# ── Lines ──────────────────────────────────────────────────────────────────

@projects_bp.route('/api/divisions/<int:division_id>/lines', methods=['GET'])
def api_list_lines(division_id):
    guard = _login_guard()
    if guard:
        return guard
    Division.query.get_or_404(division_id)
    lines = Line.query.filter_by(division_id=division_id).order_by(Line.created_at.asc()).all()
    return jsonify({'lines': [l.to_dict() for l in lines]})


@projects_bp.route('/api/divisions/<int:division_id>/lines', methods=['POST'])
def api_create_line(division_id):
    guard = _login_guard()
    if guard:
        return guard
    Division.query.get_or_404(division_id)

    form = request.form
    name = (form.get('name') or '').strip()
    if not name:
        return jsonify({'error': 'Line name is required.'}), 400

    try:
        start_lat = float(form.get('start_lat'))
        start_lng = float(form.get('start_lng'))
        end_lat   = float(form.get('end_lat'))
        end_lng   = float(form.get('end_lng'))
    except (TypeError, ValueError):
        return jsonify({'error': 'Start/end position must be valid lat, long numbers.'}), 400

    length_raw = (form.get('length_km') or '').strip()
    if length_raw:
        try:
            length_km = float(length_raw)
        except ValueError:
            return jsonify({'error': 'Line length must be a number.'}), 400
    else:
        length_km = round(_haversine_km(start_lat, start_lng, end_lat, end_lng), 2)

    try:
        tower_count = int(form.get('tower_count') or 0)
    except ValueError:
        return jsonify({'error': 'Number of towers must be a whole number.'}), 400

    kml_path = ''
    kml_file = request.files.get('kml_file')
    if kml_file and kml_file.filename:
        saved = _save_upload(kml_file, 'kml', KML_EXTS)
        if saved is None:
            return jsonify({'error': 'KML file must have a .kml or .kmz extension.'}), 400
        kml_path = saved

    line = Line(
        division_id=division_id,
        name=name,
        start_lat=start_lat, start_lng=start_lng,
        end_lat=end_lat, end_lng=end_lng,
        length_km=length_km,
        tower_count=tower_count,
        kml_path=kml_path,
    )
    db.session.add(line)
    db.session.commit()
    return jsonify(line.to_dict()), 201


@projects_bp.route('/api/lines/<int:line_id>', methods=['DELETE'])
def api_delete_line(line_id):
    guard = _login_guard()
    if guard:
        return guard
    line = Line.query.get_or_404(line_id)
    db.session.delete(line)
    db.session.commit()
    return jsonify({'deleted': line_id})
