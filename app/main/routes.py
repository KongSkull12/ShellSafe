from flask import render_template, redirect, url_for, flash, jsonify, Response, stream_with_context, request
from flask_login import login_required, current_user
from app.main import bp
from functools import wraps
from app.models import Alert, Report
from app.firestore_service import get_firestore_service
from app.alert_helpers import normalize_alerts
from app.realtime_db_service import (
    get_live_history,
    get_sms_phones,
    set_sms_phones,
    get_sms_test_status,
    request_sms_test,
    MAX_SMS_PHONES,
)
from app.sensor_view import build_live_payload, payload_fingerprint
from app.threshold_service import (
    SENSOR_ORDER,
    get_default_thresholds,
    get_thresholds,
    set_thresholds,
    thresholds_for_form,
)
from datetime import datetime
import json
import time

def role_required(role):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated or current_user.role != role:
                flash("You don't have permission to access this page.")
                return redirect(url_for('main.index'))
            return f(*args, **kwargs)
        return decorated_function
    return decorator

def _alerts_home():
    if getattr(current_user, 'role', None) == 'authority':
        return redirect(url_for('main.authority_alerts'))
    return redirect(url_for('main.alerts'))

@bp.route('/')
@bp.route('/index')
def index():
    return render_template('index.html', title='Home')

@bp.route('/features')
def features():
    return render_template('features.html', title='Features')

@bp.route('/about')
def about():
    return render_template('about.html', title='About')

@bp.route('/dashboard/admin')
@login_required
@role_required('admin')
def admin_dashboard():
    db = get_firestore_service()
    alerts = normalize_alerts(db.get_all_alerts(exclude_deleted=True)[:4])
    return render_template('admin_dashboard.html', title='Overview',
                         live=build_live_payload(),
                         history=get_live_history()[-60:],
                         alerts=alerts)

@bp.route('/dashboard/authority')
@login_required
@role_required('authority')
def authority_dashboard():
    db = get_firestore_service()
    alerts = normalize_alerts(db.get_all_alerts(exclude_deleted=True)[:4])
    return render_template('authority_dashboard.html', title='Overview',
                         live=build_live_payload(),
                         history=get_live_history()[-60:],
                         alerts=alerts)

@bp.route('/dashboard/authority/alerts')
@login_required
@role_required('authority')
def authority_alerts():
    db = get_firestore_service()
    alerts = normalize_alerts(db.get_risk_alerts())
    return render_template('authority_alerts.html', title='Authority Alerts', alerts=alerts)

@bp.route('/alerts')
@login_required
def alerts():
    db = get_firestore_service()
    all_alerts = normalize_alerts(db.get_all_alerts(exclude_deleted=True))
    return render_template('alerts.html', title='Alerts', alerts=all_alerts)

@bp.route('/alerts/mark_all_read', methods=['POST'])
@login_required
def mark_all_read():
    db = get_firestore_service()
    count = db.mark_all_alerts_read()
    if count:
        flash(f'Marked {count} alert(s) as read.', 'success')
    else:
        flash('No unread alerts to mark.', 'info')
    return _alerts_home()

@bp.route('/alerts/clear_old', methods=['POST'])
@login_required
def clear_old():
    """Delete all acknowledged alerts (soft delete)."""
    db = get_firestore_service()
    count = db.clear_acknowledged_alerts()
    if count:
        flash(f'Cleared {count} read alert(s).', 'success')
    else:
        flash('No read alerts to clear. Mark alerts as read first.', 'info')
    return _alerts_home()

@bp.route('/alerts/mark_read/<alert_id>', methods=['POST'])
@login_required
def mark_read(alert_id):
    db = get_firestore_service()
    
    # Check if alert exists
    alert_doc = db.db.collection('alerts').document(alert_id).get()
    if not alert_doc.exists:
        flash('Alert not found.', 'error')
        return _alerts_home()
    
    db.update_alert(alert_id, {'is_acknowledged': True})
    flash('Alert marked as read.', 'success')
    return _alerts_home()

@bp.route('/alerts/delete/<alert_id>', methods=['POST'])
@login_required
def delete_alert(alert_id):
    db = get_firestore_service()
    
    # Check if alert exists
    alert_doc = db.db.collection('alerts').document(alert_id).get()
    if not alert_doc.exists:
        flash('Alert not found.', 'error')
        return _alerts_home()
    
    db.delete_alert(alert_id, permanent=False)
    flash('Alert moved to Recently Deleted.', 'success')
    return _alerts_home()

@bp.route('/recently_deleted')
@login_required
def recently_deleted():
    db = get_firestore_service()
    deleted_alerts = normalize_alerts(db.get_deleted_alerts())
    return render_template('recently_deleted.html', title='Recently Deleted', alerts=deleted_alerts)

@bp.route('/recently_deleted/restore/<alert_id>', methods=['POST'])
@login_required
def restore_alert(alert_id):
    db = get_firestore_service()
    
    # Check if alert exists
    alert_doc = db.db.collection('alerts').document(alert_id).get()
    if not alert_doc.exists:
        flash('Alert not found.', 'error')
        return redirect(url_for('main.recently_deleted'))
    
    db.restore_alert(alert_id)
    flash('Alert restored.', 'success')
    return redirect(url_for('main.recently_deleted'))

@bp.route('/recently_deleted/delete_permanently/<alert_id>', methods=['POST'])
@login_required
def delete_permanently(alert_id):
    db = get_firestore_service()
    
    # Check if alert exists
    alert_doc = db.db.collection('alerts').document(alert_id).get()
    if not alert_doc.exists:
        flash('Alert not found.', 'error')
        return redirect(url_for('main.recently_deleted'))
    
    db.delete_alert(alert_id, permanent=True)
    flash('Alert permanently deleted.', 'success')
    return redirect(url_for('main.recently_deleted'))

@bp.route('/data_history')
@login_required
def data_history():
    return render_template('data_history.html', title='Data history',
                           live=build_live_payload(),
                           history=get_live_history())

@bp.route('/devices')
@login_required
def devices():
    live = build_live_payload()
    return render_template(
        'devices.html',
        title='Devices',
        live=live,
        sensor_data=live['sensor_data'],
    )


@bp.route('/settings/sms', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def sms_settings():
    """Admin Notification Settings — up to 4 SMS recipients for T-Call A7670."""
    phones = get_sms_phones()

    if request.method == 'POST':
        submitted = []
        for i in range(1, MAX_SMS_PHONES + 1):
            value = (request.form.get(f'phone_{i}') or '').strip()
            if value:
                submitted.append(value)

        if len(submitted) > MAX_SMS_PHONES:
            flash(f'You can save at most {MAX_SMS_PHONES} phone numbers.', 'error')
            return redirect(url_for('main.sms_settings'))

        try:
            saved = set_sms_phones(submitted)
        except Exception as exc:
            flash(f'Failed to save SMS numbers: {exc}', 'error')
            return redirect(url_for('main.sms_settings'))

        if submitted and not saved:
            flash('No valid phone numbers. Use E.164 format, e.g. +639171234567.', 'error')
        elif len(saved) < len(submitted):
            flash(
                f'Saved {len(saved)} valid number(s). Invalid entries were skipped.',
                'warning',
            )
        else:
            flash(f'SMS recipients updated ({len(saved)} of {MAX_SMS_PHONES} max).', 'success')
        return redirect(url_for('main.sms_settings'))

    # Pad to MAX_SMS_PHONES slots for the form
    phone_slots = list(phones) + [''] * (MAX_SMS_PHONES - len(phones))
    return render_template(
        'sms_settings.html',
        title='SMS Notification Settings',
        phone_slots=phone_slots[:MAX_SMS_PHONES],
        max_phones=MAX_SMS_PHONES,
        saved_count=len(phones),
        sms_test=get_sms_test_status(),
    )


@bp.route('/settings/sms/test', methods=['POST'])
@login_required
@role_required('admin')
def sms_test_send():
    """Queue a manual SMS test for the on-device A7670 modem."""
    wants_json = (
        request.headers.get('X-Requested-With') == 'XMLHttpRequest'
        or request.accept_mimetypes.best == 'application/json'
        or 'application/json' in (request.headers.get('Accept') or '')
    )
    try:
        payload = request_sms_test(
            requested_by=getattr(current_user, 'email', None) or 'admin'
        )
    except ValueError as exc:
        if wants_json:
            return jsonify({'ok': False, 'error': str(exc)}), 400
        flash(str(exc), 'error')
        return redirect(url_for('main.sms_settings'))
    except Exception as exc:
        if wants_json:
            return jsonify({'ok': False, 'error': f'Failed to queue test SMS: {exc}'}), 500
        flash(f'Failed to queue test SMS: {exc}', 'error')
        return redirect(url_for('main.sms_settings'))

    if wants_json:
        return jsonify({'ok': True, 'sms_test': payload})
    flash(
        'Test SMS queued. Keep the device online — the modem will send it shortly.',
        'success',
    )
    return redirect(url_for('main.sms_settings'))


@bp.route('/settings/sms/test/status')
@login_required
@role_required('admin')
def sms_test_status():
    """Poll SMS test delivery status written by firmware."""
    return jsonify({'ok': True, 'sms_test': get_sms_test_status()})


@bp.route('/settings/thresholds', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def threshold_settings():
    """Admin page to configure Normal / Warning / Alert bands per sensor."""
    if request.method == 'POST':
        submitted = {}
        for key in SENSOR_ORDER:
            submitted[key] = {
                'normal_min': request.form.get(f'{key}_normal_min'),
                'normal_max': request.form.get(f'{key}_normal_max'),
                'warning_min': request.form.get(f'{key}_warning_min'),
                'warning_max': request.form.get(f'{key}_warning_max'),
                'alert_min': request.form.get(f'{key}_alert_min'),
                'alert_max': request.form.get(f'{key}_alert_max'),
            }
        try:
            set_thresholds(submitted)
            flash('Sensor thresholds saved. Risk scoring and in-app alerts will use these values.', 'success')
        except Exception as exc:
            flash(f'Failed to save thresholds: {exc}', 'error')
        return redirect(url_for('main.threshold_settings'))

    return render_template(
        'threshold_settings.html',
        title='Alert Thresholds',
        sensors=thresholds_for_form(),
        defaults=get_default_thresholds(),
    )


@bp.route('/api/sensor-data')
@login_required
def api_sensor_data():
    return jsonify(build_live_payload())


@bp.route('/api/sensor-stream')
@login_required
def api_sensor_stream():
    """Push sensor updates when Firebase data changes (throttled)."""
    @stream_with_context
    def generate():
        last_key = object()
        keepalive_counter = 0

        while True:
            # Alerts are raised by the background sampler, not per client.
            payload = build_live_payload()
            key = payload_fingerprint(payload)
            if key != last_key:
                last_key = key
                yield f"data: {json.dumps(payload)}\n\n"
                keepalive_counter = 0
            else:
                keepalive_counter += 1
                if keepalive_counter >= 10:
                    yield ": keepalive\n\n"
                    keepalive_counter = 0

            time.sleep(3)

    return Response(
        generate(),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
            'Connection': 'keep-alive',
        },
    )

@bp.route('/reports')
@login_required
def reports():
    db = get_firestore_service()
    all_reports = db.get_all_reports(status='active')
    return render_template('reports.html', title='Monitoring Reports', reports=all_reports)

@bp.route('/reports/deleted')
@login_required
def deleted_reports_view():
    db = get_firestore_service()
    deleted = db.get_all_reports(status='deleted')
    return render_template('deleted_reports.html', title='Deleted Reports', reports=deleted)

@bp.route('/reports/delete/<report_id>', methods=['POST'])
@login_required
def delete_report(report_id):
    db = get_firestore_service()
    
    # Check if report exists
    report_doc = db.db.collection('reports').document(report_id).get()
    if not report_doc.exists:
        flash('Report not found.', 'error')
        return redirect(url_for('main.reports'))
    
    db.delete_report(report_id, permanent=False, deleted_by='System Admin')
    flash('Report moved to deleted reports.', 'success')
    return redirect(url_for('main.reports'))

@bp.route('/reports/restore/<report_id>', methods=['POST'])
@login_required
def restore_report(report_id):
    db = get_firestore_service()
    
    # Check if report exists
    report_doc = db.db.collection('reports').document(report_id).get()
    if not report_doc.exists:
        flash('Report not found.', 'error')
        return redirect(url_for('main.deleted_reports_view'))
    
    db.restore_report(report_id)
    flash('Report restored.', 'success')
    return redirect(url_for('main.deleted_reports_view'))

@bp.route('/reports/permanent_delete/<report_id>', methods=['POST'])
@login_required
def delete_report_permanently(report_id):
    db = get_firestore_service()
    
    # Check if report exists
    report_doc = db.db.collection('reports').document(report_id).get()
    if not report_doc.exists:
        flash('Report not found.', 'error')
        return redirect(url_for('main.deleted_reports_view'))
    
    db.delete_report(report_id, permanent=True)
    flash('Report permanently deleted.', 'success')
    return redirect(url_for('main.deleted_reports_view'))
