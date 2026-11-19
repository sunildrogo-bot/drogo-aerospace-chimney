"""
assistant_api.py — In-app AI chat assistant.

Runs as a tool-calling agent against Google's Gemini API (free tier —
switched from Anthropic's paid API by request). Every tool function below
queries the database using the SAME permission-filtering functions the
rest of the app already uses (visible_projects /
_visible_chimney_project_ids, imported directly from projects_routes.py
and chimney_routes.py rather than reimplemented here) — so a Client User
with restricted project access gets those same restrictions applied to
whatever the assistant can see and do on their behalf, by construction,
not by a prompt instruction that could be talked around.

Honest scope: this is a text chat assistant. It can look up and explain
data, and trigger the same "generate a report" / "create a division"
actions the UI already exposes as simple form-fills. It CANNOT draw a
defect shape on a photo (a spatial/mouse action) or receive an uploaded
file as part of a chat message — those still need the regular UI, and the
system prompt tells the assistant to say so plainly rather than pretend.

Note on the free tier: Gemini's free tier trains on submitted data by
default (no paid-tier privacy guarantee behind it) — worth knowing given
this handles real inspection/defect data. See the conversation this was
built in for the tradeoff discussion.
"""
import os
import json
from flask import Blueprint, current_app, request, jsonify, session, send_file, url_for

from models import db, Project, Division, Line, ChimneyProject, ChimneyDefect, User, HelpTicket

assistant_bp = Blueprint('assistant_bp', __name__, url_prefix='/api/assistant')

MODEL = 'gemini-3.1-flash-lite'  # switched from gemini-3.5-flash — that model's free tier is only 20 requests/DAY, which gets exhausted almost immediately with real testing. gemini-3.1-flash-lite (the stable release, not the retired -preview variant) gets 1,500/day free — same general capability class (tool-calling works the same way), just a far more usable free-tier quota. gemini-2.5-flash is deprecated for new users (404) as of Jul 2026; avoid '-latest' aliases and gemini-3.6-flash (released Jul 21 2026, still rolling out) for something this needs to keep working reliably.
MAX_TOOL_ROUNDS = 6  # hard cap on tool-call round-trips per message, so a confused loop can't run forever


def _login_guard():
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in.'}), 401
    return None


def _is_admin():
    return session.get('role') == 'Admin'


def _current_user():
    uid = session.get('user_id')
    return User.query.get(uid) if uid else None


# ── Tool implementations ─────────────────────────────────────────────────
# Every function here takes/returns plain JSON-serializable data (this is
# what gets sent back to Claude as the tool result) and is scoped to what
# the CURRENT session is actually allowed to see, using the app's real
# permission logic rather than anything reimplemented for the assistant.

def _visible_chimney_ids():
    from chimney_routes import _visible_chimney_project_ids
    return _visible_chimney_project_ids()


def tool_list_projects(module=None):
    from projects_routes import visible_projects
    rows = visible_projects(module).all()
    return {'projects': [{'id': r.id, 'name': r.name, 'module': r.module, 'state': r.state,
                          'client_name': r.client_name} for r in rows]}


def tool_list_chimney_projects():
    rows = ChimneyProject.query.all()
    allowed = _visible_chimney_ids()
    if allowed is not None:
        rows = [r for r in rows if r.id in allowed]
    return {'projects': [{'id': r.id, 'name': r.asset_name, 'category': r.asset_category} for r in rows]}


def _find_project(project_name):
    from projects_routes import visible_projects
    rows = visible_projects().filter(Project.name.ilike(f'%{project_name}%')).all()
    if not rows:
        return None, {'error': f'No project found matching "{project_name}".'}
    if len(rows) > 1:
        return None, {'error': 'Multiple projects match that name — please be more specific.',
                       'matches': [r.name for r in rows]}
    return rows[0], None


def tool_get_project_overview(project_name):
    project, err = _find_project(project_name)
    if err:
        return err
    division_count = len(project.divisions)
    line_count = sum(len(d.lines) for d in project.divisions)
    return {
        'project': project.name, 'module': project.module,
        'divisions': division_count, 'lines': line_count,
    }


def tool_list_divisions(project_name):
    project, err = _find_project(project_name)
    if err:
        return err
    return {'divisions': [{'id': d.id, 'name': d.name, 'state': d.state, 'lines': len(d.lines)}
                           for d in project.divisions]}


def tool_list_lines(project_name, division_name=None):
    project, err = _find_project(project_name)
    if err:
        return err
    divisions = project.divisions
    if division_name:
        divisions = [d for d in divisions if division_name.lower() in d.name.lower()]
        if not divisions:
            return {'error': f'No division found matching "{division_name}" in this project.'}
    out = []
    for d in divisions:
        for l in d.lines:
            out.append({'id': l.id, 'name': l.name, 'division': d.name, 'tower_count': l.tower_count,
                        'voltage_level': l.voltage_level, 'pilot_name': l.pilot_name})
    return {'lines': out}



TOOLS = [
    {'name': 'list_projects', 'description': 'List Land Survey projects the current user can see.',
     'parameters': {'type': 'object', 'properties': {'module': {'type': 'string', 'description': "Only 'Land Survey' is valid — omit to list all"}}}},
    {'name': 'list_chimney_projects', 'description': 'List 3D Inspection (chimney/water tank) projects the current user can see.',
     'parameters': {'type': 'object', 'properties': {}}},
    {'name': 'get_project_overview', 'description': 'Get division/line counts for a Land Survey project by name.',
     'parameters': {'type': 'object', 'properties': {'project_name': {'type': 'string'}}, 'required': ['project_name']}},
    {'name': 'list_divisions', 'description': "List a project's divisions.",
     'parameters': {'type': 'object', 'properties': {'project_name': {'type': 'string'}}, 'required': ['project_name']}},
    {'name': 'list_lines', 'description': "List lines in a project, optionally within one division.",
     'parameters': {'type': 'object', 'properties': {'project_name': {'type': 'string'}, 'division_name': {'type': 'string'}}, 'required': ['project_name']}},
    {'name': 'generate_central_report', 'description': 'Generate ONE combined PDF report covering every project the user can see, across Land Survey and 3D Inspection.',
     'parameters': {'type': 'object', 'properties': {}}},
    {'name': 'create_help_ticket', 'description': 'Raise a support ticket about a portal problem (a bug, something not working, a question for the team) — shows up for Admin in Settings > Help.',
     'parameters': {'type': 'object', 'properties': {
         'subject': {'type': 'string', 'description': 'A short summary of the problem, a few words'},
         'description': {'type': 'string', 'description': 'More detail about what happened, optional'},
     }, 'required': ['subject']}},
]

def _central_report_projects():
    """One combined PDF across every project the current user can see —
    Land Survey (division/line counts only, no defect concept) and 3D
    Inspection (open/closed/severity rollup) — handed to
    central_report.py."""
    out = []

    from projects_routes import visible_projects
    for project in visible_projects('Land Survey').all():
        division_count = len(project.divisions)
        line_count = sum(len(d.lines) for d in project.divisions)
        out.append({
            'name': project.name, 'module': 'Land Survey',
            'division_count': division_count, 'line_count': line_count,
            'total_defects': 0,
        })

    chimney_rows = ChimneyProject.query.all()
    allowed_chimney = _visible_chimney_ids()
    if allowed_chimney is not None:
        chimney_rows = [r for r in chimney_rows if r.id in allowed_chimney]
    for project in chimney_rows:
        defects = project.defects
        open_count = sum(1 for d in defects if d.status != 'Closed')
        closed_count = sum(1 for d in defects if d.status == 'Closed')
        severity_counts = {'Minor': 0, 'Moderate': 0, 'Critical': 0}
        for d in defects:
            if d.severity in severity_counts:
                severity_counts[d.severity] += 1
        out.append({
            'name': project.asset_name, 'module': '3D Inspection',
            'total_defects': len(defects), 'open_count': open_count, 'closed_count': closed_count,
            'severity_counts': severity_counts,
        })

    return out


def tool_generate_central_report():
    if not _is_admin():
        return {'error': 'Only administrators can generate a combined report.'}
    projects = _central_report_projects()
    if not projects:
        return {'error': "You don't have access to any projects to include in a report."}
    return {'ok': True, 'download_url': url_for('assistant_bp.central_report'),
            'project_count': len(projects), 'total_defects': sum(p['total_defects'] for p in projects)}


@assistant_bp.get('/central-report.pdf')
def central_report():
    guard = _login_guard()
    if guard:
        return guard
    if not _is_admin():
        return jsonify({'error': 'Only administrators can download a combined report.'}), 403
    projects = _central_report_projects()
    if not projects:
        return jsonify({'error': 'No accessible projects to report.'}), 403
    from central_report import build_central_report_pdf
    response = send_file(build_central_report_pdf(projects), mimetype='application/pdf',
                         as_attachment=True, download_name='central_inspection_report.pdf')
    response.headers['Cache-Control'] = 'private, no-store'
    return response


def tool_create_help_ticket(subject, description=''):
    """Raises a support ticket about a portal issue — same underlying
    HelpTicket record the Settings -> Help admin view already lists and
    works through, so a ticket raised here shows up there with zero extra
    wiring needed."""
    if _is_admin():
        return {'error': "Admin accounts resolve tickets rather than raise their own — see Settings > Raised Tickets."}
    subject = (subject or '').strip()
    if not subject:
        return {'error': 'A short subject describing the problem is required.'}
    reporter_type = 'Admin' if _is_admin() else 'Client'
    ticket = HelpTicket(
        subject=subject,
        description=(description or '').strip(),
        reporter_type=reporter_type,
        submitted_by=session.get('user_name', ''),
        status='Open',
        seen_by_reporter=True,
    )
    db.session.add(ticket)
    db.session.commit()
    return {'ok': True, 'ticket_id': ticket.id, 'note': 'Ticket raised — the team will follow up.'}


TOOL_FUNCTIONS = {
    'list_projects': tool_list_projects,
    'list_chimney_projects': tool_list_chimney_projects,
    'get_project_overview': tool_get_project_overview,
    'list_divisions': tool_list_divisions,
    'list_lines': tool_list_lines,
    'generate_central_report': tool_generate_central_report,
    'create_help_ticket': tool_create_help_ticket,
}


def _system_prompt():
    user = _current_user()
    name = user.username if user else 'there'
    role = session.get('role', 'Client User')
    ticket_line = (
        "Admin accounts resolve tickets rather than raise their own (see Settings > Raised Tickets) — don't offer to raise one for an Admin."
        if _is_admin() else
        "You can also raise a support ticket on the person's behalf if they describe a portal problem — confirm the subject with them before creating it, and let them know it's been raised."
    )
    return f"""You are the in-app assistant for DROGO AEROSPACE's inspection platform, talking to {name} ({role}).

You can look up Land Survey and 3D Inspection projects and their divisions/lines, and generate a combined central report across everything you can see (report generation is Admin only). {ticket_line} Every tool call is automatically scoped to exactly what this user is allowed to see — if something isn't accessible, the tool will say so; don't try to work around that or guess at data you don't have.

Be honest about what you can't do: you cannot mark up defects or take a photo upload through chat — for those, tell the person to use the regular screen. Don't imply you did something you didn't.

Keep answers concise and concrete — real numbers and names from tool results, not vague summaries. If a name is ambiguous, ask which one they mean rather than guessing."""


def _gemini_tools():
    tools = TOOLS
    if _is_admin():
        # Admin resolves tickets (Settings -> Raised Tickets), doesn't
        # raise their own — mirrors the UI, where the "Raise a Ticket"
        # button is hidden for Admin sessions. Excluded here too, not just
        # hidden in the UI, so asking in natural language can't get around it.
        tools = [t for t in TOOLS if t['name'] != 'create_help_ticket']
    else:
        tools = [t for t in TOOLS if t['name'] != 'generate_central_report']
    return [{'function_declarations': [
        {'name': t['name'], 'description': t['description'], 'parameters': t['parameters']} for t in tools
    ]}]


@assistant_bp.route('/chat', methods=['POST'])
def chat():
    guard = _login_guard()
    if guard:
        return guard

    api_key = os.environ.get('GEMINI_API_KEY')
    if not api_key:
        return jsonify({'error': 'The assistant is not configured yet — GEMINI_API_KEY is not set on the server.'}), 503

    data = request.get_json(force=True, silent=True) or {}
    if not isinstance(data, dict):
        return jsonify({'error': 'Expected a message and conversation history.'}), 400
    user_message = data.get('message')
    history = data.get('history', [])
    if not isinstance(history, list):
        return jsonify({'error': 'Conversation history must be a list.'}), 400
    if not isinstance(user_message, str) or not user_message.strip():
        return jsonify({'error': 'message is required.'}), 400

    try:
        from google import genai
        from google.genai import types
    except ImportError:
        return jsonify({'error': 'The google-genai package is not installed on the server.'}), 503

    client = genai.Client(api_key=api_key)

    # History is kept client-side as plain JSON (what the frontend sends
    # back each turn) and reconstructed into typed Content objects here —
    # keeps the wire format simple and avoids the frontend needing to know
    # anything about the SDK's internal types.
    try:
        contents = [types.Content.model_validate(h) for h in history]
    except ValueError:
        return jsonify({'error': 'Conversation history could not be read.'}), 400
    contents.append(types.Content(role='user', parts=[types.Part(text=user_message)]))

    config = types.GenerateContentConfig(
        system_instruction=_system_prompt(),
        tools=_gemini_tools(),
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )

    report_ready = False
    try:
        for _ in range(MAX_TOOL_ROUNDS):
            response = client.models.generate_content(model=MODEL, contents=contents, config=config)
            candidate = response.candidates[0] if response.candidates else None
            if not candidate or not candidate.content or not candidate.content.parts:
                return jsonify({'error': 'The assistant returned no answer. Please try again.'}), 502
            parts = candidate.content.parts
            function_calls = [p.function_call for p in parts if p.function_call]

            if not function_calls:
                final_text = ''.join(p.text for p in parts if p.text)
                contents.append(candidate.content)
                return jsonify({'reply': final_text, 'report_ready': report_ready, 'history': [c.model_dump(mode='json') for c in contents]})

            contents.append(candidate.content)
            response_parts = []
            for fc in function_calls:
                fn = TOOL_FUNCTIONS.get(fc.name)
                try:
                    result = fn(**(fc.args or {})) if fn else {'error': f'Unknown tool {fc.name}'}
                except Exception as e:
                    result = {'error': str(e)}
                if fc.name == 'generate_central_report' and result.get('ok'):
                    report_ready = True
                response_parts.append(types.Part(function_response=types.FunctionResponse(
                    name=fc.name, response={'result': json.loads(json.dumps(result, default=str))}
                )))
            contents.append(types.Content(role='user', parts=response_parts))

        return jsonify({'reply': "I'm having trouble finishing that request — could you try rephrasing it?",
                         'history': [c.model_dump(mode='json') for c in contents]})
    except Exception:
        current_app.logger.exception('Assistant request failed')
        return jsonify({'error': 'The assistant is temporarily unavailable. Please try again.'}), 502
