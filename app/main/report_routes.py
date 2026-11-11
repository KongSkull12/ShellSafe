"""Generate and view water quality reports (see app/report_service.py)."""

from flask import abort, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.firestore_service import get_firestore_service
from app.main import bp
from app.report_service import PERIODS, build_report


@bp.route('/reports/generate', methods=['POST'])
@login_required
def generate_report():
    period = request.form.get('period', '7')
    if period not in PERIODS:
        flash('Choose a report period.', 'error')
        return redirect(url_for('main.reports'))
    try:
        report = build_report(period)
        summary = report['summary']
        report_id = get_firestore_service().create_report(
            report_name=report['report_name'],
            report_type=report['report_type'],
            file_size=f"{summary['coverage']['readings']:,} readings",
            generated_by=getattr(current_user, 'email', None) or 'Unknown',
            summary=summary,
        )
    except Exception as exc:
        current_app.logger.warning('Report generation failed: %s', exc)
        flash('The report could not be generated right now. Please try again.', 'error')
        return redirect(url_for('main.reports'))
    return redirect(url_for('main.view_report', report_id=report_id))


@bp.route('/reports/<report_id>')
@login_required
def view_report(report_id):
    try:
        report = get_firestore_service().get_report(report_id)
    except Exception:
        report = None
    if not report:
        abort(404)
    return render_template('report_detail.html', title='Monitoring Reports',
                           report=report, summary=report.get('summary') or {})
