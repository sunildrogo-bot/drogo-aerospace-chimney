"""
settings_routes.py — Blueprint for /settings/* — Admin-only.

Covers:
  - Setting/changing the shared "delete password" required to delete any
    project (Transmission Line / Land Survey / Chimney).
  - Activity log (who deleted what, which module, when).
  - Active users + last login snapshot.

Register in app.py with: app.register_blueprint(settings_bp)
"""
from flask import Blueprint, render_template, request, jsonify, session, redirect, url_for
from datetime import datetime, date, timedelta

import settings as app_settings
from models import db, ActivityLog, User, Project, ChimneyProject, ChimneyDefect

settings_bp = Blueprint('settings_bp', __name__)


def _login_guard():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    return None


def _require_admin():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    if session.get('role') != 'Admin':
        return jsonify({'error': 'Admin access required.'}), 403
    return None


# ── Page ─────────────────────────────────────────────────────────────────────

@settings_bp.route('/settings')
def settings_page():
    guard = _require_admin()
    if guard:
        return guard
    return render_template(
        'settings.html',
        user_name=session['user_name'],
        has_delete_password=app_settings.has_delete_password(),
    )


# ── Delete password ────────────────────────────────────────────────────────────

@settings_bp.route('/api/settings/delete-password', methods=['POST'])
def api_set_delete_password():
    guard = _require_admin()
    if guard:
        return guard

    data = request.get_json(force=True, silent=True) or {}
    new_password = (data.get('new_password') or '').strip()
    current_password = (data.get('current_password') or '').strip()

    if len(new_password) < 4:
        return jsonify({'error': 'New password must be at least 4 characters.'}), 400

    # If a delete password already exists, the current one must be supplied
    # and correct before it can be changed.
    if app_settings.has_delete_password():
        if not app_settings.verify_delete_password(current_password):
            return jsonify({'error': 'Current delete password is incorrect.'}), 403

    app_settings.set_delete_password(new_password)
    ActivityLog.log(action='update', entity_type='Setting', entity_name='Delete Password',
                     performed_by=session.get('user_name', ''), details='Delete password set/changed')
    db.session.commit()
    return jsonify({'ok': True})


# ── Activity log ───────────────────────────────────────────────────────────────

@settings_bp.route('/api/settings/activity-log', methods=['GET'])
def api_activity_log():
    guard = _require_admin()
    if guard:
        return guard
    entries = ActivityLog.query.order_by(ActivityLog.created_at.desc()).limit(200).all()
    return jsonify({'entries': [e.to_dict() for e in entries]})


# ── Active users / login details ──────────────────────────────────────────────

@settings_bp.route('/api/settings/users-overview', methods=['GET'])
def api_users_overview():
    guard = _require_admin()
    if guard:
        return guard
    users = User.query.order_by(User.username.asc()).all()
    return jsonify({'users': [u.to_dict() for u in users]})


# ── Project Management (all modules, one place) ────────────────────────────────

@settings_bp.route('/api/settings/all-projects', methods=['GET'])
def api_all_projects():
    guard = _require_admin()
    if guard:
        return guard

    rows = []
    for p in Project.query.order_by(Project.created_at.desc()).all():
        rows.append({
            'id': p.id,
            'module': p.module,
            'name': p.name,
            'detail': f'{p.state}, {p.country}' if p.state or p.country else (p.email or '—'),
            'created_at': p.created_at.strftime('%d %b %Y') if p.created_at else '—',
            'delete_url': f'/api/projects/{p.id}',
            'open_url': None,  # generic projects route to their module listing, not a single page
        })
    for c in ChimneyProject.query.order_by(ChimneyProject.created_at.desc()).all():
        rows.append({
            'id': c.id,
            'module': '3D Inspection',
            'name': c.asset_name,
            'detail': c.inspection_type or '—',
            'created_at': c.created_at.strftime('%d %b %Y') if c.created_at else '—',
            'delete_url': f'/api/chimney-projects/{c.id}',
            'open_url': f'/chimney-projects/{c.id}',
        })
    rows.sort(key=lambda r: r['created_at'], reverse=True)
    return jsonify({'projects': rows})


# ── Dashboard summary (stats) ──────────────────────────────────────────────────

@settings_bp.route('/api/dashboard/notes', methods=['GET'])
def api_get_dashboard_notes():
    guard = _login_guard()
    if guard:
        return guard
    user = User.query.get(session.get('user_id'))
    return jsonify({'notes': (user.dashboard_notes if user else '') or ''})


@settings_bp.route('/api/dashboard/notes', methods=['PUT'])
def api_save_dashboard_notes():
    guard = _login_guard()
    if guard:
        return guard
    user = User.query.get(session.get('user_id'))
    if not user:
        return jsonify({'error': 'Not found'}), 404
    data = request.get_json(force=True, silent=True) or {}
    user.dashboard_notes = (data.get('notes') or '')[:20000]  # sane cap, this is a scratch pad not a document store
    db.session.commit()
    return jsonify({'ok': True})


@settings_bp.route('/api/dashboard/client-summary', methods=['GET'])
def api_client_dashboard_summary():
    """Lightweight dashboard summary for a Client User's own landing page
    — deliberately much smaller than Admin's version. Total projects
    respects the same project-wise access restrictions used everywhere
    else (a restricted client only ever counts what they can actually
    see). The activity trend is scoped to THIS user's own actions only,
    not a system-wide feed — a client has no reason to see what other
    users have been doing, and showing it would leak information about
    activity on projects they might not even have access to."""
    guard = _login_guard()
    if guard:
        return guard

    from projects_routes import _visible_project_ids
    lsurvey_projects = Project.query.filter_by(module='Land Survey').all()
    allowed_lsurvey = _visible_project_ids('Land Survey')
    if allowed_lsurvey is not None:
        lsurvey_projects = [p for p in lsurvey_projects if p.id in allowed_lsurvey]
    lsurvey_count = len(lsurvey_projects)

    from chimney_routes import _visible_chimney_project_ids
    chimney_projects = ChimneyProject.query.all()
    allowed_chimney = _visible_chimney_project_ids()
    if allowed_chimney is not None:
        chimney_projects = [p for p in chimney_projects if p.id in allowed_chimney]
    chimney_count = len(chimney_projects)

    total_projects = lsurvey_count + chimney_count

    # Open defects — Chimney only (Land Survey has no defect concept),
    # and only counting defects on chimney projects this client can
    # actually see, same restriction as the project list above.
    open_defects = sum(1 for p in chimney_projects for d in p.defects if d.status == 'Open')

    # Chimney models ready — same visible-project scoping.
    chimney_models_ready = sum(1 for p in chimney_projects if p.tileset_path)

    total_users = User.query.count()
    active_users = sum(1 for u in User.query.all() if u.effective_status() == 'Active')

    performed_by = session.get('user_name', '')
    today = date.today()
    day_labels = [(today - timedelta(days=i)) for i in range(6, -1, -1)]
    day_counts = {d.isoformat(): 0 for d in day_labels}
    week_start = datetime.combine(day_labels[0], datetime.min.time())
    week_rows = (ActivityLog.query
                 .filter(ActivityLog.created_at >= week_start, ActivityLog.performed_by == performed_by)
                 .with_entities(ActivityLog.created_at).all())
    for (created_at,) in week_rows:
        key = created_at.date().isoformat()
        if key in day_counts:
            day_counts[key] += 1
    activity_trend = [{'label': d.strftime('%a'), 'count': day_counts[d.isoformat()]} for d in day_labels]

    return jsonify({
        'projects': {'total': total_projects, 'land_survey': lsurvey_count, 'chimney_inspection': chimney_count},
        'open_defects': open_defects,
        'chimney_models_ready': chimney_models_ready,
        'users': {'total': total_users, 'active': active_users},
        'activity_trend': activity_trend,
    })


@settings_bp.route('/api/dashboard/live-load-history', methods=['GET'])
def api_dashboard_live_load_history():
    guard = _require_admin()
    if guard:
        return guard
    from load_monitor import get_snapshot_history
    return jsonify({'history': get_snapshot_history()})


@settings_bp.route('/api/dashboard/live-load', methods=['GET'])
def api_dashboard_live_load():
    guard = _require_admin()
    if guard:
        return guard
    from load_monitor import get_live_stats
    return jsonify(get_live_stats())


@settings_bp.route('/api/dashboard/summary', methods=['GET'])
def api_dashboard_summary():
    guard = _require_admin()
    if guard:
        return guard

    lsurvey_count = Project.query.filter_by(module='Land Survey').count()
    chimney_count = ChimneyProject.query.count()
    total_projects = lsurvey_count + chimney_count

    total_users = User.query.count()
    active_users = sum(1 for u in User.query.all() if u.effective_status() == 'Active')
    pending_users = User.query.filter_by(status='Pending').count()

    chimney_models_ready = ChimneyProject.query.filter(ChimneyProject.tileset_path != '').count()

    # Defect severity — Chimney (3D Inspection) is the only defect system
    # in this project; Land Survey has no defect-marking concept.
    severity_counts = {'Critical': 0, 'Major': 0, 'Minor': 0}
    for sev, count in (db.session.query(ChimneyDefect.severity, db.func.count(ChimneyDefect.id))
                        .group_by(ChimneyDefect.severity).all()):
        if sev == 'Moderate':
            severity_counts['Major'] += count
        elif sev in severity_counts:
            severity_counts[sev] += count

    # Needs Attention — things worth an admin's notice at a glance rather
    # than something they have to go looking for.
    open_critical = ChimneyDefect.query.filter_by(severity='Critical', status='Open').count()
    towers_pending = 0  # no tower/photo concept in this project (Land Survey has none, Chimney tracks per-project instead)

    last_24h = datetime.utcnow() - timedelta(hours=24)
    recent = (ActivityLog.query.filter(ActivityLog.created_at >= last_24h)
              .order_by(ActivityLog.created_at.desc()).limit(60).all())

    # Activity trend, last 7 days — how much is actually happening in the
    # portal day to day. This is genuinely dashboard-level information;
    # nothing per-project shows a cross-module activity trend like this.
    today = date.today()
    day_labels = [(today - timedelta(days=i)) for i in range(6, -1, -1)]
    day_counts = {d.isoformat(): 0 for d in day_labels}
    week_start = datetime.combine(day_labels[0], datetime.min.time())
    week_rows = (ActivityLog.query
                 .filter(ActivityLog.created_at >= week_start)
                 .with_entities(ActivityLog.created_at).all())
    for (created_at,) in week_rows:
        key = created_at.date().isoformat()
        if key in day_counts:
            day_counts[key] += 1
    activity_trend = [{'label': d.strftime('%a'), 'count': day_counts[d.isoformat()]} for d in day_labels]

    return jsonify({
        'projects': {
            'total':              total_projects,
            'land_survey':        lsurvey_count,
            'chimney_inspection': chimney_count,
        },
        'users': {
            'total':   total_users,
            'active':  active_users,
            'pending': pending_users,
        },
        'chimney_models_ready': chimney_models_ready,
        'severity_counts': severity_counts,
        'needs_attention': {
            'open_critical_defects': open_critical,
            'towers_pending_photos': towers_pending,
        },
        'recent_activity': [e.to_dict() for e in recent],
        'activity_trend': activity_trend,
    })
